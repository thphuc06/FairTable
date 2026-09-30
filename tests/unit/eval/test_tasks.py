"""P1-20: task files are validated strictly, and the starter set in eval/tasks is well-formed."""

from datetime import date
from pathlib import Path

import pytest

from eval.tasks import Task, TaskError, load_tasks, parse_task

TASKS_DIR = Path(__file__).resolve().parents[3] / "eval" / "tasks"
GOOD = {
    "id": "t1", "category": "HAPPY", "user": "alice",
    "goal": {"kind": "book", "restaurant": "luna", "time": "19:00", "party_size": 2},
    "expect": {"reservations": 1},
}


def bad(**changes):
    data = {**GOOD, **changes}
    return {k: v for k, v in data.items() if v is not None}


def test_a_good_task_parses_with_defaults():
    t = parse_task(GOOD)
    assert isinstance(t, Task) and t.agent == "alexa-plus-sim" and t.consent == "approve" and t.legit
    assert t.noise.duplicate_hold == 0 and t.expect.reservations == 1


def test_the_goal_gets_its_date_from_the_run_clock():
    goal = parse_task(GOOD).goal.resolve(date(2026, 10, 1))
    assert goal.date == "2026-10-03" and goal.restaurant == "luna" and goal.party_size == 2


@pytest.mark.parametrize("changes,message", [
    ({"category": "SPICY"}, "category"),
    ({"user": "mallory"}, "user"),
    ({"agent": "gpt"}, "agent"),
    ({"consent": "maybe"}, "consent"),
    ({"id": None}, "missing 'id'"),
    ({"expect": None}, "missing 'expect'"),
    ({"expect": {}}, "must check something"),
    ({"expect": {"reservations": 1, "typo": 2}}, "unknown key"),
    ({"goal": {"kind": "book", "party_size": 0}}, "party_size"),
    ({"goal": {"kind": "fly"}}, "goal.kind"),
    ({"goal": {"kind": "book", "time": "7pm"}}, "goal.time"),
    ({"goal": {"kind": "book", "behaviour": "sneaky"}}, "behaviour"),
    ({"surprise": 1}, "unknown key"),
    ({"noise": {"chaos": 1}}, "unknown key"),
])
def test_mistakes_are_named(changes, message):
    with pytest.raises(TaskError, match=message):
        parse_task(bad(**changes), "file.yaml")


def test_a_task_must_be_a_mapping():
    with pytest.raises(TaskError, match="mapping"):
        parse_task(["nope"])


def test_duplicate_ids_are_refused(tmp_path):
    for name in ("a.yaml", "b.yaml"):
        (tmp_path / name).write_text(
            "id: same\ncategory: HAPPY\nuser: alice\ngoal: {kind: book}\nexpect: {reservations: 1}\n", encoding="utf-8")
    with pytest.raises(TaskError, match="duplicate"):
        load_tasks(tmp_path)


def test_broken_yaml_names_the_file(tmp_path):
    (tmp_path / "broken.yaml").write_text("id: [unclosed", encoding="utf-8")
    with pytest.raises(TaskError, match="broken.yaml"):
        load_tasks(tmp_path)


def test_the_starter_tasks_are_valid_and_cover_every_category():
    tasks = load_tasks(TASKS_DIR)
    assert len(tasks) == 10 and len({t.id for t in tasks}) == 10
    counts = {c: sum(t.category == c for t in tasks) for c in ("HAPPY", "NEG", "ROB", "ADV")}
    assert counts == {"HAPPY": 4, "NEG": 2, "ROB": 2, "ADV": 2}
    assert all(t.description for t in tasks)
    # every adversarial and negative task says which rule or error must stop it
    assert all(t.expect.refused_by or t.expect.errors for t in tasks if t.category in ("NEG", "ADV"))
