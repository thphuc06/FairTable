"""Traces for the AWS profile (plan task P2-9, decisions D-031 and D-050).

What it does:
  * CloudWatch Transaction Search for the account: a Logs resource policy that lets X-Ray write spans to
    `aws/spans`, and `AWS::XRay::TransactionSearchConfig` (spans go to CloudWatch Logs, 1 % indexed for free).
  * A trace delivery (`logType=TRACES`, destination type `XRAY`) for the Gateway, so each tools/list and
    tools/call leaves a SERVER and a CLIENT span.
  * Optionally the same delivery for the Runtime (`runtime=`). The documentation does not say how to turn
    tracing on for a Runtime from the API (only a console toggle), so this is an experiment, kept in its own
    switch: if the service refuses the source, the Gateway part is unaffected.

It never turns on the Gateway's `APPLICATION_LOGS`: those log request and response bodies, which hold slot
tokens and idempotency keys.

Sources: CloudWatch docs "Using Transaction Search with CloudFormation", "Enable transaction search",
"Traces sent to X-Ray"; AgentCore docs "Add observability to your AgentCore resources" (the SDK example for
memory and gateway: delivery source TRACES, destination XRAY, one delivery).
"""

import json

from aws_cdk import CfnOutput, Stack, Tags
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_logs as logs
from aws_cdk import aws_xray as xray
from constructs import Construct

INDEXING_PERCENTAGE = 1  # the free share of spans indexed for search (the rest is still stored)
POLICY_NAME = "fairtable-transaction-search"


class ObservabilityStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        gateway: agentcore.CfnGateway,
        runtime: agentcore.CfnRuntime | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        arn = f"arn:{self.partition}:logs:{self.region}:{self.account}:log-group"
        policy = logs.CfnResourcePolicy(
            self,
            "SpansPolicy",
            policy_name=POLICY_NAME,
            policy_document=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Sid": "TransactionSearchXRayAccess",
                            "Effect": "Allow",
                            "Principal": {"Service": "xray.amazonaws.com"},
                            "Action": "logs:PutLogEvents",
                            "Resource": [f"{arn}:aws/spans:*", f"{arn}:/aws/application-signals/data:*"],
                            "Condition": {
                                "ArnLike": {"aws:SourceArn": f"arn:{self.partition}:xray:{self.region}:{self.account}:*"},
                                "StringEquals": {"aws:SourceAccount": self.account},
                            },
                        }
                    ],
                }
            ),
        )
        search = xray.CfnTransactionSearchConfig(self, "TransactionSearch", indexing_percentage=INDEXING_PERCENTAGE)
        search.node.add_dependency(policy)

        # One destination (X-Ray) serves every source.
        destination = logs.CfnDeliveryDestination(
            self, "TracesDestination", name="fairtable-traces", delivery_destination_type="XRAY"
        )
        destination.node.add_dependency(search)

        self.deliveries = [self._trace(self, "Gateway", gateway.attr_gateway_arn, destination)]
        if runtime is not None:
            self.deliveries.append(self._trace(self, "Runtime", runtime.attr_agent_runtime_arn, destination))

        CfnOutput(self, "SpansLogGroup", value="aws/spans")
        Tags.of(self).add("project", "fairtable")

    @staticmethod
    def _trace(scope: Construct, what: str, resource_arn: str, destination: logs.CfnDeliveryDestination) -> logs.CfnDelivery:
        source = logs.CfnDeliverySource(
            scope, f"{what}TracesSource", name=f"fairtable-{what.lower()}-traces", log_type="TRACES", resource_arn=resource_arn
        )
        delivery = logs.CfnDelivery(
            scope,
            f"{what}TracesDelivery",
            delivery_source_name=source.name,
            delivery_destination_arn=destination.attr_arn,
        )
        delivery.add_resource_dependency(source)
        delivery.add_resource_dependency(destination)
        return delivery
