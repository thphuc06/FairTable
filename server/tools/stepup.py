"""Step-up: turn a PEP-2 ``STEP_UP`` decision into something the agent can act on (D-016, D-020).

Rung 1: the client declared URL-mode elicitation -> JSON-RPC -32042 with the consent URL
        (``ErrorMappingMiddleware`` lets it through; MCP spec 2025-11-25).
Rung 2: otherwise -> an ``isError`` result with ``consent_url`` (code CONSENT_REQUIRED for a
        confirm, FEE_APPLIES for a cancel with a fee), phrased for the agent to say aloud.
Either way the approval happens on the consent page, outside the conversation.
"""

import logging
from datetime import datetime
from typing import NoReturn

from fastmcp.server.dependencies import get_context
from mcp.shared.exceptions import UrlElicitationRequiredError
from mcp.types import ElicitRequestURLParams

from server.consent import describe, ensure_approval
from server.domain.booking import KIND_CANCEL_FEE, KIND_CONFIRM
from server.domain.clock import iso_z
from server.domain.errors import ErrorCode, FairTableError
from server.lifecycle import extend_hold
from server.pipeline import StepUpRequired
from server.tools.common import AppDeps

log = logging.getLogger("fairtable.stepup")


def client_supports_url_elicitation() -> bool:
    """True only if the client declared ``elicitation.url`` at initialize.

    The SDK's ``check_client_capability`` only tests that *some* elicitation capability exists, and
    an empty ``elicitation: {}`` means form mode only (spec), so read the ``url`` field directly.
    Stateless requests have no initialize params: answer False (rung 2 always works).
    """
    try:
        params = get_context().session.client_params
        elicitation = params.capabilities.elicitation if params else None
        return elicitation is not None and elicitation.url is not None
    except (RuntimeError, AttributeError):
        return False


def raise_step_up(deps: AppDeps, exc: StepUpRequired) -> NoReturn:
    request = exc.op.approval_request()
    approval, url = ensure_approval(deps, request)
    now = deps.clock.now()
    if request.kind == KIND_CONFIRM:
        # Give the user the whole approval window: the hold must outlive their trip to the phone.
        extend_hold(deps.store, exc.op.hold, approval.expires_at, iso_z(now))
    minutes = max(1, -(-int((datetime.fromisoformat(approval.expires_at) - now).total_seconds()) // 60))
    text = describe(request.terms, request.kind)
    log.info("step-up %s for %s via %s", exc.decision.rule_ids, exc.identity.sub, request.subject_id)

    if client_supports_url_elicitation():
        raise UrlElicitationRequiredError(
            [ElicitRequestURLParams(
                mode="url",
                message=f"Please approve on your phone within {minutes} minutes: {text}", url=url,
                elicitationId=request.subject_id,
            )]
        )
    is_fee = request.kind == KIND_CANCEL_FEE
    raise FairTableError(
        ErrorCode.FEE_APPLIES if is_fee else ErrorCode.CONSENT_REQUIRED,
        "The user must approve this on their phone before it can go ahead.",
        hint=f"{text} Tell the user: an approval request is waiting on your phone and they have about "
             f"{minutes} minutes. Open {url} to approve or decline, then ask me to try again.",
        rule_id=exc.decision.rule_id,
        consent_url=url,
        details={"terms": request.terms},
    )
