"""P1-13: the invariant checker must be quiet on good data and loud on each kind of damage.
If it could not detect corruption, the concurrency tests that rely on it would prove nothing."""

from dataclasses import replace

import pytest
from ddb_env import ENDPOINT
from flows import book, call, hold_table, set_approval
from world import World

from server.domain.booking import Hold, Reservation
from server.domain.clock import iso_z
from server.invariants import check_invariants
from server.store import keys
from server.store.mappers import hold_to_item, reservation_to_item, slot_to_item

pytestmark = pytest.mark.ddb


@pytest.fixture
def world(ddb_client, table_name, clock):
    return World(ddb_client, table_name, ENDPOINT, clock)


def problems(world: World) -> list[str]:
    return [str(v) for v in check_invariants(world.store, iso_z(world.clock.now()))]


def codes(world: World) -> set[str]:
    return {v.code for v in check_invariants(world.store, iso_z(world.clock.now()))}


async def test_a_fresh_table_and_a_normal_history_are_clean(world):
    assert problems(world) == []
    kept = await book(world, "alice", "luna-trattoria", "19:00", tag="1")
    cancelled = await book(world, "alice", "luna-trattoria", "19:30", tag="2")
    await call(world.as_("alice"), "reservation_manage", action="cancel",
               reservation_id=cancelled["reservation_id"], idempotency_key="key-cancel-01")
    await hold_table(world, "bob", "ember-grill", "18:00", key="key-hold-bob1")  # a hold in flight
    assert problems(world) == [], problems(world)
    assert kept["code"]


async def test_an_approved_booking_outside_the_mandate_is_fine_but_an_unapproved_one_is_not(world):
    approved = await book(world, "bob", "luna-trattoria", "19:00", tag="1")  # Bob has no mandate; approval used
    assert problems(world) == []

    # A reservation that skipped consent entirely (written straight into the table) is flagged.
    hold = world.store.get_hold((await hold_table(world, "bob", "luna-trattoria", "19:30", key="key-hold-bob2"))["hold_id"])
    sneaky = Reservation("res-sneaky", "LUN-0000", hold.hold_id, "dev-bob", "alexa-plus-sim", "luna-trattoria",
                         hold.date, hold.time, hold.table_group, 2, "confirmed", hold.terms, iso_z(world.clock.now()))
    world.store.put_item(reservation_to_item(sneaky))
    world.store.put_item(hold_to_item(replace(hold, status="confirmed")))
    assert "I1" in codes(world)
    assert approved["reservation_id"]


async def test_a_double_booked_table_is_flagged(world):
    h = await hold_table(world, "alice", "luna-trattoria", "19:00")
    original = world.store.get_hold(h["hold_id"])
    twin = Hold("hold-twin", "dev-bob", "alexa-plus-sim", original.venue_id, original.date, original.time,
                original.table_group, 2, "held", original.held_until, original.created_at, False, original.terms)
    world.store.put_item(hold_to_item(twin))
    assert "I2" in codes(world)


async def test_a_wrong_counter_is_flagged(world):
    await hold_table(world, "alice", "luna-trattoria", "19:00")
    key = keys.active_holds_counter("dev-alice", "luna-trattoria")
    world.store.put_item({"PK": key.pk, "SK": key.sk, "n": 5})
    assert "COUNTER" in codes(world)
    world.store.put_item({"PK": key.pk, "SK": key.sk, "n": 1})
    assert problems(world) == []


async def test_a_slot_that_disagrees_with_its_owner_is_flagged(world):
    booking = await book(world, "alice", "luna-trattoria", "19:00")
    res = world.store.get_reservation(booking["reservation_id"])
    slot = world.store.get_slot("luna-trattoria", res.date, res.time, res.table_group)
    world.store.put_item(slot_to_item(replace(slot, status="open", reservation_id=None)))
    assert "SLOT" in codes(world)  # open slot with a confirmed reservation on it


async def test_a_fee_without_the_users_approval_is_flagged(world):
    booking = await book(world, "bob", "ember-grill", "18:00", offset=1)
    rid = booking["reservation_id"]
    out = await call(world.as_("bob"), "reservation_manage", action="cancel", reservation_id=rid,
                     idempotency_key="key-cancel-01")
    assert out.structuredContent["error"] == "FEE_APPLIES"
    set_approval(world, rid)
    done = await call(world, "reservation_manage", action="cancel", reservation_id=rid, idempotency_key="key-cancel-01")
    assert not done.isError and problems(world) == []
    world.store.replace_approval(replace(world.store.get_approval(rid), status="pending"))  # tamper: fee was never accepted
    assert "I3" in codes(world)


async def test_a_record_without_a_user_is_flagged(world):
    h = await hold_table(world, "alice", "luna-trattoria", "19:00")
    item = world.store.get_item(keys.hold(h["hold_id"]))
    world.store.put_item({**item, "sub": ""})
    assert "I5" in codes(world)
