"""The owner console on AWS (plan task P3-22, decision D-068): API Gateway HTTP API in front of one Lambda.

`web.lambda_handler.handler` (Mangum around the FastAPI app of `web/`) comes from the same zip as the Runtime and the
workers (arm64, Python 3.12). It serves the sign-in and the owner console only. Owners sign in through the Cognito app
client of the demo agent (`alexa-plus-sim`, with its secret, the same path as the local web app with
`AUTH_PROVIDER=cognito`), so the token carries the claims the console reads (owners group, `custom:venue_id`).

* The session key is a generated Secrets Manager secret handed over as a CloudFormation dynamic reference, like the slot
  secret of the Runtime: no value in the repo or in a command. The same value fills `SLOT_TOKEN_SECRET` because the aws
  profile refuses the public dev default; the console does not use it.
* The function may do what the store does and `kms:GenerateRandom` (the seed of a new Fair Drop); nothing else. Cognito's
  `InitiateAuth` is unauthenticated and needs no permission.
* The stage is throttled (burst 10, 5 requests a second): the console is for a handful of owners, and a sign-in form is
  the thing that gets hammered.
* Public address: the API's own `execute-api` URL, output as `OwnerUrl`. `WEB_PUBLIC_URL` is only used for the secure
  cookie flag, so any `https://` value works; the real URL is not wired in (it would make the function and the API
  depend on each other).

Prices checked 2026-10-04 are in the research notes of D-068; at demo traffic they come to cents.
"""

from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack, Tags
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct

HANDLER = "web.lambda_handler.handler"
FUNCTION_NAME = "FairTableOwnerWeb"


class OwnerWebStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        table: dynamodb.ITable,
        issuer: str,
        sign_in_client: cognito.IUserPoolClient,
        package_path: Path,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        session_secret = secretsmanager.Secret(
            self,
            "SessionSecret",
            description="HMAC key for the owner console session cookie",
            generate_secret_string=secretsmanager.SecretStringGenerator(password_length=48, exclude_punctuation=True),
            removal_policy=RemovalPolicy.DESTROY,
        )
        log_group = logs.LogGroup(
            self, "Logs", log_group_name=f"/aws/lambda/{FUNCTION_NAME}", retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY)
        secret_value = session_secret.secret_value.unsafe_unwrap()
        function = lambda_.Function(
            self,
            "Function",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler=HANDLER,
            code=lambda_.Code.from_asset(str(package_path)),
            timeout=Duration.seconds(15),
            memory_size=512,
            function_name=FUNCTION_NAME,
            log_group=log_group,
            description="FairTable owner console (sign-in, cancellation terms, Fair Drops, audit)",
            environment={
                "APP_PROFILE": "aws",
                "TABLE_NAME": table.table_name,
                "AUTH_PROVIDER": "cognito",
                "AUTH_ISSUER": issuer,
                "AUTH_JWKS_URL": f"{issuer}/.well-known/jwks.json",
                "AUTH_AUDIENCE_CLAIM": "client_id",
                "AUTH_AUDIENCE": sign_in_client.user_pool_client_id,
                "AUTH_TOKEN_USE": "access",
                "COGNITO_CLIENT_ID": sign_in_client.user_pool_client_id,
                "COGNITO_CLIENT_SECRET": sign_in_client.node.default_child.attr_client_secret,  # a GetAtt, resolved at deploy time
                "COGNITO_REGION": self.region,
                "WEB_SESSION_SECRET": secret_value,
                "SLOT_TOKEN_SECRET": secret_value,
                "WEB_PUBLIC_URL": "https://owner-console.invalid",  # only its https scheme is used (secure cookie)
                "SEED_PROVIDER": "kms",
            },
        )
        function.add_to_role_policy(iam.PolicyStatement(
            actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:UpdateItem",
                     "dynamodb:DeleteItem", "dynamodb:ConditionCheckItem"],
            resources=[table.table_arn, f"{table.table_arn}/index/*"]))
        function.add_to_role_policy(iam.PolicyStatement(actions=["kms:GenerateRandom"], resources=["*"]))

        api = apigw.HttpApi(
            self,
            "Api",
            api_name="fairtable-owner-console",
            description="FairTable owner console",
            default_integration=integrations.HttpLambdaIntegration("Console", function),
            create_default_stage=True,
        )
        stage = api.default_stage.node.default_child  # CfnStage
        stage.add_property_override("DefaultRouteSettings", {"ThrottlingBurstLimit": 10, "ThrottlingRateLimit": 5})

        self.function = function
        self.api = api
        CfnOutput(self, "OwnerUrl", value=api.api_endpoint)
        Tags.of(self).add("project", "fairtable")
