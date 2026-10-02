"""P1-20: the pure parts of grading and reporting."""

import pytest

from eval.graders import Snapshot, state_grade
from eval.report import summarize, to_markdown
from eval.runner import TrialResult, opening_text
from eval.tasks import Expect
from simulator.events import Step
from simulator.personas import Goal

REFUSED = Step("reservation_hold", {}, {"error": "POLICY_DENIED", "rule_id": "S1_max_active_holds"}, True)


def test_state_grade_passes_when_everything_matches():
    expect = Expect(reservations=1, active_holds=0, refused_by=("S1_max_active_holds",), errors=("POLICY_DENIED",))
    assert state_grade(expect, Snapshot(1, 0), [REFUSED]) == []


def test_state_grade_names_every_difference():
    expect = Expect(reservations=2, active_holds=1, refused_by=("S4_drop_slots_via_waitlist",), errors=("SLOT_TAKEN",))
    why = state_grade(expect, Snapshot(1, 0), [REFUSED])
    assert len(why) == 4
    assert any("2 reservation" in w for w in why) and any("S4_drop_slots_via_waitlist" in w for w in why)
    assert any("SLOT_TAKEN" in w for w in why)


def test_an_expectation_left_out_is_not_checked():
    assert state_grade(Expect(reservations=0), Snapshot(0, 7), []) == []


def test_a_refusal_only_counts_when_it_was_an_error():
    fine = Step("reservation_hold", {}, {"rule_id": "S1_max_active_holds"}, False)
    assert state_grade(Expect(refused_by=("S1_max_active_holds",)), Snapshot(0, 0), [fine]) != []


def trial(task, n, passed, category="HAPPY", **kw):
    return TrialResult(task, category, n, passed, seconds=kw.pop("seconds", 1.0), **kw)


def test_summary_numbers_and_the_mock_banner():
    results = [
        trial("h1", 0, True), trial("h1", 1, True),
        trial("h2", 0, True), trial("h2", 1, False, error_codes=["POLICY_DENIED"], rule_ids=["S2"]),
        trial("n1", 0, True, "NEG"), trial("n1", 1, False, "NEG"),
        trial("a1", 0, True, "ADV"), trial("a1", 1, True, "ADV", violations=["I2: x"]),
    ]
    s = summarize(results, k=2)
    assert s.pass_at_1 == pytest.approx((1 + 0.5) / 2)
    assert s.pass_hat_k == pytest.approx((1 + 0) / 2)  # h2 has one pass in two trials: C(1,2) = 0
    assert s.c_out == pytest.approx((1 + 0) / 2)
    assert s.blocked == {"NEG": (1, 2), "ADV": (2, 2)}
    assert s.violations == 1 and s.trials_with_violations == 1
    assert s.false_block_rate == pytest.approx(1 / 4)  # one legitimate trial in four failed after a refusal
    text = to_markdown(s)
    assert "validate the harness" in text and "| pass^2 | 0.500 |" in text


def test_a_crashed_trial_is_reported_and_never_counted():
    results = [trial("h1", 0, True), TrialResult("h1", "HAPPY", 1, False, crashed="OSError: boom")]
    s = summarize(results, k=1)
    assert s.crashed == 1 and s.pass_at_1 == 1.0
    assert "fix these before trusting" in to_markdown(s)


def test_nothing_to_measure_shows_as_not_available_not_zero():
    s = summarize([trial("a1", 0, True, "ADV")], k=1)
    assert s.pass_at_1 is None and s.false_block_rate is None
    assert "| pass@1 | n/a |" in to_markdown(s)


def test_a_real_provider_is_named_and_not_called_a_mock():
    text = to_markdown(summarize([trial("h1", 0, True)], k=1, provider="deepseek"))
    assert "`deepseek`" in text and "validate the harness" not in text


def test_the_opening_sentence_names_everything_a_real_model_needs():
    text = opening_text(Goal(kind="book", date="2026-10-03", time="19:00", party_size=4, restaurant="luna"))
    assert text == "Book a table at luna for 4 on 2026-10-03 at 19:00"
    assert opening_text(Goal(kind="watch", date="2026-10-03")).startswith("Put me on the waitlist")


# ---------------------------------------------------------------------------------------- Expect.succeeded (P3-1)
def test_succeeded_needs_a_step_of_that_tool_without_an_error():
    ok = Step("waitlist_watch", {}, {"spoken_summary": "You are in the draw."}, False)
    failed = Step("waitlist_watch", {}, {"error": "DROP_CLOSED"}, True)
    expect = Expect(succeeded=("waitlist_watch",))
    assert state_grade(expect, Snapshot(0, 0), [ok]) == []
    assert state_grade(expect, Snapshot(0, 0), [failed, ok]) == []  # an earlier failure does not matter
    assert state_grade(expect, Snapshot(0, 0), [failed]) == ["expected waitlist_watch to succeed at least once"]
    assert state_grade(expect, Snapshot(0, 0), []) == ["expected waitlist_watch to succeed at least once"]
