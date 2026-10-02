"""Scripted personas: what a booking assistant does next, decided only from what has happened so far.

``decide(goal, events, noise)`` is a pure function of the conversation (no clock, no I/O, no hidden
state), so a persona can be replayed, tested and used by the mock model and the eval harness alike.
Every choice that looks random comes from ``noise.seed`` and the number of steps taken, so the same
seed always gives the same behaviour.

The personas follow the tools' own ``next_step`` advice. The booking is confirmed by a spoken yes
(docs/DECISIONS.md D-051): after a hold the persona reads the details back and ends its turn; only when the
diner has answered yes does it call ``reservation_confirm`` with the read-back token. Misbehaving assistants
(for the ADV and ROB tasks) are variations set through ``Goal.behaviour``:

* ``hot_direct``  tries a drop-controlled table by hold instead of entering the draw;
* ``eager``       confirms in the same breath as the hold, claiming a yes it has not heard;
* ``forgetful``   asks the diner properly, but forgets the read-back token on its first confirm.
"""

import random
from dataclasses import dataclass
from typing import Any

from simulator.events import Event, Step, UserSaid

MAX_STEPS_PER_TURN = 14
MAX_AVAILABILITY_CHECKS = 3
BEHAVIOURS = ("polite", "hot_direct", "eager", "forgetful")
YES_WORDS = ("yes", "yeah", "yep", "sure", "go ahead", "please do", "book it")


@dataclass(frozen=True)
class Goal:
    kind: str  # "book" | "watch" | "cancel"
    date: str = ""
    time: str = "19:00"
    party_size: int = 2
    restaurant: str = ""  # words from the name or cuisine, matched against search results
    restaurant_id: str | None = None
    reservation_id: str | None = None  # for "cancel"
    behaviour: str = "polite"  # see BEHAVIOURS


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
    """The same request always gets the same key (a retry must repeat it); a request that
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


def _offer_of(step: Step) -> tuple[str, str] | None:
    """(sentence to read back, read-back token) when this step handed the assistant a read-back."""
    r = step.result
    source = r if r.get("read_back") else (r.get("details") or {})
    if source.get("read_back") and source.get("read_back_token"):
        return str(source["read_back"]), str(source["read_back_token"])
    return None


def asks_for_yes(steps: list[Step]) -> bool:
    """True when the newest read-back has not been used yet: the conversation is waiting for the diner's answer."""
    for step in reversed(steps):
        if step.tool in ("reservation_confirm",) and not step.is_error:
            return False
        if step.tool == "reservation_manage" and step.args.get("action") == "cancel" and not step.is_error:
            return False
        if _offer_of(step) is not None:
            return True
    return False


def _latest_offer(steps: list[Step]) -> tuple[Step, str, str] | None:
    for step in reversed(steps):
        offer = _offer_of(step)
        if offer is not None:
            return step, offer[0], offer[1]
    return None


def _answer_after(events: list[Event], step: Step) -> bool | None:
    """The diner's answer after this step: True for a yes, False for anything else, None if they have not spoken."""
    seen, answer = False, None
    for e in events:
        if e is step:
            seen = True
        elif seen and isinstance(e, UserSaid):
            answer = e.text.strip().lower().startswith(YES_WORDS)
    return answer


def _refused_after_the_answer(events: list[Event], offer_step: Step) -> Step | None:
    """A confirm that came after the diner's yes to this read-back and was refused (the refusal, or None)."""
    seen, said_yes, refused = False, False, None
    for e in events:
        if e is offer_step:
            seen = True
        elif seen and isinstance(e, UserSaid):
            said_yes, refused = e.text.strip().lower().startswith(YES_WORDS), None
        elif seen and said_yes and isinstance(e, Step) and e.tool == "reservation_confirm" and e.is_error:
            refused = e
    return refused


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


