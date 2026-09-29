"""Approvals: what the user must approve, and where (docs/DECISIONS.md D-020).

An approval is tied to one subject (a hold to confirm, or a reservation to cancel with a fee), to
the user's ``sub`` and to a hash of the exact terms. It expires after 15 minutes and can be used
once. The consent URL only *names* the approval; the consent page requires a login as the same user.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from server.domain.booking import (
    APPROVAL_DECLINED,
    APPROVAL_PENDING,
    APPROVAL_TTL_S,
    KIND_CANCEL_FEE,
    Approval,
    approval_is_expired,
    terms_hash,
)
from server.domain.clock import iso_z
from server.domain.errors import ErrorCode, FairTableError
from server.tools.common import AppDeps
from server.tools.present import cancel_policy_text_from_terms, say_date, say_money, say_time


@dataclass(frozen=True)
class ApprovalRequest:
    """What an operation asks the user to approve."""

    subject_id: str
    kind: str
    sub: str
    venue_id: str
    terms: dict[str, Any]


def consent_url(base_url: str, subject_id: str) -> str:
    return f"{base_url.rstrip('/')}/consent/{subject_id}"


def describe(terms: dict[str, Any], kind: str) -> str:
    """One plain sentence for the notification, the elicitation prompt and the consent page."""
    what = (
        f"{terms['party_size']} at {terms['restaurant']} on {say_date(terms['date'])} "
        f"at {say_time(terms['time'])}"
    )
    if kind == KIND_CANCEL_FEE:
        return (
            f"Cancel the booking for {what}. A cancellation fee of "
            f"{say_money(terms['fee_cents'])} applies."
        )
    return f"Confirm a table for {what}. {cancel_policy_text_from_terms(terms)}"


def ensure_approval(deps: AppDeps, request: ApprovalRequest) -> tuple[Approval, str]:
    """Return the pending approval for this request (creating and announcing it once)."""
    now = deps.clock.now()
    now_iso = iso_z(now)
    digest = terms_hash(request.terms)
    existing = deps.store.get_approval(request.subject_id)
    if (
        existing is not None
        and existing.terms_hash == digest
        and existing.sub == request.sub
        and existing.status == APPROVAL_PENDING
        and not approval_is_expired(existing, now_iso)
    ):
        return existing, consent_url(deps.settings.consent_base_url, request.subject_id)

    fresh = Approval(
        subject_id=request.subject_id, kind=request.kind, sub=request.sub, venue_id=request.venue_id,
        terms_hash=digest, terms=request.terms, status=APPROVAL_PENDING, created_at=now_iso,
        expires_at=iso_z(now + timedelta(seconds=APPROVAL_TTL_S)),
    )
    deps.store.replace_approval(fresh)
    url = consent_url(deps.settings.consent_base_url, request.subject_id)
    deps.notifier.notify(
        request.sub, subject="Approve your booking request",
        body=describe(request.terms, request.kind), url=url,
    )
    return fresh, url


def declined_error() -> FairTableError:
    return FairTableError(
        ErrorCode.CONSENT_DECLINED, "The user declined this request.",
        hint="Do not ask again for the same booking; offer alternatives instead.",
    )


def is_declined(approval: Approval | None, *, sub: str, terms_digest: str) -> bool:
    return (
        approval is not None
        and approval.status == APPROVAL_DECLINED
        and approval.sub == sub
        and approval.terms_hash == terms_digest
    )
