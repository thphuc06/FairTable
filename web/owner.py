"""Owner console actions beyond the agent share: cancellation terms and the creation of a Fair Drop (D-067).

Every change is one DynamoDB transaction together with its audit entry, and only the restaurant's own owner reaches
it (``web/app.py`` checks the session). The checks live here as small functions so that they are tested without a
browser: each returns an error text for the page, or ``None`` when the change was made.
"""

import re
from dataclasses import dataclass
from datetime import timedelta

from server.domain.audit import AuditEntry
from server.domain.booking import starts_at
from server.domain.clock import iso_z
from server.domain.fairdrop import Drop, commitment
from server.domain.models import SLOT_OPEN, Slot
from server.store import TransactionCancelled, TxOp, keys
from server.store.mappers import drop_to_item

MAX_FEE_DOLLARS = 200
MAX_FREE_CANCEL_HOURS = 168
DRAW_HOURS_BEFORE = (24, 12, 6, 2)  # how long before the seat the draw happens
MIN_LEAD = timedelta(minutes=10)  # entries need a moment to open before the draw
LOOKAHEAD_DAYS = 14
MAX_SEATS_LISTED = 600  # a restaurant has a few hundred open seats in two weeks; the page groups them by day
FEE = re.compile(r"[0-9]{1,3}(\.[0-9]{1,2})?")
HOURS = re.compile(r"[0-9]{1,3}")


@dataclass(frozen=True)
class SeatOption:
    """A seat the owner may release through a Fair Drop."""

    value: str  # "2026-10-16|20:00|T2"
    label: str
    slot: Slot


def drop_id_for(slot: Slot) -> str:
    return f"drop-{slot.venue_id}-{slot.date}-{slot.time.replace(':', '')}-{slot.table_group}".lower()


def _audit(deps, session, venue_id: str, now_iso: str, detail: dict) -> AuditEntry:
    return AuditEntry(
        venue_id=venue_id, timestamp=now_iso, request_id=deps.new_id(), sub=session.sub, agent_id=None,
        tool="owner_console", decision="changed", rule_ids=(), detail=detail,
    )


# ---------------------------------------------------------------------------------------------- cancellation terms
def change_cancellation_terms(deps, session, fee: str, hours: str) -> str | None:
    """Set the fee (dollars) and the free-cancellation window (hours before the table). New holds read the new terms;
    a hold or a booking keeps the terms it was made with (its snapshot)."""
    fee, hours = fee.strip(), hours.strip()
    if not FEE.fullmatch(fee) or float(fee) > MAX_FEE_DOLLARS:
        return f"The fee is an amount in dollars from 0 to {MAX_FEE_DOLLARS}, for example 25 or 12.50."
    if not HOURS.fullmatch(hours) or int(hours) > MAX_FREE_CANCEL_HOURS:
        return f"The free-cancellation window is a whole number of hours from 0 to {MAX_FREE_CANCEL_HOURS}."
    venue_id = session.owner_of
    venue = deps.store.get_venue(venue_id or "")
    if venue is None:
        return "Your restaurant is not set up yet."
    cents, window = round(float(fee) * 100), int(hours)
    key = keys.venue(venue_id)
    op = TxOp(
        "Update", key={"PK": key.pk, "SK": key.sk}, update="SET cancel_fee_cents = :fee, free_cancel_hours = :hours",
        condition="attribute_exists(PK)", values={":fee": cents, ":hours": window},
    )
    entry = _audit(deps, session, venue_id, iso_z(deps.clock.now()), {
        "cancel_fee_cents_from": venue.cancel_fee_cents, "cancel_fee_cents_to": cents,
        "free_cancel_hours_from": venue.free_cancel_hours, "free_cancel_hours_to": window,
    })
    deps.store.transact([op, deps.store.audit_op(entry)])
    return None


# ---------------------------------------------------------------------------------------------- Fair Drop
def draw_hours(value: object) -> int:
    """The draw time asked for (a query value or a form value); anything that is not one of the choices means 24."""
    text = str(value).strip()
    return int(text) if text.isdigit() and int(text) in DRAW_HOURS_BEFORE else DRAW_HOURS_BEFORE[0]


