"""P1-18, P3-10: the simulated assistant (a Strands agent with the scripted model) against the real server over
Streamable HTTP, and the diner answering the read-back aloud."""

from datetime import timedelta

import pytest
from world import SUBS, World

from server.domain.clock import iso_z
from server.invariants import check_invariants
from simulator.assistant import Assistant
from simulator.model import ScriptedModel
from simulator.personas import NO_NOISE, Goal, Noise
from simulator.user import NO, YES

pytestmark = pytest.mark.ddb


def day(world: World) -> str:
    return (world.clock.now().date() + timedelta(days=2)).isoformat()


def assistant(world: World, url: str, who: str, goal: Goal | None = None, noise: Noise = NO_NOISE) -> Assistant:
    return Assistant(url, world.token(who), ScriptedModel(goal, noise, today=world.clock.now().date()))


def luna_goal(world: World, **kw) -> Goal:
    return Goal(kind="book", date=day(world), time="19:00", party_size=2, restaurant="luna", **kw)


async def test_the_assistant_has_exactly_the_seven_tools(live):
    world, url = live
    with assistant(world, url, "alice") as a:
        assert a.tool_names == sorted([
            "restaurant_search", "availability_check", "reservation_hold",
            "reservation_confirm", "reservation_manage", "waitlist_watch", "waitlist_status"])


async def test_the_assistant_reads_the_details_back_and_does_not_book_until_the_diner_says_yes(live):
    world, url = live
    with assistant(world, url, "alice", luna_goal(world)) as a:
        asked = await a.say("Book a table at Luna Trattoria")
        assert [s.tool for s in asked.steps] == ["restaurant_search", "availability_check", "reservation_hold"]
        assert "Shall I book it?" in asked.text and not world.store.reservations_of_user(SUBS["alice"])
        world.clock.advance(8)  # the diner listens and answers
        done = await a.say(YES)
    assert [s.tool for s in done.steps] == ["reservation_confirm"] and not done.steps[-1].is_error
    assert "booked" in done.text.lower()
    reservation = world.store.reservations_of_user(SUBS["alice"])[0]
    assert reservation.confirmation == "spoken" and reservation.read_back_at
    assert check_invariants(world.store, iso_z(world.clock.now())) == []


async def test_a_no_books_nothing(live):
    world, url = live
    with assistant(world, url, "bob", luna_goal(world)) as a:
        await a.say("Book a table at Luna Trattoria")
        world.clock.advance(8)
        second = await a.say(NO)
    assert second.steps == [] and "won't book" in second.text
    assert not world.store.reservations_of_user(SUBS["bob"])
    assert check_invariants(world.store, iso_z(world.clock.now())) == []


async def test_an_eager_assistant_is_refused_and_then_asks_properly(live):
    world, url = live
    with assistant(world, url, "alice", luna_goal(world, behaviour="eager")) as a:
        first = await a.say("Book a table at Luna Trattoria")
        assert first.steps[-1].tool == "reservation_confirm" and first.steps[-1].is_error
        assert first.steps[-1].result["rule_id"] == "S5b_confirm_needs_the_diners_answer"
        assert not world.store.reservations_of_user(SUBS["alice"])  # it claimed a yes it had not heard
        world.clock.advance(8)
        second = await a.say(YES)
    assert not second.steps[-1].is_error and len(world.store.reservations_of_user(SUBS["alice"])) == 1


async def test_a_forgetful_assistant_recovers_with_the_new_read_back(live):
    world, url = live
    with assistant(world, url, "bob", luna_goal(world, behaviour="forgetful")) as a:
        await a.say("Book a table at Luna Trattoria")
        world.clock.advance(8)
        second = await a.say(YES)
        assert second.steps[-1].result["rule_id"] == "S5a_confirm_needs_read_back"
        world.clock.advance(8)
        third = await a.say(YES)
    assert not third.steps[-1].is_error and len(world.store.reservations_of_user(SUBS["bob"])) == 1


async def test_a_retried_hold_does_not_double_book(live):
    world, url = live
    with assistant(world, url, "alice", luna_goal(world), Noise(seed=3, duplicate_hold=1.0)) as a:
        reply = await a.say("Book a table at Luna Trattoria")
    holds = [s for s in reply.steps if s.tool == "reservation_hold"]
    assert len(holds) == 2 and not holds[1].is_error
    assert holds[1].result.get("idempotent_replay") is True
    assert holds[0].result["hold_id"] == holds[1].result["hold_id"]
    assert check_invariants(world.store, iso_z(world.clock.now())) == []


async def test_a_chat_sentence_is_enough_for_the_mock(live):
    """No fixed goal: the mock reads the diner's sentence, like the chat page will use it."""
    world, url = live
    with assistant(world, url, "alice") as a:
        asked = await a.say(f"Book a table at Luna Trattoria for 2 on {day(world)} at 7pm")
        assert "shall i book it" in asked.text.lower()
        world.clock.advance(8)
        done = await a.say("Yes, please")
    assert "booked" in done.text.lower()
