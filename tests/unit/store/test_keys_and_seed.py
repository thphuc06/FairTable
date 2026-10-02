"""P1-6: key builders, mappers and the deterministic seed data (no database needed)."""

from datetime import UTC, date, datetime

import pytest

from server.domain.models import Slot
from server.store import keys
from server.store.mappers import (
    item_to_slot,
    item_to_venue,
    slot_to_item,
    venue_to_item,
)
from server.store.seed_data import DAYS, TABLE_GROUPS, TIMES, VENUES, build_seed

SUBS = {"alice": "dev-alice", "bob": "dev-bob", "carol": "dev-carol"}
TODAY = date(2026, 10, 1)  # a Thursday
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------- keys
def test_key_shapes_follow_the_design():
    assert keys.venue("luna") == ("REST#luna", "PROFILE")
    assert keys.slot("luna", "2026-10-30", "19:00", "T4") == ("REST#luna#D#2026-10-30", "SLOT#1900#T4")
    assert keys.active_holds_counter("u1", "luna") == ("CNT#USER#u1#REST#luna", "ACTIVE_HOLDS")
    assert keys.agent_covers_counter("luna", "2026-10-30") == ("CNT#REST#luna#D#2026-10-30", "AGENT_COVERS")
    assert keys.idempotency("u1", "abc") == ("IDEM#u1#abc", "META")
    assert keys.hold("h1") == ("HOLD#h1", "META")


@pytest.mark.parametrize("bad", ["", "a#b", "line\nbreak", "x" * 129, None, 5])
def test_ids_that_could_collide_or_inject_are_rejected(bad):
    with pytest.raises(ValueError):
        keys.venue(bad)
    with pytest.raises(ValueError):
        keys.idempotency("u1", bad)


def test_two_different_users_can_never_share_an_idempotency_key():
    # "u#1" + "k" and "u" + "1#k" would both render IDEM#u#1#k without validation.
    with pytest.raises(ValueError):
        keys.idempotency("u#1", "k")
    assert keys.idempotency("u", "1k") != keys.idempotency("u1", "k")


# ---------------------------------------------------------------- mappers
def test_venue_and_slot_round_trip():
    seed = build_seed(TODAY, NOW, SUBS)
    for venue in seed.venues:
        assert item_to_venue(venue_to_item(venue)) == venue
    for slot in seed.slots[:50] + tuple(s for s in seed.slots if s.drop_id)[:2]:
        assert item_to_slot(slot_to_item(slot)) == slot


def test_venue_directory_sorts_by_name():
    assert venue_to_item(VENUES[1])["GSI1PK"] == keys.VENUE_DIRECTORY
    assert venue_to_item(VENUES[1])["GSI1SK"].startswith("Ember Grill#")


def test_slot_key_and_drop_flag():
    slot = Slot("luna", "2026-10-30", "19:00", "T4", 4, drop_id="d1")
    assert slot.slot_key == "1900#T4" and slot.drop_controlled
    assert not Slot("luna", "2026-10-30", "19:00", "T4", 4).drop_controlled


def test_agent_cover_cap_is_share_of_daily_seats():
    caps = {v.venue_id: v.agent_cover_cap for v in VENUES}
    assert caps == {"luna-trattoria": 24, "ember-grill": 10, "sakura-counter": 8}


# ---------------------------------------------------------------- seed data
def test_seed_is_deterministic():
    assert build_seed(TODAY, NOW, SUBS) == build_seed(TODAY, NOW, SUBS)


def test_seed_shape():
    seed = build_seed(TODAY, NOW, SUBS)
    per_day = len(TIMES) * sum(len(g) for g in TABLE_GROUPS.values())
    assert len(seed.slots) == DAYS * per_day
    assert {s.venue_id for s in seed.slots} == set(TABLE_GROUPS)
    assert len({(s.venue_id, s.date, s.time, s.table_group) for s in seed.slots}) == len(seed.slots)
    assert all(s.status == "open" and s.ver == 1 for s in seed.slots)


def test_hot_and_drop_slots_are_where_the_demo_expects_them():
    seed = build_seed(TODAY, NOW, SUBS)
    hot_ember = [s for s in seed.slots if s.venue_id == "ember-grill" and s.hot]
    assert hot_ember and all(
        date.fromisoformat(s.date).weekday() == 5 and (s.time, s.table_group) == ("19:00", "T4")
        for s in hot_ember
    )
    drops = [s for s in seed.slots if s.drop_id]
    assert drops and all(
        s.venue_id == "sakura-counter" and date.fromisoformat(s.date).weekday() == 4
        and s.time == "20:00" and s.hot and s.drop_id == f"drop-sakura-{s.date}"
        for s in drops
    )
    assert not [s for s in seed.slots if s.venue_id == "luna-trattoria" and (s.hot or s.drop_id)]
