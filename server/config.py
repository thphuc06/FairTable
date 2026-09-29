"""Server settings, read from the environment. Nothing account-specific is hard-coded."""

import os
from dataclasses import dataclass, field

from server.store import StoreConfig

# A public, obviously-fake secret for the local profile only. The AWS profile refuses to start with it.
DEV_SLOT_SECRET = "dev-only-slot-token-secret-do-not-use-elsewhere"


def _csv(value: str | None) -> list[str]:
    return [p.strip() for p in (value or "").split(",") if p.strip()]


@dataclass(frozen=True)
class Settings:
    profile: str = "local"  # "local" | "aws"
    host: str = "127.0.0.1"
    port: int = 8000
    allowed_hosts: list[str] = field(default_factory=list)  # extra Host values (hosted profiles)
    allowed_origins: list[str] = field(default_factory=list)
    issuer: str = "http://localhost:9000"
    audience: str = "fairtable-mcp"
    audience_claim: str = "aud"
    jwks_url: str = "http://localhost:9000/.well-known/jwks.json"
    slot_token_secret: str = DEV_SLOT_SECRET
    slot_token_ttl_s: int = 900
    rate_limit_per_hour: int = 20
    consent_base_url: str = "http://localhost:8080"
    store: StoreConfig = field(default_factory=lambda: StoreConfig("fairtable-dev"))

    def __post_init__(self) -> None:
        if self.profile not in ("local", "aws"):
            raise ValueError("APP_PROFILE must be 'local' or 'aws'")
        if self.profile == "aws" and self.slot_token_secret == DEV_SLOT_SECRET:
            raise ValueError("SLOT_TOKEN_SECRET must be set to a real secret in the aws profile")

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
            issuer=issuer,
            audience=env.get("AUTH_AUDIENCE", cls.audience),
            audience_claim=env.get("AUTH_AUDIENCE_CLAIM", cls.audience_claim),
            jwks_url=env.get("AUTH_JWKS_URL", issuer.rstrip("/") + "/.well-known/jwks.json"),
            slot_token_secret=env.get("SLOT_TOKEN_SECRET", DEV_SLOT_SECRET),
            slot_token_ttl_s=int(env.get("SLOT_TOKEN_TTL_S", cls.slot_token_ttl_s)),
            rate_limit_per_hour=int(env.get("RATE_LIMIT_PER_HOUR", cls.rate_limit_per_hour)),
            consent_base_url=env.get("CONSENT_BASE_URL", cls.consent_base_url),
            store=StoreConfig.from_env(env),
        )
