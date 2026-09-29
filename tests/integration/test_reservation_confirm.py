"""P1-10: reservation_confirm, approvals and both rungs of the step-up ladder."""

import re
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from ddb_env import ENDPOINT
from fastmcp import Client
from mcp import McpError
from mcp.types import URL_ELICITATION_REQUIRED
from world import World

from server.domain.clock import iso_z
from server.store import keys
from server.tools import stepup

pytestmark = pytest.mark.ddb
URL_BASE = "http://localhost:8080/consent/"


@pytest.fixture
def world(ddb_client, table_name, clock):
    w = World(ddb_client, table_name, ENDPOINT, clock)
    ids = iter(range(1, 100_000))
    w.deps.new_id = lambda: f"id{next(ids):05d}"
    return w


def day(world: World, offset: int = 2) -> str:
    return (world.clock.now().date() + timedelta(days=offset)).isoformat()


async def call(world: World, tool: str, **args):
    async with world.client() as c:
        return await c.call_tool_mcp(tool, args)


async def held(world: World, who: str, venue: str, time: str, party: int = 2, key: str = "key-hold-0001") -> dict:
    """Hold a table as ``who`` and return the hold result."""
    world.as_(who)
    r = await call(world, "availability_check", restaurant_id=venue, date=day(world),
                   time_window=f"{time}-{time}", party_size=party)
    token = r.structuredContent["slots"][0]["slot_token"]
    out = await call(world, "reservation_hold", slot_token=token, idempotency_key=key)
    assert not out.isError, out.structuredContent
    return out.structuredContent


async def confirm(world: World, hold_id: str, key: str = "key-conf-0001"):
    return await call(world, "reservation_confirm", hold_id=hold_id, idempotency_key=key)


def set_approval(world: World, subject_id: str, status: str, **changes):
    approval = world.store.get_approval(subject_id)
    world.store.replace_approval(replace(approval, status=status, decided_at=iso_z(world.clock.now()), **changes))


def counter(world: World, key) -> int:
    item = world.store.get_item(key)
    return int(item["n"]) if item else 0


def error_of(result, code: str) -> dict:
    assert result.isError, result.structuredContent
    assert result.structuredContent["error"] == code, result.structuredContent
    return result.structuredContent


# ---------------------------------------------------------------- inside the mandate
async def test_alice_confirms_inside_her_mandate_at_once(world):
    date = day(world)
    h = await held(world, "alice", "luna-trattoria", "19:00")
    r = await confirm(world, h["hold_id"])
    body = r.structuredContent
    assert not r.isError
    assert re.fullmatch(r"LUN-\d{4}", body["code"]) and body["approved_by_user"] is False
    assert body["booking_card"]["party_size"] == 2 and body["booking_card"]["cancellation"] == "Cancellation is free."
    assert f"Your code is {body['code']}" in body["spoken_summary"] and "7:00 PM" in body["spoken_summary"]
    assert body["terms_snapshot"]["restaurant_id"] == "luna-trattoria"
    assert body["next_step"]["tool"] == "reservation_manage"

    hold = world.store.get_hold(h["hold_id"])
    assert hold.status == "confirmed"
    slot = world.store.get_slot("luna-trattoria", date, "19:00", "T2")
    assert (slot.status, slot.ver, slot.reservation_id) == ("confirmed", 3, body["reservation_id"])
    assert slot.held_until is None
    assert counter(world, keys.active_holds_counter("dev-alice", "luna-trattoria")) == 0  # S1 freed
    assert counter(world, keys.agent_covers_counter("luna-trattoria", date)) == 2  # S2 stays
    res = world.store.get_reservation(body["reservation_id"])
    assert (res.status, res.sub, res.hold_id, res.party_size) == ("confirmed", "dev-alice", h["hold_id"], 2)
    assert world.store.get_item(keys.hold(h["hold_id"])).get("GSI1PK") is None


async def test_repeating_a_confirm_returns_the_same_booking(world):
    h = await held(world, "alice", "luna-trattoria", "19:00")
    first = (await confirm(world, h["hold_id"])).structuredContent
    again = (await confirm(world, h["hold_id"])).structuredContent
    assert again == {**first, "idempotent_replay": True}
    assert len(world.store.reservations_of_user("dev-alice")) == 1


async def test_confirming_an_already_confirmed_hold_with_a_new_key_points_to_the_booking(world):
    h = await held(world, "alice", "luna-trattoria", "19:00")
    first = (await confirm(world, h["hold_id"], "key-conf-0001")).structuredContent
    payload = error_of(await confirm(world, h["hold_id"], "key-conf-0002"), "INVALID_INPUT")
    assert payload["details"]["reservation_id"] == first["reservation_id"]


