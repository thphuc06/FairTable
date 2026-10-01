"""Build the FairTable MCP server (FastMCP 3.4.7, spec 2025-11-25, Streamable HTTP).

Secure defaults (docs/PLAN.md section 3a): Origin/Host validation on, unexpected error text masked,
structured errors and -32042 handled by ``ErrorMappingMiddleware``. No LLM is called in any tool.
"""

import logging
from collections.abc import Mapping

from fastmcp import FastMCP

from server import resources
from server.config import Settings
from server.domain.clock import Clock, SystemClock
from server.domain.slot_token import SlotTokenCodec
from server.identity import HttpJwks, JwksProvider, TokenVerifier, VerifierConfig
from server.kernel import TrustKernel
from server.matcher import safe_offer
from server.middleware import ErrorMappingMiddleware
from server.ratelimit import RateLimiter
from server.store import Store, make_client
from server.telemetry import TelemetryMiddleware
from server.tools import (
    availability_check,
    mandate_status,
    reservation_confirm,
    reservation_hold,
    reservation_manage,
    restaurant_search,
    waitlist_status,
    waitlist_watch,
)
from server.tools.common import AppDeps

INSTRUCTIONS = (
    "FairTable is a restaurant's front door for booking agents. Search with restaurant_search, "
    "check slots with availability_check, and read mandate_status to know what the user has "
    "pre-approved. Every result has a short spoken_summary and a next_step. On an error, follow "
    "its next_step; never retry a refused rule with the same input."
)


def build_deps(
    settings: Settings,
    *,
    clock: Clock | None = None,
    store: Store | None = None,
    jwks: JwksProvider | None = None,
    kernel: TrustKernel | None = None,
    header_provider=None,
) -> AppDeps:
    clock = clock or SystemClock()
    store = store or Store(make_client(settings.store), settings.store.table_name)
    verifier = TokenVerifier(
        VerifierConfig(settings.issuer, settings.audience, settings.audience_claim, token_use=settings.token_use),
        jwks or HttpJwks(settings.jwks_url, clock),
        clock,
    )
    deps = AppDeps(
        settings=settings,
        clock=clock,
        store=store,
        verifier=verifier,
        kernel=kernel or TrustKernel.load(),
        slot_codec=SlotTokenCodec(
            settings.slot_token_secret.encode(), clock, settings.slot_token_ttl_s
        ),
        limiter=RateLimiter(store, clock, per_hour=settings.rate_limit_per_hour),
    )
    if header_provider is not None:
        deps.header_provider = header_provider
    deps.slot_released = lambda venue_id, date, time, group: safe_offer(deps, venue_id, date, time, group)
    return deps


def create_server(deps: AppDeps) -> FastMCP:
    mcp = FastMCP(
        "fairtable",
        instructions=INSTRUCTIONS,
        middleware=[TelemetryMiddleware(), ErrorMappingMiddleware()],  # telemetry outermost: it sees the final result
        mask_error_details=True,
    )
    for module in (
        restaurant_search, availability_check, mandate_status, reservation_hold,
        reservation_confirm, reservation_manage, waitlist_watch, waitlist_status,
    ):
        module.register(mcp, deps)
    resources.register(mcp, deps)
    return mcp


http_log = logging.getLogger("fairtable.http")


def printable_host(value: str) -> str:
    """A Host header made safe to put in a log line (quoted, control characters escaped, bounded)."""
    return repr(value[:200])


class LogRefusedHost:
    """ASGI wrapper: when the Host/Origin protection answers 421, say which Host it refused. A hosted
    platform decides what Host it forwards (AgentCore Runtime does not document it), and the operator
    needs the value to put into ``MCP_ALLOWED_HOSTS``. The Host header is not a secret."""

    def __init__(self, app) -> None:
        self.app = app

    def __getattr__(self, name):  # the wrapped Starlette app's attributes (state, router, ...) stay reachable
        return getattr(self.app, name)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        host = dict(scope["headers"]).get(b"host", b"").decode("latin-1")

        async def watch(message) -> None:
            if message["type"] == "http.response.start" and message["status"] == 421:
                http_log.warning("421 refused: Host header %s is not in MCP_ALLOWED_HOSTS", printable_host(host))
            await send(message)

        await self.app(scope, receive, watch)


def create_app(deps: AppDeps):
    """ASGI app for uvicorn. Host/Origin protection is ON; hosted profiles list their hostnames
    in ``MCP_ALLOWED_HOSTS`` / ``MCP_ALLOWED_ORIGINS``."""
    s = deps.settings
    return LogRefusedHost(_http_app(deps, s))


def _http_app(deps: AppDeps, s):
    return create_server(deps).http_app(
        host_origin_protection=True,
        stateless_http=s.stateless_http,
        allowed_hosts=s.allowed_hosts or None,
        allowed_origins=s.allowed_origins or None,
    )


def headers_of(mapping: Mapping[str, str]):
    """A header provider for tests: always returns the same lower-cased headers."""
    return lambda: {k.lower(): v for k, v in mapping.items()}
