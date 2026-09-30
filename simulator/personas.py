"""Scripted personas: what a booking assistant does next, decided only from what has happened so far.

``decide(goal, events, noise)`` is a pure function of the conversation (no clock, no I/O, no hidden
state), so a persona can be replayed, tested and used by the mock model and the eval harness alike.
Every choice that looks random comes from ``noise.seed`` and the number of steps taken, so the same
seed always gives the same behaviour.

The personas follow the tools' own ``next_step`` advice. Misbehaving agents (for the ADV tasks) are
variations set through ``Goal.behaviour``.
"""

import random
from dataclasses import dataclass
from typing import Any

from simulator.events import Event, Step, UserSaid

MAX_STEPS_PER_TURN = 14
MAX_AVAILABILITY_CHECKS = 3
APPROVAL_ERRORS = ("CONSENT_REQUIRED", "FEE_APPLIES")


@dataclass(frozen=True)
class Goal:
    kind: str  # "book" | "watch" | "cancel"
    date: str = ""
    time: str = "19:00"
    party_size: int = 2
    restaurant: str = ""  # words from the name or cuisine, matched against search results
    restaurant_id: str | None = None
    reservation_id: str | None = None  # for "cancel"
    behaviour: str = "polite"  # "polite" | "hot_direct" (tries a drop-controlled table by hold)


@dataclass(frozen=True)
class Noise:
    seed: int = 0
    duplicate_hold: float = 0.0  # chance of sending the hold twice with the same key (a network retry)


NO_NOISE = Noise()


@dataclass(frozen=True)
class Call:
    tool: str
    args: dict[str, Any]


@dataclass(frozen=True)
class Say:
    text: str


Action = Call | Say


def _steps(events: list[Event]) -> list[Step]:
    return [e for e in events if isinstance(e, Step)]


def _pos(steps: list[Step], tool: str) -> int:
    """Index of the latest step of this tool, or -1."""
    return next((i for i in range(len(steps) - 1, -1, -1) if steps[i].tool == tool), -1)


def _get(steps: list[Step], tool: str) -> Step | None:
    i = _pos(steps, tool)
    return steps[i] if i >= 0 else None


def _key(noise: Noise, what: str, goal: Goal) -> str:
    """The same request always gets the same key (a retry after approval must repeat it); a request that
    differs in restaurant, day, time or party size gets its own, or the server rightly calls it a conflict."""
    where = (goal.restaurant_id or goal.restaurant or "x").replace(" ", "")
    return f"sim-{noise.seed}-{what}-{where}-{goal.date}-{goal.time.replace(':', '')}-p{goal.party_size}"[:100]


def _rng(noise: Noise, n: int) -> random.Random:
    return random.Random(f"{noise.seed}:{n}")


def _fail(step: Step) -> Say:
    """Report a refusal to the user in the tool's own words, with its advice."""
    r = step.result
    text = str(r.get("message") or "That did not work.")
    for extra in (r.get("hint"), (r.get("next_step") or {}).get("why")):
        if extra:
            text += f" {extra}"
    return Say(text)


def _asked_for_approval(step: Step) -> Say:
    text = str(step.result.get("message") or "I need your approval.")
    return Say(f"{text} Approve here: {step.result.get('consent_url', '')} Tell me when you have answered.")


def _user_spoke_after(events: list[Event], step: Step) -> bool:
    seen = False
    for e in events:
        if e is step:
            seen = True
        elif seen and isinstance(e, UserSaid):
            return True
    return False


def _pick_restaurant(goal: Goal, search: Step) -> dict[str, Any] | None:
    found = search.result.get("restaurants") or []
    if goal.restaurant_id:
        return next((r for r in found if r.get("restaurant_id") == goal.restaurant_id), None)
    words = goal.restaurant.lower().split()
    if not words:
        return None
    scored = [(sum(w in f"{r.get('name', '')} {r.get('cuisine', '')}".lower() for w in words), r) for r in found]
    best = max((s for s, _ in scored), default=0)
    winners = [r for s, r in scored if s == best]
    return winners[0] if best > 0 and len(winners) == 1 else None  # a tie is not a choice: ask


def decide(goal: Goal, events: list[Event], noise: Noise = NO_NOISE) -> Action:
    steps = _steps(events)
    this_turn = 0
    for e in reversed(events):
        if isinstance(e, UserSaid):
            break
        this_turn += 1
    if this_turn > MAX_STEPS_PER_TURN:
        return Say("I could not finish this. Please try again or call the restaurant.")
    if goal.kind == "cancel":
        return _cancel(goal, events, steps, noise)
    return _book(goal, events, steps, noise)


def _availability_call(goal: Goal, rid: str) -> Call:
    return Call("availability_check", {"restaurant_id": rid, "date": goal.date,
                                       "time_window": f"{goal.time}-{goal.time}", "party_size": goal.party_size})


def _watch_call(goal: Goal, rid: str, noise: Noise) -> Call:
    return Call("waitlist_watch", {
        "idempotency_key": _key(noise, "watch", goal), "restaurant_id": rid, "date": goal.date,
        "time_window": "17:00-22:00", "party_size": goal.party_size,
    })


