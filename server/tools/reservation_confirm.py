"""reservation_confirm: confirm a hold (write tool). Step-up when it is outside the mandate."""

from fastmcp import FastMCP

from server.domain.errors import ErrorCode, FairTableError
from server.middleware import business_errors
from server.ops.confirm import ConfirmOperation
from server.pipeline import StepUpRequired, run_write
from server.tools.common import AppDeps, authenticate
from server.tools.stepup import raise_step_up


def register(mcp: FastMCP, deps: AppDeps) -> None:
    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False,
                           "idempotentHint": True, "openWorldHint": False})
    @business_errors
    def reservation_confirm(hold_id: str, idempotency_key: str) -> dict:
        """Confirm a hold from reservation_hold and get the booking code.

        If the booking is inside the user's standing permission (see mandate_status) it is booked
        at once. If not, the user has to approve it on their phone first: you receive either a
        `-32042` URL-elicitation error or an error with `consent_url`. Tell the user to approve,
        then call this tool again with the SAME `idempotency_key`. Confirm before the hold's
        `expires_at`.
        """
        identity = authenticate(deps)
        hold = deps.store.get_hold(hold_id) if isinstance(hold_id, str) and hold_id else None
        if hold is None or hold.sub != identity.sub:
            raise FairTableError(ErrorCode.NOT_FOUND, "No such hold.")
        try:
            return run_write(deps, identity, ConfirmOperation(deps, hold), idempotency_key)
        except StepUpRequired as exc:
            raise_step_up(deps, exc)
