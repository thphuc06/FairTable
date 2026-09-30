"""reservation_confirm: turn a live hold into a reservation.

Inside the user's standing mandate it confirms at once. Outside it (or with no mandate) rule S3
answers step-up until the user has approved this exact hold on the consent page; the approval is
then consumed in the same transaction.

Transaction (plus idempotency record and audit from the pipeline):
  0. hold -> confirmed       (still held, not expired, same user)
  1. slot -> confirmed       (still owned by this hold)
  2. S1 counter - 1          (a confirmed hold is no longer an active hold; S2 covers stay)
  3. reservation record      (new)
  4. approval -> used        (only when an approval made the booking allowed)
"""

from server.consent import ApprovalRequest, declined_error, is_declined
from server.domain.booking import (
    APPROVAL_APPROVED,
    APPROVAL_USED,
    HOLD_CONFIRMED,
    HOLD_HELD,
    KIND_CONFIRM,
    RES_CONFIRMED,
    Approval,
    Hold,
    Reservation,
    approval_is_usable,
    reservation_code,
    terms_hash,
)
from server.domain.errors import ErrorCode, FairTableError
from server.domain.mandate import check_mandate
from server.domain.models import SLOT_CONFIRMED, SLOT_HELD, Identity
from server.domain.output import success
from server.domain.tool_names import ToolName
from server.kernel import Decision, PolicyContext, VenueRef
from server.lifecycle import release_expired
from server.ops.common import counter_value, parse_iso
from server.pipeline import WriteFacts, WritePlan
from server.store import Store, TransactionCancelled, TxOp, keys
from server.tools.common import AppDeps
from server.tools.present import cancel_policy_text_from_terms, say_date, say_time


def hold_expired() -> FairTableError:
    return FairTableError(ErrorCode.HOLD_EXPIRED, "This hold has expired or is no longer active.")


