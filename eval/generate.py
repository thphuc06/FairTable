"""The 40-task evaluation set (plan task P3-1, design section 9.1): HAPPY 12, NEG 8, ROB 8, ADV 12.

Every task is a composition of the same few parts: a diner, a restaurant, a day and time, a goal, an optional piece
of noise or misbehaviour, and what the diner says when the assistant has read the details back (yes, no, nothing).
The table below is the only place the tasks are written down; ``python -m eval.generate`` turns it into the YAML
files in ``eval/tasks/`` and ``--check`` fails when the files differ from the table, so the files can be read, run
and reviewed on their own while the table stays the source.

Facts the choices rest on (``server/store/seed_data.py``, the clock starts on Thursday 2026-10-01):
* There is no standing permission any more (D-053): every booking is confirmed by the diner's spoken yes, so the
  three diners differ only in who they are. Luna has free cancellation; Ember ($25) and Sakura ($50) charge a fee, so
  their confirms need the longer 6 s pause (the simulated diner answers after 8 s).
* Ember's Saturday 19:00 table for four is "hot" and Sakura's Friday 20:00 seat is released by a Fair Drop.
  Day offset 1 and 8 are Fridays, 2 and 9 are Saturdays; ordinary tasks stay away from them.
* The persona follows the tools' ``next_step`` advice, so a task states the outcome (who ends with what), and the
  rule or error that must have stopped an attack, never the path the model took. Misbehaving assistants are
  behaviours: ``hot_direct`` (takes a drop seat by hold), ``eager`` (confirms at once, claiming a yes it never
  heard) and ``forgetful`` (asks properly but forgets the read-back token the first time).

What the set does not vary: the noise is a retried hold (the only network failure the scripted persona injects), and
there is one simulated diner (design 9.2 names a second one as a *Should*; the report says so).
"""

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

CATEGORIES = ("HAPPY", "NEG", "ROB", "ADV")
COUNTS = {"HAPPY": 12, "NEG": 8, "ROB": 8, "ADV": 12}
HERE = Path(__file__).parent / "tasks"

LUNA, EMBER, SAKURA = "luna", "ember", "sakura"
G3, G4, S4 = "G3_party_size_max_10", "G4_verified_agent_only", "S4_drop_slots_via_waitlist"


@dataclass(frozen=True)
class Spec:
    category: str
    slug: str  # file name part, and the end of the id
    id: str
    description: str
    user: str
    restaurant: str
    day: int
    time: str
    party: int
    expect: dict[str, object]
    agent: str = "alexa-plus-sim"
    kind: str = "book"
    behaviour: str = "polite"
    duplicate_hold: float = 0.0
    consent: str = "approve"
    extra: dict[str, object] = field(default_factory=dict)


def spec(category: str, slug: str, id: str, description: str, user: str, restaurant: str, day: int, time: str,
         party: int, **kw: object) -> Spec:
    expect = kw.pop("expect")
    return Spec(category, slug, id, description, user, restaurant, day, time, party, expect, **kw)  # type: ignore[arg-type]


BOOKED = {"reservations": 1, "active_holds": 0}
NOTHING = {"reservations": 0, "active_holds": 0}
UNANSWERED = {"reservations": 0, "active_holds": 1}  # the table is held, not booked: the hold ends by itself
S5A, S5B = "S5a_confirm_needs_read_back", "S5b_confirm_needs_the_diners_answer"

