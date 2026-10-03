"""P3-16: the branches that only run when something goes wrong: lost races, repeated deliveries, a broken store.

The coverage report of the whole suite (2026-10-03) showed these lines never ran. Each test makes the failure happen
on purpose (a stale read, a store that refuses once, a clock that jumped) and checks that the system ends in a safe state.
"""

from datetime import timedelta

import pytest
from ddb_env import ENDPOINT
from flows import call, day, error_of, hold_table
from world import World

from server import dropper, lifecycle
from server.domain import fairdrop as fd
from server.domain.clock import iso_z
from server.domain.errors import ErrorCode, FairTableError
from server.domain.offers import SlotClaims
from server.invariants import assert_invariants
from server.offers import OfferBook
from server.ops.common import parse_slot_key
from server.ratelimit import RateLimiter
from server.store import ConditionFailed, TransactionCancelled
from server.store import CancelReason

pytestmark = pytest.mark.ddb
LUNA = "luna-trattoria"


@pytest.fixture
def world(ddb_client, table_name, clock):
    w = World(ddb_client, table_name, ENDPOINT, clock)
    ids = iter(range(1, 100_000))
    w.deps.new_id = lambda: f"id{next(ids):05d}"
    return w


async def availability(world: World, who: str, time: str = "19:00", party: int = 2):
    world.as_(who)
    r = await call(world, "availability_check", restaurant_id=LUNA, date=day(world), time_window=f"{time}-{time}",
                   party_size=party)
    return r.structuredContent["slots"][0]["offer_id"]


def blind_once(store, name: str) -> None:
    """The next call of ``store.<name>`` sees nothing (a read that was stale), later calls are normal."""
    real, seen = getattr(store, name), []

    def stale(*args, **kwargs):
        if not seen:
            seen.append(1)
            return None
        return real(*args, **kwargs)

    setattr(store, name, stale)


# ---------------------------------------------------------------- the same request delivered twice at once
async def test_a_duplicate_delivery_that_beats_the_lookup_gets_the_stored_answer(world):
    offer = await availability(world, "alice", "19:00")
    claims = world.deps.offers.verify(offer, sub="dev-alice")
    time_, group = parse_slot_key(claims.slot_key)
    slot_before = world.store.get_slot(LUNA, claims.date, time_, group)  # what a second delivery would have read
    world.as_("alice")
    first = await call(world, "reservation_hold", offer_id=offer, idempotency_key="dup-key-0001")
    assert not first.isError, first.structuredContent
    blind_once(world.store, "get_idempotency")  # the lookup misses the record that is already there
    real, seen = world.store.get_slot, []

    def stale_slot(*args, **kwargs):  # and so does the read of the slot, which is still open in that copy
        if not seen:
            seen.append(1)
            return slot_before
        return real(*args, **kwargs)

    world.store.get_slot = stale_slot
    again = await call(world, "reservation_hold", offer_id=offer, idempotency_key="dup-key-0001")
    # the write found the stored record, saw the same parameters and answered with the stored result
    assert not again.isError and again.structuredContent["hold_id"] == first.structuredContent["hold_id"]
    assert len(world.store.holds_of_user("dev-alice")) == 1
    assert_invariants(world.store, iso_z(world.clock.now()))


async def test_a_repeat_whose_slot_is_taken_by_its_own_first_delivery_gets_the_stored_answer(world):
    offer = await availability(world, "alice", "19:00")
    world.as_("alice")
    first = await call(world, "reservation_hold", offer_id=offer, idempotency_key="dup-key-0005")
    blind_once(world.store, "get_idempotency")  # the lookup misses; the slot is now held by the first delivery
    again = await call(world, "reservation_hold", offer_id=offer, idempotency_key="dup-key-0005")
    assert not again.isError and again.structuredContent["hold_id"] == first.structuredContent["hold_id"]


