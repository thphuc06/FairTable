"""reservation_hold: hold a slot from availability_check for ten minutes (write tool)."""

from fastmcp import FastMCP

from server.middleware import business_errors
from server.ops.hold import HoldOperation
from server.pipeline import run_write
from server.tools.common import AppDeps, authenticate


def register(mcp: FastMCP, deps: AppDeps) -> None:
    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False,
                           "idempotentHint": True, "openWorldHint": False})
    @business_errors
    def reservation_hold(slot_token: str, idempotency_key: str) -> dict:
        """Hold one slot for ten minutes so the user can decide.

        `slot_token` comes from availability_check (it is only valid for the user who asked).
        `idempotency_key` is a fresh unique string (8-128 characters) per booking attempt: repeat
        the same call with the same key after a network error and you get the same answer, never a
        second hold. The result says whether the booking is inside the user's standing permission
        (`within_mandate`). Follow with reservation_confirm before `expires_at`.
        """
        identity = authenticate(deps)
        claims = deps.slot_codec.verify(slot_token, sub=identity.sub)
        return run_write(deps, identity, HoldOperation(deps, claims), idempotency_key)
