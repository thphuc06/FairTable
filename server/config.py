"""Server settings, read from the environment. Nothing account-specific is hard-coded."""

import os
from dataclasses import dataclass, field

from server.store import StoreConfig

# A public, obviously-fake secret for the local profile only. The AWS profile refuses to start with it.
DEV_SLOT_SECRET = "dev-only-slot-token-secret-do-not-use-elsewhere"
DEV_SESSION_SECRET = "dev-only-web-session-secret-do-not-use-elsewhere"


def _csv(value: str | None) -> list[str]:
    return [p.strip() for p in (value or "").split(",") if p.strip()]


@dataclass(frozen=True)
class Settings:
    profile: str = "local"  # "local" | "aws"
    host: str = "127.0.0.1"
    port: int = 8000
    allowed_hosts: list[str] = field(default_factory=list)  # extra Host values (hosted profiles)
    allowed_origins: list[str] = field(default_factory=list)
    stateless_http: bool = True  # AgentCore Runtime and Alexa+ send no MCP session id: stateless is the default (MCP_STATELESS=false for a session)
    issuer: str = "http://localhost:9000"
    audience: str | tuple[str, ...] = ("fairtable-mcp",)  # AUTH_AUDIENCE may list several, comma separated
    audience_claim: str = "aud"
    token_use: str | None = None  # AUTH_TOKEN_USE=access on Cognito
    jwks_url: str = "http://localhost:9000/.well-known/jwks.json"
    slot_token_secret: str = DEV_SLOT_SECRET  # signs the read-back codes (the name is kept: the deployed secret is called this)
    offer_ttl_s: int = 900  # how long an offer_id from availability_check can be used to hold the table (D-059)
    hold_ttl_s: int = 600
    match_hold_ttl_s: int = 1800  # a waitlist match: the diner is not in a conversation when the table opens (D-054)
    drop_hold_ttl_s: int = 7200  # a Fair Drop winner (D-054)
    rate_limit_per_hour: int = 20
    web_public_url: str = "http://localhost:8080"  # where people open the web app; https makes the cookie secure
    web_host: str = "127.0.0.1"
    web_port: int = 8080
    web_session_secret: str = DEV_SESSION_SECRET
    token_url: str = ""  # where the web pages sign diners in; empty = AUTH_ISSUER + /token (docker: the issuer's service name)
    mcp_url: str = "http://127.0.0.1:8000/mcp"  # where the chat page's assistant reaches the MCP server
    mcp_via_gateway: bool = False  # MCP_URL is an AgentCore Gateway: bearer token in, tools named <target>___<tool>
    mcp_tool_prefix: str = ""  # "ft___" via the gateway, otherwise empty
    auth_provider: str = "dev"  # how the web pages sign people in: "dev" (the dev issuer) or "cognito"
    cognito_client_id: str = ""  # the app client the pages sign in with (its secret is read from the environment, not kept here)
    cognito_region: str = ""
    notify_topic_arn: str = ""  # an SNS topic for waitlist and Fair Drop notices (AWS profile; empty = the dev inbox only)
    audit_bucket: str = ""  # an S3 bucket that gets a copy of every Fair Drop audit (AWS profile; empty = DynamoDB only)
    store: StoreConfig = field(default_factory=lambda: StoreConfig("fairtable-dev"))

    def __post_init__(self) -> None:
        if self.profile not in ("local", "aws"):
            raise ValueError("APP_PROFILE must be 'local' or 'aws'")
        if self.profile == "aws" and self.slot_token_secret == DEV_SLOT_SECRET:
            raise ValueError("SLOT_TOKEN_SECRET must be set to a real secret in the aws profile")
        if self.profile == "aws" and self.web_session_secret == DEV_SESSION_SECRET:
            raise ValueError("WEB_SESSION_SECRET must be set to a real secret in the aws profile")
        if self.auth_provider not in ("dev", "cognito"):
            raise ValueError("AUTH_PROVIDER must be 'dev' or 'cognito'")
        if self.auth_provider == "cognito" and not self.cognito_client_id:
            raise ValueError("AUTH_PROVIDER=cognito needs COGNITO_CLIENT_ID")

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ) if env is None else env
        issuer = env.get("AUTH_ISSUER", cls.issuer)
        via_gateway = env.get("MCP_VIA_GATEWAY", "").strip().lower() in ("1", "true", "yes")
        return cls(
            profile=env.get("APP_PROFILE", "local"),
            host=env.get("MCP_HOST", cls.host),
            port=int(env.get("MCP_PORT", cls.port)),
            allowed_hosts=_csv(env.get("MCP_ALLOWED_HOSTS")),
            allowed_origins=_csv(env.get("MCP_ALLOWED_ORIGINS")),
            stateless_http=env.get("MCP_STATELESS", "true").strip().lower() not in ("0", "false", "no"),
            issuer=issuer,
            audience=tuple(_csv(env.get("AUTH_AUDIENCE"))) or cls.audience,
            token_use=env.get("AUTH_TOKEN_USE") or None,
            audience_claim=env.get("AUTH_AUDIENCE_CLAIM", cls.audience_claim),
            jwks_url=env.get("AUTH_JWKS_URL", issuer.rstrip("/") + "/.well-known/jwks.json"),
            slot_token_secret=env.get("SLOT_TOKEN_SECRET", DEV_SLOT_SECRET),
            offer_ttl_s=int(env.get("OFFER_TTL_S", cls.offer_ttl_s)),
            hold_ttl_s=int(env.get("HOLD_TTL_S", cls.hold_ttl_s)),
            match_hold_ttl_s=int(env.get("MATCH_HOLD_TTL_S", cls.match_hold_ttl_s)),
            drop_hold_ttl_s=int(env.get("DROP_HOLD_TTL_S", cls.drop_hold_ttl_s)),
            rate_limit_per_hour=int(env.get("RATE_LIMIT_PER_HOUR", cls.rate_limit_per_hour)),
            web_public_url=env.get("WEB_PUBLIC_URL") or cls.web_public_url,
            web_host=env.get("WEB_HOST", cls.web_host),
            web_port=int(env.get("WEB_PORT", cls.web_port)),
            web_session_secret=env.get("WEB_SESSION_SECRET", DEV_SESSION_SECRET),
            token_url=env.get("AUTH_TOKEN_URL") or issuer.rstrip("/") + "/token",
            mcp_url=env.get("MCP_URL", cls.mcp_url),
            mcp_via_gateway=via_gateway,
            mcp_tool_prefix=(env.get("MCP_TOOL_PREFIX") or "ft___") if via_gateway else "",
            auth_provider=env.get("AUTH_PROVIDER", cls.auth_provider),
            cognito_client_id=env.get("COGNITO_CLIENT_ID", ""),
            cognito_region=env.get("COGNITO_REGION") or env.get("AWS_REGION", ""),
            notify_topic_arn=env.get("NOTIFY_TOPIC_ARN", "").strip(),
            audit_bucket=env.get("AUDIT_BUCKET", "").strip(),
            store=StoreConfig.from_env(env),
        )
