"""P3-1: the 40-task set. The table in eval/generate.py is the source; the YAML files must agree with it."""

from collections import Counter
from pathlib import Path

import pytest

from eval import generate
from eval.tasks import load_tasks

ROOT = Path(__file__).resolve().parents[3]
TASKS = load_tasks(ROOT / "eval" / "tasks")


def test_the_files_agree_with_the_table():
    assert generate.problems(ROOT / "eval" / "tasks") == []


def test_the_set_has_forty_tasks_in_the_planned_split():
    assert len(TASKS) == 40 and len({t.id for t in TASKS}) == 40
    assert dict(Counter(t.category for t in TASKS)) == {"HAPPY": 12, "NEG": 8, "ROB": 8, "ADV": 12}
    assert generate.COUNTS == dict(Counter(s.category for s in generate.SPECS))


def test_every_task_says_what_it_is_for():
    assert all(len(t.description) > 30 for t in TASKS)


def test_nothing_is_booked_in_a_negative_or_adversarial_task_and_an_attack_names_the_rule_that_stops_it():
    assert all(t.expect.reservations == 0 for t in TASKS if t.category in ("NEG", "ADV"))
    assert all(t.expect.refused_by for t in TASKS if t.category == "ADV")
    # a diner who says no or nothing leaves the table held, not booked
    assert all(t.expect.active_holds == 1 for t in TASKS if t.category == "NEG" and t.consent != "approve")


def test_every_legitimate_task_ends_in_a_booking_or_an_entry():
    for t in TASKS:
        if t.legit:
            assert t.expect.reservations == 1 or t.expect.succeeded, t.id


def test_the_tasks_are_varied_enough_to_mean_something():
    assert {t.user for t in TASKS} == {"alice", "bob", "carol"}
    assert {t.goal.restaurant for t in TASKS} == {"luna", "ember", "sakura"}
    assert {t.agent for t in TASKS} == {"alexa-plus-sim", "shady-agent"}
    assert {t.consent for t in TASKS} == {"approve", "decline", "ignore"}
    assert any(t.noise.duplicate_hold == 1.0 for t in TASKS) and any(0 < t.noise.duplicate_hold < 1 for t in TASKS)
    assert {t.goal.behaviour for t in TASKS} == {"polite", "hot_direct", "eager", "forgetful"}
    # no two tasks are the same situation: same diner, place, day, time, party, agent, behaviour, noise and answer
    assert len({(t.user, t.goal.restaurant, t.goal.day_offset, t.goal.time, t.goal.party_size, t.agent, t.goal.behaviour,
                 t.noise.duplicate_hold, t.consent) for t in TASKS}) == 40


def test_ordinary_tasks_stay_off_the_hot_and_drop_days():
    """Day 1 and 8 are Fridays (Sakura's 20:00 seat is a Fair Drop), 2 and 9 are Saturdays (Ember's 19:00 table is hot)."""
    for t in TASKS:
        g = t.goal
        if g.restaurant == "sakura" and g.day_offset in (1, 8) and g.time == "20:00":
            assert t.category in ("ADV", "HAPPY") and (t.expect.refused_by or t.expect.succeeded), t.id
        if g.restaurant == "ember" and g.day_offset in (2, 9) and g.time == "19:00":
            pytest.fail(f"{t.id} books the hot Saturday table")


def test_writing_is_repeatable_and_removes_stale_files(tmp_path):
    (tmp_path / "old-task.yaml").write_text("id: old\n", encoding="utf-8")
    generate.write(tmp_path)
    first = {p.name: p.read_bytes() for p in tmp_path.glob("*.yaml")}
    generate.write(tmp_path)
    assert {p.name: p.read_bytes() for p in tmp_path.glob("*.yaml")} == first
    assert len(first) == 40 and "old-task.yaml" not in first
    assert generate.problems(tmp_path) == []


def test_a_changed_file_is_reported(tmp_path):
    generate.write(tmp_path)
    victim = sorted(tmp_path.glob("*.yaml"))[0]
    victim.write_text(victim.read_text(encoding="utf-8").replace("party_size: 2", "party_size: 3"), encoding="utf-8")
    (tmp_path / "extra.yaml").write_text("id: extra\n", encoding="utf-8")
    found = generate.problems(tmp_path)
    assert any("differs" in f for f in found) and "unexpected file extra.yaml" in found
