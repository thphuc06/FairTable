"""P1-10, P3-10: reservation_confirm after a spoken yes (D-051): the read-back token, the pause and the explicit yes.

The server cannot hear the diner. These tests pin what it can check: the token fits this hold, this user and these
terms (S5a), enough time has passed (S5b), the assistant states that the diner said yes (S5c), and that a refusal
changes nothing."""

import pytest
from ddb_env import ENDPOINT
from flows import ANSWER_AFTER_S, call, confirm_after_read_back, counter, error_of, hold_table
from world import World

from server.store import keys

pytestmark = pytest.mark.ddb
LUNA, EMBER = "luna-trattoria", "ember-grill"
S5A, S5B, S5C = (
    "S5a_confirm_needs_read_back", "S5b_confirm_needs_the_diners_answer", "S5c_confirm_needs_an_explicit_yes",
)


@pytest.fixture
def world(ddb_client, table_name, clock):
    w = World(ddb_client, table_name, ENDPOINT, clock)
    ids = iter(range(1, 100_000))
    w.deps.new_id = lambda: f"id{next(ids):05d}"
    return w


def nothing_changed(world: World, hold: dict, who: str = "alice", venue: str = LUNA) -> None:
    """After a refusal the hold is still held, the slot still belongs to it, and no reservation exists."""
    stored = world.store.get_hold(hold["hold_id"])
    assert stored.status == "held"
    assert counter(world, keys.active_holds_counter(world.store.get_hold(hold["hold_id"]).sub, venue)) == 1
    assert not world.store.reservations_of_user(stored.sub)


# ---------------------------------------------------------------- the right way
async def test_a_confirm_with_the_read_back_the_pause_and_a_yes_books_and_records_how(world):
    h = await hold_table(world, "alice", LUNA, "19:00")
    r = await confirm_after_read_back(world, "alice", h, key="key-conf-0001")
    assert not r.isError, r.structuredContent
    out = r.structuredContent
    assert out["spoken_summary"].startswith("Booked.") and out["code"].startswith("LUN-")
    assert "approved_by_user" not in out
    reservation = world.store.get_reservation(out["reservation_id"])
    assert reservation.confirmation == "spoken" and reservation.read_back_at is not None
    assert reservation.read_back_at <= reservation.created_at  # the read-back came first
    assert world.store.get_hold(h["hold_id"]).status == "confirmed"
    assert counter(world, keys.active_holds_counter(reservation.sub, LUNA)) == 0  # S1 goes down, S2 covers stay


async def test_the_hold_hands_over_what_the_assistant_needs(world):
    h = await hold_table(world, "alice", LUNA, "19:00")
    assert h["read_back"].endswith("Shall I book it?") and h["min_pause_s"] == 3 and h["read_back_token"]
    assert h["read_back"] in h["spoken_summary"]
    assert h["next_step"]["tool"] == "reservation_confirm" and "yes" in h["next_step"]["why"]
    ember = await hold_table(world, "bob", EMBER, "19:00", key="key-hold-0002")
    assert ember["min_pause_s"] == 6 and "$25.00" in ember["read_back"]  # a fee: longer pause, and the fee is said


async def test_repeating_a_confirm_returns_the_same_booking(world):
    h = await hold_table(world, "alice", LUNA, "19:00")
    first = await confirm_after_read_back(world, "alice", h, key="key-conf-0001")
    again = await call(world, "reservation_confirm", hold_id=h["hold_id"], idempotency_key="key-conf-0001")
    assert not again.isError
    assert again.structuredContent["reservation_id"] == first.structuredContent["reservation_id"]
    assert again.structuredContent["idempotent_replay"] is True  # no token needed: nothing is done twice


async def test_confirming_an_already_confirmed_hold_with_a_new_key_points_to_the_booking(world):
    h = await hold_table(world, "alice", LUNA, "19:00")
    first = await confirm_after_read_back(world, "alice", h, key="key-conf-0001")
    second = await confirm_after_read_back(world, "alice", h, key="key-conf-0002")
    err = error_of(second, "INVALID_INPUT")
    assert err["details"]["reservation_id"] == first.structuredContent["reservation_id"]


