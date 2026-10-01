"""The MCP server on AgentCore Runtime (plan task P2-3, decision D-035).

Direct code deployment: the zip from `infra/runtime/build_zip.py` goes to the CDK asset bucket and the
runtime starts `runtime_entry.py` from it (Python 3.12, arm64, no Docker, no ECR). Runtime V2, public
network, IAM (SigV4) callers only for now: the Gateway of P2-5 will be the caller, and the diner's Cognito
token travels in the `x-ft-user-token` header, which must be on the runtime's header allowlist.

Sources: docs "AWS::BedrockAgentCore::Runtime" (CloudFormation), "IAM Permissions for AgentCore Runtime"
(trust policy and execution role), "Direct code deployment", "MCP protocol contract".
"""

from pathlib import Path

from aws_cdk import CfnOutput, RemovalPolicy, Stack, Tags
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3_assets as s3_assets
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct

RUNTIME_NAME = "fairtable_mcp"  # letters, digits and underscores only
ENTRY_POINT = "runtime_entry.py"
USER_TOKEN_HEADER = "x-ft-user-token"
IDLE_TIMEOUT_S = 120  # idle sessions are billed until this passes (minimum 60)
MAX_LIFETIME_S = 900


class RuntimeStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        table: dynamodb.ITable,
        issuer: str,
        client_ids: list[str],
        package_path: Path,
        consent_base_url: str,
        allowed_hosts: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        package = s3_assets.Asset(self, "Package", path=str(package_path))

        # The server signs slot tokens with this. Generated once, kept in Secrets Manager, and handed to the
        # runtime as a CloudFormation dynamic reference (no value in the repo or in a deploy command).
        slot_secret = secretsmanager.Secret(
            self,
            "SlotTokenSecret",
            description="HMAC key for FairTable slot tokens",
            generate_secret_string=secretsmanager.SecretStringGenerator(password_length=48, exclude_punctuation=True),
            removal_policy=RemovalPolicy.DESTROY,
        )

        role = iam.Role(
            self,
            "ExecutionRole",
            assumed_by=iam.ServicePrincipal(
                "bedrock-agentcore.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": self.account},
                    "ArnLike": {"aws:SourceArn": self.format_arn(service="bedrock-agentcore", resource="*")},
                },
            ),
        )
        log_groups = f"arn:{self.partition}:logs:{self.region}:{self.account}:log-group:/aws/bedrock-agentcore/runtimes/*"
        role.add_to_policy(iam.PolicyStatement(
            actions=["logs:DescribeLogStreams", "logs:CreateLogGroup"], resources=[log_groups]))
        role.add_to_policy(iam.PolicyStatement(
            actions=["logs:DescribeLogGroups"], resources=[f"arn:{self.partition}:logs:{self.region}:{self.account}:log-group:*"]))
        role.add_to_policy(iam.PolicyStatement(
            actions=["logs:CreateLogStream", "logs:PutLogEvents"], resources=[f"{log_groups}:log-stream:*"]))
        role.add_to_policy(iam.PolicyStatement(
            actions=["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"],
            resources=["*"]))
        role.add_to_policy(iam.PolicyStatement(
            actions=["cloudwatch:PutMetricData"], resources=["*"],
            conditions={"StringEquals": {"cloudwatch:namespace": "bedrock-agentcore"}}))
        # What the store does at run time: point reads and queries, conditional writes (also the ones inside
        # TransactWriteItems, which has no IAM action of its own). No Scan, no table management.
        role.add_to_policy(iam.PolicyStatement(
            actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:UpdateItem",
                     "dynamodb:DeleteItem", "dynamodb:ConditionCheckItem"],
            resources=[table.table_arn, f"{table.table_arn}/index/*"]))

        environment = {
            "TABLE_NAME": table.table_name,
            "AWS_REGION": self.region,
            "AUTH_ISSUER": issuer,
            "AUTH_JWKS_URL": f"{issuer}/.well-known/jwks.json",
            "AUTH_AUDIENCE_CLAIM": "client_id",
            "AUTH_AUDIENCE": ",".join(client_ids),
            "AUTH_TOKEN_USE": "access",
            "SLOT_TOKEN_SECRET": slot_secret.secret_value.unsafe_unwrap(),
            "CONSENT_BASE_URL": consent_base_url,
        }
        if allowed_hosts:
            environment["MCP_ALLOWED_HOSTS"] = allowed_hosts

        runtime = agentcore.CfnRuntime(
            self,
            "Runtime",
            agent_runtime_name=RUNTIME_NAME,
            role_arn=role.role_arn,
            agent_runtime_artifact=agentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                code_configuration=agentcore.CfnRuntime.CodeConfigurationProperty(
                    code=agentcore.CfnRuntime.CodeProperty(
                        s3=agentcore.CfnRuntime.S3LocationProperty(
                            bucket=package.s3_bucket_name, prefix=package.s3_object_key
                        )
                    ),
                    entry_point=[ENTRY_POINT],
                    runtime="PYTHON_3_12",
                )
            ),
            protocol_configuration="MCP",
            network_configuration=agentcore.CfnRuntime.NetworkConfigurationProperty(network_mode="PUBLIC"),
            lifecycle_configuration=agentcore.CfnRuntime.LifecycleConfigurationProperty(
                idle_runtime_session_timeout=IDLE_TIMEOUT_S, max_lifetime=MAX_LIFETIME_S
            ),
            request_header_configuration=agentcore.CfnRuntime.RequestHeaderConfigurationProperty(
                request_header_allowlist=[USER_TOKEN_HEADER]
            ),
            environment_variables=environment,
        )
        # The L1 class of this aws-cdk-lib version has no PlatformVersion, the CloudFormation resource has.
        runtime.add_property_override("PlatformVersion", "V2")
        runtime.node.add_dependency(role)  # the role and its policy exist before the runtime does

        self.runtime = runtime
        CfnOutput(self, "RuntimeArn", value=runtime.attr_agent_runtime_arn)
        CfnOutput(self, "RuntimeId", value=runtime.attr_agent_runtime_id)
        Tags.of(self).add("project", "fairtable")
