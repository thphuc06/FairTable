"""P1-2, P3-10: PEP-2 (P0, S1, S2, S4, S5a-c) through the policy engine: table-driven, priority, fail-closed."""

from dataclasses import replace

import pytest

from server.domain.tool_names import READ_TOOLS, ToolName
from server.kernel import DecisionKind, Pep2, PolicyContext, VenueRef, default_policy_dir
from server.kernel.engine import NO_PERMIT, POLICY_ERROR, PolicyBundle

VENUE = VenueRef("luna", agent_cover_cap=20)
BASE = PolicyContext(
    agent_tier="verified",
    active_holds_user_venue=0,
    agent_covers_booked=0,
    party_size=2,
    slot_is_drop_controlled=False,
    read_back_required=False,
    read_back_matches=False,
    pause_elapsed=False,
    user_confirmed=False,
)
# a confirm that did everything right: the terms were read back, the pause passed, the diner said yes
SPOKEN = {"read_back_required": True, "read_back_matches": True, "pause_elapsed": True, "user_confirmed": True}
HOLD, CONFIRM, MANAGE, WATCH = (
    ToolName.RESERVATION_HOLD,
    ToolName.RESERVATION_CONFIRM,
    ToolName.RESERVATION_MANAGE,
    ToolName.WAITLIST_WATCH,
)


@pytest.fixture(scope="module")
def pep2() -> Pep2:
    return Pep2.from_dir(default_policy_dir())


def decide(pep2: Pep2, action: ToolName, **overrides):
    return pep2.decide(action=action, diner_id="alice", venue=VENUE, ctx=replace(BASE, **overrides))


CASES = [
    # id, action, context overrides, kind, rule ids
    ("happy-hold", HOLD, {}, "allow", ("P0_base",)),
    ("s1-two-active-holds", HOLD, {"active_holds_user_venue": 2}, "deny", ("S1_max_active_holds",)),
    ("s1-one-active-hold-is-fine", HOLD, {"active_holds_user_venue": 1}, "allow", ("P0_base",)),
    ("s2-over-cap", HOLD, {"agent_covers_booked": 19}, "deny", ("S2_agent_share_of_covers",)),
    ("s2-exactly-at-cap", HOLD, {"agent_covers_booked": 18}, "allow", ("P0_base",)),
    # S5a-c (D-051): a confirm needs the read-back, the pause and an explicit yes
    ("s5-confirm-done-right", CONFIRM, SPOKEN, "allow", ("P0_base",)),
    ("s5a-no-read-back-token", CONFIRM, {**SPOKEN, "read_back_matches": False}, "deny",
     ("S5a_confirm_needs_read_back",)),
    ("s5b-too-soon", CONFIRM, {**SPOKEN, "pause_elapsed": False}, "deny", ("S5b_confirm_needs_the_diners_answer",)),
    ("s5c-no-explicit-yes", CONFIRM, {**SPOKEN, "user_confirmed": False}, "deny",
     ("S5c_confirm_needs_an_explicit_yes",)),
    ("s5-nothing-at-all", CONFIRM, {"read_back_required": True}, "deny",
     ("S5a_confirm_needs_read_back", "S5c_confirm_needs_an_explicit_yes")),
    ("s5-token-fits-but-too-soon-and-no-yes", CONFIRM, {**SPOKEN, "pause_elapsed": False, "user_confirmed": False},
     "deny", ("S5b_confirm_needs_the_diners_answer", "S5c_confirm_needs_an_explicit_yes")),
    # S5 applies to a confirm always (the caller sets read_back_required) and to a cancel only when it costs money
    ("s5-cancel-with-fee-done-right", MANAGE, SPOKEN, "allow", ("P0_base",)),
    ("s5-cancel-with-fee-without-read-back", MANAGE, {**SPOKEN, "read_back_matches": False}, "deny",
     ("S5a_confirm_needs_read_back",)),
    ("s5-free-cancel-needs-no-read-back", MANAGE, {}, "allow", ("P0_base",)),
    ("s5-hold-is-not-covered", HOLD, {"read_back_required": True}, "allow", ("P0_base",)),
    ("s4-drop-slot", HOLD, {"slot_is_drop_controlled": True}, "deny", ("S4_drop_slots_via_waitlist",)),
    ("p0-unverified-agent", HOLD, {"agent_tier": "unverified"}, "deny", (NO_PERMIT,)),
    ("p0-empty-tier", CONFIRM, {"agent_tier": ""}, "deny", (NO_PERMIT,)),
    # D1: a watch consumes no covers, so S2 must not block it (and S2's own next step is a watch).
    ("d1-watch-when-agent-share-is-full", WATCH, {"agent_covers_booked": 19}, "allow", ("P0_base",)),
    # combinations
    ("s1-and-s2-together", HOLD, {"active_holds_user_venue": 2, "agent_covers_booked": 19},
     "deny", ("S1_max_active_holds", "S2_agent_share_of_covers")),
    ("s1-and-s4-together", HOLD, {"active_holds_user_venue": 2, "slot_is_drop_controlled": True},
     "deny", ("S1_max_active_holds", "S4_drop_slots_via_waitlist")),
    ("forbid-beats-missing-permit", HOLD, {"agent_tier": "unverified", "active_holds_user_venue": 2},
     "deny", ("S1_max_active_holds",)),
]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c[0])
def test_pep2_cases(pep2: Pep2, case):
    _, action, overrides, kind, rules = case
    d = decide(pep2, action, **overrides)
    assert (d.kind.value, d.rule_ids) == (kind, rules)
    assert d.errors == ()


