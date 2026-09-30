"""P1-18: the simulated assistant (a Strands agent with the scripted model) against the real server over
Streamable HTTP, and the simulated diner answering the consent page."""

from datetime import timedelta

import pytest
from world import SUBS, World

from server.domain.clock import iso_z
from server.invariants import check_invariants
from simulator.assistant import Assistant
from simulator.model import ScriptedModel
from simulator.personas import NO_NOISE, Goal, Noise
from simulator.user import ConsentError, SimulatedUser

pytestmark = pytest.mark.ddb


def day(world: World) -> str:
    return (world.clock.now().date() + timedelta(days=2)).isoformat()


def assistant(world: World, url: str, who: str, goal: Goal | None = None, noise: Noise = NO_NOISE) -> Assistant:
    return Assistant(url, world.token(who), ScriptedModel(goal, noise, today=world.clock.now().date()))


def luna_goal(world: World, **kw) -> Goal:
    return Goal(kind="book", date=day(world), time="19:00", party_size=2, restaurant="luna", **kw)


async def test_the_assistant_has_exactly_the_eight_tools(live):
    world, url = live
    with assistant(world, url, "alice") as a:
        assert a.tool_names == sorted([
            "restaurant_search", "availability_check", "mandate_status", "reservation_hold",
            "reservation_confirm", "reservation_manage", "waitlist_watch", "waitlist_status"])


async def test_a_booking_inside_the_mandate_completes_in_one_turn(live):
    world, url = live
    with assistant(world, url, "alice", luna_goal(world)) as a:
        reply = await a.say("Book a table at Luna Trattoria")
    assert [s.tool for s in reply.steps] == [
        "restaurant_search", "availability_check", "reservation_hold", "reservation_confirm"]
    assert not reply.steps[-1].is_error and "booked" in reply.text.lower()
    assert len(world.store.reservations_of_user(SUBS["alice"])) == 1
    assert check_invariants(world.store, iso_z(world.clock.now())) == []


async def test_a_booking_outside_the_mandate_needs_the_diner_to_approve(live):
    world, url = live
    bob = SimulatedUser(world.web(), "diner-bob", "bob-dev-pass")
    with assistant(world, url, "bob", luna_goal(world)) as a:
        first = await a.say("Book a table at Luna Trattoria")
        assert first.steps[-1].error == "CONSENT_REQUIRED" and first.consent_url
        assert first.consent_url in first.text  # the assistant hands over the link, nothing more
        assert "booked" not in first.text.lower().replace("nothing was booked", "")
        page = bob.approve_consent(first.consent_url)
        assert "You approved this" in page
        second = await a.say("I approved it")
    assert not second.steps[-1].is_error and second.steps[-1].tool == "reservation_confirm"
    assert "booked" in second.text.lower()
    assert check_invariants(world.store, iso_z(world.clock.now())) == []


async def test_a_declined_approval_books_nothing(live):
    world, url = live
    bob = SimulatedUser(world.web(), "diner-bob", "bob-dev-pass")
    with assistant(world, url, "bob", luna_goal(world)) as a:
        first = await a.say("Book a table at Luna Trattoria")
        assert "You declined this" in bob.decline(first.consent_url)
        second = await a.say("I said no")
    assert second.steps[-1].error == "CONSENT_DECLINED"
    assert check_invariants(world.store, iso_z(world.clock.now())) == []


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
        reply = await a.say(f"Book a table at Luna Trattoria for 2 on {day(world)} at 7pm")
    assert "booked" in reply.text.lower()


async def test_the_diner_cannot_approve_someone_elses_request(live):
    world, url = live
    mallory = SimulatedUser(world.web(), "diner-alice", "alice-dev-pass")
    with assistant(world, url, "bob", luna_goal(world)) as a:
        first = await a.say("Book a table at Luna Trattoria")
    with pytest.raises(ConsentError, match="403"):
        mallory.approve_consent(first.consent_url)
