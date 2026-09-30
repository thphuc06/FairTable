"""Task specs: what a simulated diner wants, how their assistant behaves, and what must be true after.

A task is a YAML file. Unknown keys and wrong values are errors, so a typo cannot silently turn into
a task that checks nothing.

    id: happy-luna-alice
    category: HAPPY            # HAPPY | NEG | ROB | ADV
    description: ...
    user: alice                # alice | bob | carol (a seeded diner)
    agent: alexa-plus-sim      # the OAuth client the assistant uses (shady-agent = unverified)
    goal: {kind: book, restaurant: luna, day_offset: 2, time: "19:00", party_size: 2}
    noise: {duplicate_hold: 0.0}
    consent: approve           # what the diner does with an approval link: approve | decline | ignore
    expect: {reservations: 1, active_holds: 0, refused_by: [S2_agent_share_of_covers], errors: [SLOT_TAKEN]}
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from simulator.personas import Goal, Noise

CATEGORIES = ("HAPPY", "NEG", "ROB", "ADV")
CONSENT = ("approve", "decline", "ignore")
USERS = ("alice", "bob", "carol")
AGENTS = ("alexa-plus-sim", "shady-agent")
LEGIT = ("HAPPY", "ROB")  # tasks a careful system must complete (used for pass^k and false blocks)


class TaskError(ValueError):
    """A task file is malformed; the message names the file and the problem."""


@dataclass(frozen=True)
class Expect:
    reservations: int | None = None  # confirmed reservations of the diner at the end
    active_holds: int | None = None  # holds of the diner still alive at the end
    refused_by: tuple[str, ...] = ()  # rule ids that must have refused something during the run
    errors: tuple[str, ...] = ()  # error codes that must have been returned during the run


@dataclass(frozen=True)
class TaskGoal:
    kind: str = "book"
    restaurant: str = ""
    day_offset: int = 2
    time: str = "19:00"
    party_size: int = 2
    behaviour: str = "polite"

    def resolve(self, today: date) -> Goal:
        return Goal(kind=self.kind, date=(today + timedelta(days=self.day_offset)).isoformat(), time=self.time,
                    party_size=self.party_size, restaurant=self.restaurant, behaviour=self.behaviour)


@dataclass(frozen=True)
class Task:
    id: str
    category: str
    description: str
    user: str
    goal: TaskGoal
    expect: Expect
    agent: str = "alexa-plus-sim"
    noise: Noise = field(default_factory=Noise)
    consent: str = "approve"

    @property
    def legit(self) -> bool:
        return self.category in LEGIT


def _only(data: dict[str, Any], allowed: set[str], where: str) -> None:
    extra = set(data) - allowed
    if extra:
        raise TaskError(f"{where}: unknown key(s) {sorted(extra)}")


def _need(cond: bool, where: str, message: str) -> None:
    if not cond:
        raise TaskError(f"{where}: {message}")


def parse_task(data: Any, where: str = "task") -> Task:
    _need(isinstance(data, dict), where, "a task must be a mapping")
    _only(data, {"id", "category", "description", "user", "agent", "goal", "noise", "consent", "expect"}, where)
    for key in ("id", "category", "user", "goal", "expect"):
        _need(key in data, where, f"missing '{key}'")
    _need(data["category"] in CATEGORIES, where, f"category must be one of {CATEGORIES}")
    _need(data["user"] in USERS, where, f"user must be one of {USERS}")
    agent = data.get("agent", "alexa-plus-sim")
    _need(agent in AGENTS, where, f"agent must be one of {AGENTS}")
    consent = data.get("consent", "approve")
    _need(consent in CONSENT, where, f"consent must be one of {CONSENT}")

    g = data["goal"]
    _need(isinstance(g, dict), where, "goal must be a mapping")
    _only(g, {"kind", "restaurant", "day_offset", "time", "party_size", "behaviour"}, f"{where}.goal")
    goal = TaskGoal(**g)
    _need(goal.kind in ("book", "watch"), where, "goal.kind must be book or watch")
    _need(goal.behaviour in ("polite", "hot_direct"), where, "goal.behaviour must be polite or hot_direct")
    _need(isinstance(goal.party_size, int) and goal.party_size > 0, where, "goal.party_size must be a positive integer")
    _need(isinstance(goal.time, str) and len(goal.time) == 5, where, "goal.time must be a quoted 'HH:MM'")

    n = data.get("noise") or {}
    _only(n, {"duplicate_hold"}, f"{where}.noise")
    e = data["expect"]
    _need(isinstance(e, dict), where, "expect must be a mapping")
    _only(e, {"reservations", "active_holds", "refused_by", "errors"}, f"{where}.expect")
    expect = Expect(e.get("reservations"), e.get("active_holds"), tuple(e.get("refused_by", ())),
                    tuple(e.get("errors", ())))
    _need(any([expect.reservations is not None, expect.active_holds is not None, expect.refused_by, expect.errors]),
          where, "expect must check something")
    return Task(
        id=str(data["id"]), category=data["category"], description=str(data.get("description", "")),
        user=data["user"], agent=agent, goal=goal, noise=Noise(seed=0, duplicate_hold=float(n.get("duplicate_hold", 0))),
        consent=consent, expect=expect,
    )


def load_tasks(directory: Path) -> list[Task]:
    """Every ``*.yaml`` file in ``directory``, sorted by file name; ids must be unique."""
    tasks: list[Task] = []
    for path in sorted(Path(directory).glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise TaskError(f"{path.name}: not valid YAML ({e})") from e
        tasks.append(parse_task(data, path.name))
    ids = [t.id for t in tasks]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise TaskError(f"duplicate task id(s): {dupes}")
    return tasks
