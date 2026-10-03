"""P1-16: Fair Drop end to end: tickets, the lazy draw, the public audit."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from ddb_env import ENDPOINT
from flows import call, counter, error_of
from mcp import McpError
from world import World

from server.domain import fairdrop as fd
from server.domain.clock import iso_z
from server.dropper import maybe_allocate
from server.invariants import assert_invariants
from server.store import keys
from server.store.mappers import slot_to_item
from server.store.seed_data import DropSpec
from server.store.seeding import create_drop

pytestmark = pytest.mark.ddb
SEED = bytes(range(32))
SAKURA = "sakura-counter"


@pytest.fixture
def world(ddb_client, table_name, clock):
    w = World(ddb_client, table_name, ENDPOINT, clock, seeds=fd.FixedSeedProvider(SEED))
    ids = iter(range(1, 100_000))
    w.deps.new_id = lambda: f"id{next(ids):05d}"
    return w


async def test_creating_a_drop_again_removes_the_tickets_of_the_old_one(world):
    """A reseed of a reused table draws a new seed: a ticket entered under the old commitment must not carry over."""
    did = drop_id(world)
    assert not (await enter(world, "alice")).isError
    assert world.store.entries_of_drop(did)
    old = world.store.get_drop(did)
    create_drop(world.store, fd.FixedSeedProvider(SEED), DropSpec(
        old.drop_id, old.venue_id, old.date, old.slot_keys, old.opens_at, old.drop_at))
    assert world.store.entries_of_drop(did) == []
    assert not (await enter(world, "alice", key="enter-alice-0002")).isError  # no ALREADY_ENTERED from the old table


def friday(world: World) -> str:
    d = world.clock.now().date()
    while d.weekday() != 4:
        d += timedelta(days=1)
    return d.isoformat()


def drop_id(world: World) -> str:
    return f"drop-sakura-{friday(world)}"


def jump_to(world: World, moment: str) -> None:
    """Move the clock; sign-ins expire with it, so users sign in again."""
    world.clock.set(datetime.fromisoformat(moment))
    world._tokens.clear()


def after_the_draw(world: World, did: str | None = None) -> None:
    drop = world.store.get_drop(did or drop_id(world))
    jump_to(world, iso_z(datetime.fromisoformat(drop.drop_at) + timedelta(seconds=1)))


async def enter(world: World, who: str, did: str | None = None, *, party: int = 2, key: str | None = None):
    return await call(world.as_(who), "waitlist_watch", drop_id=did or drop_id(world), party_size=party,
                      idempotency_key=key or f"enter-{who}-0001")


async def ticket(world: World, who: str, watch_id: str, action: str = "status"):
    return await call(world.as_(who), "waitlist_status", watch_id=watch_id, action=action)


def expected_order(*subs: str, did: str) -> list[str]:
    return fd.order_entries(SEED, [fd.entry_id(did, s) for s in subs])


# ---------------------------------------------------------------- the drop as seeded
def test_the_seed_creates_a_drop_per_friday_seat_with_a_commitment_only(world):
    drop = world.store.get_drop(drop_id(world))
    assert (drop.venue_id, drop.slot_keys, drop.capacity, drop.status) == (SAKURA, ("2000#T2",), 1, "open")
    assert drop.commitment == fd.commitment(SEED)
    assert drop.drop_at == iso_z(datetime.fromisoformat(f"{friday(world)}T20:00:00+00:00") - timedelta(days=1))


# ---------------------------------------------------------------- entering
async def test_entering_returns_a_ticket_the_commitment_and_the_audit_address(world):
    r = await enter(world, "alice")
    body = r.structuredContent
    assert not r.isError and body["status"] == "entered" and body["places"] == 1
    assert body["watch_id"] == fd.entry_id(drop_id(world), "dev-alice")
    assert body["commitment"] == fd.commitment(SEED)
    assert body["audit_resource"] == f"fairtable://drops/{drop_id(world)}/audit"
    assert body["retry_after_s"] >= 30 and body["next_step"]["tool"] == "waitlist_status"
    stored = world.store.get_entry(drop_id(world), fd.entry_hash(drop_id(world), "dev-alice"))
    assert (stored.sub, stored.status, stored.agent_tier, stored.party_size) == ("dev-alice", "entered", "verified", 2)


async def test_repeating_the_entry_with_the_same_key_is_a_replay(world):
    first = (await enter(world, "alice")).structuredContent
    again = (await enter(world, "alice")).structuredContent
    assert again == {**first, "idempotent_replay": True}
    assert len(world.store.entries_of_drop(drop_id(world))) == 1


async def test_rt12_a_second_ticket_for_the_same_person_is_refused(world):
    first = (await enter(world, "alice", key="enter-key-0001")).structuredContent
    payload = error_of(await enter(world, "alice", key="enter-key-0002"), "ALREADY_ENTERED")
    assert payload["details"]["watch_id"] == first["watch_id"]
    assert len(world.store.entries_of_drop(drop_id(world))) == 1


async def test_different_people_each_get_a_ticket_but_bots_and_unverified_agents_do_not(world):
    for who in ("alice", "bob", "carol"):
        assert not (await enter(world, who)).isError
    for who in ("shady", "bot"):
        assert error_of(await enter(world, who), "POLICY_DENIED")["rule_id"] == "G4_verified_agent_only"
    error_of(await call(world.as_(None), "waitlist_watch", drop_id=drop_id(world), idempotency_key="enter-key-0009"),
             "UNAUTHENTICATED")
    assert len(world.store.entries_of_drop(drop_id(world))) == 3


async def test_the_ticket_id_reveals_no_person(world):
    body = (await enter(world, "alice")).structuredContent
    assert "alice" not in body["watch_id"] and "dev-" not in body["watch_id"]


async def test_unknown_drops_and_missing_inputs_are_structured_errors(world):
    error_of(await enter(world, "alice", "drop-nowhere"), "NOT_FOUND")
    r = await call(world.as_("alice"), "waitlist_watch", idempotency_key="enter-key-0001")
    error_of(r, "INVALID_INPUT")  # neither a restaurant and date nor a drop_id


async def test_a_drop_that_has_not_opened_yet_is_closed_to_entries(world):
    spec = DropSpec("drop-future", SAKURA, friday(world), ("2000#T2",),
                    iso_z(world.clock.now() + timedelta(hours=2)), iso_z(world.clock.now() + timedelta(hours=5)))
    create_drop(world.store, fd.FixedSeedProvider(SEED), spec)
    error_of(await enter(world, "alice", "drop-future"), "DROP_CLOSED")


async def test_the_ticket_status_before_the_draw(world):
    watch_id = (await enter(world, "alice")).structuredContent["watch_id"]
    body = (await ticket(world, "alice", watch_id)).structuredContent
    assert body["status"] == "entered" and body["commitment"] == fd.commitment(SEED)
    assert body["retry_after_s"] >= 30 and body["next_step"]["tool"] == "waitlist_status"
    error_of(await ticket(world, "bob", watch_id), "NOT_FOUND")  # someone else's ticket
    error_of(await ticket(world, "alice", "drop-sakura-x~" + "0" * 64), "NOT_FOUND")


async def test_a_ticket_can_be_withdrawn_before_the_draw_and_taken_again(world):
    watch_id = (await enter(world, "alice")).structuredContent["watch_id"]
    assert (await ticket(world, "alice", watch_id, "cancel")).structuredContent["status"] == "cancelled"
    assert world.store.entries_of_drop(drop_id(world)) == []
    again = (await enter(world, "alice", key="enter-key-0002")).structuredContent
    assert again["watch_id"] == watch_id  # same person, same ticket id: nothing to gain by re-entering


# ---------------------------------------------------------------- the draw
async def test_the_first_request_after_the_drop_time_runs_the_draw_in_the_published_order(world):
    did = drop_id(world)
    ids = {}
    for who in ("alice", "bob", "carol"):
        ids[who] = (await enter(world, who)).structuredContent["watch_id"]
    after_the_draw(world)

    winner_id = expected_order("dev-alice", "dev-bob", "dev-carol", did=did)[0]
    winner = next(w for w, t in ids.items() if t == winner_id)
    body = (await ticket(world, "alice", ids["alice"])).structuredContent  # this call triggers the draw

    drop = world.store.get_drop(did)
    assert drop.status == "allocated" and drop.allocated_at
    statuses = {w: world.store.get_entry(did, fd.entry_hash(did, f"dev-{w}")).status for w in ids}
    assert statuses[winner] == "won" and sorted(statuses.values()) == ["lost", "lost", "won"]
    assert body["status"] == statuses["alice"]

    # the winner holds the drop seat, although direct holds on it are refused (S4)
    entry = world.store.get_entry(did, fd.entry_hash(did, f"dev-{winner}"))
    hold = world.store.get_hold(entry.hold_id)
    assert (hold.sub, hold.status, hold.time) == (f"dev-{winner}", "held", "20:00")
    assert counter(world, keys.active_holds_counter(f"dev-{winner}", SAKURA)) == 1
    answer = (await ticket(world, winner, ids[winner])).structuredContent
    assert answer["hold_id"] == hold.hold_id and answer["next_step"]["tool"] == "reservation_confirm"
    assert "You won" in answer["spoken_summary"]
    loser = next(w for w in ids if w != winner)
    assert "not picked" in (await ticket(world, loser, ids[loser])).structuredContent["spoken_summary"]
    assert [m["subject"] for m in world.store.list_inbox(f"dev-{winner}")] == ["You won the draw"]
    assert_invariants(world.store, iso_z(world.clock.now()))


async def test_a_winner_is_held_the_seat_for_two_hours_and_confirms_in_a_later_conversation(world):
    did = drop_id(world)
    ids = {who: (await enter(world, who)).structuredContent["watch_id"] for who in ("alice", "bob", "carol")}
    after_the_draw(world)
    winner_id = expected_order("dev-alice", "dev-bob", "dev-carol", did=did)[0]
    winner = next(w for w, t in ids.items() if t == winner_id)
    await ticket(world, "alice", ids["alice"])  # the first request runs the draw
    entry = world.store.get_entry(did, fd.entry_hash(did, f"dev-{winner}"))
    hold = world.store.get_hold(entry.hold_id)
    assert hold.held_until == iso_z(world.clock.now() + timedelta(hours=2))

    world.clock.advance(minutes=45)  # long past a normal hold: the winner asks again, in a new conversation
    world._tokens.clear()
    answer = (await ticket(world, winner, ids[winner])).structuredContent
    assert answer["read_back"].endswith("Shall I book it?") and answer["read_back_token"]
    world.clock.advance(8)
    done = await call(world.as_(winner), "reservation_confirm", hold_id=answer["hold_id"],
                      idempotency_key="drop-conf-0001", read_back_token=answer["read_back_token"], user_confirmed=True)
    assert not done.isError, done.structuredContent
    assert_invariants(world.store, iso_z(world.clock.now()))


async def test_the_published_audit_lets_anyone_recompute_the_draw(world):
    did = drop_id(world)
    for who in ("alice", "bob", "carol"):
        await enter(world, who)
    after_the_draw(world)
    async with world.client() as c:
        pending_before = json.loads((await c.read_resource(f"fairtable://drops/{did}/audit"))[0].text)
    audit = world.store.get_drop(did).audit
    assert pending_before == audit  # reading after the drop time ran the draw and returned the record

    assert fd.verify_audit(audit) == []
    assert audit["seed"] == SEED.hex() and audit["commitment"] == fd.commitment(SEED)
    assert [r["entry_id"] for r in audit["order"]] == expected_order("dev-alice", "dev-bob", "dev-carol", did=did)
    assert audit["winners"] == [audit["order"][0]["entry_id"]]
    assert not any(s in json.dumps(audit) for s in ("dev-", "alice", "bob", "carol"))


async def test_before_the_draw_the_audit_shows_the_commitment_but_never_the_seed(world):
    async with world.client() as c:
        text = (await c.read_resource(f"fairtable://drops/{drop_id(world)}/audit"))[0].text
    record = json.loads(text)
    assert record["commitment"] == fd.commitment(SEED) and record["status"] == "open"
    assert "seed" not in record and SEED.hex() not in text


async def test_the_walk_down_the_list_skips_people_the_rules_refuse(world):
    did = drop_id(world)
    for who in ("alice", "bob", "carol"):
        await enter(world, who)
    first, second = (s for s in expected_order("dev-alice", "dev-bob", "dev-carol", did=did)[:2])
    first_who = next(w for w in ("alice", "bob", "carol") if fd.entry_id(did, f"dev-{w}") == first)
    second_who = next(w for w in ("alice", "bob", "carol") if fd.entry_id(did, f"dev-{w}") == second)
    # The person drawn first already holds two tables at this restaurant (rule S1 still applies).
    from flows import hold_table

    drop_at = datetime.fromisoformat(world.store.get_drop(did).drop_at)
    jump_to(world, iso_z(drop_at - timedelta(minutes=5)))  # the holds must still be alive at the draw
    await hold_table(world, first_who, SAKURA, "17:30", key="pre-hold-0001")
    await hold_table(world, first_who, SAKURA, "18:00", key="pre-hold-0002")
    after_the_draw(world)
    maybe_allocate(world.deps, did)
    e1 = world.store.get_entry(did, fd.entry_hash(did, f"dev-{first_who}"))
    e2 = world.store.get_entry(did, fd.entry_hash(did, f"dev-{second_who}"))
    assert (e1.status, e1.reason) == ("skipped", "S1_max_active_holds")
    assert e2.status == "won"
    audit = world.store.get_drop(did).audit
    assert fd.verify_audit(audit) == []
    assert audit["order"][0]["outcome"] == "skipped" and audit["order"][0]["reason"] == "S1_max_active_holds"


async def test_two_places_five_tickets_and_a_party_that_fits_no_table(world):
    # Two drop seats (19:30 and 20:00), five tickets, one of them a party of 3 that no 2-seat table fits.
    fri = friday(world)
    for time in ("19:30", "20:00"):
        slot = world.store.get_slot(SAKURA, fri, time, "T2")
        world.store.put_item(slot_to_item(replace(slot, hot=True, drop_id="drop-multi")))
    spec = DropSpec("drop-multi", SAKURA, fri, ("1930#T2", "2000#T2"), iso_z(world.clock.now()),
                    iso_z(world.clock.now() + timedelta(hours=6)))
    create_drop(world.store, fd.FixedSeedProvider(SEED), spec)
    people = {"alice": 2, "bob": 3, "carol": 2}
    for i, extra in enumerate(("dana", "erin")):  # two more entrants straight into the table
        people[extra] = 2
    for who, party in people.items():
        if who in ("alice", "bob", "carol"):
            assert not (await enter(world, who, "drop-multi", party=party, key=f"enter-{who}-multi")).isError
    for extra in ("dana", "erin"):
        sub = f"dev-{extra}"
        e = fd.DropEntry(fd.entry_id("drop-multi", sub), "drop-multi", sub, extra, "verified", "alexa-plus-sim",
                         frozenset({"fairtable/book"}), 2, iso_z(world.clock.now()))
        world.store.transact([world.store.entry_put_op(e, fd.entry_hash("drop-multi", sub))])

    after_the_draw(world, "drop-multi")
    maybe_allocate(world.deps, "drop-multi")
    entries = {e.sub: e for e in world.store.entries_of_drop("drop-multi")}
    won = [s for s, e in entries.items() if e.status == "won"]
    assert len(won) == 2
    assert entries["dev-bob"].status in ("skipped", "lost")
    if entries["dev-bob"].status == "skipped":
        assert entries["dev-bob"].reason == "no_fitting_slot"
    audit = world.store.get_drop("drop-multi").audit
    assert fd.verify_audit(audit) == [] and len(audit["winners"]) == 2 and audit["capacity"] == 2
    times = sorted(world.store.get_hold(entries[s].hold_id).time for s in won)
    assert times == ["19:30", "20:00"]  # each winner has a different seat
    assert_invariants(world.store, iso_z(world.clock.now()))


async def test_late_entries_are_refused_and_the_draw_cannot_be_withdrawn_from(world):
    watch_id = (await enter(world, "alice")).structuredContent["watch_id"]
    after_the_draw(world)
    error_of(await enter(world, "bob"), "DROP_CLOSED")  # this call also triggers the draw
    assert world.store.get_drop(drop_id(world)).status == "allocated"
    error_of(await ticket(world, "alice", watch_id, "cancel"), "DROP_CLOSED")


async def test_a_second_request_after_the_draw_does_not_draw_again(world):
    await enter(world, "alice")
    after_the_draw(world)
    maybe_allocate(world.deps, drop_id(world))
    first_audit = world.store.get_drop(drop_id(world)).audit
    maybe_allocate(world.deps, drop_id(world))
    assert world.store.get_drop(drop_id(world)).audit == first_audit
    assert len(world.store.holds_of_user("dev-alice")) == 1


# ---------------------------------------------------------------- exactly once, and crash recovery
async def test_sixteen_simultaneous_first_requests_run_the_draw_exactly_once(world):
    did = drop_id(world)
    for who in ("alice", "bob", "carol"):
        await enter(world, who)
    after_the_draw(world)
    barrier = threading.Barrier(16)

    def trigger(_):
        barrier.wait()
        return maybe_allocate(world.deps, did).status

    with ThreadPoolExecutor(max_workers=16) as pool:
        statuses = list(pool.map(trigger, range(16)))
    assert set(statuses) <= {"allocating", "allocated"} and "allocated" in statuses
    drop = world.store.get_drop(did)
    assert drop.status == "allocated"
    holds = [h for s in ("alice", "bob", "carol") for h in world.store.holds_of_user(f"dev-{s}")]
    assert len(holds) == 1  # exactly one seat, exactly one hold
    assert fd.verify_audit(drop.audit) == []
    assert_invariants(world.store, iso_z(world.clock.now()))


async def test_a_draw_interrupted_half_way_is_finished_by_the_next_request(world):
    did = drop_id(world)
    for who in ("alice", "bob", "carol"):
        await enter(world, who)
    after_the_draw(world)
    # Simulate a crash: someone claimed the drop long ago and never finished.
    stale = iso_z(world.clock.now() - timedelta(minutes=5))
    world.store.put_drop(replace(world.store.get_drop(did), status="allocating", allocating_since=stale))
    finished = maybe_allocate(world.deps, did)
    assert finished.status == "allocated" and fd.verify_audit(finished.audit) == []
    assert_invariants(world.store, iso_z(world.clock.now()))


async def test_a_draw_that_is_being_run_right_now_is_left_alone(world):
    did = drop_id(world)
    await enter(world, "alice")
    after_the_draw(world)
    fresh = iso_z(world.clock.now())
    world.store.put_drop(replace(world.store.get_drop(did), status="allocating", allocating_since=fresh))
    still = maybe_allocate(world.deps, did)
    assert still.status == "allocating"  # not stolen from the runner that holds the claim
    watch_id = fd.entry_id(did, "dev-alice")
    body = (await ticket(world, "alice", watch_id)).structuredContent
    assert "being run" in body["spoken_summary"] and body["retry_after_s"] == 10


# ---------------------------------------------------------------- the policies resource
async def test_the_policies_resource_states_the_rules_with_this_restaurants_numbers(world):
    async with world.client() as c:
        text = (await c.read_resource("fairtable://restaurants/ember-grill/policies"))[0].text
        luna = (await c.read_resource("fairtable://restaurants/luna-trattoria/policies"))[0].text
    assert "Ember Grill" in text and "10 covers per day" in text and "25% of" in text
    assert "at most **2 active holds**" in text and "$25.00" in text and "48 hours" in text
    assert "is free" in luna
    async with world.client() as c:
        with pytest.raises(McpError, match="No restaurant"):
            await c.read_resource("fairtable://restaurants/nowhere/policies")
        with pytest.raises(McpError, match="No drop"):
            await c.read_resource("fairtable://drops/nowhere/audit")
