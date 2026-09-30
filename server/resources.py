"""Public MCP resources (D-023). No sign-in: they hold no personal data.

* ``fairtable://restaurants/{restaurant_id}/policies``  the booking rules in plain English, with this
  restaurant's numbers (they are the rules the server actually enforces, see policies/*.cedar).
* ``fairtable://drops/{drop_id}/audit``  a Fair Drop's commitment and rules before the draw, and the
  full verifiable record (seed, order, winners) after it. Reading it after the drop time runs the draw.
"""

import json

from fastmcp import FastMCP
from fastmcp.exceptions import ResourceError

from server.domain.booking import MAX_ACTIVE_HOLDS
from server.domain.fairdrop import DROP_ALLOCATED, pending_audit
from server.domain.models import Venue
from server.dropper import maybe_allocate
from server.tools.common import AppDeps
from server.tools.present import say_money


def policy_text(venue: Venue) -> str:
    fee = "is free" if venue.cancel_fee_cents == 0 else f"costs {say_money(venue.cancel_fee_cents)}"
    return f"""# Booking rules at {venue.name}

These rules are enforced by the FairTable server, not by the assistant. An assistant cannot skip them.

- Only a **verified agent acting for a signed-in diner** with the `fairtable/book` permission can hold,
  confirm, change or cancel a booking or join a waitlist (rules G2, G4). Machine clients can only read.
- **Groups larger than 10** must call the restaurant (G3).
- A diner can have at most **{MAX_ACTIVE_HOLDS} active holds** here at once (S1). A hold lasts 10 minutes.
- Agents can book at most **{venue.agent_cover_cap} covers per day** here ({venue.agent_share_pct}% of
  {venue.seats_per_day} seats); the rest is kept for phone and walk-in guests (S2).
- **Hot tables** are released only through a Fair Drop lottery, never by direct booking (S4). The draw
  is committed in advance and can be verified by anyone.
- **Confirming** a booking needs the diner's standing permission; anything outside it is approved by the
  diner on their phone first (S3). The approval is for that exact booking and can be used once.
- **Cancelling** {venue.free_cancel_hours} hours or less before the booking {fee}. If a fee applies the
  diner must approve it first; a booking is never cancelled silently with a fee (S3b).
"""


def register(mcp: FastMCP, deps: AppDeps) -> None:
    @mcp.resource("fairtable://restaurants/{restaurant_id}/policies", mime_type="text/markdown")
    def restaurant_policies(restaurant_id: str) -> str:
        venue = deps.store.get_venue(restaurant_id)
        if venue is None:
            raise ResourceError("No restaurant with that id.")
        return policy_text(venue)

    @mcp.resource("fairtable://drops/{drop_id}/audit", mime_type="application/json")
    def drop_audit(drop_id: str) -> str:
        drop = maybe_allocate(deps, drop_id)
        if drop is None:
            raise ResourceError("No drop with that id.")
        record = drop.audit if drop.status == DROP_ALLOCATED and drop.audit else pending_audit(drop)
        return json.dumps(record, indent=2, sort_keys=True)
