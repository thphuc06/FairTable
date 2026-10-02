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
    def reservation_hold(offer_id: str, idempotency_key: str) -> dict:
        """Hold one slot for ten minutes so the user can decide.

        `offer_id` is the short code of one slot from availability_check (about eight letters and digits; it is only valid
        for the user who asked, for a few minutes).
        `idempotency_key` is a fresh unique string (8-128 characters) per booking attempt: repeat
        the same call with the same key after a network error and you get the same answer, never a
        second hold. The result has the details to read to the user (`read_back`) and a `read_back_token`:
        read the details out, ask whether to book, and only when the user says yes follow with
        reservation_confirm before `expires_at`.
        """
        identity = authenticate(deps)
        claims = deps.offers.verify(offer_id, sub=identity.sub)
        return run_write(deps, identity, HoldOperation(deps, claims, from_agent=True), idempotency_key)
