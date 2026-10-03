"""reservation_confirm: turn a live hold into a reservation, after a spoken yes (D-051).

The diner is asked by the assistant, who read back the terms from ``reservation_hold``. The server cannot hear
the answer; rules S5a-c (Cedar) check what it can: the read-back token fits this hold, this user and these terms
(a), enough time has passed for an answer (b), and the assistant states that the diner said yes (c). The
booking records when the read-back was handed over.

Transaction (plus idempotency record and audit from the pipeline):
  0. hold -> confirmed       (still held, not expired, same user)
  1. slot -> confirmed       (still owned by this hold)
  2. S1 counter - 1          (a confirmed hold is no longer an active hold; S2 covers stay)
  3. reservation record      (new, with how it was confirmed)
  4. BOOKED# marker          (new: one confirmed table per diner, restaurant and day, D-066)
"""

from datetime import UTC, datetime

from server.domain.booking import (
    HOLD_CONFIRMED,
    HOLD_HELD,
    RES_CONFIRMED,
    Hold,
    Reservation,
    reservation_code,
)
from server.domain.clock import iso_z
from server.domain.errors import ErrorCode, FairTableError
from server.domain.models import SLOT_CONFIRMED, SLOT_HELD, Identity
from server.domain.output import success
from server.domain.readback import KIND_CONFIRM, min_pause_s, pause_elapsed
from server.domain.tool_names import ToolName
from server.kernel import Decision, PolicyContext, VenueRef, error_for_rule
from server.lifecycle import release_expired
from server.ops.common import counter_value
from server.pipeline import WriteFacts, WritePlan
from server.store import Store, TransactionCancelled, TxOp, keys
from server.tools.common import AppDeps
from server.tools.present import cancel_policy_text_from_terms, read_back_confirm, say_date, say_time


def hold_expired() -> FairTableError:
    return FairTableError(ErrorCode.HOLD_EXPIRED, "This hold has expired or is no longer active.")


class ConfirmOperation:
    tool = ToolName.RESERVATION_CONFIRM

    def __init__(self, deps: AppDeps, hold: Hold, read_back_token: str | None, user_confirmed: bool) -> None:
        self.deps = deps
        self.hold = hold
        self.venue_id = hold.venue_id
        self.party_size = hold.party_size
        self.read_back_token = read_back_token
        self.user_confirmed = user_confirmed is True
        self.read_back_at: str | None = None  # when the read-back was handed over, if the token fits

    def params(self) -> dict:
        return {"hold_id": self.hold.hold_id}

    # ------------------------------------------------------------------ the read-back, offered again
    def read_back_offer(self, identity: Identity) -> dict:
        """A fresh read-back for the assistant to say, used when the first one is missing or does not fit."""
        terms = self.hold.terms
        token = self.deps.readback_codec.issue(
            kind=KIND_CONFIRM, subject_id=self.hold.hold_id, sub=identity.sub, terms=terms)
        return {"read_back": read_back_confirm(terms), "read_back_token": token,
                "min_pause_s": min_pause_s(terms["cancel_fee_cents"])}

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

        check = self.deps.readback_codec.check(
            self.read_back_token, kind=KIND_CONFIRM, subject_id=hold.hold_id, sub=identity.sub, terms=hold.terms)
        waited = pause_elapsed(check.issued_at_ms, self.deps.clock.now(), min_pause_s(hold.terms["cancel_fee_cents"]))
        if check.matches and check.issued_at_ms is not None:
            self.read_back_at = iso_z(datetime.fromtimestamp(check.issued_at_ms / 1000, UTC))
        self.venue, self.slot = venue, slot
        return WriteFacts(
            VenueRef(venue.venue_id, venue.agent_cover_cap),
            PolicyContext(
                agent_tier=identity.agent_tier or "none",
                active_holds_user_venue=counter_value(store, keys.active_holds_counter(identity.sub, hold.venue_id)),
                agent_covers_booked=counter_value(store, keys.agent_covers_counter(hold.venue_id, hold.date)),
                party_size=hold.party_size,
                slot_is_drop_controlled=slot.drop_controlled,
                booked_same_day=False,  # S6 guards a hold; the database condition guards the confirm
                read_back_required=True,
                read_back_matches=check.matches,
                pause_elapsed=waited,
                user_confirmed=self.user_confirmed,
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
            terms_snapshot=hold.terms, created_at=now_iso, confirmation="spoken", read_back_at=self.read_back_at,
        )
        hold_key = keys.hold(hold.hold_id)
        slot_key = keys.slot(hold.venue_id, hold.date, hold.time, hold.table_group)
        s1 = keys.active_holds_counter(identity.sub, hold.venue_id)
        booked_key = keys.booked_day(identity.sub, hold.venue_id, hold.date)
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
            TxOp(
                "Put", condition="attribute_not_exists(PK)",
                item={"PK": booked_key.pk, "SK": booked_key.sk, "entity": "booked_day", "sub": identity.sub,
                      "venue_id": hold.venue_id, "date": hold.date, "reservation_id": reservation_id},
            ),
        ]
        card = {
            "title": f"Table at {venue.name}", "code": code, "restaurant": venue.name,
            "date": hold.date, "time": hold.time, "party_size": hold.party_size,
            "cancellation": cancel_policy_text_from_terms(hold.terms),
        }
        result = success(
            f"Booked. A table for {hold.party_size} at {venue.name} on {say_date(hold.date)} at "
            f"{say_time(hold.time)}. Your code is {code}.",
            reservation_id=reservation_id, code=code, terms_snapshot=hold.terms, booking_card=card,
            next_step={"tool": "reservation_manage",
                       "why": "If plans change, view or cancel the booking with its reservation_id."},
        )
        return WritePlan(ops, result, {"reservation_id": reservation_id, "hold_id": hold.hold_id,
                                       "confirmation": "spoken", "read_back_at": self.read_back_at})

    def explain_cancel(self, failed: list[int], exc: TransactionCancelled) -> FairTableError:
        marker = 4  # the BOOKED# write; when it is the only one that failed, the diner already has a table that day
        if failed == [marker]:
            return error_for_rule("S6_one_booking_per_restaurant_day")
        return hold_expired()
