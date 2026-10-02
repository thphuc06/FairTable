"""P3-9: what a diner could hear. Alexa+ functional requirements 2, 9 and 13 (docs/alexa-plus-addon-notes.md).

* Requirement 2: no API codes, tool names, JSON or internal ids in anything customer-facing, and a next step for
  every error. The parts meant to be spoken are `spoken_summary`, an error's `message` and `read_back`; the
  model-directed parts (`hint`, `next_step.why`) may name parameters but never a tool, a code or a rule.
* Requirement 9: at most five options at a time, with a way to get the next ones.
* Requirement 13: unexpected or invalid parameters give a structured error, not a stack trace.
"""

import re

import pytest
from flows import call, confirm_after_read_back, day, hold_table
from world import World

pytestmark = pytest.mark.ddb

TOOLS = ("restaurant_search", "availability_check", "reservation_hold", "reservation_confirm",
         "reservation_manage", "waitlist_watch", "waitlist_status")
PARAMS = ("offer_id", "hold_id", "read_back_token", "user_confirmed", "idempotency_key", "restaurant_id",
          "new_party_size", "watch_id", "reservation_id", "drop_id", "time_window", "party_size", "response_format")
CODES = re.compile(r"\b[A-Z]{2,}(?:_[A-Z]{2,})+\b|\b[GPS]\d[a-c]?_[a-z_]+\b")  # SLOT_TAKEN, S5a_confirm_...
IDS = re.compile(r"\b[0-9a-f]{12,}\b|\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}|\b(?:hold|res|drop|watch|entry)[-_~][\w~-]{6,}")
JARGON = re.compile(r"\bJSON\b|\bAPI\b|\btoken\b|\bids?\b|traceback|pydantic|validation error|\bNone\b|\bnull\b|\{|\}",
                    re.IGNORECASE)


VISUAL = re.compile(r"\b(shown|displayed|on screen|on the screen|tap|click|button|card|check your display)\b",
                    re.IGNORECASE)  # requirement 9: never refer to visual elements


def violations(text: str, *, strict: bool) -> list[str]:
    """`strict` for the spoken parts; the model-directed parts may name parameters."""
    found = [t for t in TOOLS if t in text] + CODES.findall(text) + IDS.findall(text)
    if strict:
        found += [p for p in PARAMS if p in text] + [m.group(0) for m in JARGON.finditer(text)]
        found += [m.group(0) for m in VISUAL.finditer(text)]
    return found


def check(result, seen: list) -> None:
    body = result.structuredContent
    assert isinstance(body, dict), result
    if result.isError:
        assert body["message"], body
        assert body["next_step"]["why"], body  # a next step for every error
        seen.append(("message", body["message"], True))
        for part in ("hint",):
            if body.get(part):
                seen.append((part, body[part], False))
        seen.append(("next_step.why", body["next_step"]["why"], False))
        text = result.content[0].text
        assert text and "Traceback" not in text and "pydantic" not in text.lower(), text
    else:
        assert body["spoken_summary"], body
        seen.append(("spoken_summary", body["spoken_summary"], True))
        if body.get("read_back"):
            seen.append(("read_back", body["read_back"], True))
        if body.get("next_step"):
            seen.append(("next_step.why", body["next_step"]["why"], False))


@pytest.fixture
def world(ddb_client, table_name, clock):
    from ddb_env import ENDPOINT

    return World(ddb_client, table_name, ENDPOINT, clock)


async def scenario(world: World) -> list:
    """Every tool, happy and unhappy, through the real server; returns the texts to scan."""
    seen: list = []

    async def go(who, tool, **args):
        r = await call(world.as_(who), tool, **args)
        check(r, seen)
        return r

    await go("alice", "restaurant_search")
    await go("alice", "restaurant_search", query="pizza hut")
    await go("alice", "restaurant_search", offset=40)
    await go("alice", "availability_check", restaurant_id="nowhere", date=day(world), time_window="18:00-21:00",
             party_size=2)
    luna = await go("alice", "availability_check", restaurant_id="luna-trattoria", date=day(world),
                    time_window="17:00-22:00", party_size=2)
    await go("alice", "availability_check", restaurant_id="luna-trattoria", date=day(world),
             time_window="03:00-04:00", party_size=2)
    await go("alice", "availability_check", restaurant_id="luna-trattoria", date=day(world), time_window="17:00-22:00",
             party_size=12)
    await go("alice", "availability_check", restaurant_id="luna-trattoria", date="2020-01-01",
             time_window="17:00-22:00", party_size=2)
    assert luna.structuredContent["slots"]

    # holds: a bad slot token, then a real one
    await go("alice", "reservation_hold", offer_id="not-a-token", idempotency_key="key-text-0001")
    await go("alice", "reservation_hold", offer_id=luna.structuredContent["slots"][0]["offer_id"],
             idempotency_key="bad key!")
    held = await hold_table(world, "alice", "luna-trattoria", "19:00", key="key-text-0002")
    check(await call(world.as_("alice"), "reservation_hold", offer_id=luna.structuredContent["slots"][0]["offer_id"],
                     idempotency_key="key-text-0002"), seen)  # a replay of a different request: conflict
    seen.append(("read_back", held["read_back"], True))
    seen.append(("spoken_summary", held["spoken_summary"], True))

    # confirm: too soon, no yes, no token, then properly
    for over in ({"answer_after": 0}, {"user_confirmed": False}, {"read_back_token": None}):
        check(await confirm_after_read_back(world, "alice", held, key="key-text-0003", **over), seen)
    done = await confirm_after_read_back(world, "alice", held, key="key-text-0004")
    check(done, seen)
    await go("alice", "reservation_confirm", hold_id="nope", idempotency_key="key-text-0005",
             read_back_token="x", user_confirmed=True)
    rid = done.structuredContent["reservation_id"]

    # manage
    await go("alice", "reservation_manage", action="view", reservation_id=rid)
    await go("alice", "reservation_manage", action="view", reservation_id="nope")
    await go("alice", "reservation_manage", action="modify", reservation_id=rid, idempotency_key="key-text-0006")
    await go("alice", "reservation_manage", action="modify", reservation_id=rid, idempotency_key="key-text-0007",
             new_party_size=5)
    await go("alice", "reservation_manage", action="cancel", reservation_id=rid, idempotency_key="key-text-0008")

    # waitlist
    await go("bob", "waitlist_watch", restaurant_id="nowhere", date=day(world, 3), party_size=2,
             idempotency_key="key-text-0009")
    await go("bob", "waitlist_watch", restaurant_id="luna-trattoria", date=day(world, 3), party_size=2,
             idempotency_key="key-text-0010")
    await go("bob", "waitlist_status", watch_id="nope")
    # wrong user
    await go(None, "restaurant_search")
    return seen