# ---------------------------------------------------------------- ownership and expiry
async def test_nobody_can_confirm_somebody_elses_hold_or_a_made_up_one(world):
    h = await held(world, "alice", "luna-trattoria", "19:00")
    world.as_("bob")
    error_of(await confirm(world, h["hold_id"]), "NOT_FOUND")
    error_of(await confirm(world, "no-such-hold-id"), "NOT_FOUND")
    assert world.store.get_hold(h["hold_id"]).status == "held"


async def test_an_expired_hold_cannot_be_confirmed_and_is_released(world):
    date = day(world)
    h = await held(world, "alice", "luna-trattoria", "19:00")
    world.clock.advance(minutes=11)
    payload = error_of(await confirm(world, h["hold_id"]), "HOLD_EXPIRED")
    assert payload["next_step"]["tool"] == "availability_check"
    assert world.store.get_hold(h["hold_id"]).status == "expired"
    assert counter(world, keys.active_holds_counter("dev-alice", "luna-trattoria")) == 0
    assert counter(world, keys.agent_covers_counter("luna-trattoria", date)) == 0
    assert world.store.get_slot("luna-trattoria", date, "19:00", "T2").status == "open"
    assert world.store.get_idempotency("dev-alice", "key-conf-0001") is None


# ---------------------------------------------------------------- rung 2: consent_url
async def test_outside_the_mandate_the_agent_gets_a_consent_url_and_nothing_changes(world):
    date = day(world)
    h = await held(world, "bob", "luna-trattoria", "19:00")  # Bob has no mandate
    r = await confirm(world, h["hold_id"])
    payload = error_of(r, "CONSENT_REQUIRED")
    assert payload["consent_url"] == URL_BASE + h["hold_id"]
    assert payload["rule_id"] == "S3_confirm_needs_mandate"
    assert "approve" in payload["hint"] and payload["consent_url"] in payload["hint"]
    assert payload["details"]["terms"]["party_size"] == 2
    assert "same idempotency_key" in payload["next_step"]["why"]
    # the booking is untouched, the key is not remembered, and an approval is waiting
    assert world.store.get_hold(h["hold_id"]).status == "held"
    assert world.store.get_slot("luna-trattoria", date, "19:00", "T2").status == "held"
    assert world.store.get_idempotency("dev-bob", "key-conf-0001") is None
    approval = world.store.get_approval(h["hold_id"])
    assert (approval.status, approval.sub, approval.kind) == ("pending", "dev-bob", "confirm")
    assert approval.expires_at == iso_z(world.clock.now() + timedelta(minutes=15))


async def test_the_user_is_told_in_the_dev_inbox_once(world):
    h = await held(world, "bob", "luna-trattoria", "19:00")
    await confirm(world, h["hold_id"])
    await confirm(world, h["hold_id"])  # the agent asks again while the user has not answered
    inbox = world.store.list_inbox("dev-bob")
    assert len(inbox) == 1
    assert inbox[0]["url"] == URL_BASE + h["hold_id"] and "Luna Trattoria" in inbox[0]["body"]
    assert world.store.list_inbox("dev-alice") == []


async def test_after_approval_the_same_call_confirms_and_uses_the_approval_up(world):
    h = await held(world, "bob", "luna-trattoria", "19:00")
    error_of(await confirm(world, h["hold_id"]), "CONSENT_REQUIRED")
    set_approval(world, h["hold_id"], "approved")  # what the consent page does
    r = await confirm(world, h["hold_id"])  # same key as before
    body = r.structuredContent
    assert not r.isError and body["approved_by_user"] is True
    assert world.store.get_approval(h["hold_id"]).status == "used"
    assert world.store.get_reservation(body["reservation_id"]).status == "confirmed"
    # a repeat still returns the stored result although the approval is now used up
    assert (await confirm(world, h["hold_id"])).structuredContent == {**body, "idempotent_replay": True}


async def test_a_declined_request_is_reported_and_changes_nothing(world):
    h = await held(world, "bob", "luna-trattoria", "19:00")
    error_of(await confirm(world, h["hold_id"]), "CONSENT_REQUIRED")
    set_approval(world, h["hold_id"], "declined")
    payload = error_of(await confirm(world, h["hold_id"]), "CONSENT_DECLINED")
    assert "alternatives" in payload["hint"]
    assert world.store.get_hold(h["hold_id"]).status == "held"


