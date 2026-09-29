"""P1-2/P1-3: denied decisions become structured errors that tell the agent how to recover."""

import pytest

from server.domain.errors import ErrorCode
from server.domain.tool_names import ToolName
from server.kernel import Decision, DecisionKind, deny_to_error
from server.kernel.engine import NO_PERMIT, POLICY_ERROR
from server.kernel.guidance import GUIDANCE, NO_PERMIT_RULE


def deny(*rule_ids, source="pep2", errors=()):
    return Decision(DecisionKind.DENY, tuple(rule_ids), source, errors)


@pytest.mark.parametrize("rule_id", sorted(GUIDANCE))
def test_every_deny_rule_maps_to_a_hint_and_next_step(rule_id):
    payload = deny_to_error(deny(rule_id)).to_payload()
    assert payload["rule_id"] == rule_id
    assert payload["hint"]
    assert payload["next_step"]["why"]


def test_s2_points_to_the_waitlist_and_is_not_self_blocking():
    payload = deny_to_error(deny("S2_agent_share_of_covers")).to_payload()
    assert payload["error"] == ErrorCode.POLICY_DENIED
    assert payload["next_step"]["tool"] == ToolName.WAITLIST_WATCH


def test_s4_is_reported_as_drop_controlled():
    err = deny_to_error(deny("S4_drop_slots_via_waitlist"))
    assert err.code is ErrorCode.DROP_CONTROLLED
    assert err.next_step.tool is ToolName.WAITLIST_WATCH


@pytest.mark.parametrize("source", ["pep1", "pep2"])
def test_no_permit_names_the_missing_permit(source):
    err = deny_to_error(deny(NO_PERMIT, source=source))
    assert err.rule_id == NO_PERMIT_RULE[source]
    assert err.code is ErrorCode.POLICY_DENIED


def test_policy_error_is_refused_safely_and_details_stay_server_side():
    err = deny_to_error(deny(POLICY_ERROR, errors=("attribute x not found",)))
    payload = err.to_payload()
    assert payload["rule_id"] == POLICY_ERROR
    assert "attribute" not in str(payload)
    assert "attribute x not found" in err.reason


def test_multiple_rules_use_the_first_for_the_message_and_all_for_the_log():
    err = deny_to_error(deny("S1_max_active_holds", "S2_agent_share_of_covers"))
    assert err.rule_id == "S1_max_active_holds"
    assert "S2_agent_share_of_covers" in err.reason


def test_only_deny_decisions_can_become_errors():
    with pytest.raises(ValueError):
        deny_to_error(Decision(DecisionKind.STEP_UP, ("S3_confirm_needs_mandate",), "pep2"))
    with pytest.raises(ValueError):
        deny_to_error(Decision(DecisionKind.ALLOW, ("P0_base",), "pep2"))
