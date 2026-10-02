"""availability_check: bookable slots for a restaurant, date and party (read tool, rule G1 +
token bucket). Each slot carries a short ``offer_id`` (D-059) for reservation_hold; the offers are stored for a few minutes."""

from fastmcp import FastMCP

from server.domain.availability import check_party_size, offered_slots, parse_date, parse_window
from server.domain.errors import ErrorCode, FairTableError
from server.domain.output import success
from server.domain.offers import SlotClaims
from server.domain.tool_names import ToolName
from server.middleware import business_errors
from server.tools.common import AppDeps, authorize
from server.tools.present import MAX_OPTIONS, cancel_policy_text, say_time, say_times, terms


def register(mcp: FastMCP, deps: AppDeps) -> None:
    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})  # it only writes disposable bookkeeping: offers and rate counters
    @business_errors
    def availability_check(
        restaurant_id: str,
        date: str,
        time_window: str = "17:00-22:00",
        party_size: int = 2,
    ) -> dict:
        """List free tables for one restaurant on one date.

        `restaurant_id` comes from restaurant_search. `date` is YYYY-MM-DD, `time_window` is
        HH:MM-HH:MM: if the user asked for one time, give just that time (for example 19:00-19:00) so
        that the table they asked for is the one offered. Each slot has an `offer_id` (a short code,
        valid for a few minutes, only for this user): pass it to reservation_hold to hold the table. Slots with `drop_id` are released by a
        Fair Drop: enter with waitlist_watch instead. At most five slots come back, earliest first;
        for later ones ask again with a `time_window` that starts after the last time shown.
        Asking too often is rate limited.
        """
        now = deps.clock.now()
        people = check_party_size(party_size, required=True)
        day = parse_date(date, today=now.date())
        window = parse_window(time_window)
        identity = authorize(deps, ToolName.AVAILABILITY_CHECK, party_size=people)

        venue = deps.store.get_venue(restaurant_id)
        if venue is None:
            raise FairTableError(ErrorCode.NOT_FOUND, "I could not find that restaurant.",
                             hint="Use a restaurant_id from the search results.")
        deps.limiter.check(identity.sub, venue.venue_id)

        slots = offered_slots(
            deps.store.get_slots(venue.venue_id, day.isoformat()),
            party_size=people, window=window, now=now,
        )
        free_times = [s.time for s in slots]
        shown = slots[:MAX_OPTIONS]
        codes = deps.offers.issue_all([
            SlotClaims(venue.venue_id, s.date, s.slot_key, people, s.ver, identity.sub, hot=s.hot, drop_id=s.drop_id)
            for s in shown
        ])
        offered = []
        for s, code in zip(shown, codes, strict=True):
            offered.append(
                {
                    "offer_id": code,
                    "time": s.time,
                    "table_seats": s.seats,
                    "hot": s.hot,
                    "drop_id": s.drop_id,
                    "how_to_book": "waitlist_watch" if s.drop_controlled else "reservation_hold",
                    "terms": terms(venue),
                }
            )
        base = {"restaurant": venue.name, "date": day.isoformat(), "party_size": people}
        if not offered:
            return success(
                f"{venue.name} has no free table for {people} on that day in that window.",
                **base,
                slots=[],
                next_step={
                    "tool": "waitlist_watch",
                    "why": "Register once and you will be told when a table opens.",
                },
            )
        times = free_times
        more = len(slots) - len(offered)
        spoken = f"{venue.name} has a table for {people} at {say_times(times)}."
        if all(o["how_to_book"] == "waitlist_watch" for o in offered):
            spoken = f"{venue.name} releases its {say_time(times[0])} table by lottery."
        first_bookable = next((o for o in offered if o["how_to_book"] == "reservation_hold"), None)
        return success(
            spoken,
            **base,
            cancellation=cancel_policy_text(venue),
            slots=offered,
            more_slots=more,
            next_step={
                "tool": "reservation_hold" if first_bookable else "waitlist_watch",
                "why": (
                    "Hold the chosen slot with its offer_id and a new idempotency_key."
                    if first_bookable
                    else "These slots are released by a Fair Drop: enter the draw for the chosen one."
                ) + (f" {more} more slots are free later: ask again with a time_window that starts after "
                     f"{offered[-1]['time']}." if more else ""),
            },
        )
