"""P3-17: the pure part of the demo preflight (scripts/demo_preflight.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from demo_preflight import STACKS, UP, Facts, judge  # noqa: E402

READY = Facts(
    today="2026-10-16", stacks={n: "UPDATE_COMPLETE" for n in STACKS}, users=4, venues=3, first_slot_day="2026-10-16",
    open_drops=["2026-10-23"], sns_confirmed=True, gateway_target="READY", schedule_state="ENABLED", spend=0.9, cap=5.0,
)


def verdicts(facts):
    return {c.name: c for c in judge(facts)}


def test_a_fully_deployed_and_freshly_seeded_account_is_ready():
    assert all(c.ok for c in judge(READY))


def test_a_missing_stack_is_reported_with_the_deploy_command():
    from dataclasses import replace

    gone = replace(READY, stacks={k: v for k, v in READY.stacks.items() if k != "FairTableRuntime"})
    c = verdicts(gone)["stack FairTableRuntime"]
    assert not c.ok and c.detail == "missing" and c.fix == UP


def test_old_seed_data_is_a_problem_because_the_drop_dates_and_slots_are_in_the_past():
    from dataclasses import replace

    old = replace(READY, first_slot_day="2026-10-03", open_drops=[])
    v = verdicts(old)
    assert not v["slots start today or later"].ok and not v["a Fair Drop is open for entries"].ok
    assert "seed" in v["slots start today or later"].fix


def test_the_things_the_developer_must_do_by_hand_and_the_money_are_checked_too():
    from dataclasses import replace

    v = verdicts(replace(READY, sns_confirmed=False, gateway_target="SYNCHRONIZING", schedule_state=None, spend=4.0))
    assert not v["SNS e-mail confirmed"].ok and not v["Gateway target READY"].ok
    assert not v["workers schedule ENABLED"].ok and not v["budget has room"].ok
