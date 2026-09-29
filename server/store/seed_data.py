"""Deterministic demo data: three restaurants, two weeks of slots (some hot, some Fair-Drop), and a
few standing mandates. Pure function of (today, now, user subs): no I/O, so tests can use it too.

Fictional restaurants; the numbers are chosen so each rule is easy to trigger in a demo:
- Luna Trattoria: roomy agent share (cap 24 covers/day), free cancellation, so Alice's mandate
  (max fee 0) covers ordinary bookings there.
- Ember Grill: small agent share (cap 10) and a hot Saturday 19:00 table: shows rule S2.
- Sakura Counter: a Friday 20:00 seat released through a Fair Drop: shows rule S4.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from server.domain.clock import iso_z as _iso
from server.domain.models import MANDATE_ACTIVE, Mandate, Slot, Venue

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
class SeedData:
    venues: tuple[Venue, ...]
    slots: tuple[Slot, ...]
    mandates: tuple[Mandate, ...]


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


def _mandates(subs: Mapping[str, str], now: datetime) -> list[Mandate]:
    approved = _iso(now)
    expires = _iso(now + timedelta(days=90))
    return [
        # Alice trusts Luna for small groups in the evening: in-scope bookings confirm at once.
        Mandate(
            subs["alice"], "luna-trattoria", MANDATE_ACTIVE, 1,
            party_size_max=4, days_ahead_max=30, window_start="17:00", window_end="22:00",
            max_cancel_fee_cents=0, allow_auto_confirm=True,
            actions=frozenset({"hold", "confirm", "watch", "drop_entry"}),
            agent_ids=frozenset({"alexa-plus-sim"}), approved_at=approved, expires_at=expires,
        ),
        # Carol never allows auto-confirm: every confirm at Ember needs step-up.
        Mandate(
            subs["carol"], "ember-grill", MANDATE_ACTIVE, 1,
            party_size_max=2, days_ahead_max=14, window_start="18:00", window_end="21:00",
            max_cancel_fee_cents=0, allow_auto_confirm=False,
            actions=frozenset({"hold", "watch"}),
            agent_ids=frozenset({"alexa-plus-sim"}), approved_at=approved, expires_at=expires,
        ),
    ]


def build_seed(today: date, now: datetime, subs: Mapping[str, str]) -> SeedData:
    """``subs`` maps "alice" / "carol" (and "bob") to the ``sub`` claim of their dev tokens."""
    return SeedData(VENUES, tuple(_slots(today)), tuple(_mandates(subs, now)))
