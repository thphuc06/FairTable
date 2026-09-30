"""P1-14: standing watches: register, match a freed table lazily, status and cancel."""

import pytest
from ddb_env import ENDPOINT
from flows import book, call, counter, day, error_of, hold_table
from world import World

from server.domain.clock import iso_z
from server.invariants import assert_invariants
from server.store import keys

pytestmark = pytest.mark.ddb
LUNA = "luna-trattoria"


@pytest.fixture
def world(ddb_client, table_name, clock):
    w = World(ddb_client, table_name, ENDPOINT, clock)
    ids = iter(range(1, 100_000))
    w.deps.new_id = lambda: f"id{next(ids):05d}"
    return w


async def watch(world: World, who: str, *, window: str = "19:00-19:00", party: int = 5, key: str = "watch-key-0001",
                offset: int = 2, venue: str = LUNA):
    return await call(world.as_(who), "waitlist_watch", restaurant_id=venue, date=day(world, offset),
                      idempotency_key=key, time_window=window, party_size=party)


async def status(world: World, who: str, watch_id: str, action: str = "status"):
    return await call(world.as_(who), "waitlist_status", watch_id=watch_id, action=action)


async def fully_booked(world: World, who: str = "bob") -> dict:
    """Bob takes the only 19:00 table that seats five, so a party of five has to wait."""
    return await book(world, who, LUNA, "19:00", party=5, tag="b")


async def cancel(world: World, who: str, reservation_id: str, key: str = "cancel-key-0001"):
    return await call(world.as_(who), "reservation_manage", action="cancel", reservation_id=reservation_id,
                      idempotency_key=key)


# ---------------------------------------------------------------- registering
async def test_a_watch_is_registered_when_nothing_fits_now(world):
    await fully_booked(world)
    r = await watch(world, "alice")
    body = r.structuredContent
    assert not r.isError and body["status"] == "waiting" and body["retry_after_s"] == 60
    assert body["next_step"]["tool"] == "waitlist_status" and "5" in body["spoken_summary"]
    w = world.store.get_watch(body["watch_id"])
    assert (w.sub, w.status, w.party_size, w.window_start) == ("dev-alice", "waiting", 5, "19:00")
    assert (w.agent_tier, w.username, "fairtable/book" in w.scopes) == ("verified", "diner-alice", True)
    assert world.store.active_watch_id("dev-alice", LUNA, day(world)) == w.watch_id


async def test_when_a_table_is_free_now_no_watch_is_created(world):
    r = await watch(world, "alice", party=2, window="19:00-19:00")
    body = r.structuredContent
    assert not r.isError and body["status"] == "tables_available"
    assert body["next_step"]["tool"] == "availability_check"
    assert world.store.active_watch_id("dev-alice", LUNA, day(world)) is None


async def test_only_one_active_watch_per_person_restaurant_and_day(world):
    await fully_booked(world)
    first = (await watch(world, "alice", key="watch-key-0001")).structuredContent
    second = await watch(world, "alice", key="watch-key-0002")
    payload = error_of(second, "ALREADY_ENTERED")
    assert payload["details"]["watch_id"] == first["watch_id"]
    # another day and another person are fine
    assert not (await watch(world, "alice", key="watch-key-0003", offset=3, party=5)).isError
    assert not (await watch(world, "carol", key="watch-key-0004")).isError


async def test_repeating_the_same_call_returns_the_same_watch(world):
    await fully_booked(world)
    first = (await watch(world, "alice")).structuredContent
    again = (await watch(world, "alice")).structuredContent
    assert again == {**first, "idempotent_replay": True}


async def test_after_cancelling_a_watch_a_new_one_is_allowed(world):
    await fully_booked(world)
    first = (await watch(world, "alice", key="watch-key-0001")).structuredContent
    done = (await status(world, "alice", first["watch_id"], "cancel")).structuredContent
    assert done["status"] == "cancelled"
    assert not (await watch(world, "alice", key="watch-key-0002")).isError


async def test_unverified_agents_and_bots_cannot_watch(world):
    await fully_booked(world)
    for who in ("shady", "bot"):
        payload = error_of(await watch(world, who, key=f"watch-{who}-0001"), "POLICY_DENIED")
        assert payload["rule_id"] == "G4_verified_agent_only"
    error_of(await call(world.as_(None), "waitlist_watch", restaurant_id=LUNA, date=day(world),
                        idempotency_key="watch-key-0009", time_window="19:00-19:00", party_size=5),
             "UNAUTHENTICATED")


@pytest.mark.parametrize("args", [
    {"date": "2020-01-01"}, {"time_window": "later"}, {"party_size": 0}, {"restaurant_id": "nowhere"},
    {"idempotency_key": "bad key"},
])
async def test_bad_input_is_a_structured_error(world, args):
    base = {"restaurant_id": LUNA, "date": day(world), "idempotency_key": "watch-key-0001",
            "time_window": "19:00-19:00", "party_size": 5}
    r = await call(world.as_("alice"), "waitlist_watch", **{**base, **args})
    assert r.isError and r.structuredContent["error"] in {"INVALID_INPUT", "NOT_FOUND"}


