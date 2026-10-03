"""P3-4: the harness grades a real model's run the way D-064 says. A stand-in "real" model (the scripted polite one,
with the provider name 'fake') plays a model that is asked to misbehave and declines."""

from dataclasses import replace
from pathlib import Path

import pytest

from eval import runner
from eval.runner import run_trial
from eval.tasks import load_tasks
from simulator.model import ScriptedModel
from simulator.personas import Goal

pytestmark = pytest.mark.ddb
BY_ID = {t.id: t for t in load_tasks(Path(__file__).resolve().parents[2] / "eval" / "tasks")}


@pytest.fixture(autouse=True)
def ddb_up(ddb_client):
    """Skip when DynamoDB Local is not running."""


@pytest.fixture
def polite_stand_in(monkeypatch):
    original = runner.build_model

    def build(provider, *, goal: Goal, noise, today, **kwargs):
        if provider != "fake":
            return original(provider, goal=goal, noise=noise, today=today, **kwargs)
        return ScriptedModel(replace(goal, behaviour="polite"), noise, today)

    monkeypatch.setattr(runner, "build_model", build)


async def test_a_model_that_declines_to_misbehave_passes_and_is_counted_apart(polite_stand_in):
    task = BY_ID["adv-hold-a-fair-drop-seat-directly"]
    real = await run_trial(task, 0, provider="fake")
    assert real.crashed is None and real.passed and real.avoided and real.violations == []
    mock = await run_trial(task, 0, provider="mock")  # the scripted attacker really tries, and the rule S4 refuses
    assert mock.passed and not mock.avoided and "S4_drop_slots_via_waitlist" in mock.rule_ids


async def test_a_model_service_error_is_a_failed_trial_of_the_model_not_a_crash_of_the_harness(monkeypatch):
    def broken(provider, **_):
        raise RuntimeError("EventLoopException: modelStreamErrorException: Model produced invalid sequence as part of ToolUse")

    monkeypatch.setattr(runner, "build_model", broken)
    real = await run_trial(BY_ID["happy-luna-alice-two"], 0, provider="fake")
    assert not real.passed and real.crashed is None and real.state_problems[0].startswith("model error:")
    scripted = await run_trial(BY_ID["happy-luna-alice-two"], 0, provider="mock")  # a scripted run never has this error
    assert scripted.crashed is not None  # so anything unexpected stays a crash


async def test_a_wrong_end_state_is_never_excused(polite_stand_in):
    task = BY_ID["happy-luna-alice-two"]
    task = replace(task, expect=replace(task.expect, reservations=0))  # the diner is expected to end with nothing: wrong
    result = await run_trial(task, 0, provider="fake")
    assert not result.passed and not result.avoided


async def test_a_happy_task_is_graded_the_same_way_with_a_real_model(polite_stand_in):
    result = await run_trial(BY_ID["happy-luna-alice-two"], 0, provider="fake")
    assert result.passed and not result.avoided


@pytest.mark.parametrize("message", [
    "EventLoopException: maximum recursion depth exceeded",
    "ValidationException: An error occurred (ValidationException) when calling the ConverseStream operation: "
    "A conversation must start with a user message. Try again with a conversation that starts with a user message.",
])
def test_a_tool_call_loop_and_a_badly_trimmed_conversation_are_model_errors(message):
    assert runner.is_model_error(message)
    assert not runner.is_model_error("KeyError: 'slots'")  # a bug of ours stays a crash

