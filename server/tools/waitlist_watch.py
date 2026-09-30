"""waitlist_watch: register once, get a hold when a table opens; or enter a Fair Drop (write tool).

Standing watch for a normal day (D-023); with ``drop_id`` it enters the verifiable lottery for a
drop-controlled table instead. Both are write tools: a verified agent acting for a signed-in user.
"""

from fastmcp import FastMCP

from server.domain.availability import (
    check_party_size,
    offered_slots,
    parse_date,
    parse_window,
)
from server.domain.errors import ErrorCode, FairTableError
from server.domain.fairdrop import DROP_OPEN
from server.domain.idempotency import validate_key
from server.domain.output import success
from server.domain.tool_names import ToolName
from server.dropper import maybe_allocate
from server.middleware import business_errors
from server.ops.fairdrop import DropEntryOperation, drop_closed
from server.ops.waitlist import WatchOperation
from server.pipeline import run_write
from server.tools.common import AppDeps, authenticate, check_pep1


def register(mcp: FastMCP, deps: AppDeps) -> None:
    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False,
                           "idempotentHint": True, "openWorldHint": False})
    @business_errors
    def waitlist_watch(
        idempotency_key: str,
        restaurant_id: str | None = None,
        date: str | None = None,
        time_window: str = "17:00-22:00",
        party_size: int = 2,
        drop_id: str | None = None,
    ) -> dict:
        """Ask to be given a table when one opens, or enter a Fair Drop lottery.

        Standing watch: give `restaurant_id`, `date`, `time_window` and `party_size`. When a fitting
        table is freed it is held for the user for a few minutes; use waitlist_status (about once a
        minute, no faster) to find the hold and reservation_confirm to book it. One active watch per
        person, restaurant and day. If a fitting table is free right now nothing is registered: book
        it with reservation_hold.
        Fair Drop: for slots with a `drop_id` (they cannot be held directly) pass `drop_id` and
        `party_size`. One ticket per person; winners are drawn by a public lottery whose commitment
        is published in the answer and whose audit anyone can verify.
        """
        people = check_party_size(party_size, required=True)
        validate_key(idempotency_key)  # before any early answer, so a bad key is never ignored
        identity = authenticate(deps)
        check_pep1(deps, identity, ToolName.WAITLIST_WATCH, people)

        if drop_id:
            drop = maybe_allocate(deps, drop_id)  # the first request after the drop time runs the draw
            if drop is None:
                raise FairTableError(ErrorCode.NOT_FOUND, "No such drop.")
            if drop.status != DROP_OPEN:
                raise drop_closed()
            return run_write(deps, identity, DropEntryOperation(deps, drop, people), idempotency_key)

        if not restaurant_id or not date:
            raise FairTableError(ErrorCode.INVALID_INPUT,
                                 "Give restaurant_id and date for a watch, or drop_id to enter a drop.")
        now = deps.clock.now()
        day = parse_date(date, today=now.date())
        window = parse_window(time_window)
        venue = deps.store.get_venue(restaurant_id)
        if venue is None:
            raise FairTableError(ErrorCode.NOT_FOUND, "No restaurant with that restaurant_id.")
        free = offered_slots(deps.store.get_slots(venue.venue_id, day.isoformat(), consistent=True),
                             party_size=people, window=window, now=now)
        if any(not s.drop_controlled for s in free):
            return success(
                f"{venue.name} already has a free table for {people} in that window, so there is nothing to wait for.",
                status="tables_available", restaurant_id=venue.venue_id,
                next_step={"tool": "availability_check", "why": "Look at the free slots and hold one."},
            )
        return run_write(deps, identity, WatchOperation(deps, venue.venue_id, day.isoformat(), window, people),
                         idempotency_key)
