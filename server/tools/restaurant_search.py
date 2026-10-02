"""restaurant_search: find restaurants (read tool, rule G1)."""

from typing import Literal

from fastmcp import FastMCP

from server.domain.availability import check_party_size, offered_slots, parse_date
from server.domain.output import success
from server.domain.tool_names import ToolName
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

        `query` matches the name, cuisine, city or description (leave empty to list all).
        Give `date` (YYYY-MM-DD) and `party_size` to also see each restaurant's earliest free
        time that day. At most five restaurants come back at a time; `offset` skips the first ones
        to see the next five. Use availability_check next to get bookable slots.
        """
        today = deps.clock.now().date()
        people = check_party_size(party_size, required=False)
        day = parse_date(date, today=today) if date else None
        authorize(deps, ToolName.RESTAURANT_SEARCH, party_size=people)

        words = query.lower().split()
        found = []
        for venue in deps.store.list_venues():
            text = f"{venue.name} {venue.cuisine} {venue.city} {venue.description}".lower()
            if not all(w in text for w in words):
                continue
            entry = {
                "restaurant_id": venue.venue_id,
                "name": venue.name,
                "cuisine": venue.cuisine,
                "city": venue.city,
                "cancellation": cancel_policy_text(venue),
            }
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
        start = max(offset, 0)
        found = found[start:start + MAX_OPTIONS]
        if not found:
            return success(
                "There are no more restaurants to show.",
                restaurants=[], total_found=total,
                next_step={"tool": "restaurant_search", "why": "Start again from the first page."},
            )
        more = max(total - start - len(found), 0)
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
            next_step={
                "tool": "availability_check",
                "why": "Pick a restaurant, then check its slots for a date and party size."
                + (f" To see the other {more}, search again with offset {start + len(found)}." if more else ""),
            },
        )
