"""P1-9: reservation_hold through the MCP tools (dev-issuer tokens, seeded DynamoDB Local)."""

import re
from datetime import timedelta
from pathlib import Path

import pytest
from ddb_env import ENDPOINT
from world import World

from server.domain.booking import MAX_ACTIVE_HOLDS
from server.domain.clock import iso_z
from server.store import keys

pytestmark = pytest.mark.ddb


@pytest.fixture
def world(ddb_client, table_name, clock):
    w = World(ddb_client, table_name, ENDPOINT, clock)
    ids = iter(range(1, 100_000))
    w.deps.new_id = lambda: f"id{next(ids):05d}"
    return w


def day(world: World, offset: int = 2) -> str:
    return (world.clock.now().date() + timedelta(days=offset)).isoformat()


def next_weekday(world: World, weekday: int) -> str:
    d = world.clock.now().date()
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d.isoformat()


async def call(world: World, tool: str, **args):
    async with world.client() as c:
        return await c.call_tool_mcp(tool, args)


async def token_for(world: World, venue: str, date: str, time: str, party: int = 2, seats: int | None = None) -> str:
    r = await call(world, "availability_check", restaurant_id=venue, date=date,
                   time_window=f"{time}-{time}", party_size=party)
    slots = r.structuredContent["slots"]
    assert slots, r.structuredContent
    chosen = next((s for s in slots if seats is None or s["table_seats"] == seats), slots[0])
    return chosen["offer_id"]


async def hold(world: World, token: str, key: str = "key-hold-0001"):
    return await call(world, "reservation_hold", offer_id=token, idempotency_key=key)


def error_of(result, code: str) -> dict:
    assert result.isError, result.structuredContent
    assert result.structuredContent["error"] == code, result.structuredContent
    return result.structuredContent


def counter(world: World, key) -> int:
    item = world.store.get_item(key)
    return int(item["n"]) if item else 0


# ---------------------------------------------------------------- happy path
async def test_alice_holds_a_table_and_gets_the_details_to_read_back(world):
    date = day(world)
    token = await token_for(world.as_("alice"), "luna-trattoria", date, "19:00", party=2)
    r = await hold(world, token)
    body = r.structuredContent
    assert not r.isError
    assert body["hold_id"] == "id00001" and body["time"] == "19:00" and body["party_size"] == 2
    assert "within_mandate" not in body
    assert body["expires_at"] == iso_z(world.clock.now() + timedelta(minutes=10))
    assert "7:00 PM" in body["spoken_summary"] and "10 minutes" in body["spoken_summary"]
    assert body["read_back"].endswith("Shall I book it?") and body["read_back_token"] and body["min_pause_s"] == 3
    assert body["next_step"]["tool"] == "reservation_confirm"

    slot = world.store.get_slot("luna-trattoria", date, "19:00", "T2")
    assert (slot.status, slot.ver, slot.hold_id, slot.held_until) == ("held", 2, "id00001", body["expires_at"])
    assert counter(world, keys.active_holds_counter("dev-alice", "luna-trattoria")) == 1
    assert counter(world, keys.agent_covers_counter("luna-trattoria", date)) == 2
    stored = world.store.get_hold("id00001")
    assert (stored.status, stored.sub, stored.agent_id) == ("held", "dev-alice", "alexa-plus-sim")
    assert stored.terms["cancel_fee_cents"] == 0
    assert [e["decision"] for e in world.store.list_audit("luna-trattoria", world.clock.now().date().isoformat())] == ["allow"]


async def test_every_diner_gets_the_same_read_back_flow_there_is_no_standing_permission(world):
    for who, key in (("alice", "key-a-0001"), ("bob", "key-b-0001"), ("carol", "key-c-0001")):
        token = await token_for(world.as_(who), "luna-trattoria", day(world), "19:30", party=2)
        body = (await hold(world, token, key)).structuredContent
        assert body["read_back"] and body["read_back_token"], who
        assert body["next_step"]["tool"] == "reservation_confirm" and "yes" in body["next_step"]["why"]


async def test_a_waitlist_match_and_a_drop_win_hold_longer_than_a_normal_hold(world):
    assert world.deps.settings.hold_ttl_s == 600
    assert world.deps.settings.match_hold_ttl_s == 1800 and world.deps.settings.drop_hold_ttl_s == 7200


# ---------------------------------------------------------------- idempotency
async def test_repeating_the_call_returns_the_same_hold_and_writes_nothing_new(world):
    date = day(world)
    token = await token_for(world.as_("alice"), "luna-trattoria", date, "19:00")
    first = (await hold(world, token)).structuredContent
    again = (await hold(world, token)).structuredContent
    assert again == {**first, "idempotent_replay": True}
    assert counter(world, keys.active_holds_counter("dev-alice", "luna-trattoria")) == 1
    assert world.store.get_slot("luna-trattoria", date, "19:00", "T2").ver == 2