async def test_a_duplicate_delivery_with_other_parameters_is_a_conflict(world):
    await hold_table(world, "alice", LUNA, "19:00", key="dup-key-0002")
    other = await availability(world, "alice", "19:30")
    blind_once(world.store, "get_idempotency")
    world.as_("alice")
    r = await call(world, "reservation_hold", offer_id=other, idempotency_key="dup-key-0002")
    error_of(r, "IDEMPOTENCY_CONFLICT")
    assert len(world.store.holds_of_user("dev-alice")) == 1


async def test_a_record_that_vanishes_between_the_write_and_the_lookup_asks_to_try_again(world):
    await hold_table(world, "alice", LUNA, "19:00", key="dup-key-0003")
    offer = await availability(world, "alice", "19:00")
    real = world.store.get_idempotency
    world.store.get_idempotency = lambda *_a, **_k: None  # never found: the write fails and the winner cannot be read
    world.as_("alice")
    try:
        r = await call(world, "reservation_hold", offer_id=offer, idempotency_key="dup-key-0003")
    finally:
        world.store.get_idempotency = real
    error_of(r, "SLOT_TAKEN")
    assert len(world.store.holds_of_user("dev-alice")) == 1


# ---------------------------------------------------------------- a broken audit write never breaks a refusal
async def test_a_failing_audit_write_does_not_turn_a_refusal_into_a_crash(world):
    world.as_("alice")
    r = await call(world, "availability_check", restaurant_id=LUNA, date=day(world), time_window="19:00-19:00",
                   party_size=2)
    offer = r.structuredContent["slots"][0]["offer_id"]
    real = world.store.put_audit

    def boom(_entry):
        raise RuntimeError("the audit store is down")

    world.store.put_audit = boom
    try:
        await call(world, "reservation_hold", offer_id=offer, idempotency_key="aud-key-0001")
        await call(world, "reservation_hold", offer_id=offer, idempotency_key="aud-key-0002")
        third = await call(world, "reservation_hold", offer_id=offer, idempotency_key="aud-key-0003")
    finally:
        world.store.put_audit = real
    assert third.isError  # the slot is taken: a refusal, not an unhandled error
    assert third.structuredContent["error"] in ("SLOT_TAKEN", "POLICY_DENIED")


# ---------------------------------------------------------------- the rate limiter under contention
def test_the_rate_limiter_gives_up_politely_when_the_bucket_keeps_changing(world):
    limiter = RateLimiter(world.store, world.clock, per_hour=20)

    def lose(*_a, **_k):
        raise ConditionFailed("someone else was faster")

    world.store.put_item = lose
    with pytest.raises(FairTableError) as e:
        limiter.check("dev-alice", LUNA)
    assert e.value.code is ErrorCode.RATE_LIMITED


# ---------------------------------------------------------------- offer ids that collide
def test_an_offer_id_that_already_exists_is_replaced_by_a_new_one(world):
    claims = SlotClaims(LUNA, day(world), "1900#T2", 2, 1, "dev-alice")
    codes = iter(["aaaaaaaa", "aaaaaaaa", "bbbbbbbb"])
    book = OfferBook(world.store, world.clock, make_code=lambda: next(codes))
    assert book.issue(claims) == "aaaaaaaa"
    assert book.issue(claims) == "bbbbbbbb"  # the first try collided with the stored one, the second is fresh


def test_two_collisions_in_a_row_are_an_error_not_a_loop(world):
    claims = SlotClaims(LUNA, day(world), "1900#T2", 2, 1, "dev-alice")
    book = OfferBook(world.store, world.clock, make_code=lambda: "cccccccc")
    book.issue(claims)
    with pytest.raises(TransactionCancelled):
        book.issue(claims)


# ---------------------------------------------------------------- lazy release when someone else was first
async def test_release_is_quiet_when_the_hold_was_already_taken_care_of(world):
    held = await hold_table(world, "alice", LUNA, "19:00", key="rel-key-0001")
    world.clock.advance(minutes=11)
    hold = world.store.get_hold(held["hold_id"])
    now_iso = iso_z(world.clock.now())
    assert lifecycle.release_expired(world.store, hold, now_iso) is True
    assert lifecycle.release_expired(world.store, hold, now_iso) is False  # the stale copy: already expired
    assert lifecycle.release_expired(world.store, world.store.get_hold(held["hold_id"]), now_iso) is False


