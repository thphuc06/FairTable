"""The standing permission a diner can grant while approving a booking (docs/DECISIONS.md D-033).

The diner sees one sentence and one line of limits on the approval page. Both are produced here from the
same numbers that become the stored mandate, so what is shown and what is granted cannot drift apart:
the grant is never wider than the text. Pure functions; the web page and the store call them.

What the diner chooses: the restaurant (the one being booked) and a number of days. What is fixed and
always shown: at most ``GRANT_PARTY_MAX`` people each time, any time of day, no cancellation fee above the
restaurant's current fee (shown), only for the assistant that asked, revocable at any time.
"""

from datetime import datetime, timedelta

from server.domain.clock import iso_z
from server.domain.mandate import is_active
from server.domain.models import MANDATE_ACTIVE, Mandate, Venue

GRANT_DAYS = (7, 30, 90)
DEFAULT_GRANT_DAYS = 30
GRANT_PARTY_MAX = 4
WHOLE_DAY = ("00:00", "23:59")
GRANT_ACTIONS = frozenset({"hold", "confirm", "watch", "drop_entry"})


def money(cents: int) -> str:
    return f"${cents / 100:.2f}"


def can_offer(existing: Mandate | None, now: datetime) -> bool:
    """A grant is offered only when there is no live permission at this restaurant: it never narrows or
    replaces one the diner already has."""
    return not is_active(existing, now)


def build_mandate(*, sub: str, venue: Venue, agent_id: str, days: int, now: datetime) -> Mandate:
    if days not in GRANT_DAYS:
        raise ValueError(f"days must be one of {GRANT_DAYS}")
    if not agent_id:
        raise ValueError("a grant is for one named assistant")
    return Mandate(
        sub=sub, venue_id=venue.venue_id, status=MANDATE_ACTIVE, version=1,
        party_size_max=GRANT_PARTY_MAX, days_ahead_max=days,
        window_start=WHOLE_DAY[0], window_end=WHOLE_DAY[1],
        max_cancel_fee_cents=venue.cancel_fee_cents, allow_auto_confirm=True,
        actions=GRANT_ACTIONS, agent_ids=frozenset({agent_id}),
        approved_at=iso_z(now), expires_at=iso_z(now + timedelta(days=days)),
    )


def offer_parts(venue: Venue, agent_id: str) -> tuple[str, str, str]:
    """(text before the number of days, text after it, the fixed limits line). The page puts a choice of
    ``GRANT_DAYS`` between the first two, so the diner reads one sentence and picks the days inside it."""
    fee = (
        "no cancellation fee" if venue.cancel_fee_cents == 0
        else f"a cancellation fee of up to {money(venue.cancel_fee_cents)} may apply"
    )
    limits = (
        f"Each booking: up to {GRANT_PARTY_MAX} people, any time, {fee}. Only for the assistant '{agent_id}'. "
        "You can take this back at any time under Permissions."
    )
    return f"Let my assistant book at {venue.name} without asking me again, for the next", "days.", limits


def describe_mandate(m: Mandate, venue_name: str) -> str:
    """The limits of a stored mandate in one plain line (the Permissions page)."""
    whole_day = (m.window_start, m.window_end) == WHOLE_DAY
    when = "any time" if whole_day else f"between {m.window_start} and {m.window_end}"
    fee = "no cancellation fee" if m.max_cancel_fee_cents == 0 else f"a cancellation fee of up to {money(m.max_cancel_fee_cents)}"
    who = f" · only for '{', '.join(sorted(m.agent_ids))}'" if m.agent_ids else ""
    return (f"{venue_name}: up to {m.party_size_max} people, {when}, within {m.days_ahead_max} days, {fee}{who} "
            f"· until {m.expires_at[:10]}")
