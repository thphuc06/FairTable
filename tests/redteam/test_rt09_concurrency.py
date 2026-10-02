"""P1-13: concurrency hardening (RT6, RT9) with the invariant checker.

Real threads hit the same DynamoDB Local table through the real operations. Whatever the timing,
the DB conditions must leave: one winner per slot, counters never above their caps, no orphan
records, and every invariant intact.
"""

import random
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest
from ddb_env import ENDPOINT
from world import World

from server.domain.booking import Hold
from server.domain.clock import iso_z
from server.domain.errors import FairTableError
from server.domain.clock import FakeClock
from server.domain.models import Identity
from server.domain.readback import KIND_CONFIRM, ReadBackCodec
from server.domain.offers import SlotClaims
from server.invariants import assert_invariants
from server.ops.confirm import ConfirmOperation
from server.ops.hold import HoldOperation
from server.ops.manage import CancelOperation
from server.pipeline import run_write
from server.store import keys

pytestmark = pytest.mark.ddb


@pytest.fixture
def world(ddb_client, table_name, clock):
    return World(ddb_client, table_name, ENDPOINT, clock)


def racer(i: int) -> Identity:
    return Identity(sub=f"racer-{i:02d}", username=f"racer{i}", agent_tier="verified",
                    agent_id="alexa-plus-sim", scopes=frozenset({"fairtable/book"}))


def confirm_op(world: World, who: Identity, hold: Hold) -> ConfirmOperation:
    """A confirm the way a good assistant sends it: the read-back token handed over ten seconds ago, and a yes.
    (The token is minted with a clock ten seconds behind, so the 3 s pause has passed whatever the test's clock is.)"""
    codec = ReadBackCodec(world.deps.settings.slot_token_secret.encode(), FakeClock(world.clock.now() - timedelta(seconds=10)))
    token = codec.issue(kind=KIND_CONFIRM, subject_id=hold.hold_id, sub=who.sub, terms=hold.terms)
    return ConfirmOperation(world.deps, hold, token, True)


def date_of(world: World, offset: int = 2) -> str:
    return (world.clock.now().date() + timedelta(days=offset)).isoformat()


def hold_op(world: World, who: Identity, venue: str, time: str, *, group: str = "T2", party: int = 2) -> HoldOperation:
    claims = SlotClaims(venue, date_of(world), f"{time.replace(':', '')}#{group}", party, 1, who.sub)
    return HoldOperation(world.deps, claims)


def attempt(fn) -> str:
    """Run one operation and name its outcome: 'ok' or the error code."""
    try:
        fn()
        return "ok"
    except FairTableError as e:
        return e.code.value


def race(jobs: list, workers: int | None = None) -> list[str]:
    """Start all jobs at the same moment and return their outcomes in order."""
    barrier = threading.Barrier(len(jobs))

    def run(job):
        barrier.wait()
        return attempt(job)

    with ThreadPoolExecutor(max_workers=workers or len(jobs)) as pool:
        return list(pool.map(run, jobs))


def counts(outcomes: list[str]) -> dict[str, int]:
    return {o: outcomes.count(o) for o in sorted(set(outcomes))}


def counter(world: World, key) -> int:
    item = world.store.get_item(key)
    return int(item["n"]) if item else 0


def now_iso(world: World) -> str:
    return iso_z(world.clock.now())


# ---------------------------------------------------------------- RT9
def test_rt09_twenty_simultaneous_holds_on_one_slot_give_exactly_one_winner(world):
    users = [racer(i) for i in range(20)]
    jobs = [
        (lambda u=u, i=i: run_write(world.deps, u, hold_op(world, u, "luna-trattoria", "19:00"), f"rt9-key-{i:04d}"))
        for i, u in enumerate(users)
    ]
    outcomes = race(jobs)
    assert counts(outcomes) == {"SLOT_TAKEN": 19, "ok": 1}
    slot = world.store.get_slot("luna-trattoria", date_of(world), "19:00", "T2")
    assert (slot.status, slot.ver) == ("held", 2)
    assert counter(world, keys.agent_covers_counter("luna-trattoria", date_of(world))) == 2
    assert sum(counter(world, keys.active_holds_counter(u.sub, "luna-trattoria")) for u in users) == 1
    assert_invariants(world.store, now_iso(world))


# ---------------------------------------------------------------- RT6 under load
def test_rt06_one_user_racing_across_many_slots_never_gets_more_than_two_holds(world):
    me = racer(1)
    times = ["17:30", "18:00", "18:30", "19:00", "19:30", "20:00", "20:30"]
    slots = [(t, g) for t in times for g in ("T2", "T4", "T6")][:20]
    jobs = [
        (lambda t=t, g=g, i=i: run_write(world.deps, me, hold_op(world, me, "luna-trattoria", t, group=g),
                                         f"rt6-key-{i:04d}"))
        for i, (t, g) in enumerate(slots)
    ]
    outcomes = race(jobs)
    assert counts(outcomes) == {"POLICY_DENIED": 18, "ok": 2}
    assert counter(world, keys.active_holds_counter(me.sub, "luna-trattoria")) == 2
    assert_invariants(world.store, now_iso(world))


