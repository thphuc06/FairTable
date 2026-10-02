"""reservation_manage: cancel (with the fee decided *before* anything is written) and reduce the
party size. ``view`` changes nothing and lives in the tool.

Cancel transaction (plus idempotency record and audit from the pipeline):
  0. reservation -> cancelled   (still confirmed, same user; the fee is recorded)
  1. slot -> open               (still owned by this reservation)
  2. S2 counter - party         (the covers are free for other agents again)
A cancel that costs money needs the fee read back to the diner and a spoken yes (D-051): the first call is
refused by rules S5a-c with a read-back token; the repeat, after the pause, with the token and
``user_confirmed``, cancels. A free cancel, a view and a smaller party need none of this.
"""

from datetime import UTC, datetime

from server.domain.booking import (
    RES_CANCELLED,
    RES_CONFIRMED,
    Reservation,
    cancel_fee_cents,
    terms_for,
)
from server.domain.clock import iso_z
from server.domain.errors import ErrorCode, FairTableError
from server.domain.models import SLOT_CONFIRMED, SLOT_OPEN, Identity
from server.domain.output import success
from server.domain.readback import KIND_CANCEL_FEE, min_pause_s, pause_elapsed
from server.domain.tool_names import ToolName
from server.kernel import Decision, PolicyContext, VenueRef
from server.ops.common import NO_READ_BACK, counter_value, parse_iso
from server.pipeline import WriteFacts, WritePlan
from server.store import Store, TransactionCancelled, TxOp, keys
from server.tools.common import AppDeps
from server.tools.present import read_back_cancel_fee, say_date, say_money, say_time


def not_active() -> FairTableError:
    return FairTableError(
        ErrorCode.INVALID_INPUT, "This reservation is not active any more.",
        hint="It was already cancelled or changed. Use view to see its current state.",
    )


class _ManageBase:
    tool = ToolName.RESERVATION_MANAGE

    def __init__(self, deps: AppDeps, reservation: Reservation) -> None:
        self.deps = deps
        self.reservation = reservation
        self.venue_id = reservation.venue_id
        self.party_size = reservation.party_size

    def _fresh(self, store: Store, identity: Identity) -> Reservation:
        res = store.get_reservation(self.reservation.reservation_id)
        if res is None or res.sub != identity.sub:
            raise FairTableError(ErrorCode.NOT_FOUND, "No such reservation.")
        if res.status != RES_CONFIRMED:
            raise not_active()
        self.reservation = res
        return res

    def _context(self, store: Store, identity: Identity, res: Reservation, **read_back: bool) -> WriteFacts:
        venue = store.get_venue(res.venue_id)
        if venue is None:
            raise FairTableError(ErrorCode.NOT_FOUND, "That restaurant no longer exists.")
        self.venue = venue
        return WriteFacts(
            VenueRef(venue.venue_id, venue.agent_cover_cap),
            PolicyContext(
                agent_tier=identity.agent_tier or "none",
                active_holds_user_venue=counter_value(store, keys.active_holds_counter(identity.sub, res.venue_id)),
                agent_covers_booked=counter_value(store, keys.agent_covers_counter(res.venue_id, res.date)),
                party_size=res.party_size,
                slot_is_drop_controlled=False,
                **{**NO_READ_BACK, **read_back},
            ),
        )


