"""Error mapping at the FastMCP boundary.

FastMCP 3.4.7 wraps every exception raised in a tool into ``ToolError`` (server.py, the final
``except Exception``), which loses structure. This middleware unwraps the two errors we raise on
purpose (docs/PLAN.md section 3a, docs/DECISIONS.md D-014):

* ``FairTableError``          -> ``isError: true`` result with the structured payload and next_step;
* ``UrlElicitationRequiredError`` -> re-raised, so the client gets a real JSON-RPC -32042 error.

Anything else stays a masked ``ToolError`` (set ``mask_error_details=True`` on the server).
"""

import functools
import logging

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware
from fastmcp.tools import ToolResult
from mcp.shared.exceptions import UrlElicitationRequiredError

from server.domain.errors import FairTableError

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

    return wrapper


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
        except ToolError as e:
            cause = e.error if isinstance(e, BusinessError) else e.__cause__
            if isinstance(cause, UrlElicitationRequiredError):
                raise cause from None
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
