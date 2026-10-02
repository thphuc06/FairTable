"""OpenTelemetry spans for tool calls (plan task P2-9, docs/DECISIONS.md D-031).

One span per tool call, named ``fairtable.tool <name>``, carrying what a person troubleshooting needs to
know: which tool, what each policy layer decided and by which rule, whether the answer was ok, a refusal,
a refusal to confirm or an error, and whether it was an idempotent replay.

Privacy is enforced in code, not by care: ``annotate`` accepts only the attribute names in ``ALLOWED``
(no token, no user id, no idempotency key, no read-back token, no free text), and a value that is not a bool,
an int or a short string is refused. A test scans real spans for anything that looks like a secret.

Without an OpenTelemetry SDK configured the API is a no-op, so the local profile pays nothing. On AWS the
AWS Distro for OpenTelemetry (or Runtime's own instrumentation) supplies the exporter and the tracer
provider; the server never configures one. If the caller (a Strands agent) sends its trace context in the
MCP ``_meta`` field, the span joins that trace.
"""

import logging
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from fastmcp.server.middleware import Middleware
from opentelemetry import propagate, trace
from opentelemetry.trace import SpanKind, Status, StatusCode

log = logging.getLogger("fairtable.telemetry")
TRACER_NAME = "fairtable.server"
PREFIX = "fairtable."
MAX_TEXT = 120
CARRIER_KEYS = ("traceparent", "tracestate", "baggage")
READ_BACK_CODES = ("CONFIRMATION_REQUIRED",)

# Every attribute the server may put on a span (without the "fairtable." prefix).
ALLOWED = frozenset({
    "tool",                    # the MCP tool that was called
    "caller.kind",             # "user" | "machine"
    "caller.agent_tier",       # "verified" | "unverified" | "none"
    "venue_id",                # the restaurant (business data, not personal)
    "party_size",
    "pep1.decision",           # "allow" | "deny"
    "pep1.rule_ids",           # rule ids that decided
    "pep2.decision",           # "allow" | "deny"
    "pep2.rule_ids",
    "outcome",                 # "ok" | "refused" | "read_back" | "error"
    "error_code",              # the tool's error code, e.g. POLICY_DENIED
    "rule_id",                 # the rule named in a refusal
    "idempotent_replay",
    "exception.type",          # class name only, never the message
})

# The span of the tool call in progress. ``annotate`` writes to it rather than to "the current span":
# FastMCP opens its own inner span, which is not recording when only our provider is configured.
_tool_span: ContextVar[trace.Span | None] = ContextVar("fairtable_tool_span", default=None)
_provider: Any = None  # tests inject a provider here; None means the global one (set by ADOT on AWS)


def use_tracer_provider(provider: Any) -> None:
    """For tests: send this server's spans to ``provider`` instead of the global one. ``None`` undoes it."""
    global _provider
    _provider = provider


def tracer() -> trace.Tracer:
    return trace.get_tracer(TRACER_NAME, tracer_provider=_provider)


def _clean(value: Any) -> Any:
    if isinstance(value, bool | int):
        return value
    if isinstance(value, str):
        return value[:MAX_TEXT]
    if isinstance(value, Sequence) and all(isinstance(v, str) for v in value):
        return [v[:MAX_TEXT] for v in value]
    raise ValueError(f"a span attribute must be a bool, an int, a string or a list of strings, got {type(value).__name__}")


def annotate(**attributes: Any) -> None:
    """Put attributes on the current span, if there is a recording one. ``None`` values are skipped.
    Names are written with ``_`` for ``.`` (``pep1_decision`` is ``pep1.decision``)."""
    span = _tool_span.get() or trace.get_current_span()
    for raw, value in attributes.items():
        name = raw.replace("_", ".", 1) if raw.split("_", 1)[0] in ("caller", "pep1", "pep2", "exception") else raw
        if name not in ALLOWED:
            raise ValueError(f"span attribute {name!r} is not on the allow-list (server/telemetry.py)")
        if value is None or not span.is_recording():
            continue
        try:
            span.set_attribute(PREFIX + name, _clean(value))
        except ValueError:
            log.warning("span attribute %s skipped: unsupported value type", name)  # telemetry never breaks a call


def annotate_caller(identity: Any) -> None:
    annotate(
        caller_kind="user" if identity.is_user else "machine",
        caller_agent_tier=identity.agent_tier or "none",
    )


def annotate_decision(layer: str, decision: Any) -> None:
    """``layer`` is ``"pep1"`` or ``"pep2"``; ``decision`` is a kernel ``Decision``."""
    annotate(**{f"{layer}_decision": str(decision.kind), f"{layer}_rule_ids": list(decision.rule_ids)})


def _carrier(context: Any) -> Mapping[str, str]:
    """The trace context a client put in the request's ``_meta``, if any. FastMCP hands it over on the
    request context (``fastmcp_context.request_context.meta``); the call's own params do not carry it."""
    request_context = getattr(getattr(context, "fastmcp_context", None), "request_context", None)
    meta = getattr(request_context, "meta", None) or getattr(getattr(context, "message", None), "meta", None)
    if meta is None:
        return {}
    data = meta.model_dump() if hasattr(meta, "model_dump") else dict(meta)
    return {k: v for k, v in data.items() if k in CARRIER_KEYS and isinstance(v, str)}


def _record_result(result: Any) -> None:
    """Outcome of a finished tool call, read from what the client will receive."""
    data = getattr(result, "structured_content", None) or {}
    if getattr(result, "is_error", False):
        code = data.get("error") if isinstance(data, dict) else None
        annotate(
            outcome="read_back" if code in READ_BACK_CODES else "refused",
            error_code=code if isinstance(code, str) else "error",
            rule_id=data.get("rule_id") if isinstance(data, dict) else None,
        )
        return
    annotate(outcome="ok", idempotent_replay=bool(isinstance(data, dict) and data.get("idempotent_replay")))


@contextmanager
def tool_span(name: str, carrier: Mapping[str, str] | None = None) -> Iterator[trace.Span]:
    context = propagate.extract(dict(carrier)) if carrier else None
    with tracer().start_as_current_span(
        f"{PREFIX}tool {name}", context=context, kind=SpanKind.SERVER, attributes={PREFIX + "tool": name},
    ) as span:
        token = _tool_span.set(span)
        try:
            yield span
        finally:
            _tool_span.reset(token)


class TelemetryMiddleware(Middleware):
    """Wrap every tool call in a span. Add it *first* so it is outermost and sees the final result
    (after ``ErrorMappingMiddleware`` has turned refusals into ``isError`` results). It never changes
    what the caller receives: every exception is re-raised untouched."""

    async def on_call_tool(self, context, call_next):
        with tool_span(context.message.name, _carrier(context)) as span:
            try:
                result = await call_next(context)
            except Exception as e:
                annotate(outcome="error", exception_type=type(e).__name__)
                span.set_status(Status(StatusCode.ERROR))
                raise
            _record_result(result)
            return result
