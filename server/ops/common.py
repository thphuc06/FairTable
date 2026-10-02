"""Helpers shared by the write operations."""

from datetime import datetime
from typing import Any

from server.domain.availability import offered_slots
from server.domain.errors import ErrorCode, FairTableError
from server.domain.models import Slot
from server.store import Store, keys

FULL_DAY = ("00:00", "23:59")


def parse_slot_key(slot_key: str) -> tuple[str, str]:
    """'1900#T4' -> ('19:00', 'T4')."""
    hhmm, sep, group = slot_key.partition("#")
    if not sep or len(hhmm) != 4 or not hhmm.isdigit() or not group:
        raise FairTableError(ErrorCode.INVALID_OFFER, "That table offer is no longer valid.",
                         hint="Use the offer_id from a fresh availability result.", reason="slot_key")
    return f"{hhmm[:2]}:{hhmm[2:]}", group


def counter_value(store: Store, key: keys.Key) -> int:
    item = store.get_item(key)
    return int(item["n"]) if item else 0


def parse_iso(moment: str) -> datetime:
    return datetime.fromisoformat(moment)


def alternatives(store: Store, venue_id: str, date: str, party_size: int, now: datetime,
                 exclude: Slot | None = None, limit: int = 3) -> list[dict[str, Any]]:
    """Other open times the same day, to help the agent recover from SLOT_TAKEN."""
    slots = offered_slots(store.get_slots(venue_id, date, consistent=True), party_size=party_size,
                          window=FULL_DAY, now=now)
    picked = [s for s in slots if not (exclude and s.slot_key == exclude.slot_key)]
    return [{"time": s.time, "table_seats": s.seats} for s in picked[:limit]]


def capacity_condition(limit: int) -> str:
    """'counter + x <= cap' written as 'counter <= cap - x' (DynamoDB has no arithmetic in
    conditions). A missing counter counts as 0, but only when even 0 fits."""
    return "attribute_not_exists(n) OR n <= :limit" if limit >= 0 else "n <= :limit"


# The spoken-confirmation facts (S5a-c) for every call that is not a confirm or a cancel with a fee: the rules
# do not apply, and Cedar still needs a complete context (docs/PLAN.md section 3a).
NO_READ_BACK = {
    "read_back_required": False, "read_back_matches": False, "pause_elapsed": False, "user_confirmed": False,
}
