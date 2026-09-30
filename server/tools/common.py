"""What every tool needs, and the one place that authenticates and applies PEP-1."""

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from fastmcp.server.dependencies import get_http_headers

from server.config import Settings
from server.domain.clock import Clock
from server.domain.models import Identity
from server.domain.slot_token import SlotTokenCodec
from server.domain.tool_names import ToolName
from server.identity import TokenVerifier
from server.kernel import TrustKernel, deny_to_error
from server.notify import DevInboxNotifier, Notifier
from server.ratelimit import RateLimiter
from server.store import Store


@dataclass
class AppDeps:
    settings: Settings
    clock: Clock
    store: Store
    verifier: TokenVerifier
    kernel: TrustKernel
    slot_codec: SlotTokenCodec
    limiter: RateLimiter
    # Where request headers come from. Tests swap it to drive the tools in-process.
    header_provider: Callable[[], Mapping[str, str]] = get_http_headers
    # Ids for holds, reservations and audit entries. Tests swap it for a counter.
    new_id: Callable[[], str] = lambda: uuid.uuid4().hex
    notifier: Notifier | None = None  # default: the dev inbox (see server/notify.py)
    # Called with (venue_id, date, time, table_group) after a table is freed; the waitlist matcher
    # plugs in here (server/matcher.py). Default: nothing.
    slot_released: Callable[[str, str, str, str], None] = lambda *_: None

    def __post_init__(self) -> None:
        if self.notifier is None:
            self.notifier = DevInboxNotifier(self.store, self.clock, lambda: self.new_id())


def authenticate(deps: AppDeps) -> Identity:
    """Verify the caller's token only. Write tools use this; ``run_write`` then applies PEP-1."""
    return deps.verifier.verify_headers(deps.header_provider())


def authorize(deps: AppDeps, tool: ToolName, *, party_size: int = 0) -> Identity:
    """Verify the caller's token, then run PEP-1 (G1-G4). Raises a structured error on refusal.

    ``JwksUnavailable`` is deliberately not caught: it is not the caller's fault and FastMCP masks
    it, so the request is refused without leaking why.
    """
    identity = deps.verifier.verify_headers(deps.header_provider())
    check_pep1(deps, identity, tool, party_size)
    return identity


def check_pep1(deps: AppDeps, identity: Identity, tool: ToolName, party_size: int = 0) -> None:
    decision = deps.kernel.pep1.decide(identity=identity, action=tool, party_size=party_size)
    if not decision.allowed:
        raise deny_to_error(decision)
