"""reservation_manage: cancel (with the fee decided *before* anything is written) and reduce the
party size. ``view`` changes nothing and lives in the tool.

Cancel transaction (plus idempotency record and audit from the pipeline):
  0. reservation -> cancelled   (still confirmed, same user; the fee is recorded)
  1. slot -> open               (still owned by this reservation)
  2. S2 counter - party         (the covers are free for other agents again)
  3. approval -> used           (only when a fee was approved)
Rule S3b turns a cancel with an unacknowledged fee into step-up: no silent cancel with a fee.
"""

from server.consent import ApprovalRequest, declined_error, is_declined
from server.domain.booking import (
    APPROVAL_APPROVED,
    APPROVAL_USED,
    KIND_CANCEL_FEE,
    RES_CANCELLED,
    RES_CONFIRMED,
    Reservation,
    approval_is_usable,
    cancel_fee_cents,
    terms_for,
    terms_hash,
)
from server.domain.errors import ErrorCode, FairTableError
from server.domain.models import SLOT_CONFIRMED, SLOT_OPEN, Identity
from server.domain.output import success
from server.domain.tool_names import ToolName
from server.kernel import Decision, PolicyContext, VenueRef
from server.ops.common import counter_value, parse_iso
from server.pipeline import WriteFacts, WritePlan
from server.store import Store, TransactionCancelled, TxOp, keys
from server.tools.common import AppDeps
from server.tools.present import say_date, say_money, say_time


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

    def _context(self, store: Store, identity: Identity, res: Reservation, *, fee: int,
                 acknowledged: bool) -> WriteFacts:
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
                mandate_covers_booking=True,  # only rule S3 (confirm) reads this
                slot_is_drop_controlled=False,
                cancel_fee_cents=fee,
                cancel_fee_acknowledged=acknowledged,
            ),
        )


class CancelOperation(_ManageBase):
    def __init__(self, deps: AppDeps, reservation: Reservation) -> None:
        super().__init__(deps, reservation)
        self.fee = 0
        self.approval = None

    def params(self) -> dict:
        return {"action": "cancel", "reservation_id": self.reservation.reservation_id}

    def _terms(self) -> dict:
        r = self.reservation
        return terms_for(self.venue, r.date, r.time, r.party_size, fee_cents=self.fee)

    def approval_request(self) -> ApprovalRequest:
        r = self.reservation
        return ApprovalRequest(r.reservation_id, KIND_CANCEL_FEE, r.sub, r.venue_id, self._terms())

    def load_facts(self, store: Store, identity: Identity, now_iso: str) -> WriteFacts:
        res = self._fresh(store, identity)
        facts = self._context(store, identity, res, fee=0, acknowledged=False)
        self.fee = cancel_fee_cents(self.venue, res.date, res.time, parse_iso(now_iso))
        acknowledged = False
        if self.fee > 0:
            digest = terms_hash(self._terms())
            approval = store.get_approval(res.reservation_id)
            if is_declined(approval, sub=identity.sub, terms_digest=digest):
                raise declined_error()
            if approval_is_usable(approval, sub=identity.sub, terms_digest=digest, now_iso=now_iso):
                self.approval, acknowledged = approval, True
        ctx = PolicyContext(**{**facts.ctx.to_cedar(), "cancel_fee_cents": self.fee,
                               "cancel_fee_acknowledged": acknowledged})
        return WriteFacts(facts.venue, ctx)

    def plan(self, store: Store, identity: Identity, now_iso: str, decision: Decision) -> WritePlan:
        res, fee = self.reservation, self.fee
        rkey = keys.reservation(res.reservation_id)
        slot_key = keys.slot(res.venue_id, res.date, res.time, res.table_group)
        s2 = keys.agent_covers_counter(res.venue_id, res.date)
        ops = [
            TxOp(
                "Update", key={"PK": rkey.pk, "SK": rkey.sk},
                update="SET #st = :cancelled, cancelled_at = :now, cancel_fee_cents = :fee",
                condition="#st = :confirmed AND #sub = :sub", names={"#st": "status", "#sub": "sub"},
                values={":cancelled": RES_CANCELLED, ":confirmed": RES_CONFIRMED, ":now": now_iso,
                        ":fee": fee, ":sub": identity.sub},
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
        if self.approval is not None:
            ak = keys.approval(res.reservation_id)
            ops.append(TxOp(
                "Update", key={"PK": ak.pk, "SK": ak.sk}, update="SET #st = :used",
                condition="#st = :approved AND #sub = :sub AND terms_hash = :h AND expires_at > :now",
                names={"#st": "status", "#sub": "sub"},
                values={":used": APPROVAL_USED, ":approved": APPROVAL_APPROVED, ":sub": identity.sub,
                        ":h": self.approval.terms_hash, ":now": now_iso},
            ))
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
        if 3 in failed:
            return FairTableError(ErrorCode.FEE_APPLIES, "The user's approval was already used or has expired.",
                                  hint="Ask the user to approve again.")
        return not_active()


class ModifyOperation(_ManageBase):
    """Reduce the party size. Never adds covers or cost, so no consent is needed."""

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
        return self._context(store, identity, res, fee=0, acknowledged=False)

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
