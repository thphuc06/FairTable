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
    stateless_http: bool = False  # AgentCore Runtime requires stateless Streamable HTTP (MCP_STATELESS=true)
    issuer: str = "http://localhost:9000"
    audience: str = "fairtable-mcp"
    audience_claim: str = "aud"
    jwks_url: str = "http://localhost:9000/.well-known/jwks.json"
    slot_token_secret: str = DEV_SLOT_SECRET
    slot_token_ttl_s: int = 900
    hold_ttl_s: int = 600
    rate_limit_per_hour: int = 20
    consent_base_url: str = "http://localhost:8080"
    web_host: str = "127.0.0.1"
    web_port: int = 8080
    web_session_secret: str = DEV_SESSION_SECRET
    token_url: str = ""  # where the web pages sign diners in; empty = AUTH_ISSUER + /token (docker: the issuer's service name)
    mcp_url: str = "http://127.0.0.1:8000/mcp"  # where the chat page's assistant reaches the MCP server
    store: StoreConfig = field(default_factory=lambda: StoreConfig("fairtable-dev"))

    def __post_init__(self) -> None:
        if self.profile not in ("local", "aws"):
            raise ValueError("APP_PROFILE must be 'local' or 'aws'")
        if self.profile == "aws" and self.slot_token_secret == DEV_SLOT_SECRET:
            raise ValueError("SLOT_TOKEN_SECRET must be set to a real secret in the aws profile")
        if self.profile == "aws" and self.web_session_secret == DEV_SESSION_SECRET:
            raise ValueError("WEB_SESSION_SECRET must be set to a real secret in the aws profile")

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ) if env is None else env
        issuer = env.get("AUTH_ISSUER", cls.issuer)
        return cls(
            profile=env.get("APP_PROFILE", "local"),
            host=env.get("MCP_HOST", cls.host),
            port=int(env.get("MCP_PORT", cls.port)),
            allowed_hosts=_csv(env.get("MCP_ALLOWED_HOSTS")),
            allowed_origins=_csv(env.get("MCP_ALLOWED_ORIGINS")),
            stateless_http=env.get("MCP_STATELESS", "").strip().lower() in ("1", "true", "yes"),
            issuer=issuer,
            audience=env.get("AUTH_AUDIENCE", cls.audience),
            audience_claim=env.get("AUTH_AUDIENCE_CLAIM", cls.audience_claim),
            jwks_url=env.get("AUTH_JWKS_URL", issuer.rstrip("/") + "/.well-known/jwks.json"),
            slot_token_secret=env.get("SLOT_TOKEN_SECRET", DEV_SLOT_SECRET),
            slot_token_ttl_s=int(env.get("SLOT_TOKEN_TTL_S", cls.slot_token_ttl_s)),
            hold_ttl_s=int(env.get("HOLD_TTL_S", cls.hold_ttl_s)),
            rate_limit_per_hour=int(env.get("RATE_LIMIT_PER_HOUR", cls.rate_limit_per_hour)),
            consent_base_url=env.get("CONSENT_BASE_URL", cls.consent_base_url),
            web_host=env.get("WEB_HOST", cls.web_host),
            web_port=int(env.get("WEB_PORT", cls.web_port)),
            web_session_secret=env.get("WEB_SESSION_SECRET", DEV_SESSION_SECRET),
            token_url=env.get("AUTH_TOKEN_URL") or issuer.rstrip("/") + "/token",
            mcp_url=env.get("MCP_URL", cls.mcp_url),
            store=StoreConfig.from_env(env),
        )
