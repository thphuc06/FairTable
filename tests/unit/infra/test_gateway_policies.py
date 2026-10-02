"""P2-6: the Gateway's Cedar policies (G1-G4), checked locally with cedarpy before anything is deployed.

The service offers no way to read the Cedar schema it generates from the gateway's tools, so the schema here
(`infra/gateway/policies/local.cedarschema`) is an approximation; the real validation happens when the policies are
created (`FAIL_ON_ANY_FINDINGS`). The behaviour is checked with the scenario table that also drives the local G1-G4
(`tests/unit/kernel/pep1_scenarios.py`, plan decision D5)."""

import importlib.util
import re
import sys
from pathlib import Path

import cedarpy
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests" / "unit" / "kernel"))
from pep1_scenarios import SCENARIOS, Caller  # noqa: E402

from server.domain.tool_names import ToolName  # noqa: E402

spec = importlib.util.spec_from_file_location("gateway_policies", ROOT / "infra" / "cdk" / "stacks" / "gateway_policies.py")
gp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gp)

GATEWAY = "arn:aws:bedrock-agentcore:us-east-1:123456789012:gateway/fairtable-gw-abc1234567"
SCHEMA = (ROOT / "infra" / "gateway" / "policies" / "local.cedarschema").read_text(encoding="utf-8")
POLICIES = gp.policy_files()
RENDERED = {name: gp.render(text, GATEWAY) for name, text in POLICIES.items()}
POLICY_SET = "\n".join(RENDERED[n] for n in sorted(RENDERED))
READS = {ToolName.RESTAURANT_SEARCH, ToolName.AVAILABILITY_CHECK, ToolName.WAITLIST_STATUS}
WRITES = set(ToolName) - READS
HAS_PARTY_SIZE = {ToolName.RESTAURANT_SEARCH, ToolName.AVAILABILITY_CHECK, ToolName.WAITLIST_WATCH}
# What the gateway cannot see: these tools take a slot token or an id, so a party above 10 is the server's to refuse.
SERVER_SIDE_ONLY = {"write-party-of-11": "allow"}


def decide(caller: Caller, tool: ToolName, party_size: int | None):
    tags = {}
    if caller.username:
        tags["username"] = caller.username
    if caller.scopes:
        tags["scope"] = " ".join(caller.scopes)
    if caller.agent_tier:
        tags["agent_tier"] = caller.agent_tier
    if caller.agent_id:
        tags["agent_id"] = caller.agent_id
    entities = [
        {"uid": {"type": "AgentCore::OAuthUser", "id": caller.sub}, "attrs": {}, "parents": [], "tags": tags},
        {"uid": {"type": "AgentCore::Gateway", "id": GATEWAY}, "attrs": {}, "parents": []},
    ]
    context_input = {"party_size": party_size} if party_size and tool in HAS_PARTY_SIZE else {}
    request = {
        "principal": f'AgentCore::OAuthUser::"{caller.sub}"',
        "action": f'AgentCore::Action::"ft___{tool.value}"',
        "resource": f'AgentCore::Gateway::"{GATEWAY}"',
        "context": {"input": context_input},
    }
    return cedarpy.is_authorized(request, POLICY_SET, entities)


# ------------------------------------------------------------------------------------------------ the files
def test_there_are_six_policies_with_valid_names_and_sizes():
    assert sorted(POLICIES) == [
        "ft_g1_reads_any_valid_jwt", "ft_g2_writes_need_user_and_scope", "ft_g3_party_size_availability_check",
        "ft_g3_party_size_restaurant_search", "ft_g3_party_size_waitlist_watch", "ft_g4_verified_agent_only",
    ]
    for name, text in RENDERED.items():
        assert gp.NAME_PATTERN.fullmatch(name)
        assert gp.MIN_STATEMENT_CHARS <= len(text) <= gp.MAX_STATEMENT_CHARS
        assert "//" not in text and gp.PLACEHOLDER not in text and GATEWAY in text


def test_a_policy_without_the_placeholder_is_refused():
    with pytest.raises(ValueError):
        gp.render('permit (principal, action, resource is AgentCore::Gateway);', GATEWAY)


def test_every_policy_validates_against_the_approximate_schema():
    result = cedarpy.validate_policies(POLICY_SET, SCHEMA)
    assert result.validation_passed, result


def test_a_policy_that_reads_an_optional_input_without_a_guard_would_fail_validation():
    """The service requires the `has` guard on an optional parameter (documented); so does the local schema."""
    unguarded = POLICY_SET + (
        f'\nforbid (principal is AgentCore::OAuthUser, action == AgentCore::Action::"ft___availability_check", '
        f'resource == AgentCore::Gateway::"{GATEWAY}") when {{ context.input.party_size > 10 }};'
    )
    assert not cedarpy.validate_policies(unguarded, SCHEMA).validation_passed


