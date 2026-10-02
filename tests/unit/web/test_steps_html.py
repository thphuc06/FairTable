"""The chat page shows the tool calls behind each answer: proof of what was asked and what the server decided."""

import re

from simulator.events import Step, transcript
from web.pages import chat_page, steps_html

OK = Step("availability_check", {"restaurant_id": "luna-trattoria", "date": "2026-10-02", "party_size": 2,
                                 "time_window": "19:00-19:00"},
          {"spoken_summary": "There is a table at 7 PM."})
HOLD = Step("reservation_hold", {"offer_id": "abcdefghijklmnopqrstuvwxyz0123456789", "idempotency_key": "sim-0-hold-luna"},
            {"hold_id": "h1", "spoken_summary": "Held for ten minutes."})
DENIED = Step("reservation_hold", {"offer_id": "tok"},
              {"error": "POLICY_DENIED", "rule_id": "S4_drop_slots_via_waitlist", "message": "Use the lottery.",
               "next_step": {"tool": "waitlist_watch", "why": "Enter the drop."}}, True)
NEEDS_OK = Step("reservation_confirm", {"hold_id": "h1", "read_back_token": "tok.en", "user_confirmed": False},
                {"error": "CONFIRMATION_REQUIRED", "message": "I need the user's yes first.",
                 "rule_id": "S5c_confirm_needs_an_explicit_yes"}, True)


def test_no_steps_shows_nothing():
    assert steps_html(()) == ""


def test_the_summary_line_lists_each_call_with_its_outcome():
    html = steps_html((OK, HOLD, DENIED, NEEDS_OK))
    summary = re.search(r"<summary>(.*?)</summary>", html).group(1)
    assert summary.startswith("4 steps: ")
    assert summary.count("&#10003;") == 2 and summary.count("&#10007;") == 2
    assert "chip no" in html and "chip wait" in html and "chip ok" in html


def test_a_single_step_is_singular():
    assert "<summary>1 step: " in steps_html((OK,))


def test_the_details_show_the_rule_that_refused_and_the_suggested_next_step():
    html = steps_html((DENIED,))
    assert "POLICY_DENIED by S4_drop_slots_via_waitlist" in html and "Use the lottery." in html
    assert "suggested next step: waitlist_watch" in html and "refused" in html


def test_a_missing_yes_is_shown_as_waiting_not_as_a_failure():
    html = steps_html((NEEDS_OK,))
    assert "waiting for the user" in html and "badge wait" in html and "refused" not in html


def test_arguments_are_shown_but_long_tokens_are_shortened():
    html = steps_html((OK, HOLD, NEEDS_OK))
    assert "restaurant_id=luna-trattoria" in html and "party_size=2" in html
    assert "abcdefghijklmnopqrstuvwxyz0123456789" not in html and "abcdefghijklm" in html  # shortened
    assert "read_back_token" not in html  # the token is never shown on the page


def test_everything_from_the_model_or_the_server_is_escaped():
    evil = Step("<script>alert(1)</script>", {"query": "<img src=x onerror=alert(1)>"},
                {"error": "X<b>", "message": "<script>", "next_step": {"tool": "<i>"}}, True, note="<b>hi</b>")
    html = steps_html((evil,))
    tags = set(re.findall(r"</?([a-zA-Z][a-zA-Z0-9]*)", html))
    assert tags <= {"details", "summary", "span", "ol", "li", "b", "div"}, tags
    assert "<script" not in html and "<img" not in html and "&lt;script&gt;" in html


def test_the_assistants_visible_remark_between_calls_is_shown_as_said_not_as_reasoning():
    html = steps_html((Step("restaurant_search", {}, {"spoken_summary": "Found 3."}, note="Let me look that up."),))
    assert "assistant said: Let me look that up." in html


def test_the_transcript_keeps_the_text_the_assistant_wrote_next_to_a_call():
    messages = [
        {"role": "user", "content": [{"text": "hi"}]},
        {"role": "assistant", "content": [{"text": "One moment."}, {"toolUse": {"toolUseId": "t1", "name": "restaurant_search",
                                                                              "input": {}}}]},
        {"role": "user", "content": [{"toolResult": {"toolUseId": "t1", "status": "success",
                                                      "content": [{"text": "{}"}]}}]},
    ]
    step = next(e for e in transcript(messages) if isinstance(e, Step))
    assert step.note == "One moment."


def test_the_chat_page_puts_the_steps_under_the_assistant_answer_only():
    page = chat_page("alice", [("you", "book", ()), ("assistant", "Booked.", (OK, HOLD))], [], "csrf")
    assert re.findall(r"<div class=.(you|bot).>", page) == ["you", "bot"]
    assert page.count("<details class='steps'>") == 1 and page.index("Booked.") < page.index("<details")


def test_the_chat_page_links_to_the_voice_page_only_when_voice_is_on():
    assert "/voice" not in chat_page("alice", [], [], "csrf")
    assert "href='/voice'" in chat_page("alice", [], [], "csrf", voice=True)
