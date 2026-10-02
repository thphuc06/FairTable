"""P2-9 (server part): every tool call becomes one span that says what was decided and by which rule,
joins the caller's trace, and never carries a secret. Uses an in-memory exporter: no AWS."""

from datetime import timedelta

import pytest
from ddb_env import ENDPOINT
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from world import World

from server import telemetry

pytestmark = pytest.mark.ddb


@pytest.fixture
def spans():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    telemetry.use_tracer_provider(provider)
    yield exporter
    telemetry.use_tracer_provider(None)


@pytest.fixture
def world(ddb_client, table_name, clock):
    w = World(ddb_client, table_name, ENDPOINT, clock)
    ids = iter(range(1, 100_000))
    w.deps.new_id = lambda: f"id{next(ids):05d}"
    return w


def day(world: World, offset: int = 2) -> str:
    return (world.clock.now().date() + timedelta(days=offset)).isoformat()


async def call(world: World, tool: str, **args):
    async with world.client() as c:
        return await c.call_tool_mcp(tool, args)


def only(spans: InMemorySpanExporter, tool: str, nth: int = -1):
    found = [s for s in spans.get_finished_spans() if s.attributes.get("fairtable.tool") == tool]
    assert found, f"no span for {tool}"
    return found[nth]


async def token_for(world: World, venue: str, date: str, time: str, party: int = 2) -> str:
    r = await call(world, "availability_check", restaurant_id=venue, date=date, time_window=f"{time}-{time}",
                   party_size=party)
    return r.structuredContent["slots"][0]["offer_id"]


async def test_a_read_call_is_one_span_with_the_caller_and_the_rule_that_allowed_it(world, spans):
    await call(world.as_("alice"), "restaurant_search")
    s = only(spans, "restaurant_search")
    a = dict(s.attributes)
    assert s.name == "fairtable.tool restaurant_search" and s.status.status_code is not StatusCode.ERROR
    assert a["fairtable.outcome"] == "ok" and a["fairtable.caller.kind"] == "user"
    assert a["fairtable.caller.agent_tier"] == "verified"
    assert a["fairtable.pep1.decision"] == "allow" and list(a["fairtable.pep1.rule_ids"]) == ["G1_reads_any_valid_jwt"]


async def test_a_refusal_names_the_rule_and_is_not_marked_as_a_failure_of_the_server(world, spans):
    world.as_("alice")
    slot = await token_for(world, "sakura-counter", day(world, 1), "20:00")  # the Fair Drop seat
    r = await call(world, "reservation_hold", offer_id=slot, idempotency_key="span-rt8-direct")
    assert r.isError
    s = only(spans, "reservation_hold")
    a = dict(s.attributes)
    assert a["fairtable.outcome"] == "refused" and a["fairtable.error_code"] == "DROP_CONTROLLED"
    assert a["fairtable.rule_id"] == "S4_drop_slots_via_waitlist"
    assert a["fairtable.pep2.decision"] == "deny" and a["fairtable.venue_id"] == "sakura-counter"
    assert s.status.status_code is not StatusCode.ERROR  # an expected refusal is not an error span


async def test_pep1_denials_are_visible_for_a_machine_client(world, spans):
    world.as_("bot")
    slot = await token_for(world, "luna-trattoria", day(world), "19:00")
    await call(world, "reservation_hold", offer_id=slot, idempotency_key="span-rt1-bot-hold")
    a = dict(only(spans, "reservation_hold").attributes)
    assert a["fairtable.caller.kind"] == "machine" and a["fairtable.pep1.decision"] == "deny"
    assert a["fairtable.outcome"] == "refused" and "fairtable.pep2.decision" not in a  # stopped before PEP-2


async def test_a_confirm_without_the_diners_answer_is_recorded_as_waiting_for_the_yes(world, spans):
    world.as_("bob")
    slot = await token_for(world, "luna-trattoria", day(world), "19:00")
    hold = await call(world, "reservation_hold", offer_id=slot, idempotency_key="span-bob-hold")
    await call(world, "reservation_confirm", hold_id=hold.structuredContent["hold_id"], idempotency_key="span-bob-conf",
               read_back_token=hold.structuredContent["read_back_token"], user_confirmed=True)  # in the same breath
    a = dict(only(spans, "reservation_confirm").attributes)
    assert a["fairtable.outcome"] == "read_back" and a["fairtable.error_code"] == "CONFIRMATION_REQUIRED"
    assert a["fairtable.pep2.decision"] == "deny"
    assert list(a["fairtable.pep2.rule_ids"]) == ["S5b_confirm_needs_the_diners_answer"]