async def test_nobody_can_confirm_somebody_elses_hold_or_a_made_up_one(world):
    h = await hold_table(world, "alice", LUNA, "19:00")
    world.clock.advance(ANSWER_AFTER_S)
    mine = await call(world.as_("bob"), "reservation_confirm", hold_id=h["hold_id"], idempotency_key="key-conf-0001",
                      read_back_token=h["read_back_token"], user_confirmed=True)
    error_of(mine, "NOT_FOUND")
    error_of(await call(world.as_("alice"), "reservation_confirm", hold_id="nope", idempotency_key="key-conf-0002"),
             "NOT_FOUND")


async def test_an_expired_hold_cannot_be_confirmed_and_is_released(world):
    h = await hold_table(world, "alice", LUNA, "19:00")
    r = await confirm_after_read_back(world, "alice", h, key="key-conf-0001", answer_after=601)
    error_of(r, "HOLD_EXPIRED")
    assert world.store.get_hold(h["hold_id"]).status == "expired"


# ---------------------------------------------------------------- S5a: the terms were not read back
async def test_a_confirm_without_the_token_is_refused_and_hands_over_a_new_read_back(world):
    h = await hold_table(world, "alice", LUNA, "19:00")
    world.clock.advance(ANSWER_AFTER_S)
    r = await call(world.as_("alice"), "reservation_confirm", hold_id=h["hold_id"], idempotency_key="key-conf-0001",
                   user_confirmed=True)
    err = error_of(r, "CONFIRMATION_REQUIRED")
    assert err["rule_id"] == S5A and err["message"] == "The user has not heard these details yet."
    offer = err["details"]
    assert offer["read_back"] == h["read_back"] and offer["read_back_token"] and offer["min_pause_s"] == 3
    nothing_changed(world, h)


async def test_after_that_refusal_the_new_token_works_once_the_diner_has_answered(world):
    h = await hold_table(world, "alice", LUNA, "19:00")
    world.clock.advance(ANSWER_AFTER_S)
    refused = await call(world.as_("alice"), "reservation_confirm", hold_id=h["hold_id"],
                         idempotency_key="key-conf-0001", user_confirmed=True)
    token = refused.structuredContent["details"]["read_back_token"]
    soon = await call(world, "reservation_confirm", hold_id=h["hold_id"], idempotency_key="key-conf-0001",
                      user_confirmed=True, read_back_token=token)
    assert error_of(soon, "CONFIRMATION_REQUIRED")["rule_id"] == S5B  # the new read-back has just been handed over
    world.clock.advance(ANSWER_AFTER_S)
    done = await call(world, "reservation_confirm", hold_id=h["hold_id"], idempotency_key="key-conf-0001",
                      user_confirmed=True, read_back_token=token)
    assert not done.isError, done.structuredContent  # the same key as the refused calls: refusals store nothing


async def test_the_token_of_another_hold_does_not_fit(world):
    a = await hold_table(world, "alice", LUNA, "19:00", key="key-hold-0001")
    b = await hold_table(world, "alice", LUNA, "20:00", key="key-hold-0002")
    r = await confirm_after_read_back(world, "alice", b, key="key-conf-0001", read_back_token=a["read_back_token"])
    assert error_of(r, "CONFIRMATION_REQUIRED")["rule_id"] == S5A
    assert world.store.get_hold(b["hold_id"]).status == "held"


async def test_somebody_elses_token_does_not_fit(world):
    mine = await hold_table(world, "alice", LUNA, "19:00", key="key-hold-0001")
    theirs = await hold_table(world, "bob", LUNA, "19:30", key="key-hold-0002")
    r = await confirm_after_read_back(world, "bob", theirs, key="key-conf-0001",
                                      read_back_token=mine["read_back_token"])
    assert error_of(r, "CONFIRMATION_REQUIRED")["rule_id"] == S5A


@pytest.mark.parametrize("token", ["", "garbage", "a.b", "x" * 3000])
async def test_a_made_up_token_is_the_same_as_none(world, token):
    h = await hold_table(world, "alice", LUNA, "19:00")
    r = await confirm_after_read_back(world, "alice", h, key="key-conf-0001", read_back_token=token)
    assert error_of(r, "CONFIRMATION_REQUIRED")["rule_id"] == S5A