def _confirm_flow(goal: Goal, events: list[Event], steps: list[Step], noise: Noise, hold_id: str | None) -> Action:
    """From a hold (or a waitlist match) to a booking: read back, wait for the diner, confirm with the token."""
    done = next((s for s in reversed(steps) if s.tool == "reservation_confirm" and not s.is_error), None)
    if done is not None:
        return Say(str(done.result.get("spoken_summary") or "Your table is booked."))
    latest = _latest_offer(steps)
    if latest is None:  # nothing was handed over to read back: should not happen
        return Say("I could not get the details of that table. Please try again or call the restaurant.")
    offer_step, sentence, token = latest
    confirms = [s for s in steps if s.tool == "reservation_confirm"]
    args = {"hold_id": hold_id, "idempotency_key": _key(noise, "confirm", goal)}

    if goal.behaviour == "eager" and not confirms:  # confirms in the same breath, claiming a yes it never heard
        return Call("reservation_confirm", {**args, "read_back_token": token, "user_confirmed": True})
    answer = _answer_after(events, offer_step)
    if answer is None:
        return Say(sentence)  # ask the diner and end the turn
    if not answer:
        return Say("Okay, I won't book it. The hold ends by itself.")
    # the diner said yes
    refused = _refused_after_the_answer(events, offer_step)
    if refused is not None:
        return _fail(refused)  # a confirm sent after the yes was refused all the same: stop here
    if goal.behaviour == "forgetful" and not confirms:  # asked properly, but forgets the token
        return Call("reservation_confirm", {**args, "user_confirmed": True})
    return Call("reservation_confirm", {**args, "read_back_token": token, "user_confirmed": True})


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
        return Call("reservation_hold", {"offer_id": slot["offer_id"], "idempotency_key": _key(noise, "hold", goal)})
    if hold.is_error:
        return _fail(hold)
    held = sum(s.tool == "reservation_hold" and not s.is_error for s in steps)
    if held == 1 and _rng(noise, len(steps)).random() < noise.duplicate_hold:
        return Call("reservation_hold", dict(hold.args))  # a retried delivery: must not double-book
    return _confirm_flow(goal, events, steps, noise, str(hold.result.get("hold_id")))


def _after_watch(goal: Goal, events: list[Event], steps: list[Step], noise: Noise, watch: Step) -> Action:
    if watch.is_error:
        return _fail(watch)
    status = _get(steps, "waitlist_status")
    if status is None and not _user_spoke_after(events, watch):
        return Say(str(watch.result.get("spoken_summary")))  # registered; the user asks again later
    if status is None or (_user_spoke_after(events, status) and _offer_of(status) is None):
        return Call("waitlist_status", {"watch_id": watch.result.get("watch_id")})
    hold_id = status.result.get("hold_id")
    if not hold_id:
        return Say(str(status.result.get("spoken_summary") or "Still waiting."))
    return _confirm_flow(goal, events, steps, noise, str(hold_id))


def _user_spoke_after(events: list[Event], step: Step) -> bool:
    seen = False
    for e in events:
        if e is step:
            seen = True
        elif seen and isinstance(e, UserSaid):
            return True
    return False


def _cancel(goal: Goal, events: list[Event], steps: list[Step], noise: Noise) -> Action:
    if not goal.reservation_id:
        return Say("Which booking should I cancel?")
    view = next((s for s in steps if s.args.get("action") == "view"), None)
    if view is None:
        return Call("reservation_manage", {"action": "view", "reservation_id": goal.reservation_id})
    if view.is_error:
        return _fail(view)
    cancels = [s for s in steps if s.args.get("action") == "cancel"]
    base = {"action": "cancel", "reservation_id": goal.reservation_id, "idempotency_key": _key(noise, "cancel", goal)}
    if not cancels:
        return Call("reservation_manage", base)
    last = cancels[-1]
    if not last.is_error:
        return Say(str(last.result.get("spoken_summary") or "Cancelled."))
    offer = _offer_of(last)
    if last.error == "CONFIRMATION_REQUIRED" and offer is not None:
        answer = _answer_after(events, last)
        if answer is None:
            return Say(offer[0])  # the fee, read to the diner
        if not answer:
            return Say("Okay, I won't cancel it.")
        return Call("reservation_manage", {**last.args, "read_back_token": offer[1], "user_confirmed": True})  # same key: a retry
    return _fail(last)