class CancelOperation(_ManageBase):
    def __init__(self, deps: AppDeps, reservation: Reservation, read_back_token: str | None = None,
                 user_confirmed: bool = False) -> None:
        super().__init__(deps, reservation)
        self.fee = 0
        self.read_back_token = read_back_token
        self.user_confirmed = user_confirmed is True
        self.read_back_at: str | None = None

    def params(self) -> dict:
        return {"action": "cancel", "reservation_id": self.reservation.reservation_id}

    def _terms(self) -> dict:
        r = self.reservation
        return terms_for(self.venue, r.date, r.time, r.party_size, fee_cents=self.fee)

    def read_back_offer(self, identity: Identity) -> dict:
        """The fee, as a sentence for the assistant to say, with the token that proves it was handed over."""
        if self.fee <= 0:
            return {}
        r = self.reservation
        token = self.deps.readback_codec.issue(
            kind=KIND_CANCEL_FEE, subject_id=r.reservation_id, sub=identity.sub, terms=self._terms())
        sentence = read_back_cancel_fee(
            {"restaurant": self.venue.name, "date": r.date, "time": r.time, "fee_cents": self.fee})
        return {"read_back": sentence, "read_back_token": token, "min_pause_s": min_pause_s(self.fee)}

    def load_facts(self, store: Store, identity: Identity, now_iso: str) -> WriteFacts:
        res = self._fresh(store, identity)
        facts = self._context(store, identity, res)
        self.fee = cancel_fee_cents(self.venue, res.date, res.time, parse_iso(now_iso))
        if self.fee == 0:
            return facts  # a free cancel needs no read-back
        check = self.deps.readback_codec.check(
            self.read_back_token, kind=KIND_CANCEL_FEE, subject_id=res.reservation_id, sub=identity.sub,
            terms=self._terms())
        if check.matches and check.issued_at_ms is not None:
            self.read_back_at = iso_z(datetime.fromtimestamp(check.issued_at_ms / 1000, UTC))
        waited = pause_elapsed(check.issued_at_ms, self.deps.clock.now(), min_pause_s(self.fee))
        return self._context(
            store, identity, res, read_back_required=True, read_back_matches=check.matches,
            pause_elapsed=waited, user_confirmed=self.user_confirmed)

    def plan(self, store: Store, identity: Identity, now_iso: str, decision: Decision) -> WritePlan:
        res, fee = self.reservation, self.fee
        rkey = keys.reservation(res.reservation_id)
        slot_key = keys.slot(res.venue_id, res.date, res.time, res.table_group)
        s2 = keys.agent_covers_counter(res.venue_id, res.date)
        ops = [
            TxOp(
                "Update", key={"PK": rkey.pk, "SK": rkey.sk},
                update="SET #st = :cancelled, cancelled_at = :now, cancel_fee_cents = :fee"
                       + (", cancel_read_back_at = :rb" if self.read_back_at else ""),
                condition="#st = :confirmed AND #sub = :sub", names={"#st": "status", "#sub": "sub"},
                values={":cancelled": RES_CANCELLED, ":confirmed": RES_CONFIRMED, ":now": now_iso,
                        ":fee": fee, ":sub": identity.sub, **({":rb": self.read_back_at} if self.read_back_at else {})},
            ),
            TxOp(
                "Update", key={"PK": slot_key.pk, "SK": slot_key.sk},
                update="SET #st = :open, ver = ver + :one REMOVE reservation_id, hold_id",
                condition="reservation_id = :rid AND #st = :confirmed", names={"#st": "status"},
                values={":open": SLOT_OPEN, ":one": 1, ":rid": res.reservation_id, ":confirmed": SLOT_CONFIRMED},
            ),
            TxOp(
                "Update", key={"PK": s2.pk, "SK": s2.sk}, update="ADD n :neg",
                condition="n >= :party", values={":neg": -res.party_size, ":party": res.party_size},
            ),
        ]
        when = f"{say_date(res.date)} at {say_time(res.time)}"
        fee_text = "There was no cancellation fee." if fee == 0 else f"The cancellation fee is {say_money(fee)}."
        result = success(
            f"Cancelled the table for {res.party_size} at {self.venue.name} on {when}. {fee_text}",
            reservation_id=res.reservation_id, code=res.code, status=RES_CANCELLED, fee_cents=fee,
            next_step={"tool": "availability_check", "why": "Look for another time if the user still wants a table."},
        )
        # P1-14: after this commit the freed slot is offered to waiting watchers.
        return WritePlan(ops, result, {"reservation_id": res.reservation_id, "fee_cents": fee})

    def explain_cancel(self, failed: list[int], exc: TransactionCancelled) -> FairTableError:
        return not_active()


class ModifyOperation(_ManageBase):
    """Reduce the party size. Never adds covers or cost, so no spoken yes is needed."""

    def __init__(self, deps: AppDeps, reservation: Reservation, new_party_size: int) -> None:
        super().__init__(deps, reservation)
        self.new_party = new_party_size

    def params(self) -> dict:
        return {"action": "modify", "reservation_id": self.reservation.reservation_id,
                "new_party_size": self.new_party}

    def load_facts(self, store: Store, identity: Identity, now_iso: str) -> WriteFacts:
        res = self._fresh(store, identity)
        if not 1 <= self.new_party < res.party_size:
            raise FairTableError(
                ErrorCode.INVALID_INPUT, "Only a smaller party can be changed here.",
                hint=f"new_party_size must be between 1 and {res.party_size - 1}. To add people, "
                     "book a new table.",
            )
        return self._context(store, identity, res)

    def plan(self, store: Store, identity: Identity, now_iso: str, decision: Decision) -> WritePlan:
        res, new = self.reservation, self.new_party
        delta = res.party_size - new
        rkey = keys.reservation(res.reservation_id)
        s2 = keys.agent_covers_counter(res.venue_id, res.date)
        ops = [
            TxOp(
                "Update", key={"PK": rkey.pk, "SK": rkey.sk},
                update="SET party_size = :new, terms_snapshot.party_size = :new",
                condition="#st = :confirmed AND party_size = :old AND #sub = :sub",
                names={"#st": "status", "#sub": "sub"},
                values={":new": new, ":old": res.party_size, ":confirmed": RES_CONFIRMED, ":sub": identity.sub},
            ),
            TxOp(
                "Update", key={"PK": s2.pk, "SK": s2.sk}, update="ADD n :neg",
                condition="n >= :delta", values={":neg": -delta, ":delta": delta},
            ),
        ]
        result = success(
            f"Changed the booking at {self.venue.name} to {new} "
            f"{'person' if new == 1 else 'people'}.",
            reservation_id=res.reservation_id, code=res.code, party_size=new,
            next_step={"tool": "reservation_manage", "why": "You can view or cancel the booking any time."},
        )
        return WritePlan(ops, result, {"reservation_id": res.reservation_id, "party": [res.party_size, new]})

    def explain_cancel(self, failed: list[int], exc: TransactionCancelled) -> FairTableError:
        return not_active()