async def test_an_idempotent_replay_is_marked(world, spans):
    world.as_("alice")
    slot = await token_for(world, "luna-trattoria", day(world), "19:00")
    await call(world, "reservation_hold", offer_id=slot, idempotency_key="span-replay-key")
    await call(world, "reservation_hold", offer_id=slot, idempotency_key="span-replay-key")
    first, second = (dict(s.attributes) for s in spans.get_finished_spans() if s.attributes["fairtable.tool"] == "reservation_hold")
    assert first["fairtable.outcome"] == "ok" and first.get("fairtable.idempotent_replay") is False
    assert second["fairtable.outcome"] == "ok" and second["fairtable.idempotent_replay"] is True


async def test_a_missing_token_is_a_refusal_with_no_caller(world, spans):
    await call(world.as_(None), "restaurant_search")
    a = dict(only(spans, "restaurant_search").attributes)
    assert a["fairtable.outcome"] == "refused" and a["fairtable.error_code"] == "UNAUTHENTICATED"
    assert not any(k.startswith("fairtable.caller") for k in a)


async def test_a_bug_is_an_error_span_with_the_exception_class_only(world, spans):
    world.as_("alice")
    world.deps.store.get_venue = lambda _id: 1 / 0  # a bug inside a tool
    r = await call(world, "availability_check", restaurant_id="luna-trattoria", date=day(world), party_size=2)
    assert r.isError
    s = only(spans, "availability_check")
    a = dict(s.attributes)
    assert s.status.status_code is StatusCode.ERROR and a["fairtable.outcome"] == "error"
    assert a["fairtable.exception.type"] == "ToolError" or a["fairtable.exception.type"] == "ZeroDivisionError"
    assert "division" not in str(a).lower()  # the message never reaches a span


async def test_the_span_joins_the_callers_trace_when_it_sends_its_context(world, spans):
    trace_id, parent = "0af7651916cd43dd8448eb211c80319c", "b7ad6b7169203331"
    world.as_("alice")
    async with world.client() as c:
        await c.call_tool_mcp("restaurant_search", {}, meta={"traceparent": f"00-{trace_id}-{parent}-01"})
    s = only(spans, "restaurant_search")
    assert format(s.context.trace_id, "032x") == trace_id and format(s.parent.span_id, "016x") == parent


async def test_a_call_without_trace_context_starts_its_own_trace(world, spans):
    await call(world.as_("alice"), "restaurant_search")
    s = only(spans, "restaurant_search")
    assert s.parent is None and s.context.trace_id != 0


async def test_no_span_of_a_whole_booking_carries_a_secret(world, spans):
    """Token, slot token, read-back token, user id, username, idempotency keys and ids: none may appear."""
    secrets = {world.token("bob"), "dev-bob", "diner-bob", "span-secret-hold", "span-secret-conf", "eyJ"}
    world.as_("bob")
    slot = await token_for(world, "luna-trattoria", day(world), "19:00")
    secrets.add(slot)
    hold = await call(world, "reservation_hold", offer_id=slot, idempotency_key="span-secret-hold")
    secrets.update({hold.structuredContent["hold_id"], hold.structuredContent["read_back_token"]})
    world.clock.advance(8)
    r = await call(world, "reservation_confirm", hold_id=hold.structuredContent["hold_id"],
                   idempotency_key="span-secret-conf", read_back_token=hold.structuredContent["read_back_token"],
                   user_confirmed=True)
    assert not r.isError, r.structuredContent
    secrets.add(r.structuredContent["reservation_id"])
    finished = spans.get_finished_spans()
    assert len(finished) >= 3
    for s in finished:
        for name, value in s.attributes.items():
            assert name.startswith("fairtable."), name
            text = str(value)
            assert not any(secret in text for secret in secrets), f"{name}={text}"
        assert not s.events  # no recorded exception messages either
