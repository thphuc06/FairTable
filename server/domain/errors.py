"""Structured tool errors (``isError: true``). Every error tells the agent what to do next."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from server.domain.tool_names import ToolName


class ErrorCode(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    INVALID_SLOT_TOKEN = "INVALID_SLOT_TOKEN"
    SLOT_TOKEN_EXPIRED = "SLOT_TOKEN_EXPIRED"
    RATE_LIMITED = "RATE_LIMITED"
    NOT_FOUND = "NOT_FOUND"
    SLOT_TAKEN = "SLOT_TAKEN"
    POLICY_DENIED = "POLICY_DENIED"
    DROP_CONTROLLED = "DROP_CONTROLLED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    HOLD_EXPIRED = "HOLD_EXPIRED"
    FEE_APPLIES = "FEE_APPLIES"
    CONSENT_DECLINED = "CONSENT_DECLINED"
    ALREADY_ENTERED = "ALREADY_ENTERED"
    DROP_CLOSED = "DROP_CLOSED"


@dataclass(frozen=True)
class NextStep:
    """What the agent should do next. ``tool`` is None when no tool helps (ask the user)."""

    why: str
    tool: ToolName | None = None

    def to_payload(self) -> dict[str, Any]:
        return {"tool": self.tool.value if self.tool else None, "why": self.why}


DEFAULT_NEXT_STEP: dict[ErrorCode, NextStep] = {
    ErrorCode.INVALID_INPUT: NextStep("Fix the input and call the tool again."),
    ErrorCode.UNAUTHENTICATED: NextStep(
        "The user must sign in again. Do not retry with the same token."
    ),
    ErrorCode.INVALID_SLOT_TOKEN: NextStep(
        "Fetch fresh slots and use the new slot_token.", ToolName.AVAILABILITY_CHECK
    ),
    ErrorCode.SLOT_TOKEN_EXPIRED: NextStep(
        "Fetch fresh slots and use the new slot_token.", ToolName.AVAILABILITY_CHECK
    ),
    ErrorCode.RATE_LIMITED: NextStep(
        "Register once; you will be notified when a table opens.", ToolName.WAITLIST_WATCH
    ),
    ErrorCode.NOT_FOUND: NextStep("Search again.", ToolName.RESTAURANT_SEARCH),
    ErrorCode.SLOT_TAKEN: NextStep(
        "Pick another slot, or join the waitlist.", ToolName.AVAILABILITY_CHECK
    ),
    ErrorCode.POLICY_DENIED: NextStep(
        "Suggest calling the restaurant or joining the waitlist.", ToolName.WAITLIST_WATCH
    ),
    ErrorCode.DROP_CONTROLLED: NextStep(
        "This slot is released through a Fair Drop; enter it with waitlist_watch.",
        ToolName.WAITLIST_WATCH,
    ),
    ErrorCode.IDEMPOTENCY_CONFLICT: NextStep(
        "Use a new idempotency_key for different parameters, or repeat the original parameters."
    ),
    ErrorCode.HOLD_EXPIRED: NextStep(
        "The hold expired. Start again with fresh slots.", ToolName.AVAILABILITY_CHECK
    ),
    ErrorCode.FEE_APPLIES: NextStep(
        "Ask the user to approve the fee, then repeat with the same idempotency_key.",
        ToolName.RESERVATION_MANAGE,
    ),
    ErrorCode.CONSENT_DECLINED: NextStep("The user declined. Do not retry; offer alternatives."),
    ErrorCode.ALREADY_ENTERED: NextStep("Check the status.", ToolName.WAITLIST_STATUS),
    ErrorCode.DROP_CLOSED: NextStep("Look for other slots.", ToolName.AVAILABILITY_CHECK),
}


class FairTableError(Exception):
    """A business error the agent can act on. The tools layer turns it into ``isError`` output."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        hint: str | None = None,
        rule_id: str | None = None,
        retry_after_s: int | None = None,
        next_step: NextStep | None = None,
        consent_url: str | None = None,
        reason: str | None = None,
    ) -> None:
        super().__init__(f"{code.value}: {message}")
        self.code = code
        self.message = message
        self.hint = hint
        self.rule_id = rule_id
        self.retry_after_s = retry_after_s
        self.next_step = next_step or DEFAULT_NEXT_STEP[code]
        self.consent_url = consent_url
        # Server-side only (logs, audit). Never sent to the agent: it could help an attacker.
        self.reason = reason

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "error": self.code.value,
            "message": self.message,
            "next_step": self.next_step.to_payload(),
        }
        if self.hint:
            payload["hint"] = self.hint
        if self.rule_id:
            payload["rule_id"] = self.rule_id
        if self.retry_after_s is not None:
            payload["retry_after_s"] = self.retry_after_s
        if self.consent_url:
            payload["consent_url"] = self.consent_url
        return payload
