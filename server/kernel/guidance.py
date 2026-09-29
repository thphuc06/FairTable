"""Turn a denied ``Decision`` into a structured error that tells the agent how to recover."""

from dataclasses import dataclass

from server.domain.errors import ErrorCode, FairTableError, NextStep
from server.domain.tool_names import ToolName
from server.kernel.engine import NO_PERMIT, POLICY_ERROR, Decision, DecisionKind


@dataclass(frozen=True)
class Guidance:
    code: ErrorCode
    hint: str
    next_step: NextStep


CALL_THE_RESTAURANT = NextStep("Suggest that the user calls the restaurant.")

GUIDANCE: dict[str, Guidance] = {
    "G2_writes_need_user_and_scope": Guidance(
        ErrorCode.POLICY_DENIED,
        "Booking needs a signed-in user who has granted the fairtable/book scope.",
        NextStep("Ask the user to sign in and allow booking, then retry."),
    ),
    "G3_party_size_max_10": Guidance(
        ErrorCode.POLICY_DENIED,
        "Groups larger than 10 need to call the restaurant directly.",
        CALL_THE_RESTAURANT,
    ),
    "G4_verified_agent_only": Guidance(
        ErrorCode.POLICY_DENIED,
        "Only verified agents can make or change bookings.",
        CALL_THE_RESTAURANT,
    ),
    "P0_base": Guidance(
        ErrorCode.POLICY_DENIED,
        "This agent is not verified for booking at this restaurant.",
        CALL_THE_RESTAURANT,
    ),
    "S1_max_active_holds": Guidance(
        ErrorCode.POLICY_DENIED,
        "The user already holds the maximum number of active holds at this restaurant.",
        NextStep(
            "Confirm or cancel an existing hold first.", ToolName.RESERVATION_MANAGE
        ),
    ),
    "S2_agent_share_of_covers": Guidance(
        ErrorCode.POLICY_DENIED,
        "Agent bookings for that day are full. Suggest calling the restaurant or joining the waitlist.",
        NextStep("Join the waitlist.", ToolName.WAITLIST_WATCH),
    ),
    "S4_drop_slots_via_waitlist": Guidance(
        ErrorCode.DROP_CONTROLLED,
        "This slot is released through a Fair Drop, not by direct booking.",
        NextStep("Enter the drop with waitlist_watch.", ToolName.WAITLIST_WATCH),
    ),
}

# Which permit was missing when nothing matched, per bundle.
NO_PERMIT_RULE = {"pep1": "G2_writes_need_user_and_scope", "pep2": "P0_base"}

SAFE_FAILURE = Guidance(
    ErrorCode.POLICY_DENIED,
    "The rule check could not be completed, so the request was refused to be safe.",
    CALL_THE_RESTAURANT,
)


def deny_to_error(decision: Decision) -> FairTableError:
    if decision.kind is not DecisionKind.DENY:
        raise ValueError("only DENY decisions become errors")
    rule_id = decision.rule_id
    reason = ",".join(decision.rule_ids)
    if rule_id == POLICY_ERROR:
        guidance, shown = SAFE_FAILURE, POLICY_ERROR
        reason = f"{reason}: {' | '.join(decision.errors)}"
    else:
        shown = NO_PERMIT_RULE.get(decision.source, "unknown") if rule_id == NO_PERMIT else rule_id
        guidance = GUIDANCE.get(shown or "", SAFE_FAILURE)
    return FairTableError(
        guidance.code,
        "The request is not allowed by the restaurant's booking rules.",
        hint=guidance.hint,
        rule_id=shown,
        next_step=guidance.next_step,
        reason=reason,
    )