# ---------------------------------------------------------------- matching after a cancel
async def test_a_cancel_gives_the_freed_table_to_the_first_watcher(world):
    date = day(world)
    booking = await fully_booked(world)
    w = (await watch(world, "alice")).structuredContent["watch_id"]
    await cancel(world, "bob", booking["reservation_id"])

    watch_now = world.store.get_watch(w)
    assert watch_now.status == "matched" and watch_now.hold_id
    hold = world.store.get_hold(watch_now.hold_id)
    assert (hold.sub, hold.status, hold.party_size, hold.time) == ("dev-alice", "held", 5, "19:00")
    slot = next(s for s in world.store.get_slots(LUNA, date) if s.time == "19:00" and s.seats == 6)
    assert (slot.status, slot.hold_id) == ("held", hold.hold_id)
    assert counter(world, keys.active_holds_counter("dev-alice", LUNA)) == 1
    assert counter(world, keys.agent_covers_counter(LUNA, date)) == 5  # Bob's five freed, Alice's five taken
    assert world.store.active_watch_id("dev-alice", LUNA, date) is None  # she may watch again
    assert [m["subject"] for m in world.store.list_inbox("dev-alice")] == ["A table opened up"]

    body = (await status(world, "alice", w)).structuredContent
    assert body["status"] == "matched" and body["hold_id"] == hold.hold_id
    assert body["hold_expires_at"] == hold.held_until and body["next_step"]["tool"] == "reservation_confirm"
    assert_invariants(world.store, iso_z(world.clock.now()))


async def test_the_watcher_can_confirm_the_table_they_were_given(world):
    booking = await fully_booked(world)
    w = (await watch(world, "alice")).structuredContent["watch_id"]
    await cancel(world, "bob", booking["reservation_id"])
    hold_id = (await status(world, "alice", w)).structuredContent["hold_id"]
    done = await call(world.as_("alice"), "reservation_confirm", hold_id=hold_id, idempotency_key="conf-key-0001")
    # party of five is above Alice's mandate limit of four, so she is asked to approve first
    payload = error_of(done, "CONSENT_REQUIRED")
    assert payload["consent_url"].endswith(hold_id)
    assert_invariants(world.store, iso_z(world.clock.now()))


async def test_watchers_are_served_first_come_first_served(world):
    booking = await fully_booked(world)
    first = (await watch(world, "alice", key="watch-key-a001")).structuredContent["watch_id"]
    world.clock.advance(seconds=5)
    second = (await watch(world, "carol", key="watch-key-c001")).structuredContent["watch_id"]
    await cancel(world, "bob", booking["reservation_id"])
    assert world.store.get_watch(first).status == "matched"
    assert world.store.get_watch(second).status == "waiting"  # still waiting for the next table


async def test_a_watcher_the_rules_refuse_is_skipped_for_the_next_one(world):
    booking = await fully_booked(world)
    first = (await watch(world, "alice", key="watch-key-a001")).structuredContent["watch_id"]
    world.clock.advance(seconds=5)
    second = (await watch(world, "carol", key="watch-key-c001")).structuredContent["watch_id"]
    # Alice already holds two tables here (rule S1), so the freed table cannot be given to her.
    await hold_table(world, "alice", LUNA, "17:30", key="alice-hold-0001")
    await hold_table(world, "alice", LUNA, "18:00", key="alice-hold-0002")
    await cancel(world, "bob", booking["reservation_id"])
    assert world.store.get_watch(first).status == "waiting"
    assert world.store.get_watch(second).status == "matched"


@pytest.mark.parametrize("start,end,party", [("18:00", "18:30", 5), ("19:30", "21:00", 5), ("19:00", "19:00", 7)])
async def test_a_watcher_whose_window_or_party_does_not_fit_is_left_alone(world, start, end, party):
    from server.domain.waitlist import Watch

    booking = await fully_booked(world)
    date = day(world)
    stray = Watch("stray", "dev-alice", "diner-alice", "verified", "alexa-plus-sim", frozenset({"fairtable/book"}),
                  LUNA, date, start, end, party, "waiting", iso_z(world.clock.now()))
    world.store.transact(world.store.watch_put_ops(stray))
    await cancel(world, "bob", booking["reservation_id"])
    assert world.store.get_watch("stray").status == "waiting"  # the freed 19:00 table does not suit it


async def test_a_cancel_with_nobody_waiting_just_frees_the_table(world):
    booking = await fully_booked(world)
    r = await cancel(world, "bob", booking["reservation_id"])
    assert not r.isError and r.structuredContent["status"] == "cancelled"
    assert world.store.get_slot(LUNA, day(world), "19:00", "T6").status == "open"


