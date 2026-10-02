"""reservation_confirm: confirm a hold after the user said yes (write tool, D-051)."""

from fastmcp import FastMCP

from server.domain.errors import ErrorCode, FairTableError
from server.middleware import business_errors
from server.ops.confirm import ConfirmOperation
from server.pipeline import run_write
from server.tools.common import AppDeps, authenticate
from server.tools.readback import offer_read_back


def register(mcp: FastMCP, deps: AppDeps) -> None:
    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False,
                           "idempotentHint": True, "openWorldHint": False})
    @business_errors
    def reservation_confirm(
        hold_id: str,
        idempotency_key: str,
        read_back_token: str | None = None,
        user_confirmed: bool = False,
    ) -> dict:
        """Book a held table, but only after the user has said yes to the details.

        Steps: reservation_hold returns the details (`read_back`) and a `read_back_token`. Read the details
        to the user and ask whether to book. Wait for their answer. Only if they say yes, call this tool with
        the `hold_id`, the `read_back_token` and `user_confirmed` set to true. Never set `user_confirmed`
        without a yes from the user, and do not call this in the same moment as reading the details. A call
        that skips a step is refused and books nothing; the answer says what to do. `idempotency_key` is a
        fresh unique string (8-128 characters), different from the one used for the hold. Confirm before the
        hold's `expires_at`.
        """
        identity = authenticate(deps)
        hold = deps.store.get_hold(hold_id) if isinstance(hold_id, str) and hold_id else None
        if hold is None or hold.sub != identity.sub:
            raise FairTableError(ErrorCode.NOT_FOUND, "No such hold.")
        op = ConfirmOperation(deps, hold, read_back_token, user_confirmed)
        try:
            return run_write(deps, identity, op, idempotency_key)
        except FairTableError as e:
            raise offer_read_back(e, op, identity)
