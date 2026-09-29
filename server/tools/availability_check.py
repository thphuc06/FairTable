"""availability_check: bookable slots for a restaurant, date and party (read tool, rule G1 +
token bucket). Each slot carries a signed ``slot_token`` for reservation_hold."""

from fastmcp import FastMCP

from server.domain.availability import check_party_size, offered_slots, parse_date, parse_window
from server.domain.errors import ErrorCode, FairTableError
from server.domain.output import success
from server.domain.slot_token import SlotClaims
from server.domain.tool_names import ToolName
from server.middleware import business_errors
from server.tools.common import AppDeps, authorize
from server.tools.present import cancel_policy_text, say_time, say_times, terms


def register(mcp: FastMCP, deps: AppDeps) -> None:
    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    @business_errors
    def availability_check(
        restaurant_id: str,
        date: str,
        time_window: str = "17:00-22:00",
        party_size: int = 2,
    ) -> dict:
        """List free tables for one restaurant on one date.

        `restaurant_id` comes from restaurant_search. `date` is YYYY-MM-DD, `time_window` is
        HH:MM-HH:MM. Each slot has a `slot_token` (valid for a short time, only for this user):
        pass it to reservation_hold to hold the table. Slots with `drop_id` are released by a
        Fair Drop: enter with waitlist_watch instead. Asking too often is rate limited.
        """
        now = deps.clock.now()
        people = check_party_size(party_size, required=True)
        day = parse_date(date, today=now.date())
        window = parse_window(time_window)
        identity = authorize(deps, ToolName.AVAILABILITY_CHECK, party_size=people)

        venue = deps.store.get_venue(restaurant_id)
        if venue is None:
            raise FairTableError(ErrorCode.NOT_FOUND, "No restaurant with that restaurant_id.")
        deps.limiter.check(identity.sub, venue.venue_id)

        slots = offered_slots(
            deps.store.get_slots(venue.venue_id, day.isoformat()),
            party_size=people, window=window, now=now,
        )
        offered = []
        for s in slots:
            token = deps.slot_codec.issue(
                SlotClaims(venue.venue_id, s.date, s.slot_key, people, s.ver, identity.sub,
                           hot=s.hot, drop_id=s.drop_id)
            )
            offered.append(
                {
                    "slot_token": token,
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
        times = [o["time"] for o in offered]
        spoken = f"{venue.name} has a table for {people} at {say_times(times)}."
        if all(o["how_to_book"] == "waitlist_watch" for o in offered):
            spoken = f"{venue.name} releases its {say_time(times[0])} table by lottery."
        first_bookable = next((o for o in offered if o["how_to_book"] == "reservation_hold"), None)
        return success(
            spoken,
            **base,
            cancellation=cancel_policy_text(venue),
            slots=offered,
            next_step={
                "tool": "reservation_hold" if first_bookable else "waitlist_watch",
                "why": (
                    "Hold the chosen slot with its slot_token and a new idempotency_key."
                    if first_bookable
                    else "These slots are released by a Fair Drop: enter it with waitlist_watch."
                ),
            },
        )