async def test_a_repeated_cancel_does_not_match_a_second_time(world):
    booking = await fully_booked(world)
    w = (await watch(world, "alice")).structuredContent["watch_id"]
    await cancel(world, "bob", booking["reservation_id"])
    hold_id = world.store.get_watch(w).hold_id
    await cancel(world, "bob", booking["reservation_id"])  # same key: a replay
    assert world.store.get_watch(w).hold_id == hold_id
    assert len(world.store.holds_of_user("dev-alice")) == 1


async def test_a_failing_matcher_never_breaks_the_cancel(world, monkeypatch):
    from server import matcher

    def boom(*_a, **_k):
        raise RuntimeError("matcher exploded")

    monkeypatch.setattr(matcher, "offer_freed_slot", boom)
    booking = await fully_booked(world)
    await watch(world, "alice")
    r = await cancel(world, "bob", booking["reservation_id"])
    assert not r.isError and world.store.get_reservation(booking["reservation_id"]).status == "cancelled"


# ---------------------------------------------------------------- matching after a hold expires
async def test_an_expired_hold_hands_its_table_to_the_next_watcher(world):
    date = day(world)
    # Bob holds the table for five but never confirms; Alice is waiting for it.
    bob_hold = await hold_table(world, "bob", LUNA, "19:00", party=5, key="bob-hold-0001")
    w = (await watch(world, "alice")).structuredContent["watch_id"]
    world.clock.advance(minutes=11)  # Bob's hold is over
    # Any hold at this restaurant and day triggers the lazy release, which offers the table.
    await hold_table(world, "carol", LUNA, "17:30", key="carol-hold-0001")
    assert world.store.get_hold(bob_hold["hold_id"]).status == "expired"
    assert world.store.get_watch(w).status == "matched"
    assert counter(world, keys.agent_covers_counter(LUNA, date)) == 2 + 5  # Carol's 2 + Alice's 5
    assert_invariants(world.store, iso_z(world.clock.now()))


async def test_a_confirm_that_finds_the_hold_expired_also_offers_the_table(world):
    bob_hold = await hold_table(world, "bob", LUNA, "19:00", party=5, key="bob-hold-0001")
    w = (await watch(world, "alice")).structuredContent["watch_id"]
    world.clock.advance(minutes=11)
    error_of(await call(world.as_("bob"), "reservation_confirm", hold_id=bob_hold["hold_id"],
                        idempotency_key="conf-key-0001"), "HOLD_EXPIRED")
    assert world.store.get_watch(w).status == "matched"


# ---------------------------------------------------------------- status, cancel, ownership, time
async def test_a_waiting_watch_says_how_long_to_wait(world):
    await fully_booked(world)
    w = (await watch(world, "alice")).structuredContent["watch_id"]
    body = (await status(world, "alice", w)).structuredContent
    assert body["status"] == "waiting" and body["retry_after_s"] == 60
    assert body["next_step"]["tool"] == "waitlist_status" and "60 seconds" in body["next_step"]["why"]


async def test_cancelling_stops_matching_and_repeating_it_is_harmless(world):
    booking = await fully_booked(world)
    w = (await watch(world, "alice")).structuredContent["watch_id"]
    assert (await status(world, "alice", w, "cancel")).structuredContent["status"] == "cancelled"
    assert (await status(world, "alice", w, "cancel")).structuredContent["status"] == "cancelled"
    await cancel(world, "bob", booking["reservation_id"])
    assert world.store.get_watch(w).status == "cancelled"
    assert world.store.get_slot(LUNA, day(world), "19:00", "T6").status == "open"


async def test_nobody_can_read_or_cancel_somebody_elses_watch(world):
    await fully_booked(world)
    w = (await watch(world, "alice")).structuredContent["watch_id"]
    for who in ("bob", "bot"):
        error_of(await status(world, who, w), "NOT_FOUND")
        error_of(await status(world, who, w, "cancel"), "NOT_FOUND")
    error_of(await status(world, "alice", "nope"), "NOT_FOUND")
    assert world.store.get_watch(w).status == "waiting"


async def test_a_watch_for_a_day_that_has_passed_reads_as_expired(world):
    await fully_booked(world)
    w = (await watch(world, "alice")).structuredContent["watch_id"]
    world.clock.advance(days=3)
    world._tokens.clear()  # the old sign-in expired with the clock; get a fresh one
    body = (await status(world, "alice", w)).structuredContent
    assert body["status"] == "expired" and "expired" in body["spoken_summary"]


async def test_a_matched_watch_reports_when_its_hold_ran_out(world):
    booking = await fully_booked(world)
    w = (await watch(world, "alice")).structuredContent["watch_id"]
    await cancel(world, "bob", booking["reservation_id"])
    world.clock.advance(minutes=11)
    body = (await status(world, "alice", w)).structuredContent
    assert body["status"] == "matched" and "ran out" in body["spoken_summary"]
    assert body["next_step"]["tool"] == "waitlist_watch"


async def test_the_status_tool_needs_a_sign_in(world):
    await fully_booked(world)
    w = (await watch(world, "alice")).structuredContent["watch_id"]
    error_of(await call(world.as_(None), "waitlist_status", watch_id=w), "UNAUTHENTICATED")
