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
    message: str | None = None  # what to say instead of the generic "not allowed by the booking rules"


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
    "S6_one_booking_per_restaurant_day": Guidance(
        ErrorCode.POLICY_DENIED,
        "The user already has a confirmed table at this restaurant on that day.",
        NextStep(
            "Tell the user they already have a table there that day; offer to look at it or cancel it first.",
            ToolName.RESERVATION_MANAGE,
        ),
        "You already have a table at this restaurant that day.",
    ),
    "S2_agent_share_of_covers": Guidance(
        ErrorCode.POLICY_DENIED,
        "Agent bookings for that day are full. Suggest calling the restaurant or joining the waitlist.",
        NextStep("Join the waitlist.", ToolName.WAITLIST_WATCH),
    ),
    # D-051: the spoken confirmation. Nothing is booked; the messages are phrased for the assistant to act on.
    "S5a_confirm_needs_read_back": Guidance(
        ErrorCode.CONFIRMATION_REQUIRED,
        "The details have not been read back to the user yet, or the read_back_token is missing, belongs to "
        "other terms, or is too old.",
        NextStep(
            "Read the details to the user (use the read_back sentence), ask for a yes, then repeat this call "
            "with the read_back_token and user_confirmed set to true."
        ),
        "The user has not heard these details yet.",
    ),
    "S5b_confirm_needs_the_diners_answer": Guidance(
        ErrorCode.CONFIRMATION_REQUIRED,
        "The user has not had time to answer: the details were handed over only a moment ago.",
        NextStep("Wait for the user's answer, then repeat this call once they have said yes."),
        "I am waiting for the user's answer.",
    ),
    "S5c_confirm_needs_an_explicit_yes": Guidance(
        ErrorCode.CONFIRMATION_REQUIRED,
        "The user's yes is required, and user_confirmed was not set to true.",
        NextStep("Ask the user whether to go ahead; set user_confirmed to true only after they say yes."),
        "I need the user's yes first.",
    ),
    "S4_drop_slots_via_waitlist": Guidance(
        ErrorCode.DROP_CONTROLLED,
        "This slot is released through a Fair Drop, not by direct booking.",
        NextStep("Enter the draw for this slot instead.", ToolName.WAITLIST_WATCH),
    ),
}

# Which permit was missing when nothing matched, per bundle.
NO_PERMIT_RULE = {"pep1": "G2_writes_need_user_and_scope", "pep2": "P0_base"}

SAFE_FAILURE = Guidance(
    ErrorCode.POLICY_DENIED,
    "The rule check could not be completed, so the request was refused to be safe.",
    CALL_THE_RESTAURANT,
)


def error_for_rule(rule_id: str) -> FairTableError:
    """The error of a rule that a database condition enforced after the policy check passed (the race the rule cannot see)."""
    guidance = GUIDANCE[rule_id]
    return FairTableError(
        guidance.code,
        guidance.message or "The request is not allowed by the restaurant's booking rules.",
        hint=guidance.hint,
        rule_id=rule_id,
        next_step=guidance.next_step,
        reason=f"{rule_id}:database_condition",
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
        guidance.message or "The request is not allowed by the restaurant's booking rules.",
        hint=guidance.hint,
        rule_id=shown,
        next_step=guidance.next_step,
        reason=reason,
    )
