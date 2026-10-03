"""Fair Drop operations: entering a drop, and the hold a winner receives (D-023).

Entry transaction (plus idempotency record and audit from the pipeline):
  0. ticket record         (new: one ticket per person per drop, rule RT12 / invariant I4)
  1. drop condition check  (still open, drop time not reached)
Winner's hold: the normal hold transaction plus
  +  ticket -> won         (only while still 'entered', so a resumed run cannot double-award)
It is the one sanctioned route around rule S4: winning the draw is the authorisation.
"""

import math
from datetime import datetime

from server.domain.errors import ErrorCode, FairTableError
from server.domain.fairdrop import (
    DROP_OPEN,
    ENTRY_ENTERED,
    ENTRY_WON,
    Drop,
    DropEntry,
    entry_hash,
    entry_id,
)
from server.domain.models import Identity, Slot
from server.domain.output import success
from server.domain.offers import SlotClaims
from server.domain.tool_names import ToolName
from server.kernel import Decision, PolicyContext, VenueRef
from server.ops.common import NO_READ_BACK, counter_value
from server.ops.hold import HoldOperation
from server.pipeline import WriteFacts, WritePlan
from server.store import Store, TransactionCancelled, TxOp, keys
from server.tools.common import AppDeps
from server.tools.present import say_date, say_time


def drop_closed() -> FairTableError:
    return FairTableError(
        ErrorCode.DROP_CLOSED, "This drop is closed for new entries.",
        hint="The draw has been (or is being) run. Check the ticket's status, or look for other slots.",
    )


def retry_after_until(drop: Drop, now: datetime) -> int:
    """Seconds until the draw, kept between 30 seconds and an hour so agents neither hammer nor vanish."""
    left = math.ceil((datetime.fromisoformat(drop.drop_at) - now).total_seconds())
    return max(30, min(3600, left))


class DropEntryOperation:
    tool = ToolName.WAITLIST_WATCH

    def __init__(self, deps: AppDeps, drop: Drop, party_size: int) -> None:
        self.deps = deps
        self.drop = drop
        self.venue_id = drop.venue_id
        self.party_size = party_size

    def params(self) -> dict:
        return {"kind": "drop", "drop_id": self.drop.drop_id, "party": self.party_size}

    def load_facts(self, store: Store, identity: Identity, now_iso: str) -> WriteFacts:
        drop = store.get_drop(self.drop.drop_id)
        if drop is None:
            raise FairTableError(ErrorCode.NOT_FOUND, "No such drop.")
        if drop.status != DROP_OPEN or not drop.opens_at <= now_iso < drop.drop_at:
            raise drop_closed()
        venue = store.get_venue(drop.venue_id)
        if venue is None:
            raise FairTableError(ErrorCode.NOT_FOUND, "That restaurant no longer exists.")
        self.drop, self.venue = drop, venue
        return WriteFacts(
            VenueRef(venue.venue_id, venue.agent_cover_cap),
            PolicyContext(
                agent_tier=identity.agent_tier or "none",
                active_holds_user_venue=counter_value(store, keys.active_holds_counter(identity.sub, venue.venue_id)),
                agent_covers_booked=counter_value(store, keys.agent_covers_counter(venue.venue_id, drop.date)),
                party_size=self.party_size,
                slot_is_drop_controlled=False,  # entering is not holding: S4 guards direct holds only
                booked_same_day=False,  # S6 guards a hold, not an entry in the draw
                **NO_READ_BACK,
            ),
        )

    def plan(self, store: Store, identity: Identity, now_iso: str, decision: Decision) -> WritePlan:
        drop = self.drop
        ticket = DropEntry(
            entry_id=entry_id(drop.drop_id, identity.sub), drop_id=drop.drop_id, sub=identity.sub,
            username=identity.username, agent_tier=identity.agent_tier, agent_id=identity.agent_id,
            scopes=identity.scopes, party_size=self.party_size, created_at=now_iso,
        )
        self.ticket = ticket
        dk = keys.drop(drop.drop_id)
        ops = [
            store.entry_put_op(ticket, entry_hash(drop.drop_id, identity.sub)),
            TxOp(
                "ConditionCheck", key={"PK": dk.pk, "SK": dk.sk},
                condition="#st = :open AND drop_at > :now", names={"#st": "status"},
                values={":open": DROP_OPEN, ":now": now_iso},
            ),
        ]
        retry = retry_after_until(drop, datetime.fromisoformat(now_iso))
        slot_key = drop.slot_keys[0]
        result = success(
            f"You're in the draw for {self.venue.name} on {say_date(drop.date)}. "
            f"Winners are picked by a public, checkable lottery on {say_date(drop.drop_at[:10])} "
            f"at {say_time(drop.drop_at[11:16])}.",
            watch_id=ticket.entry_id, status=ENTRY_ENTERED, restaurant=self.venue.name, date=drop.date,
            places=drop.capacity, slot=slot_key, commitment=drop.commitment, drop_at=drop.drop_at,
            audit_resource=f"fairtable://drops/{drop.drop_id}/audit", retry_after_s=retry,
            next_step={"tool": "waitlist_status",
                       "why": f"Ask after {drop.drop_at}; not sooner than {retry} seconds from now."},
        )
        return WritePlan(ops, result, {"entry_id": ticket.entry_id, "drop_id": drop.drop_id})

    def explain_cancel(self, failed: list[int], exc: TransactionCancelled) -> FairTableError:
        if 0 in failed:
            return FairTableError(
                ErrorCode.ALREADY_ENTERED, "You already have a ticket in this drop.",
                details={"watch_id": self.ticket.entry_id},
                next_step=None,
            )
        return drop_closed()


class DropWinHoldOperation(HoldOperation):
    """The hold a winner receives. Rules P0, S1 and S2 still apply; S4 is set aside on purpose."""

    def __init__(self, deps: AppDeps, drop: Drop, entry: DropEntry, slot: Slot) -> None:
        claims = SlotClaims(slot.venue_id, slot.date, slot.slot_key, entry.party_size, slot.ver, entry.sub,
                            hot=slot.hot, drop_id=drop.drop_id)
        super().__init__(deps, claims)
        self.drop, self.entry = drop, entry
        self.drop_exempt = True
        self.ttl_s = deps.settings.drop_hold_ttl_s  # the winner is not in a conversation at draw time (D-054)

    def params(self) -> dict:
        return {**super().params(), "entry_id": self.entry.entry_id}

    def extra_ops(self, hold_id: str, now_iso: str) -> list[TxOp]:
        k = keys.entry(self.drop.drop_id, entry_hash(self.drop.drop_id, self.entry.sub))
        return [TxOp(
            "Update", key={"PK": k.pk, "SK": k.sk}, update="SET #st = :won, hold_id = :hid",
            condition="#st = :entered", names={"#st": "status"},
            values={":won": ENTRY_WON, ":entered": ENTRY_ENTERED, ":hid": hold_id},
        )]

    def decorate(self, result: dict) -> dict:
        return {**result, "entry_id": self.entry.entry_id}

    def explain_extra(self, failed: list[int]) -> FairTableError:
        return FairTableError(ErrorCode.INVALID_INPUT, "This ticket has already been decided.")
