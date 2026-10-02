"""P1-12, P3-10: reservation_manage: view, reduce the party, cancel (a fee is read back and needs a spoken yes)."""

import pytest
from ddb_env import ENDPOINT
from flows import ANSWER_AFTER_S, book, call, counter, day, error_of, hold_table
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
    assert "$25.00" in body["spoken_summary"] and "yes" in body["spoken_summary"]


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
    assert (res.status, res.cancel_fee_cents, res.cancelled_at) == ("cancelled", 0, "2026-10-01T12:00:08Z")  # the booking took the 8 s the diner needed to answer
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


# ---------------------------------------------------------------- cancel with a fee: no silent cancel (D-051)
S5A, S5B, S5C = (
    "S5a_confirm_needs_read_back", "S5b_confirm_needs_the_diners_answer", "S5c_confirm_needs_an_explicit_yes",
)


async def fee_booking(world: World) -> str:
    """A booking at Ember for tomorrow: inside the 48 h window, so cancelling costs $25."""
    return (await book(world, "bob", "ember-grill", "18:00", offset=1))["reservation_id"]


async def first_cancel(world: World, rid: str) -> dict:
    """The refused first call: it carries the fee as a sentence and the token that proves it was handed over."""
    payload = error_of(await manage(world.as_("bob"), "cancel", rid), "CONFIRMATION_REQUIRED")
    assert payload["rule_id"] == S5A
    return payload["details"]


async def test_a_cancel_with_a_fee_is_refused_with_the_fee_read_back_and_changes_nothing(world):
    rid = await fee_booking(world)
    offer = await first_cancel(world, rid)
    assert "$25.00" in offer["read_back"] and offer["read_back"].endswith("cancel?") and offer["min_pause_s"] == 6
    assert offer["read_back_token"]
    assert world.store.get_reservation(rid).status == "confirmed"
    assert world.store.get_idempotency("dev-bob", "key-mng-0001") is None


async def test_after_the_pause_and_a_yes_the_second_call_cancels_and_records_the_read_back(world):
    rid = await fee_booking(world)
    offer = await first_cancel(world, rid)
    world.clock.advance(ANSWER_AFTER_S)
    body = (await manage(world, "cancel", rid, read_back_token=offer["read_back_token"], user_confirmed=True)).structuredContent
    assert body["fee_cents"] == 2500 and "$25.00" in body["spoken_summary"]
    res = world.store.get_reservation(rid)
    assert (res.status, res.cancel_fee_cents) == ("cancelled", 2500) and res.cancel_read_back_at is not None


async def test_the_second_call_too_soon_is_refused_and_the_token_stays_good(world):
    rid = await fee_booking(world)
    offer = await first_cancel(world, rid)
    world.clock.advance(4)  # more than the 3 s of a free booking, less than the 6 s of money
    soon = error_of(await manage(world, "cancel", rid, read_back_token=offer["read_back_token"], user_confirmed=True),
                    "CONFIRMATION_REQUIRED")
    assert soon["rule_id"] == S5B and "details" not in soon
    world.clock.advance(3)
    done = await manage(world, "cancel", rid, read_back_token=offer["read_back_token"], user_confirmed=True)
    assert not done.isError


async def test_without_the_explicit_yes_the_booking_is_kept(world):
    rid = await fee_booking(world)
    offer = await first_cancel(world, rid)
    world.clock.advance(ANSWER_AFTER_S)
    err = error_of(await manage(world, "cancel", rid, read_back_token=offer["read_back_token"]), "CONFIRMATION_REQUIRED")
    assert err["rule_id"] == S5C
    assert world.store.get_reservation(rid).status == "confirmed"


async def test_a_read_back_of_a_different_fee_is_worthless(world):
    """The fee was read back while it was $25; if the free window has passed and the terms differ, the token is stale."""
    rid = await fee_booking(world)
    offer = await first_cancel(world, rid)
    other = await book(world, "bob", "ember-grill", "18:30", offset=1, tag="2")  # another booking, same fee
    world.clock.advance(ANSWER_AFTER_S)
    err = error_of(await manage(world, "cancel", other["reservation_id"], read_back_token=offer["read_back_token"],
                                user_confirmed=True), "CONFIRMATION_REQUIRED")
    assert err["rule_id"] == S5A  # the token belongs to the first booking
    assert world.store.get_reservation(other["reservation_id"]).status == "confirmed"


async def test_a_free_cancel_needs_no_read_back(world):
    booking = await book(world, "bob", "ember-grill", "18:00", offset=4)  # more than 48 h ahead: free
    body = (await manage(world.as_("bob"), "cancel", booking["reservation_id"])).structuredContent
    assert body["fee_cents"] == 0


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