def _book(goal: Goal, events: list[Event], steps: list[Step], noise: Noise) -> Action:
    search = _get(steps, "restaurant_search")
    if search is None:
        return Call("restaurant_search", {"query": "", "date": goal.date, "party_size": goal.party_size})
    if search.is_error:
        return _fail(search)
    venue = _pick_restaurant(goal, search)
    if venue is None:
        names = ", ".join(r["name"] for r in search.result.get("restaurants", []))
        return Say(f"Which restaurant? I can book at: {names}." if names else "I found no restaurants.")
    rid = venue["restaurant_id"]

    confirm = _get(steps, "reservation_confirm")
    if confirm is not None and not confirm.is_error:
        return Say(str(confirm.result.get("spoken_summary") or "Your table is booked."))
    watch = _get(steps, "waitlist_watch")
    if goal.kind == "watch" and watch is not None:
        return _after_watch(goal, events, steps, noise, watch)
    if watch is not None and _pos(steps, "waitlist_watch") > _pos(steps, "availability_check"):
        return _fail(watch) if watch.is_error else Say(str(watch.result.get("spoken_summary")))

    avail_pos, hold_pos = _pos(steps, "availability_check"), _pos(steps, "reservation_hold")
    hold = steps[hold_pos] if hold_pos >= 0 else None
    checks = sum(s.tool == "availability_check" for s in steps)
    if avail_pos < 0 or (hold is not None and hold.error == "SLOT_TAKEN" and hold_pos > avail_pos):
        if checks >= MAX_AVAILABILITY_CHECKS:
            return _fail(hold) if hold is not None else Say("I could not find a table.")
        return _availability_call(goal, rid)
    avail = steps[avail_pos]
    if avail.is_error:
        return _watch_call(goal, rid, noise) if avail.error == "RATE_LIMITED" else _fail(avail)
    slots = avail.result.get("slots") or []
    if not slots:
        return _watch_call(goal, rid, noise)
    slot = slots[0]
    if slot.get("drop_id") and goal.behaviour != "hot_direct":
        return Call("waitlist_watch", {"idempotency_key": _key(noise, "drop", goal), "drop_id": slot["drop_id"],
                                       "party_size": goal.party_size})
    if goal.kind == "watch":
        return Say(f"A table is free right now at {venue['name']}, so there is nothing to wait for.")

    if hold is None:
        return Call("reservation_hold", {"slot_token": slot["slot_token"], "idempotency_key": _key(noise, "hold", goal)})
    if hold.is_error:
        return _fail(hold)
    held = sum(s.tool == "reservation_hold" and not s.is_error for s in steps)
    if held == 1 and _rng(noise, len(steps)).random() < noise.duplicate_hold:
        return Call("reservation_hold", dict(hold.args))  # a retried delivery: must not double-book
    if confirm is None or (confirm.error in APPROVAL_ERRORS and _user_spoke_after(events, confirm)):
        return Call("reservation_confirm", {"hold_id": hold.result.get("hold_id"),
                                            "idempotency_key": _key(noise, "confirm", goal)})
    return _asked_for_approval(confirm) if confirm.error in APPROVAL_ERRORS else _fail(confirm)


def _after_watch(goal: Goal, events: list[Event], steps: list[Step], noise: Noise, watch: Step) -> Action:
    if watch.is_error:
        return _fail(watch)
    status = _get(steps, "waitlist_status")
    if status is None and not _user_spoke_after(events, watch):
        return Say(str(watch.result.get("spoken_summary")))  # registered; the user asks again later
    if status is None or _user_spoke_after(events, status):
        return Call("waitlist_status", {"watch_id": watch.result.get("watch_id")})
    hold_id = status.result.get("hold_id")
    if not hold_id:
        return Say(str(status.result.get("spoken_summary") or "Still waiting."))
    confirm = _get(steps, "reservation_confirm")
    if confirm is None:
        return Call("reservation_confirm", {"hold_id": hold_id, "idempotency_key": _key(noise, "confirm", goal)})
    if confirm.is_error:
        return _asked_for_approval(confirm) if confirm.error in APPROVAL_ERRORS else _fail(confirm)
    return Say(str(confirm.result.get("spoken_summary") or "Your table is booked."))


def _cancel(goal: Goal, events: list[Event], steps: list[Step], noise: Noise) -> Action:
    if not goal.reservation_id:
        return Say("Which booking should I cancel?")
    view = next((s for s in steps if s.args.get("action") == "view"), None)
    if view is None:
        return Call("reservation_manage", {"action": "view", "reservation_id": goal.reservation_id})
    if view.is_error:
        return _fail(view)
    cancels = [s for s in steps if s.args.get("action") == "cancel"]
    if not cancels:
        return Call("reservation_manage", {"action": "cancel", "reservation_id": goal.reservation_id,
                                           "idempotency_key": _key(noise, "cancel", goal)})
    last = cancels[-1]
    if not last.is_error:
        return Say(str(last.result.get("spoken_summary") or "Cancelled."))
    if last.error in APPROVAL_ERRORS:
        return Call("reservation_manage", dict(last.args)) if _user_spoke_after(events, last) else _asked_for_approval(last)
    return _fail(last)