# ---------------------------------------------------------------- S5b: the diner has not had time to answer
async def test_a_confirm_in_the_same_breath_is_refused_and_the_old_token_stays_good(world):
    h = await hold_table(world, "alice", LUNA, "19:00")
    r = await confirm_after_read_back(world, "alice", h, key="key-conf-0001", answer_after=0)
    err = error_of(r, "CONFIRMATION_REQUIRED")
    assert err["rule_id"] == S5B and "details" not in err  # no new token: it would restart the pause
    nothing_changed(world, h)
    done = await confirm_after_read_back(world, "alice", h, key="key-conf-0001")
    assert not done.isError, done.structuredContent


async def test_the_pause_is_three_seconds_and_six_with_a_fee(world):
    free = await hold_table(world, "alice", LUNA, "19:00", key="key-hold-0001")
    fee = await hold_table(world, "alice", EMBER, "19:00", key="key-hold-0002")
    world.clock.advance(2.9)
    assert error_of(await call(world.as_("alice"), "reservation_confirm", hold_id=free["hold_id"],
                               idempotency_key="key-conf-0001", user_confirmed=True,
                               read_back_token=free["read_back_token"]), "CONFIRMATION_REQUIRED")["rule_id"] == S5B
    world.clock.advance(0.2)  # 3.1 s
    assert not (await call(world, "reservation_confirm", hold_id=free["hold_id"], idempotency_key="key-conf-0001",
                           user_confirmed=True, read_back_token=free["read_back_token"])).isError
    # the same 3.1 s is not enough for the restaurant with a fee ...
    assert error_of(await call(world, "reservation_confirm", hold_id=fee["hold_id"], idempotency_key="key-conf-0002",
                               user_confirmed=True, read_back_token=fee["read_back_token"]),
                    "CONFIRMATION_REQUIRED")["rule_id"] == S5B
    world.clock.advance(3)  # 6.1 s
    assert not (await call(world, "reservation_confirm", hold_id=fee["hold_id"], idempotency_key="key-conf-0002",
                           user_confirmed=True, read_back_token=fee["read_back_token"])).isError


# ---------------------------------------------------------------- S5c: no explicit yes
@pytest.mark.parametrize("claim", [False, None])
async def test_without_the_explicit_yes_nothing_is_booked(world, claim):
    h = await hold_table(world, "alice", LUNA, "19:00")
    r = await confirm_after_read_back(world, "alice", h, key="key-conf-0001", user_confirmed=claim)
    err = error_of(r, "CONFIRMATION_REQUIRED")
    assert err["rule_id"] == S5C and err["message"] == "I need the user's yes first."
    nothing_changed(world, h)
    done = await confirm_after_read_back(world, "alice", h, key="key-conf-0001", answer_after=0)
    assert not done.isError  # the diner said yes after all; the pause has long passed


async def test_a_refusal_names_the_first_thing_the_assistant_should_fix(world):
    h = await hold_table(world, "alice", LUNA, "19:00")
    r = await call(world.as_("alice"), "reservation_confirm", hold_id=h["hold_id"], idempotency_key="key-conf-0001")
    assert error_of(r, "CONFIRMATION_REQUIRED")["rule_id"] == S5A  # no token, no pause, no yes: the token comes first


async def test_a_refusal_stores_nothing_and_is_audited(world):
    h = await hold_table(world, "alice", LUNA, "19:00")
    await confirm_after_read_back(world, "alice", h, key="key-conf-0001", user_confirmed=False)
    sub = world.store.get_hold(h["hold_id"]).sub
    assert world.store.get_idempotency(sub, "key-conf-0001") is None
    audit = world.store.list_audit(LUNA, world.clock.now().date().isoformat())
    assert any(a["tool"] == "reservation_confirm" and a["decision"] == "deny" for a in audit)


async def test_the_refusal_text_has_no_internal_words(world):
    h = await hold_table(world, "alice", LUNA, "19:00")
    r = await call(world.as_("alice"), "reservation_confirm", hold_id=h["hold_id"], idempotency_key="key-conf-0001")
    spoken = r.structuredContent["message"].lower()
    assert not any(word in spoken for word in ("token", "hash", "s5a", "rule", "tool", "hold_id", "_"))
