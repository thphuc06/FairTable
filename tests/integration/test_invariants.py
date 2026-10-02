"""P1-13: the invariant checker must be quiet on good data and loud on each kind of damage.
If it could not detect corruption, the concurrency tests that rely on it would prove nothing."""

from dataclasses import replace

import pytest
from ddb_env import ENDPOINT
from flows import ANSWER_AFTER_S, book, call, hold_table
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


async def test_a_booking_made_after_a_read_back_is_fine_but_one_written_without_it_is_not(world):
    read_back = await book(world, "bob", "luna-trattoria", "19:00", tag="1")
    assert problems(world) == []

    # A reservation that skipped the read-back entirely (written straight into the table) is flagged (I1).
    hold = world.store.get_hold((await hold_table(world, "bob", "luna-trattoria", "19:30", key="key-hold-bob2"))["hold_id"])
    sneaky = Reservation("res-sneaky", "LUN-0000", hold.hold_id, "dev-bob", "alexa-plus-sim", "luna-trattoria",
                         hold.date, hold.time, hold.table_group, 2, "confirmed", hold.terms, iso_z(world.clock.now()))
    world.store.put_item(reservation_to_item(sneaky))
    world.store.put_item(hold_to_item(replace(hold, status="confirmed")))
    assert "I1" in codes(world)
    assert read_back["reservation_id"]


async def test_a_double_booked_table_is_flagged(world):
    h = await hold_table(world, "alice", "luna-trattoria", "19:00")
    original = world.store.get_hold(h["hold_id"])
    twin = Hold("hold-twin", "dev-bob", "alexa-plus-sim", original.venue_id, original.date, original.time,
                original.table_group, 2, "held", original.held_until, original.created_at, original.terms)
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


async def test_a_fee_that_was_not_read_back_is_flagged(world):
    booking = await book(world, "bob", "ember-grill", "18:00", offset=1)
    rid = booking["reservation_id"]
    out = await call(world.as_("bob"), "reservation_manage", action="cancel", reservation_id=rid,
                     idempotency_key="key-cancel-01")
    assert out.structuredContent["error"] == "CONFIRMATION_REQUIRED"
    token = out.structuredContent["details"]["read_back_token"]
    world.clock.advance(ANSWER_AFTER_S)
    done = await call(world, "reservation_manage", action="cancel", reservation_id=rid, idempotency_key="key-cancel-01",
                      read_back_token=token, user_confirmed=True)
    assert not done.isError and problems(world) == []
    item = world.store.get_item(keys.reservation(rid))
    item.pop("cancel_read_back_at")  # tamper: the fee was charged but never read back
    world.store.put_item(item)
    assert "I3" in codes(world)


async def test_a_record_without_a_user_is_flagged(world):
    h = await hold_table(world, "alice", "luna-trattoria", "19:00")
    item = world.store.get_item(keys.hold(h["hold_id"]))
    world.store.put_item({**item, "sub": ""})
    assert "I5" in codes(world)


async def test_two_tickets_for_one_person_in_a_drop_are_flagged(world):
    from server.domain import fairdrop as fd
    from server.store.mappers import entry_to_item

    friday = next(d for d in world.store.scan_all() if d.get("entity") == "drop")["drop_id"]
    sub = "dev-alice"
    real = fd.DropEntry(fd.entry_id(friday, sub), friday, sub, "diner-alice", "verified", "alexa-plus-sim",
                        frozenset({"fairtable/book"}), 2, "2026-10-01T12:00:00Z")
    world.store.put_item(entry_to_item(real, fd.entry_hash(friday, sub)))
    assert problems(world) == []
    twin = replace(real, entry_id=fd.entry_id(friday, sub) + "x", created_at="2026-10-01T12:00:05Z")
    world.store.put_item(entry_to_item(twin, "f" * 64))  # a second ticket, hidden under another key
    assert "I4" in codes(world)


async def test_a_doctored_draw_audit_is_flagged(world):
    from datetime import datetime, timedelta

    from server.domain import fairdrop as fd
    from server.dropper import maybe_allocate

    drop = next(d for d in map(fd_item_to_drop, [i for i in world.store.scan_all() if i.get("entity") == "drop"]))
    sub = "dev-alice"
    ticket = fd.DropEntry(fd.entry_id(drop.drop_id, sub), drop.drop_id, sub, "diner-alice", "verified",
                          "alexa-plus-sim", frozenset({"fairtable/book"}), 2, iso_z(world.clock.now()))
    from server.store.mappers import entry_to_item

    world.store.put_item(entry_to_item(ticket, fd.entry_hash(drop.drop_id, sub)))
    world.clock.set(datetime.fromisoformat(drop.drop_at) + timedelta(seconds=1))
    maybe_allocate(world.deps, drop.drop_id)
    assert problems(world) == []
    done = world.store.get_drop(drop.drop_id)
    forged = {**done.audit, "seed": (b"x" * 32).hex()}  # a seed that does not match the commitment
    world.store.put_drop(replace(done, audit=forged))
    assert "I4" in codes(world)


def fd_item_to_drop(item):
    from server.store.mappers import item_to_drop

    return item_to_drop(item)
