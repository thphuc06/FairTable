"""Small shared domain models. Richer models (venue, slot, hold, ...) arrive with the store (P1-6)."""

from dataclasses import dataclass, field

SCOPE_BOOK = "fairtable/book"
TIER_VERIFIED = "verified"


@dataclass(frozen=True)
class Identity:
    """A verified caller, built only by the token verifier from a validated JWT."""

    sub: str
    username: str | None = None  # absent on M2M (bot) tokens
    agent_tier: str | None = None  # absent unless the issuer adds the claim
    agent_id: str | None = None
    scopes: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_user(self) -> bool:
        return self.username is not None

    @property
    def is_verified_agent(self) -> bool:
        return self.agent_tier == TIER_VERIFIED

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes
