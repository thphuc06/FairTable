"""P1-7: the three read tools end to end (dev-issuer tokens, seeded DynamoDB Local, real kernel)."""

from datetime import timedelta

import pytest
from world import World

from server.domain.clock import iso_z

pytestmark = pytest.mark.ddb


@pytest.fixture
def world(ddb_client, table_name, clock):
    from ddb_env import ENDPOINT

    return World(ddb_client, table_name, ENDPOINT, clock)


def next_weekday(clock, weekday: int) -> str:
    day = clock.now().date()
    while day.weekday() != weekday:
        day += timedelta(days=1)
    return day.isoformat()


async def call(world: World, tool: str, **args):
    async with world.client() as c:
        return await c.call_tool_mcp(tool, args)


def assert_error(result, code: str):
    assert result.isError is True
    payload = result.structuredContent
    assert payload["error"] == code
    assert payload["next_step"]["why"]
    assert result.content[0].text  # a plain sentence for models that only read text
    return payload


# ---------------------------------------------------------------- restaurant_search
async def test_search_lists_all_restaurants_with_a_spoken_summary(world):
    r = await call(world.as_("alice"), "restaurant_search")
    assert not r.isError
    body = r.structuredContent
    assert [x["name"] for x in body["restaurants"]] == ["Ember Grill", "Luna Trattoria", "Sakura Counter"]
    assert body["spoken_summary"].startswith("I found 3 restaurants")
    assert body["next_step"]["tool"] == "availability_check"


async def test_search_filters_by_words_and_may_find_nothing(world):
    world.as_("alice")
    italian = (await call(world, "restaurant_search", query="ITALIAN pasta")).structuredContent
    assert [x["restaurant_id"] for x in italian["restaurants"]] == ["luna-trattoria"]
    none = await call(world, "restaurant_search", query="pizza hut")
    assert not none.isError  # an empty result is an answer, not an error
    assert none.structuredContent["restaurants"] == []
    assert none.structuredContent["spoken_summary"]


async def test_search_with_date_and_party_shows_the_earliest_free_time(world, clock):
    day = next_weekday(clock, 2)
    r = await call(world.as_("alice"), "restaurant_search", query="luna", date=day, party_size=4)
    assert r.structuredContent["restaurants"][0]["earliest_free_time"] == "17:30"
    assert "5:30 PM" in r.structuredContent["spoken_summary"]


async def test_detailed_format_adds_terms(world):
    body = (await call(world.as_("alice"), "restaurant_search", query="ember",
                       response_format="detailed")).structuredContent
    assert body["restaurants"][0]["terms"] == {"cancel_fee_cents": 2500, "free_cancel_hours": 48}
    assert body["restaurants"][0]["agent_covers_per_day"] == 10


# ---------------------------------------------------------------- access control on reads
async def test_no_token_and_bad_token_are_unauthenticated(world):
    payload = assert_error(await call(world.as_(None), "restaurant_search"), "UNAUTHENTICATED")
    assert "reason" not in payload and "token" not in payload["message"].lower().replace("user token", "")
    world.current = "not-a-jwt"
    assert_error(await call(world, "availability_check", restaurant_id="luna-trattoria",
                            date=next_weekday(world.clock, 2)), "UNAUTHENTICATED")


async def test_bots_and_unverified_agents_may_read(world, clock):
    day = next_weekday(clock, 2)
    for who in ("bot", "shady"):
        r = await call(world.as_(who), "availability_check", restaurant_id="luna-trattoria", date=day)
        assert not r.isError, who


async def test_large_groups_are_refused_by_g3_even_for_reads(world, clock):
    r = await call(world.as_("alice"), "availability_check", restaurant_id="luna-trattoria",
                   date=next_weekday(clock, 2), party_size=11)
    payload = assert_error(r, "POLICY_DENIED")
    assert payload["rule_id"] == "G3_party_size_max_10" and "call the restaurant" in payload["hint"]


# ---------------------------------------------------------------- availability_check
async def test_availability_returns_signed_slots_bound_to_the_caller(world, clock):
    day = next_weekday(clock, 2)
    r = await call(world.as_("alice"), "availability_check", restaurant_id="luna-trattoria",
                   date=day, time_window="18:00-19:00", party_size=4)
    body = r.structuredContent
    assert {s["time"] for s in body["slots"]} == {"18:00", "18:30", "19:00"}
    assert all(s["table_seats"] >= 4 for s in body["slots"])  # the T2 tables are not offered
    assert "6:00 PM" in body["spoken_summary"] and body["next_step"]["tool"] == "reservation_hold"
    first = body["slots"][0]
    claims = world.deps.offers.verify(first["offer_id"], sub="dev-alice")
    assert (claims.restaurant_id, claims.date, claims.party_size) == ("luna-trattoria", day, 4)
    # the token is useless to someone else
    with pytest.raises(Exception) as exc:
        world.deps.offers.verify(first["offer_id"], sub="dev-bob")
    assert exc.value.code.value == "INVALID_OFFER"


async def test_hot_and_drop_slots_are_flagged(world, clock):
    sat, fri = next_weekday(clock, 5), next_weekday(clock, 4)
    ember = (await call(world.as_("alice"), "availability_check", restaurant_id="ember-grill",
                        date=sat, time_window="19:00-19:00", party_size=4)).structuredContent
    assert [(s["hot"], s["how_to_book"]) for s in ember["slots"]] == [(True, "reservation_hold")]
    sakura = (await call(world, "availability_check", restaurant_id="sakura-counter", date=fri,
                         time_window="20:00-20:00", party_size=2)).structuredContent
    slot = sakura["slots"][0]
    assert slot["drop_id"] == f"drop-sakura-{fri}" and slot["how_to_book"] == "waitlist_watch"
    assert sakura["next_step"]["tool"] == "waitlist_watch"
    assert "lottery" in sakura["spoken_summary"]


