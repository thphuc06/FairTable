"""P1-12: reservation_manage: view, reduce the party, cancel (with the fee decided before writing)."""

import pytest
from ddb_env import ENDPOINT
from fastmcp import Client
from flows import book, call, counter, day, error_of, hold_table, set_approval
from mcp import McpError
from world import World

from server.store import keys

pytestmark = pytest.mark.ddb


@pytest.fixture
def world(ddb_client, table_name, clock):
    w = World(ddb_client, table_name, ENDPOINT, clock)
    ids = iter(range(1, 100_000))
    w.deps.new_id = lambda: f"id{next(ids):05d}"
    return w


async def manage(world: World, action: str, reservation_id: str, key: str | None = "key-mng-0001", **extra):
    args = {"action": action, "reservation_id": reservation_id, **extra}
    if key is not None:
        args["idempotency_key"] = key
    return await call(world, "reservation_manage", **args)


# ---------------------------------------------------------------- view
async def test_view_shows_the_booking_and_what_cancelling_costs_now(world):
    booking = await book(world, "alice", "luna-trattoria", "19:00")
    r = await manage(world.as_("alice"), "view", booking["reservation_id"], key=None)  # no key needed
    body = r.structuredContent
    assert not r.isError and body["reservation"]["code"] == booking["code"]
    assert body["reservation"]["status"] == "confirmed" and body["cancel_fee_now_cents"] == 0
    assert "Cancelling now is free" in body["spoken_summary"]


async def test_view_warns_when_cancelling_now_would_cost_money(world):
    booking = await book(world, "bob", "ember-grill", "18:00", offset=1)  # tomorrow: inside the 48 h window
    body = (await manage(world.as_("bob"), "view", booking["reservation_id"], key=None)).structuredContent
    assert body["cancel_fee_now_cents"] == 2500
    assert "$25.00" in body["spoken_summary"] and "approval" in body["spoken_summary"]


async def test_far_enough_ahead_the_same_restaurant_cancels_for_free(world):
    booking = await book(world, "bob", "ember-grill", "18:00", offset=4)  # more than 48 h ahead
    body = (await manage(world.as_("bob"), "view", booking["reservation_id"], key=None)).structuredContent
    assert body["cancel_fee_now_cents"] == 0


async def test_nobody_can_see_or_touch_somebody_elses_booking(world):
    booking = await book(world, "alice", "luna-trattoria", "19:00")
    world.as_("bob")
    for action in ("view", "cancel"):
        error_of(await manage(world, action, booking["reservation_id"], key=None if action == "view" else "key-mng-0001"),
                 "NOT_FOUND")
    error_of(await manage(world, "view", "no-such-id", key=None), "NOT_FOUND")
    error_of(await manage(world, "view", "", key=None), "NOT_FOUND")
    assert world.store.get_reservation(booking["reservation_id"]).status == "confirmed"


# ---------------------------------------------------------------- cancel without a fee
async def test_a_free_cancel_frees_the_table_the_counter_and_the_slot(world):
    date = day(world)
    booking = await book(world, "alice", "luna-trattoria", "19:00", party=4)
    assert counter(world, keys.agent_covers_counter("luna-trattoria", date)) == 4
    r = await manage(world.as_("alice"), "cancel", booking["reservation_id"])
    body = r.structuredContent
    assert not r.isError and body["status"] == "cancelled" and body["fee_cents"] == 0
    assert "no cancellation fee" in body["spoken_summary"]

    res = world.store.get_reservation(booking["reservation_id"])
    assert (res.status, res.cancel_fee_cents, res.cancelled_at) == ("cancelled", 0, "2026-10-01T12:00:00Z")
    slot = next(s for s in world.store.get_slots("luna-trattoria", date) if s.time == "19:00" and s.seats == 4)
    assert (slot.status, slot.reservation_id, slot.hold_id) == ("open", None, None)
    assert counter(world, keys.agent_covers_counter("luna-trattoria", date)) == 0
    # the table can be booked again straight away
    again = await hold_table(world, "bob", "luna-trattoria", "19:00", party=4, key="key-hold-bob01")
    assert again["time"] == "19:00"


async def test_repeating_a_cancel_returns_the_same_answer_and_a_new_key_says_it_is_over(world):
    booking = await book(world, "alice", "luna-trattoria", "19:00")
    first = (await manage(world.as_("alice"), "cancel", booking["reservation_id"])).structuredContent
    again = (await manage(world, "cancel", booking["reservation_id"])).structuredContent
    assert again == {**first, "idempotent_replay": True}
    error_of(await manage(world, "cancel", booking["reservation_id"], key="key-mng-0002"), "INVALID_INPUT")


async def test_a_cancelled_booking_can_still_be_viewed(world):
    booking = await book(world, "alice", "luna-trattoria", "19:00")
    await manage(world.as_("alice"), "cancel", booking["reservation_id"])
    body = (await manage(world, "view", booking["reservation_id"], key=None)).structuredContent
    assert "was cancelled" in body["spoken_summary"] and body["reservation"]["status"] == "cancelled"


