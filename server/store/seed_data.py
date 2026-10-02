"""Deterministic demo data: three restaurants and two weeks of slots (some hot, some Fair-Drop).
Pure function of (today, now, user subs): no I/O, so tests can use it too.

Fictional restaurants; the numbers are chosen so each rule is easy to trigger in a demo:
- Luna Trattoria: roomy agent share (cap 24 covers/day) and free cancellation.
- Ember Grill: small agent share (cap 10) and a hot Saturday 19:00 table: shows rule S2.
- Sakura Counter: a Friday 20:00 seat released through a Fair Drop: shows rule S4.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from server.domain.booking import starts_at
from server.domain.clock import iso_z as _iso
from server.domain.models import Slot, Venue

DAYS = 14
TIMES = ("17:30", "18:00", "18:30", "19:00", "19:30", "20:00", "20:30")
FRIDAY, SATURDAY = 4, 5

VENUES: tuple[Venue, ...] = (
    Venue(
        "luna-trattoria", "Luna Trattoria", "Italian", "Riverside",
        "Neighbourhood trattoria with handmade pasta and a wood-fired oven.",
        seats_per_day=60, agent_share_pct=40, cancel_fee_cents=0, free_cancel_hours=0,
    ),
    Venue(
        "ember-grill", "Ember Grill", "Steakhouse", "Old Town",
        "Charcoal grill with a short menu; Saturday evenings fill up quickly.",
        seats_per_day=40, agent_share_pct=25, cancel_fee_cents=2500, free_cancel_hours=48,
    ),
    Venue(
        "sakura-counter", "Sakura Counter", "Japanese omakase", "Harbor",
        "Eight-seat sushi counter. Friday seats are released by lottery.",
        seats_per_day=16, agent_share_pct=50, cancel_fee_cents=5000, free_cancel_hours=72,
    ),
)

# venue -> {table group: seats}
TABLE_GROUPS: dict[str, dict[str, int]] = {
    "luna-trattoria": {"T2": 2, "T4": 4, "T6": 6},
    "ember-grill": {"T2": 2, "T4": 4},
    "sakura-counter": {"T2": 2},
}


@dataclass(frozen=True)
class DropSpec:
    """A Fair Drop to create: the seed (and so the commitment) is drawn when it is stored."""

    drop_id: str
    venue_id: str
    date: str
    slot_keys: tuple[str, ...]
    opens_at: str
    drop_at: str


@dataclass(frozen=True)
class SeedData:
    venues: tuple[Venue, ...]
    slots: tuple[Slot, ...]
    drops: tuple[DropSpec, ...] = ()


def _slots(today: date) -> list[Slot]:
    slots: list[Slot] = []
    for offset in range(DAYS):
        day = today + timedelta(days=offset)
        iso = day.isoformat()
        for venue_id, groups in TABLE_GROUPS.items():
            for time_ in TIMES:
                for group, seats in groups.items():
                    hot = venue_id == "ember-grill" and day.weekday() == SATURDAY and (
                        time_ == "19:00" and group == "T4"
                    )
                    drop = venue_id == "sakura-counter" and day.weekday() == FRIDAY and time_ == "20:00"
                    slots.append(
                        Slot(
                            venue_id, iso, time_, group, seats,
                            hot=hot or drop,
                            drop_id=f"drop-sakura-{iso}" if drop else None,
                        )
                    )
    return slots


def _drops(slots: list[Slot], now: datetime) -> list[DropSpec]:
    """One drop per ``drop_id``: entries open now; the draw is a day before the seats, but never
    sooner than ten minutes from now so a fresh demo always has time to enter."""
    grouped: dict[str, list[Slot]] = {}
    for s in slots:
        if s.drop_id:
            grouped.setdefault(s.drop_id, []).append(s)
    specs = []
    for drop_id, group in sorted(grouped.items()):
        first = min(group, key=lambda s: (s.time, s.table_group))
        drop_at = max(starts_at(first.date, first.time) - timedelta(days=1), now + timedelta(minutes=10))
        specs.append(DropSpec(drop_id, first.venue_id, first.date, tuple(sorted(s.slot_key for s in group)),
                              _iso(now), _iso(drop_at)))
    return specs


def build_seed(today: date, now: datetime, subs: Mapping[str, str]) -> SeedData:
    """``subs`` maps "alice" / "carol" (and "bob") to the ``sub`` claim of their dev tokens."""
    slots = _slots(today)
    return SeedData(VENUES, tuple(slots), tuple(_drops(slots, now)))
