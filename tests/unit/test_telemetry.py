"""P2-9 (server part): the span attributes are limited to an allow-list, and nothing else can get in."""

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from server import telemetry
from server.domain.models import Identity
from server.kernel import Decision, DecisionKind


@pytest.fixture
def spans():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    telemetry.use_tracer_provider(provider)
    yield exporter
    telemetry.use_tracer_provider(None)


def attrs(exporter) -> dict:
    (span,) = exporter.get_finished_spans()
    return dict(span.attributes)


def test_a_span_carries_the_tool_and_only_allowed_attributes(spans):
    with telemetry.tool_span("reservation_hold"):
        telemetry.annotate(venue_id="luna-trattoria", party_size=2, outcome="ok")
    assert attrs(spans) == {"fairtable.tool": "reservation_hold", "fairtable.venue_id": "luna-trattoria",
                            "fairtable.party_size": 2, "fairtable.outcome": "ok"}
    (span,) = spans.get_finished_spans()
    assert span.name == "fairtable.tool reservation_hold"


@pytest.mark.parametrize("name", ["sub", "token", "slot_token", "idempotency_key", "consent_url", "message", "username"])
def test_an_attribute_that_is_not_on_the_allow_list_is_refused(spans, name):
    with telemetry.tool_span("x"), pytest.raises(ValueError, match="allow-list"):
        telemetry.annotate(**{name: "value"})


def test_the_names_with_a_dot_are_written_with_underscores(spans):
    identity = Identity(sub="dev-alice", username="diner-alice", agent_tier="verified")
    with telemetry.tool_span("x"):
        telemetry.annotate_caller(identity)
        telemetry.annotate_decision("pep2", Decision(DecisionKind.STEP_UP, ("S3_confirm_needs_mandate",), "pep2"))
    a = attrs(spans)
    assert a["fairtable.caller.kind"] == "user" and a["fairtable.caller.agent_tier"] == "verified"
    assert a["fairtable.pep2.decision"] == "step_up" and list(a["fairtable.pep2.rule_ids"]) == ["S3_confirm_needs_mandate"]
    assert "dev-alice" not in str(a) and "diner-alice" not in str(a)  # who the caller is never appears


def test_a_machine_caller_is_described_without_an_identity(spans):
    with telemetry.tool_span("x"):
        telemetry.annotate_caller(Identity(sub="bot-m2m"))
    a = attrs(spans)
    assert a["fairtable.caller.kind"] == "machine" and a["fairtable.caller.agent_tier"] == "none"


def test_an_unsupported_value_is_skipped_not_raised(spans):
    with telemetry.tool_span("x"):
        telemetry.annotate(error_code={"nested": "dict"})  # telemetry never breaks a call
        telemetry.annotate(outcome="ok")
    assert attrs(spans) == {"fairtable.tool": "x", "fairtable.outcome": "ok"}


def test_long_text_is_cut(spans):
    with telemetry.tool_span("x"):
        telemetry.annotate(error_code="E" * 1000)
    assert len(attrs(spans)["fairtable.error_code"]) == telemetry.MAX_TEXT


def test_none_is_skipped_and_nothing_happens_without_a_span():
    telemetry.annotate(venue_id=None, party_size=None)  # no provider, no recording span: a no-op
    telemetry.annotate(outcome="ok")
    with pytest.raises(ValueError):
        telemetry.annotate(sub="x")  # even then, a name off the list is a bug worth failing on


def test_only_trace_context_keys_are_read_from_the_request_meta():
    class Meta:
        def model_dump(self):
            return {"traceparent": "00-" + "a" * 32 + "-" + "b" * 16 + "-01", "progressToken": 7, "secret": "x",
                    "baggage": "k=v"}

    class Ctx:
        request_context = type("R", (), {"meta": Meta()})()

    class Context:
        fastmcp_context = Ctx()
        message = object()

    assert set(telemetry._carrier(Context())) == {"traceparent", "baggage"}
    assert telemetry._carrier(object()) == {}
    assert telemetry._carrier(type("C", (), {"message": type("M", (), {"meta": Meta()})()})()) == {
        "traceparent": Meta().model_dump()["traceparent"], "baggage": "k=v"}  # falls back to the params
