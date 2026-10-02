"""Running a Fair Drop lazily and exactly once (D-023).

``maybe_allocate`` is called by the first request after the drop time (a ticket status check, an
entry attempt, a read of the audit). It claims the drop with a conditional status change, walks the
entries in the verifiable lottery order giving each a hold on the next free drop slot, records every
outcome, and finally reveals the seed and stores the audit. Every step is idempotent, so a crashed
run is finished by the next caller (a claim older than ``STALE_CLAIM_S`` may be taken over).
"""

import logging
from datetime import datetime, timedelta

from server.domain.clock import iso_z
from server.domain.errors import ErrorCode, FairTableError
from server.domain.fairdrop import (
    DROP_ALLOCATED,
    DROP_ALLOCATING,
    DROP_OPEN,
    ENTRY_ENTERED,
    ENTRY_LOST,
    ENTRY_SKIPPED,
    ENTRY_WON,
    Drop,
    DropEntry,
    build_audit,
    entry_hash,
    order_entries,
)
from server.domain.models import SLOT_OPEN, Identity, Slot
from server.ops.common import parse_slot_key
from server.ops.fairdrop import DropWinHoldOperation
from server.pipeline import run_write
from server.store import Store, TransactionCancelled, TxOp, keys
from server.tools.common import AppDeps
from server.tools.present import say_date

log = logging.getLogger("fairtable.dropper")
STALE_CLAIM_S = 60


def _persist(store: Store, drop_id: str, sub: str, status: str, reason: str | None) -> None:
    k = keys.entry(drop_id, entry_hash(drop_id, sub))
    update = "SET #st = :new" + (", reason = :reason" if reason else "")
    values = {":new": status, ":entered": ENTRY_ENTERED, **({":reason": reason} if reason else {})}
    try:
        store.transact([TxOp("Update", key={"PK": k.pk, "SK": k.sk}, update=update,
                             condition="#st = :entered", names={"#st": "status"}, values=values)])
    except TransactionCancelled:
        pass  # already decided by an earlier (interrupted) run


def _claim(store: Store, drop: Drop, now_iso: str) -> bool:
    k = keys.drop(drop.drop_id)
    stale = iso_z(datetime.fromisoformat(now_iso) - timedelta(seconds=STALE_CLAIM_S))
    op = TxOp(
        "Update", key={"PK": k.pk, "SK": k.sk}, update="SET #st = :allocating, allocating_since = :now",
        condition="#st = :open OR (#st = :allocating AND allocating_since <= :stale)",
        names={"#st": "status"},
        values={":allocating": DROP_ALLOCATING, ":open": DROP_OPEN, ":now": now_iso, ":stale": stale},
    )
    try:
        store.transact([op])
    except TransactionCancelled:
        return False
    return True


def maybe_allocate(deps: AppDeps, drop_id: str) -> Drop | None:
    """Run the draw if its time has come and nobody else is doing it. Returns the drop as it is now."""
    store = deps.store
    drop = store.get_drop(drop_id)
    now_iso = iso_z(deps.clock.now())
    if drop is None or drop.status not in (DROP_OPEN, DROP_ALLOCATING) or now_iso < drop.drop_at:
        return drop
    if not _claim(store, drop, now_iso):
        return store.get_drop(drop_id)  # somebody else is running it, or it is done
    try:
        _allocate(deps, store.get_drop(drop_id) or drop, now_iso)
    except Exception:
        log.exception("allocating drop %s failed; the next caller will resume it", drop_id)
        raise
    return store.get_drop(drop_id)


def _free_slots(store: Store, drop: Drop, won: list[DropEntry], now_iso: str) -> list[Slot]:
    """Drop slots not yet given to a winner and really free."""
    given = set()
    for e in won:
        hold = store.get_hold(e.hold_id) if e.hold_id else None
        if hold is not None:
            given.add(f"{hold.time.replace(':', '')}#{hold.table_group}")
    free = []
    for slot_key in drop.slot_keys:
        if slot_key in given:
            continue
        time_, group = parse_slot_key(slot_key)
        slot = store.get_slot(drop.venue_id, drop.date, time_, group)
        if slot is not None and slot.effective_status(now_iso) == SLOT_OPEN:
            free.append(slot)
    return free


def _allocate(deps: AppDeps, drop: Drop, now_iso: str) -> None:
    store = deps.store
    seed = bytes.fromhex(drop.seed_hex or "")
    entries = store.entries_of_drop(drop.drop_id)
    by_id = {e.entry_id: e for e in entries}
    order = order_entries(seed, list(by_id))
    free = _free_slots(store, drop, [e for e in entries if e.status == ENTRY_WON], now_iso)
    winners_left = drop.capacity - sum(e.status == ENTRY_WON for e in entries)

    for eid in order:
        e = by_id[eid]
        if e.status != ENTRY_ENTERED:
            continue  # decided by an earlier, interrupted run
        if winners_left <= 0 or not free:
            _persist(store, drop.drop_id, e.sub, ENTRY_LOST, None)
            continue
        outcome, reason = _try_award(deps, drop, e, free)
        if outcome == ENTRY_WON:
            winners_left -= 1
        else:
            _persist(store, drop.drop_id, e.sub, ENTRY_SKIPPED, reason)

    final = store.entries_of_drop(drop.drop_id)
    outcomes = {e.entry_id: (e.status, e.reason) for e in final}
    audit = build_audit(drop, seed, final, outcomes, now_iso)
    k = keys.drop(drop.drop_id)
    store.transact([TxOp(
        "Update", key={"PK": k.pk, "SK": k.sk}, update="SET #st = :done, allocated_at = :now, audit = :audit",
        condition="#st = :allocating", names={"#st": "status"},
        values={":done": DROP_ALLOCATED, ":allocating": DROP_ALLOCATING, ":now": now_iso, ":audit": audit},
    )])
    _tell_winners(deps, drop, final)


def _try_award(deps: AppDeps, drop: Drop, entry: DropEntry, free: list[Slot]) -> tuple[str, str | None]:
    """Give this entry the next free slot that seats them. The rules still apply (S1, S2, P0)."""
    fitting = [s for s in free if s.seats >= entry.party_size]
    if not fitting:
        return ENTRY_SKIPPED, "no_fitting_slot"
    for slot in fitting:
        identity = _identity_of(entry)
        key = f"drop-{drop.drop_id}-{entry_hash(drop.drop_id, entry.sub)[:24]}"
        try:
            run_write(deps, identity, DropWinHoldOperation(deps, drop, entry, slot), key)
        except FairTableError as e:
            if e.code is ErrorCode.SLOT_TAKEN:
                free.remove(slot)  # gone: try the next one for the same entry
                continue
            return ENTRY_SKIPPED, e.rule_id or e.code.value
        free.remove(slot)
        return ENTRY_WON, None
    return ENTRY_SKIPPED, "no_fitting_slot"


def _identity_of(entry: DropEntry) -> Identity:
    return Identity(sub=entry.sub, username=entry.username, agent_tier=entry.agent_tier,
                    agent_id=entry.agent_id, scopes=entry.scopes)


def _tell_winners(deps: AppDeps, drop: Drop, entries: list[DropEntry]) -> None:
    venue = deps.store.get_venue(drop.venue_id)
    name = venue.name if venue else drop.venue_id
    for e in entries:
        if e.status == ENTRY_WON:
            deps.notifier.notify(
                e.sub, subject="You won the draw",
                body=f"You won a table at {name} on {say_date(drop.date)}. It is held for you for two "
                     "hours: ask your assistant about your waitlist.",
            )