async def test_a_full_window_is_an_answer_with_the_waitlist_as_next_step(world, clock):
    r = await call(world.as_("alice"), "availability_check", restaurant_id="sakura-counter",
                   date=next_weekday(clock, 2), party_size=4)  # the counter only has 2-seat tables
    body = r.structuredContent
    assert not r.isError and body["slots"] == [] and body["next_step"]["tool"] == "waitlist_watch"


async def test_held_slots_are_hidden_until_the_hold_runs_out(world, clock):
    from dataclasses import replace

    day = next_weekday(clock, 2)
    slot = world.store.get_slot("luna-trattoria", day, "19:00", "T4")
    held_until = iso_z(clock.now() + timedelta(minutes=10))
    from server.store.mappers import slot_to_item

    world.store.put_item(slot_to_item(replace(slot, status="held", held_until=held_until)))

    args = {"restaurant_id": "luna-trattoria", "date": day, "time_window": "19:00-19:00", "party_size": 4}
    r = await call(world.as_("alice"), "availability_check", **args)
    assert [s["table_seats"] for s in r.structuredContent["slots"]] == [6]  # only the T6 is left
    clock.advance(minutes=11)  # lazy expiry: no worker needed
    world.current = None
    r = await call(world.as_("alice"), "availability_check", **args)
    assert sorted(s["table_seats"] for s in r.structuredContent["slots"]) == [4, 6]


@pytest.mark.parametrize(
    "args",
    [
        {"date": "next week"},
        {"date": "2020-01-01"},
        {"date": "2026-10-03", "time_window": "late"},
        {"date": "2026-10-03", "time_window": "22:00-17:00"},
        {"date": "2026-10-03", "party_size": 0},
        {"date": "2026-10-03", "party_size": 99},
    ],
)
async def test_bad_input_is_a_structured_error(world, args):
    r = await call(world.as_("alice"), "availability_check", restaurant_id="luna-trattoria", **args)
    assert_error(r, "INVALID_INPUT")


async def test_unknown_restaurant_is_not_found_and_uses_no_rate_limit_token(world, clock):
    r = await call(world.as_("alice"), "availability_check", restaurant_id="nowhere",
                   date=next_weekday(clock, 2))
    assert_error(r, "NOT_FOUND")
    assert world.store.get_item(__import__("server.store", fromlist=["keys"]).keys.rate_bucket(
        "dev-alice", "nowhere")) is None


# ---------------------------------------------------------------- RT2: rate limiting
async def test_rt2_the_21st_check_in_an_hour_is_rate_limited(world, clock):
    args = {"restaurant_id": "luna-trattoria", "date": next_weekday(clock, 2)}
    world.as_("alice")
    async with world.client() as c:
        results = [await c.call_tool_mcp("availability_check", args) for _ in range(25)]
    assert [r.isError for r in results] == [False] * 20 + [True] * 5
    payload = assert_error(results[20], "RATE_LIMITED")
    assert payload["retry_after_s"] == 180 and payload["next_step"]["tool"] == "waitlist_watch"


async def test_rate_limit_is_per_user_and_per_restaurant_and_recovers(world, clock):
    day = next_weekday(clock, 2)
    world.as_("alice")
    async with world.client() as c:
        for _ in range(20):
            await c.call_tool_mcp("availability_check", {"restaurant_id": "luna-trattoria", "date": day})
        blocked = await c.call_tool_mcp("availability_check", {"restaurant_id": "luna-trattoria", "date": day})
        other_venue = await c.call_tool_mcp("availability_check", {"restaurant_id": "ember-grill", "date": day})
        world.as_("bob")
        other_user = await c.call_tool_mcp("availability_check", {"restaurant_id": "luna-trattoria", "date": day})
        world.as_("alice")
        clock.advance(seconds=181)  # one token has been refilled
        again = await c.call_tool_mcp("availability_check", {"restaurant_id": "luna-trattoria", "date": day})
        second = await c.call_tool_mcp("availability_check", {"restaurant_id": "luna-trattoria", "date": day})
    assert blocked.isError and not other_venue.isError and not other_user.isError
    assert not again.isError and second.isError


# ---------------------------------------------------------------- logging
class _Capture:
    """Collect log records from FastMCP's logger tree (it may not propagate to the root logger)."""

    def __init__(self):
        import logging

        self.records: list = []
        self.handler = logging.Handler()
        self.handler.emit = self.records.append
        self.logger = logging.getLogger("fastmcp")

    def __enter__(self):
        self.logger.addHandler(self.handler)
        return self

    def __exit__(self, *exc):
        self.logger.removeHandler(self.handler)


async def test_expected_refusals_do_not_produce_error_logs_but_real_bugs_do(world):
    with _Capture() as expected:
        await call(world.as_(None), "restaurant_search")  # UNAUTHENTICATED: routine
        await call(world.as_("alice"), "availability_check", restaurant_id="nowhere", date="2026-10-03",
                   party_size=2)  # NOT_FOUND: routine
    assert [r for r in expected.records if r.levelno >= 40 or r.exc_info] == []

    world.deps.store.get_venue = lambda _id: 1 / 0  # a genuine bug must stay loud
    with _Capture() as bug:
        await call(world.as_("alice"), "availability_check", restaurant_id="luna-trattoria", date="2026-10-03",
                   party_size=2)
    assert [r for r in bug.records if r.levelno >= 40]
