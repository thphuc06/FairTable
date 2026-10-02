"""Holds and reservations (design section 7.1) and their pure rules."""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from server.domain.models import Venue

HOLD_TTL_S = 600  # a hold lasts 10 minutes
MAX_ACTIVE_HOLDS = 2  # per user per restaurant; must equal the Cedar rule S1 (a test checks it)

HOLD_HELD = "held"
HOLD_CONFIRMED = "confirmed"
HOLD_EXPIRED = "expired"
HOLD_RELEASED = "released"

RES_CONFIRMED = "confirmed"
RES_CANCELLED = "cancelled"


@dataclass(frozen=True)
class Hold:
    hold_id: str
    sub: str
    agent_id: str | None
    venue_id: str
    date: str
    time: str
    table_group: str
    party_size: int
    status: str
    held_until: str  # ISO, checked on read (never TTL)
    created_at: str
    terms: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    code: str
    hold_id: str
    sub: str
    agent_id: str | None
    venue_id: str
    date: str
    time: str
    table_group: str
    party_size: int
    status: str
    terms_snapshot: dict[str, Any]
    created_at: str
    cancelled_at: str | None = None
    cancel_fee_cents: int | None = None
    # How the booking was confirmed (D-051): the assistant relays the diner's spoken yes. The server cannot
    # hear it, so it stores what it can know: when the read-back was handed over (None if no valid token came).
    confirmation: str = "spoken"
    read_back_at: str | None = None
    cancel_read_back_at: str | None = None  # when the fee was read back, for a cancellation that cost money


# ------------------------------------------------------------------ terms and codes
def terms_for(venue: Venue, date: str, time: str, party_size: int, **extra: Any) -> dict[str, Any]:
    return {
        "restaurant": venue.name,
        "restaurant_id": venue.venue_id,
        "date": date,
        "time": time,
        "party_size": party_size,
        "cancel_fee_cents": venue.cancel_fee_cents,
        "free_cancel_hours": venue.free_cancel_hours,
        **extra,
    }


def terms_hash(terms: dict[str, Any]) -> str:
    canonical = json.dumps(terms, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def reservation_code(venue_id: str, reservation_id: str) -> str:
    """A short readable code such as ``LUN-4821``. Display only: lookups use the reservation id."""
    prefix = "".join(c for c in venue_id.upper() if c.isalpha())[:3].ljust(3, "X")
    number = 1000 + int(hashlib.sha256(reservation_id.encode()).hexdigest(), 16) % 9000
    return f"{prefix}-{number}"


def starts_at(date: str, time: str) -> datetime:
    """Slot times are wall-clock times in the server's time zone (UTC by default), D-019."""
    return datetime.fromisoformat(f"{date}T{time}:00+00:00").astimezone(UTC)


def cancel_fee_cents(venue: Venue, date: str, time: str, now: datetime) -> int:
    """The flat venue fee applies when the booking starts inside the free-cancellation window."""
    hours_left = (starts_at(date, time) - now).total_seconds() / 3600
    return venue.cancel_fee_cents if hours_left < venue.free_cancel_hours else 0