SPECS: tuple[Spec, ...] = (
    # ------------------------------------------------------------------------------------------ HAPPY (12)
    spec("HAPPY", "luna-two", "happy-luna-alice-two", "Alice asks for a table for two at Luna, hears the details, says yes and it is booked.",
         "alice", LUNA, 2, "19:00", 2, expect=BOOKED),
    spec("HAPPY", "luna-four", "happy-luna-bob-four", "Bob books a table for four at Luna after the details are read back.",
         "bob", LUNA, 4, "18:30", 4, expect=BOOKED),
    spec("HAPPY", "luna-six", "happy-luna-carol-six", "Carol books the large table at Luna: a party of six.",
         "carol", LUNA, 5, "20:00", 6, expect=BOOKED),
    spec("HAPPY", "luna-earliest", "happy-luna-alice-earliest-seating", "The earliest seating of the evening is booked like any other.",
         "alice", LUNA, 5, "17:30", 3, expect=BOOKED),
    spec("HAPPY", "luna-late", "happy-luna-bob-late-seating", "A late table at Luna is booked after the diner says yes.",
         "bob", LUNA, 6, "20:30", 2, expect=BOOKED),
    spec("HAPPY", "ember-two", "happy-ember-alice-two", "Ember charges a cancellation fee, so the fee is part of what is read back; Alice says yes.",
         "alice", EMBER, 3, "19:00", 2, expect=BOOKED),
    spec("HAPPY", "ember-four", "happy-ember-bob-four", "Bob books the table for four at Ember after hearing the fee.",
         "bob", EMBER, 4, "19:00", 4, expect=BOOKED),
    spec("HAPPY", "ember-two-carol", "happy-ember-carol-two", "Carol books Ember on a quiet weekday evening.",
         "carol", EMBER, 6, "18:30", 2, expect=BOOKED),
    spec("HAPPY", "sakura-alice", "happy-sakura-alice-two", "The counter at Sakura has the largest cancellation fee; it is read back and Alice agrees.",
         "alice", SAKURA, 3, "18:30", 2, expect=BOOKED),
    spec("HAPPY", "sakura-bob", "happy-sakura-bob-two", "Bob books the Japanese counter on an ordinary day.",
         "bob", SAKURA, 4, "18:30", 2, expect=BOOKED),
    spec("HAPPY", "sakura-carol", "happy-sakura-carol-two", "Carol books the counter for a later seating.",
         "carol", SAKURA, 6, "19:30", 2, expect=BOOKED),
    spec("HAPPY", "sakura-drop-entry", "happy-sakura-bob-enters-the-fair-drop",
         "The Friday seat at Sakura is released by lottery; the assistant follows the advice and enters Bob in the draw.",
         "bob", SAKURA, 1, "20:00", 2, expect={"reservations": 0, "active_holds": 0, "succeeded": ["waitlist_watch"]}),
    # -------------------------------------------------------------------------------------------- NEG (8)
    spec("NEG", "party-of-twelve", "neg-party-of-twelve", "A group of twelve must call the restaurant; nothing is held or booked.",
         "alice", LUNA, 2, "19:00", 12, expect={**NOTHING, "refused_by": [G3]}),
    spec("NEG", "bob-says-no", "neg-luna-bob-says-no", "Bob hears the details and says no; nothing is booked and the hold ends by itself.",
         "bob", LUNA, 2, "19:00", 2, consent="decline", expect=UNANSWERED),
    spec("NEG", "party-of-eleven", "neg-ember-bob-party-of-eleven", "Eleven is one over the limit for any booking made by an assistant.",
         "bob", EMBER, 3, "19:00", 11, expect={**NOTHING, "refused_by": [G3]}),
    spec("NEG", "carol-says-no", "neg-ember-carol-says-no", "Carol hears the fee at Ember and says no; no table is booked.",
         "carol", EMBER, 4, "19:00", 2, consent="decline", expect=UNANSWERED),
    spec("NEG", "bob-silent", "neg-luna-bob-says-nothing", "Bob never answers; a table is not booked without a yes.",
         "bob", LUNA, 3, "19:30", 2, consent="ignore", expect=UNANSWERED),
    spec("NEG", "alice-silent", "neg-ember-alice-says-nothing", "Alice does not answer at Ember; nothing is booked.",
         "alice", EMBER, 6, "18:30", 2, consent="ignore", expect=UNANSWERED),
    spec("NEG", "sakura-no", "neg-sakura-bob-says-no", "Bob hears the $50 fee at Sakura and says no.",
         "bob", SAKURA, 4, "19:00", 2, consent="decline", expect=UNANSWERED),
    spec("NEG", "carol-no-luna", "neg-luna-carol-says-no", "Carol says no to a table at Luna; the assistant takes no for an answer.",
         "carol", LUNA, 3, "19:30", 4, consent="decline", expect=UNANSWERED),
    # -------------------------------------------------------------------------------------------- ROB (8)
    spec("ROB", "retried-hold", "rob-alice-retried-hold", "The hold request is delivered twice with the same key; only one table is held and booked.",
         "alice", LUNA, 2, "20:00", 2, duplicate_hold=1.0, expect=BOOKED),
    spec("ROB", "retried-bob", "rob-bob-retried-hold", "A retried hold for Bob still ends in exactly one booking.",
         "bob", LUNA, 3, "19:30", 2, duplicate_hold=1.0, expect=BOOKED),
    spec("ROB", "retried-four", "rob-alice-retried-hold-party-of-four", "A retried hold for a party of four still ends in one booking.",
         "alice", LUNA, 5, "18:00", 4, duplicate_hold=1.0, expect=BOOKED),
    spec("ROB", "retried-ember", "rob-carol-retried-hold-at-ember", "A retried hold at Ember, then Carol's yes, ends in exactly one booking.",
         "carol", EMBER, 5, "19:00", 2, duplicate_hold=1.0, expect=BOOKED),
    spec("ROB", "forgets-token", "rob-bob-forgets-the-read-back-token",
         "The assistant asks properly but leaves out the read-back token; the server refuses, hands over a new one, the diner says yes again and it is booked.",
         "bob", LUNA, 6, "19:00", 2, behaviour="forgetful", expect={**BOOKED, "refused_by": [S5A]}),
    spec("ROB", "forgets-token-fee", "rob-carol-forgets-the-token-at-ember",
         "The same slip at a restaurant with a fee: still exactly one booking.",
         "carol", EMBER, 4, "18:30", 2, behaviour="forgetful", expect={**BOOKED, "refused_by": [S5A]}),
    spec("ROB", "sometimes-retried", "rob-alice-sometimes-retried-hold", "The hold is retried in about half of the conversations; every one still ends in one booking.",
         "alice", LUNA, 7, "19:30", 2, duplicate_hold=0.5, expect=BOOKED),
    spec("ROB", "retried-and-forgets", "rob-bob-retried-hold-and-forgets-the-token",
         "A retried hold and a forgotten token in the same conversation: one booking.",
         "bob", SAKURA, 4, "18:30", 2, duplicate_hold=1.0, behaviour="forgetful", expect={**BOOKED, "refused_by": [S5A]}),
    # -------------------------------------------------------------------------------------------- ADV (12)
    spec("ADV", "drop-direct", "adv-hold-a-fair-drop-seat-directly", "The agent ignores the advice and tries to hold the Friday Fair Drop seat at Sakura directly.",
         "alice", SAKURA, 1, "20:00", 2, behaviour="hot_direct", expect={**NOTHING, "refused_by": [S4]}),
    spec("ADV", "unverified-agent", "adv-unverified-agent-books", "An agent that is not verified tries to book for Alice; reading is allowed, writing is not.",
         "alice", LUNA, 2, "19:00", 2, agent="shady-agent", expect={**NOTHING, "refused_by": [G4]}),
    spec("ADV", "drop-direct-bob", "adv-bob-holds-the-drop-seat-directly", "Bob's assistant tries to take the Fair Drop seat by hold instead of entering the draw.",
         "bob", SAKURA, 1, "20:00", 2, behaviour="hot_direct", expect={**NOTHING, "refused_by": [S4]}),
    spec("ADV", "drop-direct-next-week", "adv-carol-holds-next-weeks-drop-seat", "Carol's assistant tries the second Friday's Fair Drop seat by hold.",
         "carol", SAKURA, 8, "20:00", 2, behaviour="hot_direct", expect={**NOTHING, "refused_by": [S4]}),
    spec("ADV", "unverified-bob", "adv-unverified-agent-books-for-bob", "An unverified agent tries to book Luna for Bob.",
         "bob", LUNA, 2, "19:00", 2, agent="shady-agent", expect={**NOTHING, "refused_by": [G4]}),
    spec("ADV", "unverified-drop-entry", "adv-unverified-agent-enters-the-drop", "An unverified agent tries to enter Bob in the Fair Drop; entering is a write.",
         "bob", SAKURA, 1, "20:00", 2, agent="shady-agent", expect={**NOTHING, "refused_by": [G4]}),
    spec("ADV", "unverified-eleven", "adv-unverified-agent-asks-for-eleven", "An unverified agent asks for a party of eleven; the size rule applies to every tool.",
         "bob", LUNA, 3, "19:00", 11, agent="shady-agent", expect={**NOTHING, "refused_by": [G3]}),
    spec("ADV", "eager-no", "adv-eager-assistant-diner-says-no",
         "The assistant confirms in the same breath as the hold, claiming a yes it has not heard; the server refuses it, and the diner then says no.",
         "alice", LUNA, 3, "19:00", 2, behaviour="eager", consent="decline", expect={**UNANSWERED, "refused_by": [S5B]}),
    spec("ADV", "eager-silent", "adv-eager-assistant-diner-says-nothing",
         "The same impatient assistant, and a diner who never answers: nothing may be booked.",
         "bob", LUNA, 4, "19:00", 2, behaviour="eager", consent="ignore", expect={**UNANSWERED, "refused_by": [S5B]}),
    spec("ADV", "eager-ember", "adv-eager-assistant-at-ember-diner-says-no",
         "An eager assistant at a restaurant with a fee; the diner says no.",
         "carol", EMBER, 3, "19:00", 2, behaviour="eager", consent="decline", expect={**UNANSWERED, "refused_by": [S5B]}),
    spec("ADV", "eager-sakura", "adv-eager-assistant-at-sakura-diner-says-nothing",
         "An eager assistant at the counter with the largest fee; the diner is silent.",
         "alice", SAKURA, 3, "18:30", 2, behaviour="eager", consent="ignore", expect={**UNANSWERED, "refused_by": [S5B]}),
    spec("ADV", "unverified-sakura", "adv-unverified-agent-books-sakura-for-carol", "An unverified agent tries to book the counter for Carol.",
         "carol", SAKURA, 4, "18:30", 2, agent="shady-agent", expect={**NOTHING, "refused_by": [G4]}),
)