class ConfirmOperation:
    tool = ToolName.RESERVATION_CONFIRM

    def __init__(self, deps: AppDeps, hold: Hold) -> None:
        self.deps = deps
        self.hold = hold
        self.venue_id = hold.venue_id
        self.party_size = hold.party_size
        self.approval: Approval | None = None  # set when an approval makes the booking allowed

    def params(self) -> dict:
        return {"hold_id": self.hold.hold_id}

    def approval_request(self) -> ApprovalRequest:
        h = self.hold
        return ApprovalRequest(h.hold_id, KIND_CONFIRM, h.sub, h.venue_id, h.terms)

    # ------------------------------------------------------------------ facts
    def load_facts(self, store: Store, identity: Identity, now_iso: str) -> WriteFacts:
        hold = store.get_hold(self.hold.hold_id)
        if hold is None or hold.sub != identity.sub:
            raise FairTableError(ErrorCode.NOT_FOUND, "No such hold.")
        if hold.status == HOLD_CONFIRMED:
            raw = store.get_item(keys.hold(hold.hold_id)) or {}
            raise FairTableError(
                ErrorCode.INVALID_INPUT, "This hold was already confirmed.",
                details={"reservation_id": raw.get("reservation_id")},
            )
        if hold.status != HOLD_HELD:
            raise hold_expired()
        if hold.held_until <= now_iso:
            if release_expired(store, hold, now_iso):
                self.deps.slot_released(hold.venue_id, hold.date, hold.time, hold.table_group)
            raise hold_expired()
        self.hold = hold

        venue = store.get_venue(hold.venue_id)
        slot = store.get_slot(hold.venue_id, hold.date, hold.time, hold.table_group)
        if venue is None or slot is None or slot.hold_id != hold.hold_id or slot.status != SLOT_HELD:
            raise hold_expired()

        mandate = store.get_mandate(identity.sub, hold.venue_id)
        check = check_mandate(
            mandate, now=parse_iso(now_iso), agent_id=identity.agent_id, party_size=hold.party_size,
            day=parse_iso(hold.date).date(), time=hold.time, cancel_fee_cents=venue.cancel_fee_cents,
        )
        allowed = check.covered
        if not allowed:
            digest = terms_hash(hold.terms)
            approval = store.get_approval(hold.hold_id)
            if is_declined(approval, sub=identity.sub, terms_digest=digest):
                raise declined_error()
            if approval_is_usable(approval, sub=identity.sub, terms_digest=digest, now_iso=now_iso):
                self.approval, allowed = approval, True
        self.venue, self.slot, self.check = venue, slot, check
        return WriteFacts(
            VenueRef(venue.venue_id, venue.agent_cover_cap),
            PolicyContext(
                agent_tier=identity.agent_tier or "none",
                active_holds_user_venue=counter_value(store, keys.active_holds_counter(identity.sub, hold.venue_id)),
                agent_covers_booked=counter_value(store, keys.agent_covers_counter(hold.venue_id, hold.date)),
                party_size=hold.party_size,
                mandate_covers_booking=allowed,
                slot_is_drop_controlled=slot.drop_controlled,
                cancel_fee_cents=0,
                cancel_fee_acknowledged=False,
            ),
        )

    # ------------------------------------------------------------------ the transaction
    def plan(self, store: Store, identity: Identity, now_iso: str, decision: Decision) -> WritePlan:
        hold, venue = self.hold, self.venue
        reservation_id = self.deps.new_id()
        code = reservation_code(hold.venue_id, reservation_id)
        reservation = Reservation(
            reservation_id=reservation_id, code=code, hold_id=hold.hold_id, sub=identity.sub,
            agent_id=identity.agent_id, venue_id=hold.venue_id, date=hold.date, time=hold.time,
            table_group=hold.table_group, party_size=hold.party_size, status=RES_CONFIRMED,
            terms_snapshot=hold.terms, created_at=now_iso,
        )
        hold_key = keys.hold(hold.hold_id)
        slot_key = keys.slot(hold.venue_id, hold.date, hold.time, hold.table_group)
        s1 = keys.active_holds_counter(identity.sub, hold.venue_id)
        ops = [
            TxOp(
                "Update", key={"PK": hold_key.pk, "SK": hold_key.sk},
                update="SET #st = :confirmed, reservation_id = :rid REMOVE GSI1PK, GSI1SK",
                condition="#st = :held AND held_until > :now AND #sub = :sub",
                names={"#st": "status", "#sub": "sub"},
                values={":confirmed": HOLD_CONFIRMED, ":rid": reservation_id, ":held": HOLD_HELD,
                        ":now": now_iso, ":sub": identity.sub},
            ),
            TxOp(
                "Update", key={"PK": slot_key.pk, "SK": slot_key.sk},
                update="SET #st = :confirmed, ver = ver + :one, reservation_id = :rid REMOVE held_until",
                condition="hold_id = :hid AND #st = :held", names={"#st": "status"},
                values={":confirmed": SLOT_CONFIRMED, ":one": 1, ":rid": reservation_id,
                        ":hid": hold.hold_id, ":held": SLOT_HELD},
            ),
            TxOp(
                "Update", key={"PK": s1.pk, "SK": s1.sk}, update="ADD n :neg",
                condition="n >= :one", values={":neg": -1, ":one": 1},
            ),
            store.reservation_put_op(reservation),
        ]
        if self.approval is not None:
            ak = keys.approval(hold.hold_id)
            ops.append(TxOp(
                "Update", key={"PK": ak.pk, "SK": ak.sk}, update="SET #st = :used",
                condition="#st = :approved AND #sub = :sub AND terms_hash = :h AND expires_at > :now",
                names={"#st": "status", "#sub": "sub"},
                values={":used": APPROVAL_USED, ":approved": APPROVAL_APPROVED, ":sub": identity.sub,
                        ":h": self.approval.terms_hash, ":now": now_iso},
            ))
        card = {
            "title": f"Table at {venue.name}", "code": code, "restaurant": venue.name,
            "date": hold.date, "time": hold.time, "party_size": hold.party_size,
            "cancellation": cancel_policy_text_from_terms(hold.terms),
        }
        result = success(
            f"Booked. A table for {hold.party_size} at {venue.name} on {say_date(hold.date)} at "
            f"{say_time(hold.time)}. Your code is {code}.",
            reservation_id=reservation_id, code=code, terms_snapshot=hold.terms, booking_card=card,
            approved_by_user=self.approval is not None,
            next_step={"tool": "reservation_manage",
                       "why": "If plans change, view or cancel the booking with its reservation_id."},
        )
        return WritePlan(ops, result, {"reservation_id": reservation_id, "hold_id": hold.hold_id,
                                       "approved_by_user": self.approval is not None})

    def explain_cancel(self, failed: list[int], exc: TransactionCancelled) -> FairTableError:
        if 4 in failed:
            return FairTableError(
                ErrorCode.CONSENT_REQUIRED, "The user's approval was already used or has expired.",
                hint="Ask the user to approve again.",
            )
        return hold_expired()
