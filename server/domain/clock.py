"""Injectable clock. Everything time-dependent takes a ``Clock`` so tests never sleep."""

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Current time as a timezone-aware UTC datetime."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FakeClock:
    """Manually driven clock for tests and deterministic runs."""

    def __init__(self, start: datetime | None = None) -> None:
        start = start or datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
        if start.tzinfo is None:
            raise ValueError("FakeClock needs a timezone-aware datetime")
        self._now = start.astimezone(UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float = 0, **kwargs: float) -> None:
        self._now += timedelta(seconds=seconds, **kwargs)

    def set(self, moment: datetime) -> None:
        if moment.tzinfo is None:
            raise ValueError("FakeClock needs a timezone-aware datetime")
        self._now = moment.astimezone(UTC)


def iso_z(moment: datetime) -> str:
    """Fixed-width UTC timestamp ('2026-10-01T12:00:00Z'). Fixed width matters: the strings are
    compared as text (expiry checks, sort keys), which only works when every one has the same shape."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def epoch_seconds(clock: Clock) -> int:
    return int(clock.now().timestamp())
