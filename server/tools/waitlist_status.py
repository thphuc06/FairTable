"""waitlist_status: where is my watch (or Fair Drop ticket)? Also cancels it (read tool, rule G1)."""

from typing import Literal

from fastmcp import FastMCP

from server.domain.booking import HOLD_CONFIRMED, HOLD_HELD
from server.domain.clock import iso_z
from server.domain.errors import ErrorCode, FairTableError
from server.domain.fairdrop import (
    DROP_ALLOCATED,
    DROP_OPEN,
    ENTRY_ENTERED,
    ENTRY_LOST,
    ENTRY_SKIPPED,
    ENTRY_WON,
    Drop,
    DropEntry,
    split_entry_id,
)
from server.domain.models import Identity
from server.domain.readback import KIND_CONFIRM, min_pause_s
from server.domain.output import success
from server.domain.tool_names import ToolName
from server.domain.waitlist import (
    RETRY_AFTER_S,
    WATCH_CANCELLED,
    WATCH_EXPIRED,
    WATCH_MATCHED,
    WATCH_WAITING,
    Watch,
    effective_status,
)
from server.dropper import maybe_allocate
from server.middleware import business_errors
from server.ops.fairdrop import drop_closed, retry_after_until
from server.store import TransactionCancelled, TxOp, keys
from server.tools.common import AppDeps, authorize
from server.tools.present import read_back_confirm, say_date, say_time


def register(mcp: FastMCP, deps: AppDeps) -> None:
    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False,
                           "idempotentHint": True, "openWorldHint": False})
    @business_errors
    def waitlist_status(watch_id: str, action: Literal["status", "cancel"] = "status") -> dict:
        """Check a waitlist watch or a Fair Drop ticket, or cancel it.

        `watch_id` is what waitlist_watch returned. While it says `waiting` or `entered`, ask again
        no sooner than `retry_after_s`. `matched` (or `won`) comes with a `hold_id`, the details to read to the user
        (`read_back`) and a `read_back_token`: ask the user, and if they say yes confirm with
        reservation_confirm before `hold_expires_at`. For a drop, `audit_resource` is a public
        record anyone can check once the draw has happened.
        """
        identity = authorize(deps, ToolName.WAITLIST_STATUS)
        ticket = split_entry_id(watch_id) if isinstance(watch_id, str) else None
        if ticket:
            return _ticket(deps, identity, *ticket, action)
        watch = deps.store.get_watch(watch_id) if isinstance(watch_id, str) and watch_id else None
        if watch is None or watch.sub != identity.sub:
            raise FairTableError(ErrorCode.NOT_FOUND, "No such watch.")
        return _cancel(deps, watch) if action == "cancel" else _status(deps, watch)


def _venue_name(deps: AppDeps, venue_id: str) -> str:
    venue = deps.store.get_venue(venue_id)
    return venue.name if venue else venue_id


def _hold_answer(deps: AppDeps, hold_id: str, where: str, base: dict, source: str) -> dict:
    now_iso = iso_z(deps.clock.now())
    hold = deps.store.get_hold(hold_id)
    if hold is not None and hold.status == HOLD_CONFIRMED:
        return success(f"That table at {where} is booked.", **base, hold_id=hold_id,
                       next_step={"tool": "reservation_manage", "why": "View or cancel the booking."})
    if hold is not None and hold.status == HOLD_HELD and hold.held_until > now_iso:
        read_back = read_back_confirm(hold.terms)
        pause = min_pause_s(hold.terms["cancel_fee_cents"])
        token = deps.readback_codec.issue(kind=KIND_CONFIRM, subject_id=hold.hold_id, sub=hold.sub, terms=hold.terms)
        return success(
            f"{source} at {where} at {say_time(hold.time)}. It is held for the user. {read_back}",
            **base, hold_id=hold_id, hold_expires_at=hold.held_until, time=hold.time,
            read_back=read_back, read_back_token=token, min_pause_s=pause,
            next_step={"tool": "reservation_confirm",
                       "why": "Read the details to the user and ask whether to book. If they say yes (wait at least "
                              f"{pause} seconds after reading), confirm with the hold_id, the "
                              "read_back_token and user_confirmed set to true, before hold_expires_at."},
        )
    return success(
        f"{source} at {where}, but the hold ran out before it was confirmed.", **base, hold_id=hold_id,
        next_step={"tool": "waitlist_watch", "why": "Register again if the user still wants a table."},
    )


# ---------------------------------------------------------------- standing watches
def _status(deps: AppDeps, w: Watch) -> dict:
    now = deps.clock.now()
    state = effective_status(w, now.date().isoformat())
    where = f"{_venue_name(deps, w.venue_id)} on {say_date(w.date)}"
    base = {"watch_id": w.watch_id, "status": state, "restaurant_id": w.venue_id, "date": w.date}
    if state == WATCH_WAITING:
        return success(
            f"Still watching for a table at {where}. Nothing has opened yet.", **base,
            retry_after_s=RETRY_AFTER_S,
            next_step={"tool": "waitlist_status", "why": f"Ask again in about {RETRY_AFTER_S} seconds."},
        )
    if state == WATCH_MATCHED and w.hold_id:
        return _hold_answer(deps, w.hold_id, where, base, "A table opened")
    text = {WATCH_CANCELLED: "That watch was cancelled.", WATCH_EXPIRED: "That watch has expired: its date has passed."}
    return success(text.get(state, "That watch is over."), **base,
                   next_step={"tool": "availability_check", "why": "Look for another time."})


