"""Build the FairTable MCP server (FastMCP 3.4.7, spec 2025-11-25, Streamable HTTP).

Secure defaults (docs/PLAN.md section 3a): Origin/Host validation on, unexpected error text masked,
structured errors and -32042 handled by ``ErrorMappingMiddleware``. No LLM is called in any tool.
"""

from collections.abc import Mapping

from fastmcp import FastMCP

from server.config import Settings
from server.domain.clock import Clock, SystemClock
from server.domain.slot_token import SlotTokenCodec
from server.identity import HttpJwks, JwksProvider, TokenVerifier, VerifierConfig
from server.kernel import TrustKernel
from server.middleware import ErrorMappingMiddleware
from server.ratelimit import RateLimiter
from server.store import Store, make_client
from server.tools import (
    availability_check,
    mandate_status,
    reservation_confirm,
    reservation_hold,
    reservation_manage,
    restaurant_search,
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
        VerifierConfig(settings.issuer, settings.audience, settings.audience_claim),
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
    return deps


def create_server(deps: AppDeps) -> FastMCP:
    mcp = FastMCP(
        "fairtable",
        instructions=INSTRUCTIONS,
        middleware=[ErrorMappingMiddleware()],
        mask_error_details=True,
    )
    for module in (
        restaurant_search, availability_check, mandate_status, reservation_hold,
        reservation_confirm, reservation_manage,
    ):
        module.register(mcp, deps)
    return mcp


def create_app(deps: AppDeps):
    """ASGI app for uvicorn. Host/Origin protection is ON; hosted profiles list their hostnames
    in ``MCP_ALLOWED_HOSTS`` / ``MCP_ALLOWED_ORIGINS``."""
    s = deps.settings
    return create_server(deps).http_app(
        host_origin_protection=True,
        allowed_hosts=s.allowed_hosts or None,
        allowed_origins=s.allowed_origins or None,
    )


def headers_of(mapping: Mapping[str, str]):
    """A header provider for tests: always returns the same lower-cased headers."""
    return lambda: {k.lower(): v for k, v in mapping.items()}
