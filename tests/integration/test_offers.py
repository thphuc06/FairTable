"""D-059: the offer ids behind availability_check and reservation_hold (DynamoDB Local)."""

import re
from datetime import timedelta

import pytest
from flows import call, day
from world import World

from server.domain.errors import FairTableError
from server.domain.offers import SlotClaims
from server.store import keys

pytestmark = pytest.mark.ddb
CODE = re.compile(r"^[0-9a-hjkmnp-tv-z]{8}$")


@pytest.fixture
def world(ddb_client, table_name, clock):
    from ddb_env import ENDPOINT

    return World(ddb_client, table_name, ENDPOINT, clock)


async def offered(world: World, who: str = "alice", **over) -> list[dict]:
    args = {"restaurant_id": "luna-trattoria", "date": day(world), "time_window": "17:00-22:00", "party_size": 2, **over}
    r = await call(world.as_(who), "availability_check", **args)
    assert not r.isError, r.structuredContent
    return r.structuredContent["slots"]


async def test_every_slot_gets_a_short_id_and_at_most_five_are_shown(world):
    slots = await offered(world)
    assert 1 <= len(slots) <= 5
    assert all(CODE.match(s["offer_id"]) for s in slots), [s["offer_id"] for s in slots]
    assert len({s["offer_id"] for s in slots}) == len(slots)


async def test_the_offer_is_kept_for_the_user_with_an_expiry_and_a_cleanup_time(world):
    slot = (await offered(world))[0]
    item = world.store.get_item(keys.offer(slot["offer_id"]))
    assert item["rid"] == "luna-trattoria" and item["sub"] == "dev-alice" and item["party"] == 2
    assert item["expires_at"] > item["created_at"] and item["ttl"] > 0


async def test_an_offer_holds_the_table_once_for_its_user_and_survives_a_model_s_writing_of_it(world):
    slot = (await offered(world))[0]
    written = f" {slot['offer_id'][:4].upper()}-{slot['offer_id'][4:]} "  # capitals, a dash, spaces
    r = await call(world.as_("alice"), "reservation_hold", offer_id=written, idempotency_key="key-offer-0001")
    assert not r.isError, r.structuredContent
    assert r.structuredContent["read_back"] and len(r.structuredContent["read_back_token"]) == 11


async def test_another_user_an_unknown_id_and_a_malformed_one_are_all_just_invalid(world):
    slot = (await offered(world))[0]
    for who, code in (("bob", slot["offer_id"]), ("alice", "zzzzzzzz"), ("alice", "short"), ("alice", "x" * 300)):
        r = await call(world.as_(who), "reservation_hold", offer_id=code, idempotency_key=f"key-bad-{who}-{len(code)}")
        assert r.isError and r.structuredContent["error"] == "INVALID_OFFER", (who, code, r.structuredContent)
        assert r.structuredContent["message"] == "That table offer is no longer valid."  # never which check failed


async def test_an_offer_expires_after_its_lifetime(world, clock):
    slot = (await offered(world))[0]
    clock.advance(world.deps.settings.offer_ttl_s + 1)
    r = await call(world.as_("alice"), "reservation_hold", offer_id=slot["offer_id"], idempotency_key="key-late-0001")
    assert r.isError and r.structuredContent["error"] == "OFFER_EXPIRED"
    assert r.structuredContent["next_step"]["tool"] == "availability_check"


async def test_the_offer_book_issues_and_verifies_directly(world, clock):
    claims = SlotClaims("luna-trattoria", day(world), "1900#T2", 2, 1, "dev-alice", hot=True, drop_id="drop-x")
    code = world.deps.offers.issue(claims)
    assert world.deps.offers.verify(code, sub="dev-alice") == claims
    with pytest.raises(FairTableError) as wrong:
        world.deps.offers.verify(code, sub="dev-bob")
    assert wrong.value.reason == "wrong_user"
    clock.advance(timedelta(seconds=world.deps.settings.offer_ttl_s).total_seconds())
    with pytest.raises(FairTableError) as late:
        world.deps.offers.verify(code, sub="dev-alice")
    assert late.value.reason == "expired"


async def test_a_code_that_already_exists_is_never_overwritten(ddb_client, table_name, clock):
    from ddb_env import ENDPOINT

    w = World(ddb_client, table_name, ENDPOINT, clock)
    claims = SlotClaims("luna-trattoria", day(w), "1900#T2", 2, 1, "dev-alice")
    first = w.deps.offers.issue(claims)
    codes = iter([first, "aaaaaaaa", "bbbbbbbb", "cccccccc"])
    w.deps.offers._make_code = lambda: next(codes)  # the first draw collides, the second does not
    second = w.deps.offers.issue(SlotClaims("luna-trattoria", day(w), "2000#T2", 4, 1, "dev-alice"))
    assert second == "aaaaaaaa" and w.deps.offers.verify(first, sub="dev-alice").party_size == 2