async def test_an_approval_for_another_user_or_other_terms_or_past_its_time_is_worthless(world):
    h = await held(world, "bob", "luna-trattoria", "19:00")
    error_of(await confirm(world, h["hold_id"]), "CONSENT_REQUIRED")
    for tamper in ({"sub": "dev-alice"}, {"terms_hash": "0" * 64}):
        set_approval(world, h["hold_id"], "approved", **tamper)
        error_of(await confirm(world, h["hold_id"]), "CONSENT_REQUIRED")
        # each refused attempt leaves a fresh pending approval for the right user and terms
        fresh = world.store.get_approval(h["hold_id"])
        assert (fresh.status, fresh.sub) == ("pending", "dev-bob")
    set_approval(world, h["hold_id"], "approved")
    world.clock.advance(minutes=16)  # approved, but too late (and the hold has expired too)
    error_of(await confirm(world, h["hold_id"]), "HOLD_EXPIRED")


async def test_an_expired_approval_asks_again(world):
    # A booking whose hold lives longer than the approval window: make the hold last an hour.
    world.deps.settings = replace(world.deps.settings, hold_ttl_s=3600)
    h = await held(world, "bob", "luna-trattoria", "19:00")
    error_of(await confirm(world, h["hold_id"]), "CONSENT_REQUIRED")
    set_approval(world, h["hold_id"], "approved")
    world.clock.advance(minutes=16)
    payload = error_of(await confirm(world, h["hold_id"]), "CONSENT_REQUIRED")
    assert world.store.get_approval(h["hold_id"]).status == "pending"
    assert payload["consent_url"] == URL_BASE + h["hold_id"]


@pytest.mark.parametrize(
    "who,venue,party,why",
    [
        ("alice", "luna-trattoria", 5, "larger than 4"),  # party over the mandate
        ("carol", "ember-grill", 2, "without asking"),  # mandate never auto-confirms
    ],
)
async def test_other_ways_of_leaving_the_mandate_also_need_approval(world, who, venue, party, why):
    h = await held(world, who, venue, "18:00", party=party)
    assert any(why in reason for reason in h["outside_mandate_because"])
    error_of(await confirm(world, h["hold_id"]), "CONSENT_REQUIRED")


# ---------------------------------------------------------------- rung 1: -32042
async def test_a_client_that_can_open_urls_gets_a_real_minus_32042(world):
    h = await held(world, "bob", "luna-trattoria", "19:00")
    world.as_("bob")

    async def never_called(*_args):  # the client declares URL elicitation; the server never asks live
        raise AssertionError("no server-initiated elicitation expected")

    async with Client(world.mcp, elicitation_handler=never_called) as c:
        assert c.initialize_result is not None
        with pytest.raises(McpError) as exc:
            await c.call_tool_mcp("reservation_confirm", {"hold_id": h["hold_id"], "idempotency_key": "key-conf-0001"})
    err = exc.value.error
    assert err.code == URL_ELICITATION_REQUIRED == -32042
    [ask] = err.data["elicitations"]
    assert ask["mode"] == "url" and ask["url"] == URL_BASE + h["hold_id"]
    assert ask["elicitationId"] == h["hold_id"] and "approve" in ask["message"].lower()
    assert world.store.get_approval(h["hold_id"]).status == "pending"
    assert world.store.get_idempotency("dev-bob", "key-conf-0001") is None


def test_only_the_url_capability_counts(monkeypatch):
    from mcp.types import ElicitationCapability

    def context_with(elicitation):
        caps = SimpleNamespace(elicitation=elicitation)
        return SimpleNamespace(session=SimpleNamespace(client_params=SimpleNamespace(capabilities=caps)))

    cases = [
        (None, False),  # no elicitation at all
        (ElicitationCapability(), False),  # empty = form mode only (spec 2025-11-25)
        (ElicitationCapability(form={}), False),
        (ElicitationCapability(url={}), True),
        (ElicitationCapability(form={}, url={}), True),
    ]
    for capability, expected in cases:
        monkeypatch.setattr(stepup, "get_context", lambda c=capability: context_with(c))
        assert stepup.client_supports_url_elicitation() is expected

    monkeypatch.setattr(stepup, "get_context", lambda: SimpleNamespace(session=SimpleNamespace(client_params=None)))
    assert stepup.client_supports_url_elicitation() is False  # stateless request: no initialize seen

    def no_context():
        raise RuntimeError("no active context")

    monkeypatch.setattr(stepup, "get_context", no_context)
    assert stepup.client_supports_url_elicitation() is False