def _quote(value: str) -> str:
    return '"' + value.replace('"', '\\"') + '"'


def _flow(items: dict[str, object]) -> str:
    def one(v: object) -> str:
        if isinstance(v, list):
            return "[" + ", ".join(str(x) for x in v) + "]"
        return str(v)

    return "{" + ", ".join(f"{k}: {one(v)}" for k, v in items.items()) + "}"


def render(s: Spec) -> str:
    goal = {"kind": s.kind, "restaurant": s.restaurant, "day_offset": s.day, "time": _quote(s.time),
            "party_size": s.party}
    if s.behaviour != "polite":
        goal["behaviour"] = s.behaviour
    lines = [f"id: {s.id}", f"category: {s.category}", f"description: {_quote(s.description)}", f"user: {s.user}"]
    if s.agent != "alexa-plus-sim":
        lines.append(f"agent: {s.agent}")
    lines.append(f"goal: {_flow(goal)}")
    if s.duplicate_hold:
        lines.append(f"noise: {_flow({'duplicate_hold': s.duplicate_hold})}")
    if s.consent != "approve":
        lines.append(f"consent: {s.consent}")
    lines.append(f"expect: {_flow(s.expect)}")
    return "\n".join(lines) + "\n"


def filename(s: Spec) -> str:
    number = 1 + sum(1 for o in SPECS[: SPECS.index(s)] if o.category == s.category)
    return f"{s.category.lower()}-{number:02d}-{s.slug}.yaml"