# ---------------------------------------------------------------- RT7 under load
def test_rt07_the_agent_share_cap_holds_under_concurrent_holds(world):
    """Ember Grill: 25% of 40 seats = 10 covers a day for agents; parties of 2 -> exactly 5 holds."""
    users = [racer(i) for i in range(12)]
    slots = [(t, g) for g in ("T2", "T4") for t in ("17:30", "18:00", "18:30", "19:00", "19:30", "20:00", "20:30")]
    jobs = [
        (lambda u=u, t=t, g=g, i=i: run_write(world.deps, u, hold_op(world, u, "ember-grill", t, group=g),
                                              f"rt7-key-{i:04d}"))
        for i, (u, (t, g)) in enumerate(zip(users, slots, strict=False))
    ]
    outcomes = race(jobs)
    assert counts(outcomes) == {"POLICY_DENIED": 7, "ok": 5}
    assert counter(world, keys.agent_covers_counter("ember-grill", date_of(world))) == 10
    assert_invariants(world.store, now_iso(world))


# ---------------------------------------------------------------- confirm and cancel races
def make_hold(world: World, who: Identity, time: str = "19:00", key: str = "setup-hold-01") -> Hold:
    result = run_write(world.deps, who, hold_op(world, who, "luna-trattoria", time), key)
    return world.store.get_hold(result["hold_id"])


def test_twenty_deliveries_of_the_same_confirm_make_one_booking(world):
    alice = racer(1)
    hold = make_hold(world, alice)
    jobs = [lambda: run_write(world.deps, alice, confirm_op(world, alice, hold), "confirm-key-0001")
            for _ in range(20)]
    results: list = []

    def collect(job):
        results.append(job())
    outcomes = race([lambda j=j: collect(j) for j in jobs])
    assert counts(outcomes) == {"ok": 20}
    assert len({r["reservation_id"] for r in results}) == 1
    assert sum("idempotent_replay" not in r for r in results) == 1
    assert len(world.store.reservations_of_user(alice.sub)) == 1
    assert_invariants(world.store, now_iso(world))


def test_ten_different_keys_confirming_one_hold_make_one_booking(world):
    alice = racer(1)
    hold = make_hold(world, alice)
    jobs = [lambda i=i: run_write(world.deps, alice, confirm_op(world, alice, hold), f"confirm-key-{i:04d}")
            for i in range(10)]
    outcomes = race(jobs)
    assert outcomes.count("ok") == 1
    assert set(outcomes) <= {"ok", "INVALID_INPUT", "HOLD_EXPIRED"}
    assert len(world.store.reservations_of_user(alice.sub)) == 1
    assert counter(world, keys.active_holds_counter(alice.sub, "luna-trattoria")) == 0
    assert_invariants(world.store, now_iso(world))


def test_ten_cancels_of_one_booking_free_the_table_exactly_once(world):
    alice = racer(1)
    hold = make_hold(world, alice)
    booked = run_write(world.deps, alice, confirm_op(world, alice, hold), "confirm-key-0001")
    reservation = world.store.get_reservation(booked["reservation_id"])
    jobs = [lambda i=i: run_write(world.deps, alice, CancelOperation(world.deps, reservation), f"cancel-key-{i:04d}")
            for i in range(10)]
    outcomes = race(jobs)
    assert outcomes.count("ok") == 1 and set(outcomes) <= {"ok", "INVALID_INPUT"}
    assert counter(world, keys.agent_covers_counter("luna-trattoria", date_of(world))) == 0  # not negative
    assert world.store.get_slot("luna-trattoria", date_of(world), "19:00", "T2").status == "open"
    assert_invariants(world.store, now_iso(world))


# ---------------------------------------------------------------- expiry boundary
def test_a_confirm_one_second_before_expiry_works_and_at_the_exact_moment_it_does_not(world):
    alice, bob = racer(1), racer(2)
    early = make_hold(world, alice, time="19:00", key="setup-hold-01")
    world.clock.set(datetime.fromisoformat(early.held_until) - timedelta(seconds=1))
    assert attempt(lambda: run_write(world.deps, alice, confirm_op(world, alice, early), "confirm-key-early")) == "ok"

    late = make_hold(world, alice, time="19:30", key="setup-hold-02")
    world.clock.set(datetime.fromisoformat(late.held_until))  # exactly held_until: the hold is over
    assert attempt(lambda: run_write(world.deps, alice, confirm_op(world, alice, late), "confirm-key-late")) == "HOLD_EXPIRED"
    # the table is free again for somebody else, with no worker involved
    assert attempt(lambda: run_write(world.deps, bob, hold_op(world, bob, "luna-trattoria", "19:30"), "bob-hold-key-01")) == "ok"
    assert_invariants(world.store, now_iso(world))