def test_all_seven_rules_are_loaded(pep2: Pep2):
    assert pep2.bundle.rule_ids == {
        "P0_base",
        "S1_max_active_holds",
        "S2_agent_share_of_covers",
        "S4_drop_slots_via_waitlist",
        "S5a_confirm_needs_read_back",
        "S5b_confirm_needs_the_diners_answer",
        "S5c_confirm_needs_an_explicit_yes",
    }


def test_every_deny_carries_a_rule_id(pep2: Pep2):
    for _, action, overrides, kind, _rules in CASES:
        d = decide(pep2, action, **overrides)
        if kind != "allow":
            assert d.rule_id


def test_read_tools_are_not_pep2_tools(pep2: Pep2):
    for tool in READ_TOOLS:
        with pytest.raises(ValueError):
            decide(pep2, tool)


# ---------------------------------------------------------------- PolicyContext discipline
def test_context_requires_every_field():
    with pytest.raises(TypeError):
        PolicyContext(agent_tier="verified")  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "overrides,exc",
    [
        ({"party_size": True}, TypeError),  # bool is not a count
        ({"party_size": "2"}, TypeError),
        ({"agent_covers_booked": -1}, ValueError),
        ({"user_confirmed": 1}, TypeError),
        ({"agent_tier": None}, TypeError),
    ],
)
def test_context_rejects_wrongly_typed_facts(overrides, exc):
    with pytest.raises(exc):
        replace(BASE, **overrides)


# ---------------------------------------------------------------- priority and fail-closed
PRIORITY = """
@id("P") permit (principal, action, resource);
@id("D1") @on_deny("deny") forbid (principal, action, resource);
@id("D2") @on_deny("deny") forbid (principal, action, resource);
"""
LOOSE_SCHEMA = """
entity Diner;
entity Venue;
action x appliesTo { principal: Diner, resource: Venue, context: {} };
"""
REQ = {"principal": 'Diner::"a"', "action": 'Action::"x"', "resource": 'Venue::"v"', "context": {}}
ENTS = [
    {"uid": {"type": "Diner", "id": "a"}, "attrs": {}, "parents": []},
    {"uid": {"type": "Venue", "id": "v"}, "attrs": {}, "parents": []},
]


def test_a_forbid_beats_a_permit_and_every_matching_forbid_is_named():
    d = PolicyBundle("t", PRIORITY, LOOSE_SCHEMA).evaluate(REQ, ENTS)
    assert (d.kind, d.rule_ids) == (DecisionKind.DENY, ("D1", "D2"))


def test_a_forbid_without_on_deny_deny_is_refused_at_load_time():
    """step_up is gone (D-051): only @on_deny("deny") is a valid annotation."""
    from server.kernel.engine import PolicyLoadError

    text = """
    @id("P") permit (principal, action, resource);
    @id("U") @on_deny("step_up") forbid (principal, action, resource);
    """
    with pytest.raises(PolicyLoadError):
        PolicyBundle("t", text, LOOSE_SCHEMA)


def test_no_matching_permit_is_a_deny():
    only_forbid_that_misses = """
    @id("P") permit (principal, action == Action::"y", resource);
    """
    schema = LOOSE_SCHEMA.replace("action x appliesTo", "action y, x appliesTo")
    d = PolicyBundle("t", only_forbid_that_misses, schema).evaluate(REQ, ENTS)
    assert (d.kind, d.rule_ids) == (DecisionKind.DENY, (NO_PERMIT,))


def test_evaluation_error_fails_closed():
    """A forbid that errors is skipped by Cedar and the permit would win. The engine must deny."""
    text = """
    @id("P") permit (principal, action, resource);
    @id("F") @on_deny("deny") forbid (principal, action, resource) when { context.limit > 1 };
    """
    schema = LOOSE_SCHEMA.replace("context: {}", "context: { limit: Long }")
    d = PolicyBundle("t", text, schema).evaluate(REQ, ENTS)  # request context lacks `limit`
    assert d.kind is DecisionKind.DENY
    assert d.rule_ids == (POLICY_ERROR,)
    assert d.errors, "the Cedar error text is kept for server-side logs"