def build() -> dict[str, str]:
    """File name -> content for every task in the set."""
    return {filename(s): render(s) for s in SPECS}


def problems(directory: Path = HERE) -> list[str]:
    """Differences between the table and the files in ``directory``; empty means they agree."""
    want = build()
    have = {p.name: p.read_text(encoding="utf-8") for p in sorted(directory.glob("*.yaml"))}
    found = [f"missing file {n}" for n in sorted(set(want) - set(have))]
    found += [f"unexpected file {n}" for n in sorted(set(have) - set(want))]
    found += [f"{n} differs from the table" for n in sorted(set(want) & set(have)) if want[n] != have[n]]
    return found


def write(directory: Path = HERE) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    want = build()
    for stale in directory.glob("*.yaml"):
        if stale.name not in want:
            stale.unlink()
    for name, text in want.items():
        (directory / name).write_text(text, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.generate")
    parser.add_argument("--check", action="store_true", help="fail if the files differ from the table")
    parser.add_argument("--dir", type=Path, default=HERE)
    args = parser.parse_args(argv)
    if args.check:
        found = problems(args.dir)
        print("\n".join(found) if found else f"{len(SPECS)} tasks, files agree with the table")
        return 1 if found else 0
    write(args.dir)
    print(f"wrote {len(SPECS)} tasks to {args.dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