# ---------------------------------------------------------------- the hold is lengthened for the approval (D-022)
async def test_asking_for_approval_lengthens_the_hold_to_the_whole_approval_window(world):
    from server.invariants import assert_invariants

    date = day(world)
    h = await held(world, "bob", "luna-trattoria", "19:00")
    original_until = world.store.get_hold(h["hold_id"]).held_until  # 10 minutes after the hold
    world.clock.advance(minutes=2)
    payload = error_of(await confirm(world, h["hold_id"]), "CONSENT_REQUIRED")

    approval = world.store.get_approval(h["hold_id"])
    hold = world.store.get_hold(h["hold_id"])
    slot = world.store.get_slot("luna-trattoria", date, "19:00", "T2")
    assert approval.expires_at == iso_z(world.clock.now() + timedelta(minutes=15))
    assert hold.held_until == slot.held_until == approval.expires_at > original_until
    assert hold.extended is True
    assert "about 15 minutes" in payload["hint"]
    # listed by its new expiry, not the old one
    assert world.store.expired_holds_on_day("luna-trattoria", date, iso_z(world.clock.now() + timedelta(minutes=14))) == []
    assert_invariants(world.store, iso_z(world.clock.now()))


async def test_the_slow_user_can_now_finish_what_used_to_time_out(world):
    h = await held(world, "bob", "luna-trattoria", "19:00")
    error_of(await confirm(world, h["hold_id"]), "CONSENT_REQUIRED")  # minute 0: link sent
    world.clock.advance(minutes=12)  # minute 12: the old 10-minute hold would be gone
    set_approval(world, h["hold_id"], "approved")
    r = await confirm(world, h["hold_id"])
    assert not r.isError and r.structuredContent["approved_by_user"] is True


async def test_the_extension_is_once_and_bounded(world):
    from server.lifecycle import extend_hold

    date = day(world)
    h = await held(world, "bob", "luna-trattoria", "19:00")
    error_of(await confirm(world, h["hold_id"]), "CONSENT_REQUIRED")
    extended_until = world.store.get_hold(h["hold_id"]).held_until

    world.clock.advance(minutes=5)
    error_of(await confirm(world, h["hold_id"]), "CONSENT_REQUIRED")  # asked again: same approval
    assert world.store.get_hold(h["hold_id"]).held_until == extended_until

    later = iso_z(world.clock.now() + timedelta(minutes=30))
    assert extend_hold(world.store, world.store.get_hold(h["hold_id"]), later, iso_z(world.clock.now())) is False
    assert world.store.get_hold(h["hold_id"]).held_until == extended_until  # never a second time

    world.clock.advance(minutes=11)  # past the extended expiry (15 minutes after the first ask)
    error_of(await confirm(world, h["hold_id"]), "HOLD_EXPIRED")
    assert world.store.get_slot("luna-trattoria", date, "19:00", "T2").status == "open"


async def test_a_booking_that_needs_no_approval_is_not_lengthened(world):
    h = await held(world, "alice", "luna-trattoria", "19:00")
    await confirm(world, h["hold_id"])
    assert world.store.get_hold(h["hold_id"]).extended is False


async def test_an_expired_hold_cannot_be_lengthened(world):
    from server.lifecycle import extend_hold

    h = await held(world, "bob", "luna-trattoria", "19:00")
    world.clock.advance(minutes=11)
    hold = world.store.get_hold(h["hold_id"])
    later = iso_z(world.clock.now() + timedelta(minutes=15))
    assert extend_hold(world.store, hold, later, iso_z(world.clock.now())) is False
    error_of(await confirm(world, h["hold_id"]), "HOLD_EXPIRED")


async def test_a_lengthened_hold_still_blocks_the_slot_for_others_until_it_ends(world):
    date = day(world)
    h = await held(world, "bob", "luna-trattoria", "19:00")
    error_of(await confirm(world, h["hold_id"]), "CONSENT_REQUIRED")
    world.clock.advance(minutes=12)
    world.as_("alice")
    r = await call(world, "availability_check", restaurant_id="luna-trattoria", date=date,
                   time_window="19:00-19:00", party_size=2)
    assert all(s["table_seats"] != 2 for s in r.structuredContent["slots"])  # Bob's T2 is still his
    world.clock.advance(minutes=4)  # now past the extended expiry
    r = await call(world.as_("alice"), "availability_check", restaurant_id="luna-trattoria", date=date,
                   time_window="19:00-19:00", party_size=2)
    assert any(s["table_seats"] == 2 for s in r.structuredContent["slots"])
