"""DynamoDB single-table key builders (design section 5.4). Pure functions, no I/O.

Every id that goes into a key is validated: a ``#`` or control character in a user-controlled value
(for example ``sub`` or an idempotency key) could otherwise make two different entities share a key.
"""

from typing import NamedTuple

MAX_PART = 128


class Key(NamedTuple):
    pk: str
    sk: str


def part(value: object, name: str = "id") -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_PART:
        raise ValueError(f"{name} must be a non-empty string up to {MAX_PART} characters")
    if "#" in value or not value.isprintable():
        raise ValueError(f"{name} must not contain '#' or control characters")
    return value


def venue(venue_id: str) -> Key:
    return Key(f"REST#{part(venue_id, 'venue_id')}", "PROFILE")


def slot_day(venue_id: str, date: str) -> str:
    return f"REST#{part(venue_id, 'venue_id')}#D#{part(date, 'date')}"


def slot(venue_id: str, date: str, time: str, table_group: str) -> Key:
    hhmm = part(time, "time").replace(":", "")
    return Key(slot_day(venue_id, date), f"SLOT#{hhmm}#{part(table_group, 'table_group')}")


def active_holds_counter(sub: str, venue_id: str) -> Key:
    return Key(f"CNT#USER#{part(sub, 'sub')}#REST#{part(venue_id, 'venue_id')}", "ACTIVE_HOLDS")


def agent_covers_counter(venue_id: str, date: str) -> Key:
    return Key(f"CNT#REST#{part(venue_id, 'venue_id')}#D#{part(date, 'date')}", "AGENT_COVERS")


def hold(hold_id: str) -> Key:
    return Key(f"HOLD#{part(hold_id, 'hold_id')}", "META")


def hold_day_partition(venue_id: str, date: str) -> str:
    return f"HOLDS#{part(venue_id, 'venue_id')}#{part(date, 'date')}"


def offer(code: str) -> Key:
    return Key(f"OFFER#{part(code, 'offer_id')}", "META")


def user_partition(sub: str) -> str:
    return f"USER#{part(sub, 'sub')}"


def inbox_partition(sub: str) -> str:
    return f"INBOX#{part(sub, 'sub')}"


def inbox(sub: str, timestamp: str, message_id: str) -> Key:
    return Key(inbox_partition(sub), f"{part(timestamp, 'timestamp')}#{part(message_id, 'message_id')}")


def watch(watch_id: str) -> Key:
    return Key(f"WATCH#{part(watch_id, 'watch_id')}", "META")


def watch_slot(sub: str, venue_id: str, date: str) -> Key:
    """One active watch per person per restaurant per day is a conditional write on this key."""
    return Key(f"WATCHKEY#{part(sub, 'sub')}#{part(venue_id, 'venue_id')}#{part(date, 'date')}", "META")


def watch_day_partition(venue_id: str, date: str) -> str:
    return f"WATCHES#{part(venue_id, 'venue_id')}#{part(date, 'date')}"


def drop(drop_id: str) -> Key:
    return Key(f"DROP#{part(drop_id, 'drop_id')}", "META")


def drop_partition(drop_id: str) -> str:
    return f"DROP#{part(drop_id, 'drop_id')}"


def entry(drop_id: str, digest: str) -> Key:
    """One ticket per person per drop is a conditional write on this key (ticket hash, no sub)."""
    return Key(drop_partition(drop_id), f"ENTRY#{part(digest, 'entry')}")


def reservation(reservation_id: str) -> Key:
    return Key(f"RES#{part(reservation_id, 'reservation_id')}", "META")


def idempotency(sub: str, idempotency_key: str) -> Key:
    return Key(f"IDEM#{part(sub, 'sub')}#{part(idempotency_key, 'idempotency_key')}", "META")


def audit_partition(venue_id: str, date: str) -> str:
    return f"AUDIT#{part(venue_id, 'venue_id')}#{part(date, 'date')}"


def audit(venue_id: str, date: str, timestamp: str, request_id: str) -> Key:
    return Key(
        audit_partition(venue_id, date),
        f"{part(timestamp, 'timestamp')}#{part(request_id, 'request_id')}",
    )


def rate_bucket(sub: str, venue_id: str) -> Key:
    return Key(f"RL#{part(sub, 'sub')}#{part(venue_id, 'venue_id')}", "BUCKET")


# Overloaded global secondary indexes (attribute names on the items).
GSI1 = "GSI1"  # GSI1PK / GSI1SK: venue directory now; hold-expiry buckets later
GSI2 = "GSI2"  # GSI2PK / GSI2SK: a user's holds and reservations later
VENUE_DIRECTORY = "VENUE"
