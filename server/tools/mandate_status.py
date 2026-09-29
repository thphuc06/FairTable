"""mandate_status: what the user has pre-approved at a restaurant, and what will need approval
(read tool, rule G1). Lets the agent warn the user before a booking surprises them."""

from fastmcp import FastMCP

from server.domain.errors import ErrorCode, FairTableError
from server.domain.mandate import is_active
from server.domain.models import Mandate
from server.domain.output import success
from server.domain.tool_names import ToolName
from server.middleware import business_errors
from server.tools.common import AppDeps, authorize
from server.tools.present import say_money, say_time


def approval_needed_when(m: Mandate) -> list[str]:
    conditions = [
        f"the party is larger than {m.party_size_max}",
        f"the date is more than {m.days_ahead_max} days ahead",
        f"the time is outside {say_time(m.window_start)} to {say_time(m.window_end)}",
        f"the cancellation fee is above {say_money(m.max_cancel_fee_cents)}",
    ]
    if not m.allow_auto_confirm or "confirm" not in m.actions:
        conditions.insert(0, "any booking (confirming without asking is not allowed)")
    return conditions


def register(mcp: FastMCP, deps: AppDeps) -> None:
    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    @business_errors
    def mandate_status(restaurant_id: str) -> dict:
        """Show the standing permission this user gave for a restaurant.

        Bookings inside it confirm immediately; anything outside it needs the user's approval
        on their phone. Call this before booking so you can tell the user what to expect.
        """
        identity = authorize(deps, ToolName.MANDATE_STATUS)
        venue = deps.store.get_venue(restaurant_id)
        if venue is None:
            raise FairTableError(ErrorCode.NOT_FOUND, "No restaurant with that restaurant_id.")
        mandate = deps.store.get_mandate(identity.sub, venue.venue_id)
        now = deps.clock.now()

        if mandate is None or not is_active(mandate, now):
            state = "none" if mandate is None else "inactive"
            return success(
                f"There is no active standing permission at {venue.name}, so every booking there "
                "will need the user's approval on their phone.",
                restaurant_id=venue.venue_id,
                mandate_state=state,
                scope=None,
                needs_approval_when=["always"],
                next_step={
                    "tool": "availability_check",
                    "why": "You can still hold a table; confirming will ask the user to approve.",
                },
            )
        return success(
            f"At {venue.name} you may book up to {mandate.party_size_max} people, "
            f"between {say_time(mandate.window_start)} and {say_time(mandate.window_end)}, "
            f"up to {mandate.days_ahead_max} days ahead. Anything else needs approval.",
            restaurant_id=venue.venue_id,
            mandate_state="active",
            scope={
                "party_size_max": mandate.party_size_max,
                "days_ahead_max": mandate.days_ahead_max,
                "time_window": f"{mandate.window_start}-{mandate.window_end}",
                "max_cancel_fee_cents": mandate.max_cancel_fee_cents,
                "auto_confirm": mandate.allow_auto_confirm,
                "actions": sorted(mandate.actions),
                "expires_at": mandate.expires_at,
            },
            needs_approval_when=approval_needed_when(mandate),
            next_step={"tool": "availability_check", "why": "Look for a slot inside the scope."},
        )