def _cancel(deps: AppDeps, w: Watch) -> dict:
    now_iso = iso_z(deps.clock.now())
    wk, key = keys.watch(w.watch_id), keys.watch_slot(w.sub, w.venue_id, w.date)
    ops = [
        TxOp("Update", key={"PK": wk.pk, "SK": wk.sk},
             update="SET #st = :cancelled, cancelled_at = :now REMOVE GSI1PK, GSI1SK",
             condition="#st = :waiting", names={"#st": "status"},
             values={":cancelled": WATCH_CANCELLED, ":waiting": WATCH_WAITING, ":now": now_iso}),
        TxOp("Delete", key={"PK": key.pk, "SK": key.sk}, condition="attribute_exists(PK)"),
    ]
    try:
        deps.store.transact(ops)
    except TransactionCancelled:
        return _status(deps, deps.store.get_watch(w.watch_id) or w)  # already over: show how it ended
    return success("Cancelled. You will not be offered a table for that watch.", watch_id=w.watch_id,
                   status=WATCH_CANCELLED,
                   next_step={"tool": "availability_check", "why": "Look for another time."})


# ---------------------------------------------------------------- Fair Drop tickets
def _ticket(deps: AppDeps, identity: Identity, drop_id: str, digest: str, action: str) -> dict:
    drop = maybe_allocate(deps, drop_id)  # the first request after the drop time runs the draw
    entry = deps.store.get_entry(drop_id, digest) if drop is not None else None
    if drop is None or entry is None or entry.sub != identity.sub:
        raise FairTableError(ErrorCode.NOT_FOUND, "No such ticket.")
    if action == "cancel":
        return _withdraw(deps, drop, entry)
    return _ticket_status(deps, drop, entry)


def _ticket_status(deps: AppDeps, drop: Drop, e: DropEntry) -> dict:
    now = deps.clock.now()
    where = f"{_venue_name(deps, drop.venue_id)} on {say_date(drop.date)}"
    base = {"watch_id": e.entry_id, "status": e.status, "restaurant_id": drop.venue_id, "date": drop.date,
            "commitment": drop.commitment, "audit_resource": f"fairtable://drops/{drop.drop_id}/audit"}
    if e.status == ENTRY_ENTERED and drop.status == DROP_OPEN:
        retry = retry_after_until(drop, now)
        return success(
            f"You're in the draw for {where}. It happens on {say_date(drop.drop_at[:10])} at "
            f"{say_time(drop.drop_at[11:16])}.", **base, drop_at=drop.drop_at,
            retry_after_s=retry,
            next_step={"tool": "waitlist_status", "why": f"The draw is not run yet; ask again in {retry} seconds."},
        )
    if e.status == ENTRY_ENTERED:  # allocation in progress
        return success(f"The draw for {where} is being run right now.", **base, retry_after_s=10,
                       next_step={"tool": "waitlist_status", "why": "Ask again in about 10 seconds."})
    if e.status == ENTRY_WON and e.hold_id:
        return _hold_answer(deps, e.hold_id, where, base, "You won the draw: a table is yours")
    if e.status == ENTRY_LOST:
        return success(f"You were not picked in the draw for {where}. Anyone can check the draw fairly.", **base,
                       next_step={"tool": "waitlist_watch", "why": "Watch for a table on another day, or look for other slots."})
    if e.status == ENTRY_SKIPPED:
        return success(f"You were drawn for {where} but could not be given a table.", **base,
                       reason=e.reason,
                       next_step={"tool": "availability_check", "why": "Look for other slots."})
    return success("That ticket is closed.", **base,
                   next_step={"tool": "availability_check", "why": "Look for other slots."})


def _withdraw(deps: AppDeps, drop: Drop, e: DropEntry) -> dict:
    """Take the ticket back before the draw. The lottery order does not depend on who else is in,
    so withdrawing (or re-entering with the same ticket id) gains nothing."""
    now_iso = iso_z(deps.clock.now())
    ek = keys.entry(drop.drop_id, e.entry_id.rpartition("~")[2])
    dk = keys.drop(drop.drop_id)
    ops = [
        TxOp("Delete", key={"PK": ek.pk, "SK": ek.sk}, condition="#st = :entered",
             names={"#st": "status"}, values={":entered": ENTRY_ENTERED}),
        TxOp("ConditionCheck", key={"PK": dk.pk, "SK": dk.sk}, condition="#st = :open AND drop_at > :now",
             names={"#st": "status"}, values={":open": DROP_OPEN, ":now": now_iso}),
    ]
    try:
        deps.store.transact(ops)
    except TransactionCancelled:
        if drop.status == DROP_ALLOCATED or now_iso >= drop.drop_at:
            raise drop_closed() from None
        return _ticket_status(deps, drop, deps.store.get_entry(drop.drop_id, e.entry_id.rpartition("~")[2]) or e)
    return success("Your ticket was withdrawn from the draw.", watch_id=e.entry_id, status="cancelled",
                   next_step={"tool": "availability_check", "why": "Look for other slots."})
