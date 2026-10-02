"""P1-18, P3-10: personas are pure functions of the conversation, so they are tested with hand-made events."""

from datetime import date

import pytest

from simulator.events import Step, UserSaid, transcript
from simulator.personas import NO_NOISE, Call, Goal, Noise, Say, decide
from simulator.request import parse_date, parse_request, parse_time

LUNA = {"restaurant_id": "luna-trattoria", "name": "Luna Trattoria", "cuisine": "Italian"}
GOAL = Goal(kind="book", date="2026-10-05", time="19:00", party_size=2, restaurant="luna")
SEARCH = Step("restaurant_search", {}, {"restaurants": [LUNA, {"restaurant_id": "ember-grill", "name": "Ember Grill",
                                                              "cuisine": "Steakhouse"}]})
SLOTS = Step("availability_check", {}, {"slots": [{"offer_id": "tok", "time": "19:00", "drop_id": None}]})
SENTENCE = "Luna Trattoria, Monday at 7:00 PM, a table for 2. Cancellation is free. Shall I book it?"
HELD = Step("reservation_hold", {"offer_id": "tok", "idempotency_key": "k"},
            {"hold_id": "h1", "read_back": SENTENCE, "read_back_token": "tok-1", "min_pause_s": 3})
YES, NO = UserSaid("Yes, please."), UserSaid("No, thanks.")
BOOKED = Step("reservation_confirm", {"hold_id": "h1"}, {"spoken_summary": "Booked. Your code is ABC."})
NO_TOKEN = Step("reservation_confirm", {"hold_id": "h1", "user_confirmed": True},
                {"error": "CONFIRMATION_REQUIRED", "message": "The user has not heard these details yet.",
                 "rule_id": "S5a_confirm_needs_read_back",
                 "details": {"read_back": SENTENCE, "read_back_token": "tok-2", "min_pause_s": 3}}, True)
TOO_SOON = Step("reservation_confirm", {"hold_id": "h1", "read_back_token": "tok-1", "user_confirmed": True},
                {"error": "CONFIRMATION_REQUIRED", "message": "I am waiting for the user's answer.",
                 "rule_id": "S5b_confirm_needs_the_diners_answer"}, True)


def run(goal, events, noise=NO_NOISE):
    return decide(goal, [UserSaid("book"), *events], noise)


def test_the_first_move_is_a_search():
    a = run(GOAL, [])
    assert isinstance(a, Call) and a.tool == "restaurant_search" and a.args["party_size"] == 2


def test_the_happy_path_reads_the_details_back_and_waits_for_the_diner():
    assert run(GOAL, [SEARCH]).tool == "availability_check"
    a = run(GOAL, [SEARCH, SLOTS])
    assert a.tool == "reservation_hold" and a.args["offer_id"] == "tok"
    asked = run(GOAL, [SEARCH, SLOTS, HELD])
    assert asked == Say(SENTENCE)  # it asks and ends its turn: it does not confirm on its own
    a = run(GOAL, [SEARCH, SLOTS, HELD, YES])
    assert a.tool == "reservation_confirm" and a.args == {
        "hold_id": "h1", "idempotency_key": a.args["idempotency_key"], "read_back_token": "tok-1", "user_confirmed": True}
    assert run(GOAL, [SEARCH, SLOTS, HELD, YES, BOOKED]) == Say("Booked. Your code is ABC.")


def test_a_no_ends_the_conversation_without_a_confirm():
    a = run(GOAL, [SEARCH, SLOTS, HELD, NO])
    assert isinstance(a, Say) and "won't book" in a.text


def test_anything_but_a_yes_counts_as_no():
    assert isinstance(run(GOAL, [SEARCH, SLOTS, HELD, UserSaid("hmm, maybe")]), Say)
    assert run(GOAL, [SEARCH, SLOTS, HELD, UserSaid("Sure, go ahead")]).tool == "reservation_confirm"


def test_the_confirm_key_is_the_same_each_time_the_same_request_is_sent():
    first = run(GOAL, [SEARCH, SLOTS, HELD, YES]).args["idempotency_key"]
    assert first == decide(GOAL, [UserSaid("book"), SEARCH, SLOTS, HELD, YES]).args["idempotency_key"]


def test_an_eager_assistant_confirms_at_once_and_then_asks_when_refused():
    eager = Goal(**{**GOAL.__dict__, "behaviour": "eager"})
    a = run(eager, [SEARCH, SLOTS, HELD])
    assert a.tool == "reservation_confirm" and a.args["read_back_token"] == "tok-1" and a.args["user_confirmed"] is True
    assert run(eager, [SEARCH, SLOTS, HELD, TOO_SOON]) == Say(SENTENCE)  # refused: now it asks, as it should have
    assert run(eager, [SEARCH, SLOTS, HELD, TOO_SOON, YES]).tool == "reservation_confirm"
    assert isinstance(run(eager, [SEARCH, SLOTS, HELD, TOO_SOON, NO]), Say)