async def test_a_retry_with_a_second_token_for_the_same_slot_is_the_same_request(world):
    """The agent asked twice before holding (two different token strings for one slot), then retried
    the hold with the other token after a network error: same key, same slot, same party = replay."""
    date = day(world)
    world.as_("alice")
    token1 = await token_for(world, "luna-trattoria", date, "19:00", seats=2)
    world.clock.advance(seconds=5)
    token2 = await token_for(world, "luna-trattoria", date, "19:00", seats=2)
    assert token1 != token2
    first = (await hold(world, token1)).structuredContent
    second = await hold(world, token2)
    assert not second.isError and second.structuredContent["hold_id"] == first["hold_id"]
    assert second.structuredContent["idempotent_replay"] is True


async def test_a_key_reused_after_its_hold_is_over_is_a_conflict_not_a_replay(world):
    """A speech model likes the key "hold-luna-1" in every conversation. While the hold is live a repeat is the same
    request; once the hold has expired the same key must not report an old hold as held (D-059)."""
    date = day(world)
    world.as_("alice")
    token1 = await token_for(world, "luna-trattoria", date, "19:00", seats=2)
    first = (await hold(world, token1)).structuredContent
    world.clock.advance(seconds=601)  # the ten minutes are over
    token2 = await token_for(world, "luna-trattoria", date, "19:00", seats=2)
    again = await hold(world, token2)
    assert again.isError and again.structuredContent["error"] == "IDEMPOTENCY_CONFLICT"
    assert first["hold_id"] not in str(again.structuredContent)
    fresh = await call(world, "reservation_hold", offer_id=token2, idempotency_key="key-hold-0002")
    assert not fresh.isError and fresh.structuredContent["hold_id"] != first["hold_id"]


async def test_reusing_a_key_for_another_slot_is_a_conflict(world):
    date = day(world)
    world.as_("alice")
    await hold(world, await token_for(world, "luna-trattoria", date, "19:00"))
    r = await hold(world, await token_for(world, "luna-trattoria", date, "19:30"))
    error_of(r, "IDEMPOTENCY_CONFLICT")
    assert world.store.get_slot("luna-trattoria", date, "19:30", "T2").status == "open"


# ---------------------------------------------------------------- the rules
async def test_s1_a_third_active_hold_at_one_restaurant_is_refused(world):
    date = day(world)
    world.as_("alice")
    for i, time in enumerate(["18:00", "18:30"]):
        assert not (await hold(world, await token_for(world, "luna-trattoria", date, time), f"key-s1-{i:04d}")).isError
    r = await hold(world, await token_for(world, "luna-trattoria", date, "19:00"), "key-s1-0009")
    payload = error_of(r, "POLICY_DENIED")
    assert payload["rule_id"] == "S1_max_active_holds"
    assert counter(world, keys.active_holds_counter("dev-alice", "luna-trattoria")) == 2
    assert world.store.get_slot("luna-trattoria", date, "19:00", "T2").status == "open"
    # a different restaurant has its own counter
    assert not (await hold(world, await token_for(world, "ember-grill", date, "18:00"), "key-s1-0010")).isError


async def test_s2_the_agent_share_of_covers_is_capped(world):
    date = day(world)  # Ember Grill: 25% of 40 seats = 10 covers a day for agents
    for who, key, time in [("alice", "key-s2-0001", "17:30"), ("bob", "key-s2-0002", "18:00")]:
        token = await token_for(world.as_(who), "ember-grill", date, time, party=4)
        assert not (await hold(world, token, key)).isError
    payload = error_of(await hold(world.as_("carol"), await token_for(world, "ember-grill", date, "18:30", party=4),
                                  "key-s2-0003"), "POLICY_DENIED")
    assert payload["rule_id"] == "S2_agent_share_of_covers"
    assert payload["next_step"]["tool"] == "waitlist_watch"
    assert counter(world, keys.agent_covers_counter("ember-grill", date)) == 8
    # two more covers still fit exactly
    assert not (await hold(world, await token_for(world, "ember-grill", date, "19:30", party=2), "key-s2-0004")).isError
    assert counter(world, keys.agent_covers_counter("ember-grill", date)) == 10


async def test_s4_drop_controlled_seats_cannot_be_held_directly(world):
    fri = next_weekday(world, 4)
    token = await token_for(world.as_("alice"), "sakura-counter", fri, "20:00")
    payload = error_of(await hold(world, token), "DROP_CONTROLLED")
    assert payload["rule_id"] == "S4_drop_slots_via_waitlist" and payload["next_step"]["tool"] == "waitlist_watch"
    assert world.store.get_slot("sakura-counter", fri, "20:00", "T2").status == "open"


async def test_unverified_agents_and_bots_cannot_hold(world):
    token = await token_for(world.as_("alice"), "luna-trattoria", day(world), "19:00")
    for who, rule in [("shady", "G4_verified_agent_only"), ("bot", "G4_verified_agent_only")]:
        # the slot token is bound to Alice, so mint one for each caller first
        own = await token_for(world.as_(who), "luna-trattoria", day(world), "19:00")
        error_of_ = error_of(await hold(world, own, f"key-{who}-00001"), "POLICY_DENIED")
        assert error_of_["rule_id"] == rule
    assert token  # Alice's token was never used