# ---------------------------------------------------------------- a storm of mixed operations
@dataclass
class Trader:
    who: Identity
    holds: list
    bookings: list


def test_a_storm_of_mixed_operations_leaves_every_invariant_intact(world):
    rng_seed = 20261001
    traders = [Trader(racer(i), [], []) for i in range(10)]
    venues = ["luna-trattoria", "ember-grill"]
    times = ["17:30", "18:00", "18:30", "19:00"]
    outcomes: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(len(traders))

    def work(index: int) -> None:
        rng = random.Random(rng_seed + index)
        t = traders[index]
        barrier.wait()
        for step in range(12):
            action = rng.choice(["hold", "hold", "confirm", "cancel"])
            key = f"storm-{index:02d}-{step:03d}"
            if action == "hold":
                venue, time, group = rng.choice(venues), rng.choice(times), rng.choice(["T2", "T4"])
                op = hold_op(world, t.who, venue, time, group=group, party=rng.choice([2, 2, 3, 4]))
                result = _try(lambda op=op, key=key: run_write(world.deps, t.who, op, key))
                if isinstance(result, dict):
                    t.holds.append(result["hold_id"])
            elif action == "confirm" and t.holds:
                hold_id = t.holds.pop(rng.randrange(len(t.holds)))
                hold = world.store.get_hold(hold_id)
                result = _try(lambda hold=hold, key=key: run_write(world.deps, t.who, confirm_op(world, t.who, hold), key))
                if isinstance(result, dict):
                    t.bookings.append(result["reservation_id"])
            elif action == "cancel" and t.bookings:
                res = world.store.get_reservation(t.bookings.pop(rng.randrange(len(t.bookings))))
                result = _try(lambda res=res, key=key: run_write(world.deps, t.who, CancelOperation(world.deps, res), key))
            else:
                continue
            with lock:
                outcomes.append("ok" if isinstance(result, dict) else result)

    with ThreadPoolExecutor(max_workers=len(traders)) as pool:
        list(pool.map(work, range(len(traders))))

    tally = counts(outcomes)
    assert tally.get("ok", 0) >= 20, tally  # the storm really did things
    assert set(tally) <= {"ok", "SLOT_TAKEN", "POLICY_DENIED", "HOLD_EXPIRED", "INVALID_INPUT", "NOT_FOUND"}, tally
    assert_invariants(world.store, now_iso(world))


def _try(fn):
    try:
        return fn()
    except FairTableError as e:
        return e.code.value


# ---------------------------------------------------------------- RT12 and the draw under load
def test_rt12_one_person_sending_twenty_entries_at_once_gets_one_ticket(world):
    from server.domain.fairdrop import entry_hash
    from server.ops.fairdrop import DropEntryOperation

    friday = date_of(world)
    while __import__("datetime").date.fromisoformat(friday).weekday() != 4:
        friday = (__import__("datetime").date.fromisoformat(friday) + timedelta(days=1)).isoformat()
    drop_id = f"drop-sakura-{friday}"
    me = racer(1)
    drop = world.store.get_drop(drop_id)
    jobs = [
        (lambda i=i: run_write(world.deps, me, DropEntryOperation(world.deps, drop, 2), f"rt12-key-{i:04d}"))
        for i in range(20)
    ]
    outcomes = race(jobs)
    assert counts(outcomes) == {"ALREADY_ENTERED": 19, "ok": 1}
    entries = world.store.entries_of_drop(drop_id)
    assert len(entries) == 1 and entries[0].sub == me.sub
    assert world.store.get_entry(drop_id, entry_hash(drop_id, me.sub)) is not None
    assert_invariants(world.store, now_iso(world))


def test_twenty_people_entering_together_all_get_exactly_one_ticket_each(world):
    from server.ops.fairdrop import DropEntryOperation

    friday = date_of(world)
    while __import__("datetime").date.fromisoformat(friday).weekday() != 4:
        friday = (__import__("datetime").date.fromisoformat(friday) + timedelta(days=1)).isoformat()
    drop_id = f"drop-sakura-{friday}"
    drop = world.store.get_drop(drop_id)
    users = [racer(i) for i in range(20)]
    jobs = [
        (lambda u=u, i=i: run_write(world.deps, u, DropEntryOperation(world.deps, drop, 2), f"enter-key-{i:04d}"))
        for i, u in enumerate(users)
    ]
    assert counts(race(jobs)) == {"ok": 20}
    assert len({e.sub for e in world.store.entries_of_drop(drop_id)}) == 20
    assert_invariants(world.store, now_iso(world))
