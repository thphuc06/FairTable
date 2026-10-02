"""P1-20, P3-10: the harness end to end against DynamoDB Local: real server, real Strands assistant, the diner
answering aloud, an isolated table per trial."""

import asyncio
import dataclasses
from pathlib import Path

import pytest
from ddb_env import ENDPOINT

from eval.env import EvalEnv
from eval.report import summarize, to_markdown
from eval.runner import run_all, run_trial
from eval.tasks import Expect, load_tasks
from server.store import StoreConfig, make_client

pytestmark = pytest.mark.ddb

TASKS = load_tasks(Path(__file__).resolve().parents[2] / "eval" / "tasks")  # the 40-task set
BY_ID = {t.id: t for t in TASKS}


@pytest.fixture(autouse=True)
def ddb_up(ddb_client):
    """Skip these tests when DynamoDB Local is not running (the shared fixture does the check)."""


def tables() -> set[str]:
    client = make_client(StoreConfig("unused", ENDPOINT, "us-east-1"))
    return set(client.list_tables()["TableNames"])


def test_every_task_of_the_set_passes_under_a1_and_leaves_no_table_behind():
    before = tables()
    results = run_all(TASKS, 1)
    assert len(results) == 40
    failed = [(r.task_id, r.trial, r.state_problems, r.violations, r.crashed) for r in results if not r.passed]
    assert failed == []
    assert all(r.violations == [] for r in results)
    assert tables() == before  # every trial's table was deleted

    s = summarize(results, k=1)
    assert (s.pass_at_1, s.pass_hat_k, s.c_out) == (1.0, 1.0, 1.0)
    assert s.blocked == {"NEG": (8, 8), "ADV": (12, 12)}
    assert s.violations == 0 and s.crashed == 0
    assert "validate the harness" in to_markdown(s)


def test_the_run_is_reproducible():
    """Same tasks, same seeds: the same tool calls and the same outcomes."""
    task = BY_ID["rob-alice-retried-hold"]
    first = asyncio.run(run_trial(task, 3))
    second = asyncio.run(run_trial(task, 3))
    same = dataclasses.replace(second, seconds=first.seconds)
    assert first == same and first.tools.count("reservation_hold") == 2


def test_a_wrong_expectation_fails_the_trial_with_a_reason():
    task = dataclasses.replace(BY_ID["happy-luna-alice-two"], expect=Expect(reservations=5, errors=("SLOT_TAKEN",)))
    r = asyncio.run(run_trial(task, 0))
    assert not r.passed and r.crashed is None
    assert any("5 reservation" in p for p in r.state_problems) and any("SLOT_TAKEN" in p for p in r.state_problems)


def test_a_harness_failure_is_a_crash_not_a_pass_or_a_block():
    def broken(**_kwargs):
        raise OSError("no database")

    r = asyncio.run(run_trial(BY_ID["happy-luna-alice-two"], 0, env_factory=broken))
    assert not r.passed and r.crashed == "OSError: no database"
    assert summarize([r], k=1).crashed == 1


def test_the_safety_grader_sees_damage_done_behind_the_agents_back():
    """A double booking created by hand is reported as I2, so a system that allowed it would not pass."""
    from datetime import timedelta

    from eval.graders import safety_grade
    from server.domain.booking import HOLD_HELD, Hold
    from server.domain.clock import iso_z
    from server.store.mappers import hold_to_item

    with EvalEnv() as env:
        day = (env.clock.now().date() + timedelta(days=2)).isoformat()
        slot = env.store.get_slot("luna-trattoria", day, "19:00", "T2")
        assert slot is not None
        assert safety_grade(env.store, iso_z(env.clock.now())) == []
        for who in ("a1", "a2"):  # two live holds on one table, as if the database conditions had failed
            hold = Hold(
                hold_id=who, sub=who, agent_id="alexa-plus-sim", venue_id="luna-trattoria", date=day, time="19:00",
                table_group="T2", party_size=2, status=HOLD_HELD,
                held_until=iso_z(env.clock.now() + timedelta(minutes=5)), created_at=iso_z(env.clock.now()),
                terms={},
            )
            env.store.put_item(hold_to_item(hold))
        codes = {v.code for v in safety_grade(env.store, iso_z(env.clock.now()))}
    assert "I2" in codes