# ---------------------------------------------------------------- lost races and bad tokens
async def test_the_second_person_for_a_slot_gets_slot_taken_with_alternatives(world):
    date = day(world)
    a = await token_for(world.as_("alice"), "luna-trattoria", date, "19:00", seats=2)
    b = await token_for(world.as_("bob"), "luna-trattoria", date, "19:00", seats=2)
    assert not (await hold(world.as_("alice"), a)).isError
    payload = error_of(await hold(world.as_("bob"), b), "SLOT_TAKEN")
    assert payload["details"]["alternatives"], "the agent should be offered other times"
    assert all(alt["time"] and alt["table_seats"] >= 2 for alt in payload["details"]["alternatives"])
    assert counter(world, keys.active_holds_counter("dev-bob", "luna-trattoria")) == 0


async def test_a_token_belongs_to_the_user_it_was_issued_to(world):
    alices = await token_for(world.as_("alice"), "luna-trattoria", day(world), "19:00")
    error_of(await hold(world.as_("bob"), alices), "INVALID_OFFER")


async def test_an_expired_offer_asks_for_fresh_slots(world):
    token = await token_for(world.as_("alice"), "luna-trattoria", day(world), "19:00")
    world.clock.advance(minutes=16)
    payload = error_of(await hold(world, token), "OFFER_EXPIRED")
    assert payload["next_step"]["tool"] == "availability_check"


@pytest.mark.parametrize("bad", ["", "short", "spaces are bad!"])
async def test_a_bad_idempotency_key_is_rejected_before_anything_is_written(world, bad):
    date = day(world)
    token = await token_for(world.as_("alice"), "luna-trattoria", date, "19:00")
    error_of(await hold(world, token, bad), "INVALID_INPUT")
    assert world.store.get_slot("luna-trattoria", date, "19:00", "T2").status == "open"


async def test_without_a_token_nothing_happens(world):
    token = await token_for(world.as_("alice"), "luna-trattoria", day(world), "19:00")
    error_of(await hold(world.as_(None), token), "UNAUTHENTICATED")


# ---------------------------------------------------------------- lazy expiry (D4)
async def test_an_expired_hold_frees_the_slot_and_the_counters_without_any_worker(world):
    date = day(world)
    a = await token_for(world.as_("alice"), "luna-trattoria", date, "19:00", seats=2)
    b = await token_for(world.as_("bob"), "luna-trattoria", date, "19:00", seats=2)
    alices = (await hold(world.as_("alice"), a)).structuredContent["hold_id"]
    world.clock.advance(minutes=11)  # the hold ran out; Bob's token (15 min) is still valid

    body = (await hold(world.as_("bob"), b)).structuredContent
    bobs = body["hold_id"]
    assert bobs != alices
    assert world.store.get_hold(alices).status == "expired"
    assert world.store.get_item(keys.hold(alices)).get("GSI1PK") is None  # no longer listed by expiry
    assert counter(world, keys.active_holds_counter("dev-alice", "luna-trattoria")) == 0
    assert counter(world, keys.agent_covers_counter("luna-trattoria", date)) == 2  # only Bob's now
    slot = world.store.get_slot("luna-trattoria", date, "19:00", "T2")
    assert (slot.hold_id, slot.status) == (bobs, "held")


async def test_stale_holds_do_not_count_toward_s1_or_s2(world):
    date = day(world)
    world.as_("alice")
    old_ids = []
    for i, time in enumerate(["18:00", "18:30"]):
        r = await hold(world, await token_for(world, "luna-trattoria", date, time), f"key-old-{i:04d}")
        old_ids.append(r.structuredContent["hold_id"])
    world.clock.advance(minutes=11)
    # Alice would be at the S1 maximum, but both holds are stale: a new one must work.
    r = await hold(world, await token_for(world, "luna-trattoria", date, "19:00"), "key-new-0001")
    assert not r.isError
    assert counter(world, keys.active_holds_counter("dev-alice", "luna-trattoria")) == 1
    assert {world.store.get_hold(i).status for i in old_ids} == {"expired"}


async def test_a_hold_that_is_still_alive_is_not_released(world):
    date = day(world)
    world.as_("alice")
    first = (await hold(world, await token_for(world, "luna-trattoria", date, "18:00"), "key-live-0001")).structuredContent
    world.clock.advance(minutes=9)
    await hold(world, await token_for(world, "luna-trattoria", date, "18:30"), "key-live-0002")
    assert world.store.get_hold(first["hold_id"]).status == "held"


# ---------------------------------------------------------------- consistency with the policy text
def test_the_s1_maximum_in_code_matches_the_cedar_rule():
    text = (Path(__file__).resolve().parents[2] / "policies" / "s1_max_active_holds.cedar").read_text()
    limit = int(re.search(r"active_holds_user_venue\s*>=\s*(\d+)", text).group(1))
    assert limit == MAX_ACTIVE_HOLDS
