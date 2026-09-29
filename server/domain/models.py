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


# ---------------------------------------------------------------------------- store-backed models
SLOT_OPEN = "open"
SLOT_HELD = "held"
SLOT_CONFIRMED = "confirmed"
MANDATE_ACTIVE = "active"
MANDATE_REVOKED = "revoked"


@dataclass(frozen=True)
class Venue:
    venue_id: str
    name: str
    cuisine: str
    city: str
    description: str
    seats_per_day: int  # total covers the restaurant offers per day
    agent_share_pct: int  # owner-set: share of covers agents may book (0-100)
    cancel_fee_cents: int  # fee when cancelling inside the free window
    free_cancel_hours: int  # cancelling earlier than this many hours before is free

    @property
    def agent_cover_cap(self) -> int:
        """Covers per day that agents may book (input to rule S2)."""
        return self.seats_per_day * self.agent_share_pct // 100


@dataclass(frozen=True)
class Slot:
    venue_id: str
    date: str  # ISO date
    time: str  # "19:00"
    table_group: str  # "T2", "T4", "T6"
    seats: int
    status: str = SLOT_OPEN
    ver: int = 1  # bumped on every state change; the write condition compares it
    hot: bool = False
    drop_id: str | None = None  # set when the slot is released through a Fair Drop
    held_until: str | None = None  # ISO timestamp while status == held; checked on read (no TTL)

    @property
    def slot_key(self) -> str:
        return f"{self.time.replace(':', '')}#{self.table_group}"

    @property
    def drop_controlled(self) -> bool:
        return self.drop_id is not None

    def effective_status(self, now_iso: str) -> str:
        """A hold whose ``held_until`` has passed counts as open (lazy expiry, design D4)."""
        if self.status == SLOT_HELD and self.held_until is not None and self.held_until <= now_iso:
            return SLOT_OPEN
        return self.status


@dataclass(frozen=True)
class Mandate:
    """A standing permission a user gave for one restaurant (design section 4.2)."""

    sub: str
    venue_id: str
    status: str
    version: int
    party_size_max: int
    days_ahead_max: int
    window_start: str  # "17:00"
    window_end: str  # "22:00"
    max_cancel_fee_cents: int
    allow_auto_confirm: bool
    actions: frozenset[str]
    agent_ids: frozenset[str]
    approved_at: str  # ISO timestamp
    expires_at: str  # ISO timestamp