# ---------------------------------------------------------------- cancel with a fee: no silent cancel
async def test_a_cancel_with_a_fee_waits_for_the_user_and_changes_nothing(world):
    booking = await book(world, "bob", "ember-grill", "18:00", offset=1)
    rid = booking["reservation_id"]
    payload = error_of(await manage(world.as_("bob"), "cancel", rid), "FEE_APPLIES")
    assert payload["rule_id"] == "S3b_cancel_fee_needs_ack"
    assert payload["consent_url"] == f"http://localhost:8080/consent/{rid}"
    assert payload["details"]["terms"]["fee_cents"] == 2500 and "$25.00" in payload["hint"]
    assert world.store.get_reservation(rid).status == "confirmed"
    approval = world.store.get_approval(rid)
    assert (approval.kind, approval.status, approval.terms["fee_cents"]) == ("cancel_fee", "pending", 2500)
    assert world.store.get_idempotency("dev-bob", "key-mng-0001") is None


async def test_after_the_user_approves_the_fee_the_same_call_cancels(world):
    booking = await book(world, "bob", "ember-grill", "18:00", offset=1)
    rid = booking["reservation_id"]
    error_of(await manage(world.as_("bob"), "cancel", rid), "FEE_APPLIES")
    set_approval(world, rid)
    body = (await manage(world, "cancel", rid)).structuredContent
    assert body["fee_cents"] == 2500 and "$25.00" in body["spoken_summary"]
    res = world.store.get_reservation(rid)
    assert (res.status, res.cancel_fee_cents) == ("cancelled", 2500)
    assert world.store.get_approval(rid).status == "used"


async def test_declining_the_fee_keeps_the_booking(world):
    booking = await book(world, "bob", "ember-grill", "18:00", offset=1)
    rid = booking["reservation_id"]
    error_of(await manage(world.as_("bob"), "cancel", rid), "FEE_APPLIES")
    set_approval(world, rid, "declined")
    error_of(await manage(world, "cancel", rid), "CONSENT_DECLINED")
    assert world.store.get_reservation(rid).status == "confirmed"


async def test_an_approval_for_a_different_fee_is_worthless(world):
    booking = await book(world, "bob", "ember-grill", "18:00", offset=1)
    rid = booking["reservation_id"]
    error_of(await manage(world.as_("bob"), "cancel", rid), "FEE_APPLIES")
    set_approval(world, rid, terms_hash="0" * 64)  # approved terms do not match the real fee
    error_of(await manage(world, "cancel", rid), "FEE_APPLIES")
    assert world.store.get_reservation(rid).status == "confirmed"


async def test_a_client_that_can_open_urls_gets_minus_32042_for_the_fee(world):
    booking = await book(world, "bob", "ember-grill", "18:00", offset=1)
    world.as_("bob")

    async def never(*_a):
        raise AssertionError("no live elicitation expected")

    async with Client(world.mcp, elicitation_handler=never) as c:
        with pytest.raises(McpError) as exc:
            await c.call_tool_mcp("reservation_manage", {"action": "cancel",
                                  "reservation_id": booking["reservation_id"], "idempotency_key": "key-mng-0001"})
    assert exc.value.error.code == -32042
    [ask] = exc.value.error.data["elicitations"]
    assert ask["url"].endswith(booking["reservation_id"]) and "$25.00" in ask["message"]


# ---------------------------------------------------------------- reduce the party
async def test_a_smaller_party_frees_covers_and_updates_the_booking(world):
    date = day(world)
    booking = await book(world, "alice", "luna-trattoria", "19:00", party=4)
    r = await manage(world.as_("alice"), "modify", booking["reservation_id"], new_party_size=2)
    body = r.structuredContent
    assert not r.isError and body["party_size"] == 2 and "2 people" in body["spoken_summary"]
    res = world.store.get_reservation(booking["reservation_id"])
    assert (res.party_size, res.terms_snapshot["party_size"]) == (2, 2)
    assert counter(world, keys.agent_covers_counter("luna-trattoria", date)) == 2
    # and a later cancel frees exactly the remaining covers
    await manage(world, "cancel", booking["reservation_id"], key="key-mng-0002")
    assert counter(world, keys.agent_covers_counter("luna-trattoria", date)) == 0


@pytest.mark.parametrize("new_size", [4, 5, 0, -1])
async def test_only_a_smaller_party_can_be_changed(world, new_size):
    booking = await book(world, "alice", "luna-trattoria", "19:00", party=4)
    payload = error_of(await manage(world.as_("alice"), "modify", booking["reservation_id"],
                                    new_party_size=new_size), "INVALID_INPUT")
    assert "smaller party" in payload["message"]
    assert world.store.get_reservation(booking["reservation_id"]).party_size == 4


async def test_modify_and_cancel_need_their_inputs(world):
    booking = await book(world, "alice", "luna-trattoria", "19:00", party=4)
    rid = booking["reservation_id"]
    world.as_("alice")
    error_of(await manage(world, "modify", rid), "INVALID_INPUT")  # no new_party_size
    error_of(await manage(world, "cancel", rid, key=None), "INVALID_INPUT")  # no key
    error_of(await manage(world, "cancel", rid, key="bad key!"), "INVALID_INPUT")
    assert world.store.get_reservation(rid).status == "confirmed"


async def test_without_a_token_nothing_can_be_managed(world):
    booking = await book(world, "alice", "luna-trattoria", "19:00")
    error_of(await manage(world.as_(None), "view", booking["reservation_id"], key=None), "UNAUTHENTICATED")
