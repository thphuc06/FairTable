"""Error mapping at the FastMCP boundary.

FastMCP 3.4.7 wraps every exception raised in a tool into ``ToolError`` (server.py, the final
``except Exception``), which loses structure. This middleware unwraps the two errors we raise on
purpose (docs/PLAN.md section 3a, docs/DECISIONS.md D-014): ``FairTableError`` becomes an ``isError: true``
result with the structured payload and next_step. (The ``-32042`` URL-elicitation path of D-014 is gone: Alexa+
declares no elicitation and confirmation is spoken, D-051.)

Anything else stays a masked ``ToolError`` (set ``mask_error_details=True`` on the server).
"""

import functools
import logging

from fastmcp.exceptions import ToolError
from fastmcp.exceptions import ValidationError as ArgumentError
from fastmcp.server.middleware import Middleware
from fastmcp.tools import ToolResult
from pydantic import ValidationError

from server.domain.errors import ErrorCode, FairTableError
from server.store import StoreBusy

log = logging.getLogger("fairtable.tools")


class BusinessError(ToolError):
    """A ``FairTableError`` crossing the FastMCP boundary. It is a ``FastMCPError``, so FastMCP
    logs it at INFO without a traceback and re-raises it as is (it is an expected outcome, not a
    bug); the middleware below turns it into an ``isError`` result."""

    def __init__(self, error: FairTableError) -> None:
        super().__init__(error.message, log_level=logging.INFO)
        self.error = error


def business_errors(fn):
    """Decorator for tool functions: let domain code raise ``FairTableError`` freely."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except FairTableError as e:
            raise BusinessError(e) from None
        except StoreBusy:
            # Real DynamoDB can keep cancelling a transaction with TransactionConflict under heavy
            # contention. Nothing was written, so asking the agent to repeat the call is safe.
            raise BusinessError(
                FairTableError(
                    ErrorCode.TEMPORARILY_BUSY, "The service is busy right now.", retry_after_s=1
                )
            ) from None

    return wrapper


FIELD_WORDS = {"party_size": "the number of people", "date": "the date", "time_window": "the time",
               "restaurant_id": "the restaurant", "new_party_size": "the new number of people",
               "offer_id": "the table offer", "hold_id": "the held table", "reservation_id": "the booking",
               "watch_id": "the waitlist entry", "action": "what to do with the booking",
               "idempotency_key": "the request key", "query": "what to look for"}


def _validation_error(exc: BaseException | None) -> ValidationError | None:
    while exc is not None:
        if isinstance(exc, ValidationError):
            return exc
        exc = exc.__cause__ or exc.__context__
    return None


def invalid_input(exc: ValidationError) -> FairTableError:
    """A tool argument of the wrong type or missing: a specific re-prompt for the diner and the field names for the
    assistant, never pydantic's text (it carries a documentation URL and the raw input)."""
    fields = list(dict.fromkeys(str(err["loc"][-1]) for err in exc.errors() if err["loc"]))
    words = [FIELD_WORDS.get(f, f.replace("_", " ")) for f in fields]
    wanted = words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1] if words else "the details"
    detail = "; ".join(f"{err['loc'][-1]}: {err['msg']}" for err in exc.errors() if err["loc"])
    return FairTableError(
        ErrorCode.INVALID_INPUT, f"I need a valid value for {wanted}.",
        hint=detail or None,
        reason=str(exc),
    )


def error_text(error: FairTableError) -> str:
    parts = [error.message]
    if error.hint:
        parts.append(error.hint)
    parts.append(f"Next: {error.next_step.why}")
    return " ".join(parts)


class ErrorMappingMiddleware(Middleware):
    async def on_call_tool(self, context, call_next):
        try:
            return await call_next(context)
        except ArgumentError as e:  # FastMCP's own wrapper for a bad argument (type or missing)
            invalid = _validation_error(e)
            error = invalid_input(invalid) if invalid is not None else FairTableError(
                ErrorCode.INVALID_INPUT, "Some of the details are missing or not valid.")
            log.info("tool=%s code=%s reason=%s", context.message.name, error.code.value, error.reason)
            return ToolResult(content=error_text(error), structured_content=error.to_payload(), is_error=True)
        except ToolError as e:
            cause = e.error if isinstance(e, BusinessError) else e.__cause__
            if isinstance(cause, FairTableError):
                # The reason (why a token failed, Cedar error text) is for logs only.
                log.info(
                    "tool=%s code=%s rule=%s reason=%s",
                    context.message.name, cause.code.value, cause.rule_id, cause.reason,
                )
                return ToolResult(
                    content=error_text(cause), structured_content=cause.to_payload(), is_error=True
                )
            raise
