"""P3-19 (D-066): one confirmed table per diner, restaurant and day.

The early refusal is rule S6 at ``reservation_hold``; the guarantee under concurrency is the ``BOOKED#`` marker written in
the confirm transaction and removed in the cancel transaction.
"""

import asyncio

import pytest
from ddb_env import ENDPOINT
from flows import ANSWER_AFTER_S, book, call, confirm_after_read_back, day, error_of, hold_table
from world import World

from server.domain.clock import iso_z
from server.invariants import assert_invariants
from server.store import TxOp, keys

pytestmark = pytest.mark.ddb
LUNA, EMBER = "luna-trattoria", "ember-grill"
S6 = "S6_one_booking_per_restaurant_day"


@pytest.fixture
def world(ddb_client, table_name, clock):
    w = World(ddb_client, table_name, ENDPOINT, clock)
    ids = iter(range(1, 100_000))
    w.deps.new_id = lambda: f"id{next(ids):05d}"
    return w


async def try_hold(world: World, who: str, venue: str, time: str, *, offset: int = 2, key: str):
    world.as_(who)
    r = await call(world, "availability_check", restaurant_id=venue, date=day(world, offset),
                   time_window=f"{time}-{time}", party_size=2)
    return await call(world, "reservation_hold", offer_id=r.structuredContent["slots"][0]["offer_id"], idempotency_key=key)


def marker(world: World, who: str, venue: str, offset: int = 2):
    return world.store.get_item(keys.booked_day(f"dev-{who}", venue, day(world, offset)))


# ---------------------------------------------------------------- the early refusal
async def test_a_second_table_at_the_same_restaurant_the_same_day_is_refused_before_anything_is_held(world):
    first = await book(world, "alice", LUNA, "19:00")
    refused = error_of(await try_hold(world, "alice", LUNA, "19:30", key="key-dup-0002"), "POLICY_DENIED")
    assert refused["rule_id"] == S6 and "already have a table" in refused["message"]
    assert refused["next_step"]["tool"] == "reservation_manage"
    assert world.store.holds_of_user("dev-alice") == [h for h in world.store.holds_of_user("dev-alice") if h.status != "held"]
    assert world.store.get_reservation(first["reservation_id"]).status == "confirmed"
    assert_invariants(world.store, iso_z(world.clock.now()))


async def test_another_day_another_restaurant_or_another_diner_is_fine(world):
    await book(world, "alice", LUNA, "19:00", tag="1")
    assert not (await try_hold(world, "alice", LUNA, "19:00", offset=3, key="key-dup-0003")).isError  # another day
    assert not (await try_hold(world, "alice", EMBER, "18:00", key="key-dup-0004")).isError  # another restaurant
    assert not (await try_hold(world, "bob", LUNA, "19:30", key="key-dup-0005")).isError  # another diner


async def test_two_holds_to_compare_are_still_allowed_until_one_is_confirmed(world):
    """S1 lets a diner hold two tables; S6 only counts confirmed ones, so comparing two times keeps working."""
    first = await hold_table(world, "alice", LUNA, "19:00", key="key-dup-0006")
    second = await hold_table(world, "alice", LUNA, "19:30", key="key-dup-0007")
    assert first["hold_id"] != second["hold_id"]


# ---------------------------------------------------------------- the guarantee at confirm time
async def test_confirming_the_second_of_two_holds_is_refused_and_the_hold_stays_to_expire(world):
    a = await hold_table(world, "alice", LUNA, "19:00", key="key-dup-0008")
    b = await hold_table(world, "alice", LUNA, "19:30", key="key-dup-0009")
    first = await confirm_after_read_back(world, "alice", a, key="key-dup-0010")
    assert not first.isError, first.structuredContent
    world.clock.advance(ANSWER_AFTER_S)
    second = await confirm_after_read_back(world, "alice", b, key="key-dup-0011")
    err = error_of(second, "POLICY_DENIED")
    assert err["rule_id"] == S6
    assert world.store.get_hold(b["hold_id"]).status == "held"  # nothing changed: it runs out by itself
    reservations = [r for r in world.store.reservations_of_user("dev-alice") if r.status == "confirmed"]
    assert [r.reservation_id for r in reservations] == [first.structuredContent["reservation_id"]]
    assert marker(world, "alice", LUNA)["reservation_id"] == first.structuredContent["reservation_id"]
    assert_invariants(world.store, iso_z(world.clock.now()))


async def test_two_confirms_at_the_same_moment_make_exactly_one_booking(world):
    """Both holds were taken legally (S1 allows two); the two confirms race, and only one write can create the marker."""
    a = await hold_table(world, "alice", LUNA, "19:00", key="key-dup-0030")
    b = await hold_table(world, "alice", LUNA, "19:30", key="key-dup-0031")
    world.clock.advance(ANSWER_AFTER_S)
    args = [{"hold_id": h["hold_id"], "idempotency_key": f"key-dup-003{i}", "read_back_token": h["read_back_token"],
             "user_confirmed": True} for i, h in ((2, a), (3, b))]
    world.as_("alice")
    results = await asyncio.gather(*(call(world, "reservation_confirm", **x) for x in args))
    assert sorted(r.isError for r in results) == [False, True]
    assert len([r for r in world.store.reservations_of_user("dev-alice") if r.status == "confirmed"]) == 1
    assert_invariants(world.store, iso_z(world.clock.now()))


# ---------------------------------------------------------------- cancel frees the day
async def test_cancelling_frees_the_day_for_a_new_booking(world):
    first = await book(world, "alice", LUNA, "19:00", offset=5, tag="1")  # far ahead: a free cancel
    assert marker(world, "alice", LUNA, 5) is not None
    cancelled = await call(world.as_("alice"), "reservation_manage", action="cancel",
                           reservation_id=first["reservation_id"], idempotency_key="key-dup-0016")
    assert not cancelled.isError, cancelled.structuredContent
    assert marker(world, "alice", LUNA, 5) is None
    again = await book(world, "alice", LUNA, "19:30", offset=5, tag="2")
    assert again["reservation_id"] != first["reservation_id"] and marker(world, "alice", LUNA, 5) is not None


async def test_a_booking_from_before_the_marker_existed_is_still_seen_and_still_cancels(world):
    """Reservations made before D-066 have no marker: the early check reads the reservations, and a cancel needs no marker."""
    booking = await book(world, "alice", LUNA, "19:00", offset=5, tag="1")
    k = keys.booked_day("dev-alice", LUNA, day(world, 5))
    world.store.transact([TxOp("Delete", key={"PK": k.pk, "SK": k.sk})])
    assert marker(world, "alice", LUNA, 5) is None
    error_of(await try_hold(world, "alice", LUNA, "19:30", offset=5, key="key-dup-0017"), "POLICY_DENIED")
    cancelled = await call(world.as_("alice"), "reservation_manage", action="cancel",
                           reservation_id=booking["reservation_id"], idempotency_key="key-dup-0018")
    assert not cancelled.isError, cancelled.structuredContent


async def test_a_cancelled_booking_does_not_count(world):
    booking = await book(world, "alice", LUNA, "19:00", offset=5, tag="1")
    await call(world.as_("alice"), "reservation_manage", action="cancel",
               reservation_id=booking["reservation_id"], idempotency_key="key-dup-0019")
    assert not (await try_hold(world, "alice", LUNA, "19:30", offset=5, key="key-dup-0020")).isError
