"""AgentCore Gateway in front of the Runtime (plan task P2-5, decision D-035).

Callers (the simulator, an assistant) present a Cognito access token. The Gateway checks it (`CUSTOM_JWT`,
the pool's discovery URL, the app clients), a REQUEST interceptor copies it into `x-ft-user-token`, and the
Gateway calls the Runtime with its own service role (IAM SigV4, service `bedrock-agentcore`). The server
still verifies the token itself.

Sources: docs "AWS::BedrockAgentCore::Gateway" and "GatewayTarget" (CloudFormation), "Set up inbound
authorization for your gateway", "Set up outbound authorization", "MCP servers targets", "Using interceptors
with Gateway", "Header propagation with Gateway", "Set up permissions for AgentCore Gateway"; the IAM actions
come from the service reference (`InvokeAgentRuntime` on `runtime` and `runtime-endpoint`, `InvokeGateway`
on `gateway`).
"""

from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack, Tags
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from constructs import Construct

INTERCEPTOR_DIR = Path(__file__).resolve().parents[2] / "gateway" / "interceptor"
GATEWAY_NAME = "fairtable-gw"  # hyphens only (the pattern allows no underscore)
TARGET_NAME = "ft"  # tools are named <target>___<tool>, so keep it short
USER_TOKEN_HEADER = "x-ft-user-token"
MCP_VERSIONS = ["2025-11-25"]  # the version this server speaks


class GatewayStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        runtime: agentcore.CfnRuntime,
        issuer: str,
        client_ids: list[str],
        sessions: bool = False,
        streaming: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        log_group = logs.LogGroup(
            self, "InterceptorLogs", retention=logs.RetentionDays.ONE_WEEK, removal_policy=RemovalPolicy.DESTROY
        )
        interceptor = lambda_.Function(
            self,
            "Interceptor",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset(str(INTERCEPTOR_DIR)),
            timeout=Duration.seconds(5),
            memory_size=128,
            log_group=log_group,
        )

        gateway_arns = f"arn:{self.partition}:bedrock-agentcore:{self.region}:{self.account}:gateway/{GATEWAY_NAME}-*"
        role = iam.Role(
            self,
            "GatewayRole",
            assumed_by=iam.ServicePrincipal(
                "bedrock-agentcore.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": self.account},
                    "ArnLike": {"aws:SourceArn": gateway_arns},
                },
            ),
        )
        runtime_arn = runtime.attr_agent_runtime_arn
        role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock-agentcore:InvokeAgentRuntime"],
            resources=[runtime_arn, f"{runtime_arn}/runtime-endpoint/*"],
        ))
        # The documentation asks for it on the service role as well; scoped to this gateway only.
        role.add_to_policy(iam.PolicyStatement(actions=["bedrock-agentcore:InvokeGateway"], resources=[gateway_arns]))
        role.add_to_policy(iam.PolicyStatement(actions=["lambda:InvokeFunction"], resources=[interceptor.function_arn]))

        gateway = agentcore.CfnGateway(
            self,
            "Gateway",
            name=GATEWAY_NAME,
            role_arn=role.role_arn,
            authorizer_type="CUSTOM_JWT",
            authorizer_configuration=agentcore.CfnGateway.AuthorizerConfigurationProperty(
                custom_jwt_authorizer=agentcore.CfnGateway.CustomJWTAuthorizerConfigurationProperty(
                    discovery_url=f"{issuer}/.well-known/openid-configuration",
                    # Cognito access tokens have `client_id` and no `aud`: allow clients, never an audience.
                    allowed_clients=client_ids,
                )
            ),
            protocol_type="MCP",
            protocol_configuration=agentcore.CfnGateway.GatewayProtocolConfigurationProperty(
                mcp=agentcore.CfnGateway.MCPGatewayConfigurationProperty(
                    supported_versions=MCP_VERSIONS,
                    # Sessions and response streaming are what URL elicitation through the Gateway needs
                    # ("Use elicitation with your AgentCore gateway"); off unless asked (D-048).
                    session_configuration=(
                        agentcore.CfnGateway.SessionConfigurationProperty(session_timeout_in_seconds=900)
                        if sessions else None
                    ),
                    streaming_configuration=(
                        agentcore.CfnGateway.StreamingConfigurationProperty(enable_response_streaming=True)
                        if streaming else None
                    ),
                )
            ),
            interceptor_configurations=[
                agentcore.CfnGateway.GatewayInterceptorConfigurationProperty(
                    interception_points=["REQUEST"],
                    interceptor=agentcore.CfnGateway.InterceptorConfigurationProperty(
                        lambda_=agentcore.CfnGateway.LambdaInterceptorConfigurationProperty(arn=interceptor.function_arn)
                    ),
                    input_configuration=agentcore.CfnGateway.InterceptorInputConfigurationProperty(
                        pass_request_headers=True  # the interceptor needs `Authorization`; it never logs it
                    ),
                )
            ],
            description="FairTable front door: Cognito JWT in, SigV4 to the Runtime",
        )
        gateway.node.add_dependency(role)

        # The Runtime's invocation URL, URL-encoded, as the target's endpoint ("MCP servers targets").
        encoded_arn = (
            f"arn%3A{self.partition}%3Abedrock-agentcore%3A{self.region}%3A{self.account}"
            f"%3Aruntime%2F{runtime.attr_agent_runtime_id}"
        )
        endpoint = (
            f"https://bedrock-agentcore.{self.region}.amazonaws.com/runtimes/{encoded_arn}/invocations?qualifier=DEFAULT"
        )
        target = agentcore.CfnGatewayTarget(
            self,
            "Target",
            gateway_identifier=gateway.attr_gateway_identifier,
            name=TARGET_NAME,
            description="FairTable MCP server on AgentCore Runtime",
            target_configuration=agentcore.CfnGatewayTarget.TargetConfigurationProperty(
                mcp=agentcore.CfnGatewayTarget.McpTargetConfigurationProperty(
                    mcp_server=agentcore.CfnGatewayTarget.McpServerTargetConfigurationProperty(
                        endpoint=endpoint, listing_mode="DEFAULT"
                    )
                )
            ),
            credential_provider_configurations=[
                agentcore.CfnGatewayTarget.CredentialProviderConfigurationProperty(
                    credential_provider_type="GATEWAY_IAM_ROLE",
                    credential_provider=agentcore.CfnGatewayTarget.CredentialProviderProperty(
                        iam_credential_provider=agentcore.CfnGatewayTarget.IamCredentialProviderProperty(
                            service="bedrock-agentcore", region=self.region
                        )
                    ),
                )
            ],
            metadata_configuration=agentcore.CfnGatewayTarget.MetadataConfigurationProperty(
                allowed_request_headers=[USER_TOKEN_HEADER]
            ),
        )
        target.node.add_dependency(role)  # the role's policy must exist before the first synchronisation

        self.gateway = gateway
        CfnOutput(self, "GatewayUrl", value=gateway.attr_gateway_url)
        CfnOutput(self, "GatewayId", value=gateway.attr_gateway_identifier)
        Tags.of(self).add("project", "fairtable")
