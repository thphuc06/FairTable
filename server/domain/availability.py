"""Input validation and slot selection for the read tools (pure)."""

from datetime import date, datetime

from server.domain.clock import iso_z
from server.domain.errors import ErrorCode, FairTableError
from server.domain.models import SLOT_OPEN, Slot

MAX_PARTY = 50  # sanity bound; larger than 10 is refused by rule G3 before it matters
MAX_DAYS_AHEAD = 90
MAX_SLOTS_RETURNED = 12


def invalid(message: str) -> FairTableError:
    return FairTableError(ErrorCode.INVALID_INPUT, message)


def parse_date(value: str, *, today: date) -> date:
    try:
        day = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise invalid("date must be an ISO date such as 2026-10-30.") from None
    if day < today:
        raise invalid("date is in the past.")
    if (day - today).days > MAX_DAYS_AHEAD:
        raise invalid(f"date is more than {MAX_DAYS_AHEAD} days ahead.")
    return day


def parse_time(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%H:%M")  # noqa: DTZ007 (a wall-clock time, no date)
    except (TypeError, ValueError):
        raise invalid("times must look like 19:00.") from None
    return parsed.strftime("%H:%M")


def parse_window(value: str) -> tuple[str, str]:
    start, sep, end = str(value).partition("-")
    if not sep:
        raise invalid("time_window must look like 17:00-22:00.")
    start, end = parse_time(start.strip()), parse_time(end.strip())
    if start > end:
        raise invalid("time_window must start before it ends.")
    return start, end


def check_party_size(value: object, *, required: bool) -> int:
    if value is None and not required:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_PARTY:
        raise invalid(f"party_size must be a whole number from 1 to {MAX_PARTY}.")
    return value


def offered_slots(
    slots: list[Slot], *, party_size: int, window: tuple[str, str], now: datetime
) -> list[Slot]:
    """Open slots that seat the party inside the window, tightest fitting table first, at most 12."""
    now_iso = iso_z(now)
    today, clock_time = now.date().isoformat(), now.strftime("%H:%M")
    fitting = [
        s
        for s in slots
        if s.effective_status(now_iso) == SLOT_OPEN
        and s.seats >= party_size
        and window[0] <= s.time <= window[1]
        and (s.date > today or s.time >= clock_time)
    ]
    fitting.sort(key=lambda s: (s.time, s.seats, s.table_group))
    return fitting[:MAX_SLOTS_RETURNED]