def seat_options(deps, venue_id: str, hours: int = DRAW_HOURS_BEFORE[0]) -> list[SeatOption]:
    """Open seats in the next two weeks that are not in a drop yet and far enough away for a draw ``hours`` before them
    (and at least ten minutes from now), so every seat in the list can be released with that draw time."""
    hours = draw_hours(hours)
    now = deps.clock.now()
    options: list[SeatOption] = []
    for offset in range(LOOKAHEAD_DAYS + 1):
        date = (now.date() + timedelta(days=offset)).isoformat()
        for slot in deps.store.get_slots(venue_id, date):
            if slot.status != SLOT_OPEN or slot.drop_controlled:
                continue
            if starts_at(slot.date, slot.time) - timedelta(hours=hours) < now + MIN_LEAD:
                continue
            options.append(SeatOption(f"{slot.date}|{slot.time}|{slot.table_group}",
                                      f"{slot.time} · table {slot.table_group} ({slot.seats} seats)", slot))
    return options[:MAX_SEATS_LISTED]


def create_fair_drop(deps, session, seat: str, hours_before: str) -> str | None:
    """Release one open seat through a lottery: the seed is drawn now, only its SHA-256 is published, entries run until
    the draw. The seat is marked in the same transaction, so nobody can book it directly any more (rule S4)."""
    venue_id = session.owner_of or ""
    parts = seat.split("|")
    if len(parts) != 3 or not hours_before.strip().isdigit() or int(hours_before) not in DRAW_HOURS_BEFORE:
        return "Choose a seat from the list and one of the draw times."
    date, time_, group = parts
    try:
        slot = deps.store.get_slot(venue_id, date, time_, group)
    except ValueError:
        slot = None
    now = deps.clock.now()
    if slot is None or slot.status != SLOT_OPEN or slot.drop_controlled:
        return "That seat is not open any more. Choose another."
    draw_at = starts_at(slot.date, slot.time) - timedelta(hours=int(hours_before))
    if draw_at < now + MIN_LEAD:
        return "That draw time has passed or is too close. Choose a shorter time before the seat."
    seed = deps.seeds.new_seed()
    drop = Drop(drop_id_for(slot), venue_id, slot.date, (slot.slot_key,), iso_z(now), iso_z(draw_at),
                commitment(seed), seed_hex=seed.hex())
    slot_key = keys.slot(venue_id, slot.date, slot.time, slot.table_group)
    mark = TxOp(
        "Update", key={"PK": slot_key.pk, "SK": slot_key.sk},
        update="SET drop_id = :drop, hot = :yes, ver = ver + :one",
        condition="ver = :v AND #st = :open AND attribute_not_exists(drop_id)", names={"#st": "status"},
        values={":drop": drop.drop_id, ":yes": True, ":one": 1, ":v": slot.ver, ":open": SLOT_OPEN},
    )
    put = TxOp("Put", item=drop_to_item(drop), condition="attribute_not_exists(PK)")
    entry = _audit(deps, session, venue_id, iso_z(now), {
        "fair_drop": drop.drop_id, "seat": f"{slot.date} {slot.time} {slot.table_group}", "draw_at": drop.drop_at,
        "commitment": drop.commitment,
    })
    try:
        deps.store.transact([mark, put, deps.store.audit_op(entry)])
    except TransactionCancelled:  # a diner held the seat first, or the drop already exists
        return "That seat changed while you were choosing. Choose again."
    return None


def venue_drops(deps, venue_id: str):
    """The venue's drops that are still ahead of their seat, found from the seats that carry a drop id."""
    seen: dict[str, Drop] = {}
    now = deps.clock.now()
    for offset in range(LOOKAHEAD_DAYS + 3):
        date = (now.date() + timedelta(days=offset)).isoformat()
        for slot in deps.store.get_slots(venue_id, date):
            if slot.drop_id and slot.drop_id not in seen:
                drop = deps.store.get_drop(slot.drop_id)
                if drop is not None:
                    seen[slot.drop_id] = drop
    return sorted(seen.values(), key=lambda d: d.drop_at)