def test_a_forgetful_assistant_leaves_out_the_token_then_asks_again_with_the_new_one():
    forgetful = Goal(**{**GOAL.__dict__, "behaviour": "forgetful"})
    first = run(forgetful, [SEARCH, SLOTS, HELD, YES])
    assert first.tool == "reservation_confirm" and "read_back_token" not in first.args and first.args["user_confirmed"] is True
    assert run(forgetful, [SEARCH, SLOTS, HELD, YES, NO_TOKEN]) == Say(SENTENCE)  # the refusal handed over a new read-back
    again = run(forgetful, [SEARCH, SLOTS, HELD, YES, NO_TOKEN, YES])
    assert again.tool == "reservation_confirm" and again.args["read_back_token"] == "tok-2"


def test_a_confirm_refused_after_the_yes_is_not_retried_forever():
    stuck = Step("reservation_confirm", {"hold_id": "h1"}, {"error": "HOLD_EXPIRED", "message": "The hold ran out."}, True)
    a = run(GOAL, [SEARCH, SLOTS, HELD, YES, stuck])
    assert isinstance(a, Say) and "ran out" in a.text


def test_an_unknown_restaurant_asks_which_one():
    a = run(Goal(kind="book", date="2026-10-05", restaurant="zzz"), [SEARCH])
    assert isinstance(a, Say) and "Luna Trattoria" in a.text


def test_a_tie_between_restaurants_asks_instead_of_guessing():
    a = run(Goal(kind="book", date="2026-10-05", restaurant=""), [SEARCH])
    assert isinstance(a, Say) and a.text.startswith("Which restaurant")


def test_no_free_slot_joins_the_waitlist():
    a = run(GOAL, [SEARCH, Step("availability_check", {}, {"slots": []})])
    assert a.tool == "waitlist_watch" and a.args["restaurant_id"] == "luna-trattoria"


def test_a_rate_limit_is_answered_with_a_watch_not_more_polling():
    limited = Step("availability_check", {}, {"error": "RATE_LIMITED", "message": "Slow down"}, True)
    assert run(GOAL, [SEARCH, limited]).tool == "waitlist_watch"


def test_a_drop_slot_is_entered_through_the_lottery():
    drop = Step("availability_check", {}, {"slots": [{"offer_id": "t", "drop_id": "drop-1"}]})
    a = run(GOAL, [SEARCH, drop])
    assert a.tool == "waitlist_watch" and a.args["drop_id"] == "drop-1"


def test_a_taken_slot_is_rechecked_at_most_three_times():
    taken = Step("reservation_hold", {}, {"error": "SLOT_TAKEN", "message": "Gone."}, True)
    assert run(GOAL, [SEARCH, SLOTS, taken]).tool == "availability_check"
    many = [SEARCH, SLOTS, taken, SLOTS, taken, SLOTS, taken]
    assert isinstance(run(GOAL, many), Say)


def test_a_refusal_is_reported_with_the_hint():
    denied = Step("reservation_hold", {}, {"error": "POLICY_DENIED", "message": "Too many holds.",
                                           "hint": "Confirm one first."}, True)
    a = run(GOAL, [SEARCH, SLOTS, denied])
    assert isinstance(a, Say) and "Too many holds." in a.text and "Confirm one first." in a.text


def test_a_runaway_conversation_is_stopped():
    endless = [Step("availability_check", {}, {"slots": []}) for _ in range(20)]
    assert isinstance(run(GOAL, [SEARCH, *endless]), Say)


def test_noise_is_reproducible_and_can_repeat_a_hold():
    noisy = Noise(seed=7, duplicate_hold=1.0)
    a = run(GOAL, [SEARCH, SLOTS, HELD], noisy)
    assert a.tool == "reservation_hold" and a.args == HELD.args  # same key: a retried delivery
    assert run(GOAL, [SEARCH, SLOTS, HELD], noisy) == a
    assert run(GOAL, [SEARCH, SLOTS, HELD], Noise(seed=7, duplicate_hold=0.0)) == Say(SENTENCE)


def test_different_seeds_give_different_idempotency_keys():
    k1 = run(GOAL, [SEARCH, SLOTS], Noise(seed=1)).args["idempotency_key"]
    k2 = run(GOAL, [SEARCH, SLOTS], Noise(seed=2)).args["idempotency_key"]
    assert k1 != k2 and 8 <= len(k1) <= 128


