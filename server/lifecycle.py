"""Lazy release of expired holds (no worker; design decision D4).

An expired hold still counts toward the user's S1 and the restaurant's S2 until it is released, so
holds are released right before they matter: when someone holds or confirms. One small transaction
per hold (hold to ``expired`` + both counters down); the slot is restored best-effort because a slot
whose ``held_until`` has passed already reads as open. The same functions can be wrapped by a
Lambda sweeper later.
"""

import logging

from server.domain.booking import HOLD_EXPIRED, HOLD_HELD, Hold
from server.domain.models import SLOT_HELD, SLOT_OPEN
from server.store import Store, TransactionCancelled, TxOp, keys

log = logging.getLogger("fairtable.lifecycle")


def release_ops(hold: Hold, *, new_status: str = HOLD_EXPIRED) -> list[TxOp]:
    """The conditional writes that end a *held* hold: status, S1 counter, S2 counter."""
    hold_key = keys.hold(hold.hold_id)
    s1 = keys.active_holds_counter(hold.sub, hold.venue_id)
    s2 = keys.agent_covers_counter(hold.venue_id, hold.date)
    return [
        TxOp(
            "Update", key={"PK": hold_key.pk, "SK": hold_key.sk},
            update="SET #st = :new REMOVE GSI1PK, GSI1SK",
            condition="#st = :held", names={"#st": "status"},
            values={":new": new_status, ":held": HOLD_HELD},
        ),
        TxOp(
            "Update", key={"PK": s1.pk, "SK": s1.sk}, update="ADD n :neg",
            condition="n >= :one", values={":neg": -1, ":one": 1},
        ),
        TxOp(
            "Update", key={"PK": s2.pk, "SK": s2.sk}, update="ADD n :neg",
            condition="n >= :party", values={":neg": -hold.party_size, ":party": hold.party_size},
        ),
    ]


def restore_slot(store: Store, hold: Hold) -> None:
    """Give the slot back if it still belongs to this hold. Best effort: a slot whose hold has
    expired is treated as open anyway, so a lost race here is harmless."""
    slot_key = keys.slot(hold.venue_id, hold.date, hold.time, hold.table_group)
    op = TxOp(
        "Update", key={"PK": slot_key.pk, "SK": slot_key.sk},
        update="SET #st = :open, ver = ver + :one REMOVE held_until, hold_id",
        condition="hold_id = :hid AND #st = :held", names={"#st": "status"},
        values={":open": SLOT_OPEN, ":held": SLOT_HELD, ":hid": hold.hold_id, ":one": 1},
    )
    try:
        store.transact([op])
    except TransactionCancelled:
        pass


def release_expired(store: Store, hold: Hold, now_iso: str) -> bool:
    """Release one hold if it is really expired. True when this call released it."""
    if hold.status != HOLD_HELD or hold.held_until > now_iso:
        return False
    try:
        store.transact(release_ops(hold))
    except TransactionCancelled as exc:
        # Someone else released or confirmed it first (fine), or the counters disagree with the
        # holds (a bug: the invariant checker in tests would flag it). Never block the caller.
        log.info("hold %s not released: %s", hold.hold_id, exc)
        return False
    restore_slot(store, hold)
    return True


def release_expired_for(store: Store, *, venue_id: str, date: str, sub: str, now_iso: str) -> list[Hold]:
    """Release expired holds that could distort a decision: the restaurant's day and the user's.
    Returns the holds released now, so the caller can offer their tables to waiting watchers."""
    seen: set[str] = set()
    released: list[Hold] = []
    candidates = [
        *store.expired_holds_on_day(venue_id, date, now_iso),
        *(h for h in store.holds_of_user(sub) if h.status == HOLD_HELD and h.held_until <= now_iso),
    ]
    for hold in candidates:
        if hold.hold_id in seen:
            continue
        seen.add(hold.hold_id)
        if release_expired(store, hold, now_iso):
            released.append(hold)
    return released


def extend_hold(store: Store, hold: Hold, new_until: str, now_iso: str) -> bool:
    """Lengthen a live hold ONCE so the user has time to approve on their phone (D-022).

    Hold and slot move together in one transaction, guarded so that a hold that already expired,
    was already extended, or was taken over cannot be extended. Returns True when extended.
    The total lock is bounded: the step-up can only start while the hold is alive (at most 10
    minutes after it was taken) and adds at most the approval window.
    """
    if new_until <= hold.held_until:
        return False
    hold_key = keys.hold(hold.hold_id)
    slot_key = keys.slot(hold.venue_id, hold.date, hold.time, hold.table_group)
    ops = [
        TxOp(
            "Update", key={"PK": hold_key.pk, "SK": hold_key.sk},
            update="SET held_until = :new, hold_extended = :yes, GSI1SK = :sk",
            condition="#st = :held AND held_until > :now AND (attribute_not_exists(hold_extended) OR hold_extended = :no)",
            names={"#st": "status"},
            values={":new": new_until, ":yes": True, ":no": False, ":held": HOLD_HELD, ":now": now_iso,
                    ":sk": f"{new_until}#{hold.hold_id}"},
        ),
        TxOp(
            "Update", key={"PK": slot_key.pk, "SK": slot_key.sk}, update="SET held_until = :new",
            condition="hold_id = :hid AND #st = :slot_held", names={"#st": "status"},
            values={":new": new_until, ":hid": hold.hold_id, ":slot_held": SLOT_HELD},
        ),
    ]
    try:
        store.transact(ops)
    except TransactionCancelled:
        return False
    return True
