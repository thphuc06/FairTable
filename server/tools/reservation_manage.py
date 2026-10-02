"""reservation_manage: view, reduce or cancel a booking (write tool)."""

from typing import Literal

from fastmcp import FastMCP

from server.domain.booking import cancel_fee_cents
from server.domain.errors import ErrorCode, FairTableError
from server.domain.idempotency import validate_key
from server.domain.output import success
from server.domain.tool_names import ToolName
from server.middleware import business_errors
from server.ops.manage import CancelOperation, ModifyOperation
from server.pipeline import run_write
from server.tools.common import AppDeps, authenticate, check_pep1
from server.tools.present import cancel_policy_text_from_terms, say_date, say_money, say_time
from server.tools.readback import offer_read_back


def register(mcp: FastMCP, deps: AppDeps) -> None:
    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True,
                           "idempotentHint": True, "openWorldHint": False})
    @business_errors
    def reservation_manage(
        action: Literal["view", "modify", "cancel"],
        reservation_id: str,
        idempotency_key: str | None = None,
        new_party_size: int | None = None,
        read_back_token: str | None = None,
        user_confirmed: bool = False,
    ) -> dict:
        """View, shrink or cancel one of the user's bookings.

        `view` shows the booking and what cancelling it would cost right now. `modify` lowers the
        party size (`new_party_size`); to add people, book a new table. `cancel` frees the table. If a
        cancellation fee applies, the first `cancel` is refused and returns the fee as a sentence
        (`read_back`) with a `read_back_token`: read it to the user and ask. Only if they say yes, call
        `cancel` again with that `read_back_token` and `user_confirmed` set to true (after a short pause for
        their answer). `modify` and `cancel` need an `idempotency_key`.
        """
        identity = authenticate(deps)
        res = deps.store.get_reservation(reservation_id) if isinstance(reservation_id, str) and reservation_id else None
        if res is None or res.sub != identity.sub:
            raise FairTableError(ErrorCode.NOT_FOUND, "No such reservation.")

        if action == "view":
            check_pep1(deps, identity, ToolName.RESERVATION_MANAGE, res.party_size)
            return _view(deps, res)

        validate_key(idempotency_key)
        if action == "modify":
            if not isinstance(new_party_size, int) or isinstance(new_party_size, bool):
                raise FairTableError(ErrorCode.INVALID_INPUT, "How many people should the booking be for?",
                                 hint="Pass new_party_size as a whole number.")
            op = ModifyOperation(deps, res, new_party_size)
        else:
            op = CancelOperation(deps, res, read_back_token, user_confirmed)
        try:
            result = run_write(deps, identity, op, idempotency_key)
        except FairTableError as e:
            raise offer_read_back(e, op, identity)
        if action == "cancel" and not result.get("idempotent_replay"):
            deps.slot_released(res.venue_id, res.date, res.time, res.table_group)  # waitlist matching
        return result


def _view(deps: AppDeps, res) -> dict:
    venue = deps.store.get_venue(res.venue_id)
    when = f"{say_date(res.date)} at {say_time(res.time)}"
    card = {
        "reservation_id": res.reservation_id, "code": res.code, "status": res.status,
        "restaurant": res.terms_snapshot.get("restaurant"), "date": res.date, "time": res.time,
        "party_size": res.party_size, "cancellation": cancel_policy_text_from_terms(res.terms_snapshot),
    }
    if res.status != "confirmed":
        return success(
            f"That booking at {card['restaurant']} on {when} was cancelled.",
            reservation=card, cancelled_at=res.cancelled_at, cancel_fee_cents=res.cancel_fee_cents,
            next_step={"tool": "availability_check", "why": "Look for another time."},
        )
    fee = cancel_fee_cents(venue, res.date, res.time, deps.clock.now()) if venue else 0
    fee_text = "Cancelling now is free." if fee == 0 else (
        f"Cancelling now costs {say_money(fee)} and needs the user's yes."
    )
    return success(
        f"A table for {res.party_size} at {card['restaurant']} on {when}, code {res.code}. {fee_text}",
        reservation=card, cancel_fee_now_cents=fee,
        next_step={"tool": "reservation_manage", "why": "Cancel or reduce the party if plans changed."},
    )