async def test_a_hold_that_has_not_run_out_is_not_released(world):
    held = await hold_table(world, "alice", LUNA, "19:00", key="rel-key-0002")
    hold = world.store.get_hold(held["hold_id"])
    assert lifecycle.release_expired(world.store, hold, iso_z(world.clock.now())) is False
    assert world.store.get_hold(held["hold_id"]).status == "held"


async def test_a_lost_race_on_the_slot_is_harmless(world):
    held = await hold_table(world, "alice", LUNA, "19:00", key="rel-key-0003")
    hold = world.store.get_hold(held["hold_id"])
    lifecycle.restore_slot(world.store, hold)  # the slot belongs to this hold: it opens
    lifecycle.restore_slot(world.store, hold)  # again: the condition fails and nothing happens
    assert world.store.get_slot(LUNA, hold.date, hold.time, hold.table_group).status == "open"


async def test_a_release_whose_counters_disagree_never_blocks_the_caller(world):
    held = await hold_table(world, "alice", LUNA, "19:00", key="rel-key-0004")
    hold = world.store.get_hold(held["hold_id"])
    world.clock.advance(minutes=11)
    real = world.store.transact

    def cancelled(_ops):
        raise TransactionCancelled([CancelReason("ConditionalCheckFailed", "x")])

    world.store.transact = cancelled
    try:
        assert lifecycle.release_expired(world.store, hold, iso_z(world.clock.now())) is False
    finally:
        world.store.transact = real


# ---------------------------------------------------------------- a Fair Drop draw that crashes is finished later
async def test_a_draw_that_raises_is_resumed_by_the_next_caller(world, monkeypatch):
    drop = next(iter(sorted(d for d in _drop_ids(world))))
    entry_day = world.store.get_drop(drop)
    await _enter(world, "alice", drop)
    world.clock.set(_after(entry_day.drop_at))
    world._tokens.clear()

    def boom(*_a, **_k):
        raise RuntimeError("the draw crashed half way")

    real = dropper._allocate
    monkeypatch.setattr(dropper, "_allocate", boom)
    with pytest.raises(RuntimeError):
        dropper.maybe_allocate(world.deps, drop)
    assert world.store.get_drop(drop).status == fd.DROP_ALLOCATING  # claimed, not finished
    monkeypatch.setattr(dropper, "_allocate", real)
    assert dropper.maybe_allocate(world.deps, drop).status == fd.DROP_ALLOCATING  # too soon: still claimed by the first
    world.clock.advance(seconds=dropper.STALE_CLAIM_S + 1)
    assert dropper.maybe_allocate(world.deps, drop).status == fd.DROP_ALLOCATED


async def test_deciding_an_entry_twice_changes_nothing(world):
    drop = next(iter(sorted(_drop_ids(world))))
    await _enter(world, "alice", drop)
    dropper._persist(world.store, drop, "dev-alice", "lost", None)
    dropper._persist(world.store, drop, "dev-alice", "won", None)  # an interrupted run repeats: the first decision stays
    assert world.store.get_entry(drop, fd.entry_hash(drop, "dev-alice")).status == "lost"


def _drop_ids(world: World) -> list[str]:
    ids = set()
    for venue in world.store.list_venues():
        for offset in range(15):
            d = (world.clock.now().date() + timedelta(days=offset)).isoformat()
            ids.update(s.drop_id for s in world.store.get_slots(venue.venue_id, d) if s.drop_id)
    return list(ids)


async def _enter(world: World, who: str, drop: str):
    world.as_(who)
    r = await call(world, "waitlist_watch", drop_id=drop, party_size=2, idempotency_key=f"enter-{who}-0001")
    assert not r.isError, r.structuredContent
    return r.structuredContent


def _after(moment: str):
    from datetime import datetime

    return datetime.fromisoformat(moment) + timedelta(seconds=1)
