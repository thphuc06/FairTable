"""Small presentation helpers shared by the read tools (words for voice, rule summaries)."""

from datetime import date as _date

from server.domain.models import Venue


def say_time(hhmm: str) -> str:
    """'19:30' -> '7:30 PM' (short and easy to read aloud)."""
    hour, minute = int(hhmm[:2]), hhmm[3:5]
    suffix = "AM" if hour < 12 else "PM"
    return f"{hour % 12 or 12}:{minute} {suffix}"


def say_money(cents: int) -> str:
    return "free" if cents == 0 else f"${cents / 100:.2f}"


def say_times(times: list[str], limit: int = 3) -> str:
    """'5:30 PM, 6:00 PM and 6:30 PM' (each time once, in order); 'and N more times' beyond limit."""
    unique = list(dict.fromkeys(times))
    spoken = [say_time(t) for t in unique[:limit]]
    extra = len(unique) - limit
    if extra > 0:
        return ", ".join(spoken) + f" and {extra} more times"
    if len(spoken) == 1:
        return spoken[0]
    return ", ".join(spoken[:-1]) + " and " + spoken[-1]


def terms(venue: Venue) -> dict[str, int]:
    return {"cancel_fee_cents": venue.cancel_fee_cents, "free_cancel_hours": venue.free_cancel_hours}


def cancel_policy_text(venue: Venue) -> str:
    if venue.cancel_fee_cents == 0:
        return "Cancellation is free."
    return (
        f"Cancel at least {venue.free_cancel_hours} hours ahead for free; "
        f"after that the fee is {say_money(venue.cancel_fee_cents)}."
    )


def say_date(iso: str) -> str:
    """'2026-10-02' -> 'Friday, October 2'."""
    d = _date.fromisoformat(iso)
    return f"{d.strftime('%A')}, {d.strftime('%B')} {d.day}"


def cancel_policy_text_from_terms(terms: dict) -> str:
    fee, hours = terms["cancel_fee_cents"], terms["free_cancel_hours"]
    if fee == 0:
        return "Cancellation is free."
    return f"Cancel at least {hours} hours ahead for free; after that the fee is {say_money(fee)}."
