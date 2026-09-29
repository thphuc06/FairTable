"""P1-3: PEP-1 (G1-G4) through cedarpy, including the has-guard on G4."""

import cedarpy
import pytest
from pep1_scenarios import SCENARIOS, Caller, Scenario

from server.domain.models import Identity
from server.domain.tool_names import ToolName
from server.kernel import Pep1, default_policy_dir


@pytest.fixture(scope="module")
def pep1() -> Pep1:
    return Pep1.from_dir(default_policy_dir())


def identity_of(caller: Caller) -> Identity:
    return Identity(
        sub=caller.sub,
        username=caller.username,
        agent_tier=caller.agent_tier,
        agent_id=caller.agent_id,
        scopes=frozenset(caller.scopes),
    )


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_pep1_scenarios(pep1: Pep1, scenario: Scenario):
    decision = pep1.decide(
        identity=identity_of(scenario.caller),
        action=scenario.action,
        party_size=scenario.party_size,
    )
    assert (decision.kind.value, decision.rule_ids) == (scenario.expected, scenario.expected_rules)
    assert decision.errors == ()  # the has-guard must keep evaluation error-free


def test_every_tool_is_covered_by_some_scenario():
    assert {s.action for s in SCENARIOS} == set(ToolName)


def test_g1_to_g4_are_all_loaded(pep1: Pep1):
    assert pep1.bundle.rule_ids == {
        "G1_reads_any_valid_jwt",
        "G2_writes_need_user_and_scope",
        "G3_party_size_max_10",
        "G4_verified_agent_only",
    }


def test_party_size_must_be_a_non_negative_int(pep1: Pep1):
    for bad in (-1, True, "3", 2.5):
        with pytest.raises(ValueError):
            pep1.decide(
                identity=identity_of(Caller()), action=ToolName.RESERVATION_HOLD, party_size=bad
            )


def test_odd_subject_ids_are_handled(pep1: Pep1):
    """Cedar ids are passed as structured values, so quotes or newlines in `sub` cannot inject."""
    who = Caller(sub='evil"\n} || true //')
    decision = pep1.decide(identity=identity_of(who), action=ToolName.RESERVATION_HOLD, party_size=2)
    assert decision.allowed


# ---------------------------------------------------------------- design section 6.1 regression
NAIVE_G4 = """
@id("G2") permit (principal, action, resource)
  when { principal has scope && principal.scope == "fairtable/book" };
@id("G4") forbid (principal, action, resource)
  when { principal.agent_tier != "verified" };
"""
GUARDED_G4 = """
@id("G2") permit (principal, action, resource)
  when { principal has scope && principal.scope == "fairtable/book" };
@id("G4") forbid (principal, action, resource)
  unless { principal has agent_tier && principal.agent_tier == "verified" };
"""
NO_TIER_TOKEN = [
    {"uid": {"type": "Client", "id": "c"}, "attrs": {"scope": "fairtable/book"}, "parents": []},
    {"uid": {"type": "Service", "id": "fairtable"}, "attrs": {}, "parents": []},
]
REQUEST = {
    "principal": 'Client::"c"',
    "action": 'Action::"reservation_hold"',
    "resource": 'Service::"fairtable"',
    "context": {},
}


def test_naive_g4_would_let_a_token_without_agent_tier_through():
    """Why the has-guard exists: the naive forbid errors, is skipped, and the permit wins."""
    result = cedarpy.is_authorized(REQUEST, NAIVE_G4, NO_TIER_TOKEN)
    assert result.allowed
    assert result.diagnostics.errors


def test_guarded_g4_denies_the_same_token():
    result = cedarpy.is_authorized(REQUEST, GUARDED_G4, NO_TIER_TOKEN)
    assert result.decision == cedarpy.Decision.Deny
    assert result.diagnostics.errors == []