def test_a_watch_registers_then_reports_status_when_asked_again():
    goal = Goal(kind="watch", date="2026-10-05", restaurant="luna")
    empty = Step("availability_check", {}, {"slots": []})
    watch = Step("waitlist_watch", {}, {"watch_id": "w1", "spoken_summary": "You are on the list."})
    assert run(goal, [SEARCH, empty]).tool == "waitlist_watch"
    assert run(goal, [SEARCH, empty, watch]) == Say("You are on the list.")
    later = decide(goal, [UserSaid("x"), SEARCH, empty, watch, UserSaid("any news?")])
    assert later.tool == "waitlist_status" and later.args == {"watch_id": "w1"}
    status = Step("waitlist_status", {}, {"hold_id": "h9", "spoken_summary": "A table opened.",
                                          "read_back": SENTENCE, "read_back_token": "tok-9", "min_pause_s": 3})
    asked = decide(goal, [UserSaid("x"), SEARCH, empty, watch, UserSaid("news?"), status])
    assert asked == Say(SENTENCE)
    then = decide(goal, [UserSaid("x"), SEARCH, empty, watch, UserSaid("news?"), status, YES])
    assert then.tool == "reservation_confirm" and then.args["hold_id"] == "h9" and then.args["read_back_token"] == "tok-9"


def test_cancel_views_first_then_reads_the_fee_back_and_waits_for_a_yes():
    goal = Goal(kind="cancel", reservation_id="r1")
    view = Step("reservation_manage", {"action": "view"}, {"spoken_summary": "Cancelling costs $25."})
    fee_sentence = "Cancelling your booking at Ember Grill on Monday at 7:00 PM costs $25.00. Shall I go ahead and cancel?"
    fee = Step("reservation_manage", {"action": "cancel", "reservation_id": "r1", "idempotency_key": "kk"},
               {"error": "CONFIRMATION_REQUIRED", "message": "The user has not heard these details yet.",
                "details": {"read_back": fee_sentence, "read_back_token": "ft-1", "min_pause_s": 6}}, True)
    assert run(goal, []).args["action"] == "view"
    assert run(goal, [view]).args["action"] == "cancel"
    assert run(goal, [view, fee]) == Say(fee_sentence)
    retry = decide(goal, [UserSaid("x"), view, fee, YES])
    assert retry.args == {**fee.args, "read_back_token": "ft-1", "user_confirmed": True}
    assert isinstance(decide(goal, [UserSaid("x"), view, fee, NO]), Say)


def test_transcript_pairs_calls_with_results_and_reads_json_text():
    messages = [
        {"role": "user", "content": [{"text": "book me a table"}]},
        {"role": "assistant", "content": [{"toolUse": {"toolUseId": "t1", "name": "restaurant_search",
                                                        "input": {"query": ""}}}]},
        {"role": "user", "content": [{"toolResult": {"toolUseId": "t1", "status": "success",
                                                      "content": [{"text": '{"restaurants": []}'}]}}]},
        {"role": "assistant", "content": [{"toolUse": {"toolUseId": "t2", "name": "reservation_hold", "input": {}}}]},
        {"role": "user", "content": [{"toolResult": {"toolUseId": "t2", "status": "error",
                                                      "structuredContent": {"error": "SLOT_TAKEN"}, "content": []}}]},
    ]
    events = transcript(messages)
    assert events[0] == UserSaid("book me a table")
    assert events[1] == Step("restaurant_search", {"query": ""}, {"restaurants": []}, False)
    assert events[2].error == "SLOT_TAKEN"


TODAY = date(2026, 10, 5)


@pytest.mark.parametrize("text,expected", [
    ("7pm", "19:00"), ("7:30 pm", "19:30"), ("12am", "00:00"), ("12 pm", "12:00"), ("at 19:45", "19:45"),
    ("nothing here", None), ("13pm", None),
])
def test_parse_time(text, expected):
    assert parse_time(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("tomorrow", "2026-10-06"), ("tonight", "2026-10-05"), ("in 3 days", "2026-10-08"),
    ("on 2026-11-01", "2026-11-01"), ("sometime", None),
])
def test_parse_date(text, expected):
    assert parse_date(text, TODAY) == expected


def test_parse_request_reads_a_booking_sentence():
    g = parse_request("Book a table at Luna Trattoria for 4 tomorrow at 7:30pm", TODAY)
    assert g == Goal(kind="book", date="2026-10-06", time="19:30", party_size=4, restaurant="luna trattoria")


def test_parse_request_recognises_a_waitlist_ask_and_needs_a_date():
    assert parse_request("put me on the waitlist at ember grill tomorrow", TODAY).kind == "watch"
    assert parse_request("hello there", TODAY) is None
