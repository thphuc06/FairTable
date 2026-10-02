"""restaurant_search: find restaurants (read tool, rule G1)."""

from typing import Literal

from fastmcp import FastMCP

from server.domain.availability import check_party_size, offered_slots, parse_date
from server.domain.output import success
from server.domain.tool_names import ToolName
from server.domain.venue_match import CLOSE, is_choice, needs_confirmation, rank
from server.middleware import business_errors
from server.tools.common import AppDeps, authorize
from server.tools.present import MAX_OPTIONS, cancel_policy_text, say_time, terms

FULL_DAY = ("00:00", "23:59")


def register(mcp: FastMCP, deps: AppDeps) -> None:
    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    @business_errors
    def restaurant_search(
        query: str = "",
        date: str | None = None,
        party_size: int | None = None,
        response_format: Literal["concise", "detailed"] = "concise",
        offset: int = 0,
    ) -> dict:
        """Find restaurants that take bookings through FairTable.

        `query` is a restaurant name, or a cuisine, city or word of the description (leave empty to list
        all). A name that was heard a little wrong still finds the closest restaurants. Each result says
        how it matched in `match`: "exact", "topic" or "close". When `confirm_name` is true the best result
        is only a close match: say its name to the diner and ask whether that is the restaurant they mean,
        and use availability_check only after a yes (after a no, search again with another spelling).
        Give `date` (YYYY-MM-DD) and `party_size` to also see each restaurant's earliest free
        time that day. At most five restaurants come back at a time; `offset` skips the first ones
        to see the next five. Use availability_check next to get bookable slots.
        """
        today = deps.clock.now().date()
        people = check_party_size(party_size, required=False)
        day = parse_date(date, today=today) if date else None
        authorize(deps, ToolName.RESTAURANT_SEARCH, party_size=people)

        matches = rank(query, deps.store.list_venues())
        found = []
        for match in matches:
            venue = match.venue
            entry = {
                "restaurant_id": venue.venue_id,
                "name": venue.name,
                "cuisine": venue.cuisine,
                "city": venue.city,
                "cancellation": cancel_policy_text(venue),
                "match": match.kind,
            }
            if match.kind == CLOSE:
                entry["match_score"] = match.score
            if response_format == "detailed":
                entry.update(
                    description=venue.description,
                    terms=terms(venue),
                    agent_covers_per_day=venue.agent_cover_cap,
                )
            if day is not None:
                slots = deps.store.get_slots(venue.venue_id, day.isoformat())
                free = offered_slots(
                    slots, party_size=people or 1, window=FULL_DAY, now=deps.clock.now()
                )
                entry["earliest_free_time"] = free[0].time if free else None
            found.append(entry)

        if not found:
            return success(
                "I could not find a restaurant matching that.",
                restaurants=[],
                next_step={"tool": "restaurant_search", "why": "Try a broader query or none."},
            )
        total = len(found)
        confirm = needs_confirmation(matches)
        start = max(offset, 0)
        found = found[start:start + MAX_OPTIONS]
        if not found:
            return success(
                "There are no more restaurants to show.",
                restaurants=[], total_found=total,
                next_step={"tool": "restaurant_search", "why": "Start again from the first page."},
            )
        more = max(total - start - len(found), 0)
        if confirm and start == 0:
            return success(
                _ask_which(matches), restaurants=found, total_found=total, more_after=more, confirm_name=True,
                next_step={
                    "tool": "availability_check",
                    "why": "The name is only a close match. Say the name to the diner and wait for a yes before "
                           "you check availability; after a no, search again with another spelling or by cuisine.",
                },
            )
        names = ", ".join(e["name"] for e in found[:3])
        spoken = f"I found {total} restaurant{'s' if total != 1 else ''}: {names}."
        if more:
            spoken += f" There are {more} more."
        if day is not None:
            first = next((e for e in found if e["earliest_free_time"]), None)
            if first:
                spoken += f" {first['name']} has a table from {say_time(first['earliest_free_time'])}."
        return success(
            spoken,
            restaurants=found,
            total_found=total,
            more_after=more,
            confirm_name=False,
            next_step={
                "tool": "availability_check",
                "why": "Pick a restaurant, then check its slots for a date and party size."
                + (f" To see the other {more}, search again with offset {start + len(found)}." if more else ""),
            },
        )


def _ask_which(matches) -> str:
    """What to say when the best result is only a close match of a name: ask, never assume."""
    close = [m.venue.name for m in matches if m.kind == CLOSE][:3]
    if is_choice(matches):
        return f"I did not find that exact name. The closest are {', '.join(close[:-1])} and {close[-1]}. Which one do you mean?"
    return f"I did not find that exact name. The closest is {close[0]}. Is that the restaurant you mean?"
