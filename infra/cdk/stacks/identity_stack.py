"""Cognito user pool, pre token trigger and app clients (plan task P2-2, decision D-035).

Mirrors the dev issuer (`devauth/`): the same three app clients by name, the same scope
(`fairtable/book`), the `owners` group and the `custom:venue_id` attribute. The claims the server reads
are added by `infra/cognito/pre_token/handler.py` (trigger event version V3_0, so that machine tokens
get them too). Sign-in for the demo is `USER_PASSWORD_AUTH` (D-035); the pool allows no self sign-up.
"""

from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack, Tags
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from constructs import Construct

PRE_TOKEN_DIR = Path(__file__).resolve().parents[2] / "cognito" / "pre_token"
RESOURCE_SERVER = "fairtable"
BOOK_SCOPE_NAME = "book"  # the scope in tokens is "fairtable/book"


class IdentityStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, domain_prefix: str | None = None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        log_group = logs.LogGroup(
            self, "PreTokenLogs", retention=logs.RetentionDays.ONE_WEEK, removal_policy=RemovalPolicy.DESTROY
        )
        pre_token = lambda_.Function(
            self,
            "PreToken",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset(str(PRE_TOKEN_DIR)),
            timeout=Duration.seconds(5),
            memory_size=128,
            log_group=log_group,
        )
        # The app client id is only known after deployment, so the function finds the client's name
        # instead (wiring the id in would make the pool and the function depend on each other).
        pre_token.add_to_role_policy(
            iam.PolicyStatement(
                actions=["cognito-idp:DescribeUserPoolClient"],
                resources=[self.format_arn(service="cognito-idp", resource="userpool", resource_name="*")],
            )
        )

        pool = cognito.UserPool(
            self,
            "Pool",
            user_pool_name="fairtable-users",
            feature_plan=cognito.FeaturePlan.ESSENTIALS,  # V2_0 / V3_0 trigger events need Essentials or Plus
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(username=True),
            password_policy=cognito.PasswordPolicy(
                # Demo accounts with the public dev passwords of the README (lowercase and hyphens).
                min_length=8,
                require_lowercase=False,
                require_uppercase=False,
                require_digits=False,
                require_symbols=False,
            ),
            custom_attributes={"venue_id": cognito.StringAttribute(min_len=1, max_len=64, mutable=True)},
            account_recovery=cognito.AccountRecovery.NONE,
            mfa=cognito.Mfa.OFF,
            removal_policy=RemovalPolicy.DESTROY,
            deletion_protection=False,
        )
        pool.add_trigger(
            cognito.UserPoolOperation.PRE_TOKEN_GENERATION_CONFIG, pre_token, lambda_version=cognito.LambdaVersion.V3_0
        )
        cognito.CfnUserPoolGroup(self, "OwnersGroup", user_pool_id=pool.user_pool_id, group_name="owners")

        book = cognito.ResourceServerScope(scope_name=BOOK_SCOPE_NAME, scope_description="Book tables for a diner")
        server = pool.add_resource_server("Api", identifier=RESOURCE_SERVER, scopes=[book])
        book_scope = cognito.OAuthScope.resource_server(server, book)
        machine = cognito.OAuthSettings(
            flows=cognito.OAuthFlows(client_credentials=True), scopes=[book_scope]
        )

        # Same names as devauth/accounts.py: the trigger finds the agent profile by name.
        clients = {
            # The simulated Alexa+ agent: diners sign in through it, and it also works as a machine.
            "alexa-plus-sim": pool.add_client(
                "AlexaSim",
                user_pool_client_name="alexa-plus-sim",
                generate_secret=True,
                auth_flows=cognito.AuthFlow(user_password=True),
                o_auth=machine,
                **self._common(),
            ),
            # An agent that has not been verified (shows the G4 / P0 refusals).
            "shady-agent": pool.add_client(
                "ShadyAgent",
                user_pool_client_name="shady-agent",
                auth_flows=cognito.AuthFlow(user_password=True),
                disable_o_auth=True,
                **self._common(),
            ),
            # A machine client without agent claims (RT1 and RT3).
            "bot-m2m": pool.add_client(
                "BotM2M",
                user_pool_client_name="bot-m2m",
                generate_secret=True,
                o_auth=machine,
                **self._common(),
            ),
        }

        # CDK leaves ExplicitAuthFlows out when no flow is enabled, and Cognito then turns on its own
        # defaults (user SRP and custom auth). A machine client needs no user sign-in at all.
        clients["bot-m2m"].node.default_child.add_property_override("ExplicitAuthFlows", ["ALLOW_REFRESH_TOKEN_AUTH"])

        self.pool = pool
        self.clients = clients

        prefix = domain_prefix or f"fairtable-{self.account}"
        domain = pool.add_domain("Domain", cognito_domain=cognito.CognitoDomainOptions(domain_prefix=prefix))

        self.domain_base_url = domain.base_url()

        CfnOutput(self, "UserPoolId", value=pool.user_pool_id)
        CfnOutput(self, "Issuer", value=pool.user_pool_provider_url)
        CfnOutput(self, "TokenEndpoint", value=f"{domain.base_url()}/oauth2/token")
        for name, client in clients.items():
            CfnOutput(self, f"ClientId{name.title().replace('-', '')}", value=client.user_pool_client_id)
        Tags.of(self).add("project", "fairtable")

    @staticmethod
    def _common() -> dict:
        return {
            "prevent_user_existence_errors": True,
            "enable_token_revocation": True,
            "access_token_validity": Duration.hours(1),
            "id_token_validity": Duration.hours(1),
            "refresh_token_validity": Duration.days(1),
        }
