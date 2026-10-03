"""P3-4: running the evaluation with a real model (D-064): the words that ask a model to misbehave, the labels."""

from eval.report import Summary, summarize, to_markdown
from eval.runner import NOT_ATTEMPTED, TrialResult, _is_a_state_problem
from simulator.model import is_real, model_label
from simulator.personas import MISBEHAVIOUR_PROMPTS, RETRY_PROMPT, misbehaviour_prompt


def test_a_polite_assistant_gets_no_extra_instruction_and_the_others_get_one_each():
    assert misbehaviour_prompt("polite") == ""
    assert set(MISBEHAVIOUR_PROMPTS) == {"eager", "forgetful", "hot_direct"}
    for behaviour, text in MISBEHAVIOUR_PROMPTS.items():
        assert misbehaviour_prompt(behaviour) == text and "reservation" in text


def test_the_retry_noise_is_asked_for_in_words_only_when_the_task_has_it():
    assert misbehaviour_prompt("polite", 0.0) == ""
    assert misbehaviour_prompt("polite", 0.5) == RETRY_PROMPT
    assert misbehaviour_prompt("eager", 0.5) == MISBEHAVIOUR_PROMPTS["eager"] + " " + RETRY_PROMPT


def test_a_real_model_is_anything_but_the_scripted_one_and_reports_say_which(monkeypatch):
    assert not is_real(None) and not is_real("mock") and is_real("deepseek") and is_real("bedrock")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "us.amazon.nova-lite-v1:0")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")
    assert model_label("bedrock") == "bedrock (us.amazon.nova-lite-v1:0)"
    assert model_label("deepseek") == "deepseek (deepseek-flash)"
    assert model_label("mock") == "mock" and model_label(None) == "mock"


def test_only_a_missing_refusal_can_be_waived_never_a_wrong_end_state():
    assert not _is_a_state_problem([])
    assert not _is_a_state_problem(["expected a refusal by S4_drop_slots_via_waitlist", "expected the error SLOT_TAKEN"])
    assert _is_a_state_problem(["expected 0 reservation(s), found 1"])
    assert _is_a_state_problem(["expected a refusal by S4_drop_slots_via_waitlist", "expected 0 active hold(s), found 1"])
    assert all(p.startswith(NOT_ATTEMPTED) for p in ["expected a refusal by X", "expected the error Y"])


def _result(task, category, passed=True, avoided=False):
    return TrialResult(task, category, 0, passed, avoided=avoided)


def test_the_report_counts_the_misbehaviour_a_real_model_did_not_attempt():
    trials = [_result("a", "ADV", avoided=True), _result("b", "ADV"), _result("c", "ROB", avoided=True),
              _result("d", "HAPPY"), _result("e", "NEG")]
    real = summarize(trials, k=1, provider="deepseek (deepseek-flash)")
    assert (real.not_attempted, real.misbehaviour_trials) == (2, 3)
    assert "| Misbehaviour not attempted | 2/3 |" in to_markdown(real)
    mock = summarize(trials, k=1, provider="mock")
    assert mock.misbehaviour_trials == 0 and "Misbehaviour not attempted" not in to_markdown(mock)


def test_an_old_saved_summary_without_the_new_fields_still_loads():
    old = {"provider": "mock", "config": "A1", "k": 1, "tasks": 1, "trials": 1, "crashed": 0, "pass_at_1": 1.0,
           "pass_hat_k": 1.0, "tasks_in_pass_hat_k": 1, "c_out": 1.0, "violations": 0, "trials_with_violations": 0,
           "blocked": {"NEG": (1, 1), "ADV": (1, 1)}, "false_block_rate": 0.0, "seconds_p50": 0.1, "seconds_p95": 0.2,
           "tool_calls_per_trial": 3.0}
    assert Summary(**old).not_attempted == 0