def test_a_policy_naming_actions_names_the_gateway_not_a_wildcard():
    for text in RENDERED.values():
        assert f'resource == AgentCore::Gateway::"{GATEWAY}"' in text
        assert not re.search(r"resource\s*[,)]", text)  # a bare resource is rejected by the service


def test_the_tool_lists_match_the_local_policies():
    """Drift guard: the reads and writes named here are the ones the server's own G1 and G2 name."""
    def tools_in(text):
        return set(re.findall(r'"ft___(\w+)"', text))

    def local_tools(path):
        return set(re.findall(r'Action::"(\w+)"', (ROOT / "policies" / path).read_text(encoding="utf-8")))

    assert tools_in(RENDERED["ft_g1_reads_any_valid_jwt"]) == {t.value for t in READS} == local_tools("g1_reads_any_valid_jwt.cedar")
    assert tools_in(RENDERED["ft_g2_writes_need_user_and_scope"]) == {t.value for t in WRITES} == local_tools("g2_writes_need_user_and_scope.cedar")
    assert tools_in(RENDERED["ft_g4_verified_agent_only"]) == {t.value for t in WRITES} == local_tools("g4_verified_agent_only.cedar")


def test_the_party_size_limit_is_the_same_number_as_the_local_rule():
    local = (ROOT / "policies" / "g3_party_size_max_10.cedar").read_text(encoding="utf-8")
    assert "context.party_size > 10" in local
    for name in ("ft_g3_party_size_availability_check", "ft_g3_party_size_restaurant_search", "ft_g3_party_size_waitlist_watch"):
        assert "context.input.party_size > 10" in RENDERED[name]


# ------------------------------------------------------------------------------------------ the behaviour
@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_the_gateway_policies_decide_like_the_local_ones(scenario):
    expected = SERVER_SIDE_ONLY.get(scenario.id, scenario.expected)
    result = decide(scenario.caller, scenario.action, scenario.party_size)
    assert result.decision.value.lower() == expected, (scenario.id, result.diagnostics)
    assert not result.diagnostics.errors  # the has / hasTag guards keep evaluation error-free


def test_the_one_scenario_the_gateway_cannot_see_is_the_hold_with_a_big_party():
    assert SERVER_SIDE_ONLY == {"write-party-of-11": "allow"}
    scenario = next(s for s in SCENARIOS if s.id == "write-party-of-11")
    assert scenario.action is ToolName.RESERVATION_HOLD  # no party_size in its input


@pytest.mark.parametrize("tool", sorted(HAS_PARTY_SIZE, key=lambda t: t.value))
def test_every_tool_with_a_party_size_refuses_a_party_of_eleven_and_accepts_ten(tool):
    caller = Caller()
    assert decide(caller, tool, 11).decision.value == "Deny"
    assert decide(caller, tool, 10).decision.value == "Allow"


def test_a_search_without_a_party_size_is_allowed():
    assert decide(Caller(), ToolName.RESTAURANT_SEARCH, None).decision.value == "Allow"


def test_the_agent_claims_can_not_be_replaced_by_a_look_alike_scope():
    """`like` matches substrings (documented): a scope that merely contains the text would pass G2, so the
    trigger must only ever put the exact scope. Pinned here so a change to the scope name shows up."""
    assert decide(Caller(scopes=("fairtable/book:admin",)), ToolName.RESERVATION_HOLD, None).decision.value == "Allow"
    assert decide(Caller(scopes=("fairtable/read",)), ToolName.RESERVATION_HOLD, None).decision.value == "Deny"


def test_a_token_with_a_null_or_missing_agent_tier_is_refused_on_every_write_tool():
    for tool in WRITES:
        assert decide(Caller(agent_tier=None), tool, None).decision.value == "Deny"


def test_the_bot_sees_the_reads_and_none_of_the_writes():
    bot = Caller(sub="bot", username=None, agent_tier=None, agent_id=None)
    allowed = {t for t in ToolName if decide(bot, t, None).decision.value == "Allow"}
    assert allowed == READS


def test_the_unverified_agent_sees_the_reads_and_none_of_the_writes():
    shady = Caller(agent_tier="unverified")
    assert {t for t in ToolName if decide(shady, t, None).decision.value == "Allow"} == READS


def test_the_verified_user_sees_every_tool():
    assert {t for t in ToolName if decide(Caller(), t, None).decision.value == "Allow"} == set(ToolName)


def test_the_first_deploy_has_only_the_permits_and_the_second_adds_every_forbid():
    permits = gp.policy_files(permits_only=True)
    assert sorted(permits) == ["ft_g1_reads_any_valid_jwt", "ft_g2_writes_need_user_and_scope"]
    assert set(POLICIES) - set(permits) == {n for n in POLICIES if n.startswith(("ft_g3_", "ft_g4_"))}
    assert not any(gp.is_permit(POLICIES[n]) for n in set(POLICIES) - set(permits))