async def test_no_code_tool_name_or_id_in_what_is_spoken(world):
    seen = await scenario(world)
    assert len(seen) > 40
    bad = [(where, text, v) for where, text, strict in seen if (v := violations(text, strict=strict))]
    assert not bad, "\n".join(f"{w}: {t!r} -> {v}" for w, t, v in bad)


async def test_a_fresh_read_back_keeps_the_spoken_parts_clean_too(world):
    """S5a hands over a new read-back with the refusal; what is spoken in it is as clean as the first one."""
    held = await hold_table(world, "alice", "ember-grill", "19:00", key="key-text-1001")
    r = await confirm_after_read_back(world, "alice", held, key="key-text-1002", read_back_token="stale")
    assert r.isError
    details = r.structuredContent["details"]
    assert not violations(details["read_back"], strict=True), details["read_back"]


# ---------------------------------------------------------------- requirement 9: at most five options
async def test_at_most_five_slots_come_back_and_the_rest_are_one_call_away(world):
    r = await call(world.as_("alice"), "availability_check", restaurant_id="luna-trattoria", date=day(world),
                   time_window="00:00-23:59", party_size=1)
    body = r.structuredContent
    assert 0 < len(body["slots"]) <= 5, body
    shown = body["slots"][-1]["time"]
    if body["more_slots"]:
        assert shown in body["next_step"]["why"], body["next_step"]
        nxt = await call(world.as_("alice"), "availability_check", restaurant_id="luna-trattoria", date=day(world),
                         time_window=f"{shown}-23:59", party_size=1)
        assert nxt.structuredContent["slots"], "a later window reaches the rest"


async def test_restaurant_search_pages_five_at_a_time(world):
    from server.domain.models import Venue

    for n in range(1, 6):  # eight restaurants in all
        world.store.put_venue(Venue(f"extra-{n}", f"Extra Place {n}", "Thai", "Springfield", "Another place.", 40, 50, 0, 24))
    alice = world.as_("alice")
    first = (await call(alice, "restaurant_search")).structuredContent
    assert len(first["restaurants"]) == 5 and first["total_found"] == 8 and first["more_after"] == 3
    assert "offset 5" in first["next_step"]["why"] and "3 more" in first["spoken_summary"]
    second = (await call(alice, "restaurant_search", offset=5)).structuredContent
    assert len(second["restaurants"]) == 3 and second["more_after"] == 0
    names = [r["name"] for r in first["restaurants"] + second["restaurants"]]
    assert len(set(names)) == 8
    beyond = (await call(alice, "restaurant_search", offset=40)).structuredContent
    assert beyond["restaurants"] == [] and beyond["spoken_summary"]


# ---------------------------------------------------------------- requirement 13: bad parameters
@pytest.mark.parametrize("tool,args", [
    ("availability_check", {"restaurant_id": "luna-trattoria", "date": "tomorrow-ish", "time_window": "evening",
                            "party_size": "two"}),
    ("availability_check", {}),
    ("restaurant_search", {"party_size": "lots"}),
    ("reservation_hold", {"offer_id": 7, "idempotency_key": None}),
    ("reservation_manage", {"action": "teleport", "reservation_id": "x"}),
    ("waitlist_watch", {}),
])
async def test_invalid_parameters_give_an_error_not_a_crash(world, tool, args):
    r = await call(world.as_("alice"), tool, **args)
    assert r.isError
    text = r.content[0].text
    assert "Traceback" not in text and "errors.pydantic.dev" not in text, text
    assert text.strip()
