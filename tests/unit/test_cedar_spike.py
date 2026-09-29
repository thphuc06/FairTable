"""P0-2: Cedar spike (cedarpy 4.12.1).

Verifies against the installed package (not from memory):
  * API: ``cedarpy.is_authorized(request, policies, entities)`` -> ``AuthzResult``
    (``.decision``, ``.diagnostics.reasons``, ``.diagnostics.errors``,
    ``.diagnostics.id_annotations_by_reason``) and ``cedarpy.policies_to_json_str``.
  * The 7 scenarios of design section 6.2 against ``policies/*.cedar``.
  * The mapping ``policyN -> (rule_id, on_deny)`` built from ``policies_to_json_str``.
  * The ``has``-guard vs naive G4 behaviour of design section 6.1.

The helpers here are spike-level only; the real loader lives in ``server/kernel`` (P1-2).
"""

import json
import pathlib
from dataclasses import dataclass

import cedarpy
import pytest

POLICY_DIR = pathlib.Path(__file__).resolve().parents[2] / "policies"


# --------------------------------------------------------------------------- helpers
def load_pep2_text() -> str:
    """Concatenate the PEP-2 files (p*, s*) in a stable order."""
    files = sorted(POLICY_DIR.glob("[ps]*.cedar"))
    assert files, "no PEP-2 policy files found"
    return "\n".join(f.read_text(encoding="utf-8") for f in files)


def rule_table(policy_text: str) -> dict[str, tuple[str, str | None]]:
    """policyN -> (@id, @on_deny), derived from policies_to_json_str (never by position)."""
    parsed = json.loads(cedarpy.policies_to_json_str(policy_text))
    table = {}
    for pid, pol in parsed["staticPolicies"].items():
        ann = pol.get("annotations", {})
        table[pid] = (ann["id"], ann.get("on_deny"))
    return table


@dataclass(frozen=True)
class Decision:
    kind: str  # "allow" | "deny" | "step_up"
    rule_ids: tuple[str, ...] = ()


def decide(policy_text, request, entities) -> Decision:
    """deny > step_up > allow; no matching permit -> deny (rule 'no_permit')."""
    table = rule_table(policy_text)
    res = cedarpy.is_authorized(request, policy_text, entities)
    assert res.diagnostics.errors == [], res.diagnostics.errors
    matched = [table[r] for r in res.diagnostics.reasons]
    if res.allowed:
        return Decision("allow", tuple(rid for rid, _ in matched))
    if not matched:
        return Decision("deny", ("no_permit",))
    denies = [rid for rid, od in matched if od == "deny"]
    steps = [rid for rid, od in matched if od == "step_up"]
    if denies:
        return Decision("deny", tuple(denies))
    return Decision("step_up", tuple(steps))


ENTITIES = [
    {"uid": {"type": "Diner", "id": "alice"}, "attrs": {}, "parents": []},
    {"uid": {"type": "Venue", "id": "luna"}, "attrs": {"agent_cover_cap": 20}, "parents": []},
]

BASE_CTX = {
    "agent_tier": "verified",
    "active_holds_user_venue": 0,
    "agent_covers_booked": 0,
    "party_size": 2,
    "mandate_covers_booking": True,
    "slot_is_drop_controlled": False,
    "cancel_fee_cents": 0,
    "cancel_fee_acknowledged": False,
}


def req(action: str, **ctx_overrides) -> dict:
    return {
        "principal": 'Diner::"alice"',
        "action": f'Action::"{action}"',
        "resource": 'Venue::"luna"',
        "context": {**BASE_CTX, **ctx_overrides},
    }


@pytest.fixture(scope="module")
def pep2() -> str:
    return load_pep2_text()


# --------------------------------------------------------------------------- API facts
def test_api_surface_exists():
    for name in ("is_authorized", "policies_to_json_str", "PolicySet", "Entities", "Decision"):
        assert hasattr(cedarpy, name), name


def test_policy_ids_are_policyN_and_annotations_survive_json_export(pep2):
    table = rule_table(pep2)
    assert len(table) == 6
    assert all(k.startswith("policy") for k in table)
    assert sorted(v[0] for v in table.values()) == [
        "P0_base",
        "S1_max_active_holds",
        "S2_agent_share_of_covers",
        "S3_confirm_needs_mandate",
        "S3b_cancel_fee_needs_ack",
        "S4_drop_slots_via_waitlist",
    ]
    assert {v[0]: v[1] for v in table.values()} == {
        "P0_base": None,
        "S1_max_active_holds": "deny",
        "S2_agent_share_of_covers": "deny",
        "S3_confirm_needs_mandate": "step_up",
        "S3b_cancel_fee_needs_ack": "step_up",
        "S4_drop_slots_via_waitlist": "deny",
    }


def test_reasons_are_policyN_not_the_id_annotation(pep2):
    res = cedarpy.is_authorized(req("reservation_hold"), pep2, ENTITIES)
    assert res.allowed
    assert res.diagnostics.reasons == [next(k for k, v in rule_table(pep2).items() if v[0] == "P0_base")]
    # cedarpy also exposes the @id directly; the on_deny still needs policies_to_json_str.
    assert list(res.diagnostics.id_annotations_by_reason.values()) == ["P0_base"]


# --------------------------------------------------------------------------- the 7 scenarios
def test_scenario_1_happy_path(pep2):
    assert decide(pep2, req("reservation_hold"), ENTITIES) == Decision("allow", ("P0_base",))


def test_scenario_2_s1_too_many_active_holds(pep2):
    d = decide(pep2, req("reservation_hold", active_holds_user_venue=2), ENTITIES)
    assert d == Decision("deny", ("S1_max_active_holds",))


def test_scenario_3_s2_agent_share_of_covers(pep2):
    # 19 booked + 2 > cap 20
    d = decide(pep2, req("reservation_hold", agent_covers_booked=19), ENTITIES)
    assert d == Decision("deny", ("S2_agent_share_of_covers",))
    # exactly at the cap is fine
    assert decide(pep2, req("reservation_hold", agent_covers_booked=18), ENTITIES).kind == "allow"


def test_scenario_4_s3_confirm_without_mandate_needs_step_up(pep2):
    d = decide(pep2, req("reservation_confirm", mandate_covers_booking=False), ENTITIES)
    assert d == Decision("step_up", ("S3_confirm_needs_mandate",))


def test_scenario_5_s3_confirm_with_mandate_allowed(pep2):
    d = decide(pep2, req("reservation_confirm", mandate_covers_booking=True), ENTITIES)
    assert d == Decision("allow", ("P0_base",))


def test_scenario_6_s4_drop_slot_only_via_waitlist(pep2):
    d = decide(pep2, req("reservation_hold", slot_is_drop_controlled=True), ENTITIES)
    assert d == Decision("deny", ("S4_drop_slots_via_waitlist",))


def test_scenario_7_unverified_agent_has_no_matching_permit(pep2):
    d = decide(pep2, req("reservation_hold", agent_tier="unverified"), ENTITIES)
    assert d == Decision("deny", ("no_permit",))


# --------------------------------------------------------------------------- priority and edges
def test_priority_deny_beats_step_up_when_both_match():
    # Synthetic set: a hold that trips both a deny forbid and a step_up forbid.
    text = """
    @id("P") permit (principal, action, resource);
    @id("D") @on_deny("deny") forbid (principal, action, resource);
    @id("U") @on_deny("step_up") forbid (principal, action, resource);
    """
    d = decide(text, {"principal": 'Diner::"alice"', "action": 'Action::"x"',
                      "resource": 'Venue::"luna"', "context": {}}, ENTITIES)
    assert d == Decision("deny", ("D",))


def test_two_step_up_rules_still_step_up():
    text = """
    @id("P") permit (principal, action, resource);
    @id("U1") @on_deny("step_up") forbid (principal, action, resource);
    @id("U2") @on_deny("step_up") forbid (principal, action, resource);
    """
    d = decide(text, {"principal": 'Diner::"alice"', "action": 'Action::"x"',
                      "resource": 'Venue::"luna"', "context": {}}, ENTITIES)
    assert d.kind == "step_up" and set(d.rule_ids) == {"U1", "U2"}


def test_no_policy_matches_other_action_gives_no_permit(pep2):
    d = decide(pep2, req("restaurant_search"), ENTITIES)
    assert d == Decision("deny", ("no_permit",))


def test_d1_s2_does_not_apply_to_waitlist_watch(pep2):
    """D1 (D-014): a watch consumes no covers, so an S2-style cap must not block it."""
    d = decide(pep2, req("waitlist_watch", agent_covers_booked=19), ENTITIES)
    assert d == Decision("allow", ("P0_base",))
    # ...while the hold created for the watcher is still capped.
    d = decide(pep2, req("reservation_hold", agent_covers_booked=19), ENTITIES)
    assert d == Decision("deny", ("S2_agent_share_of_covers",))


def test_d1_s2_denial_next_step_is_not_self_blocking(pep2):
    """S2 denies a hold; the suggested next step (waitlist_watch) must itself be allowed."""
    ctx = {"agent_covers_booked": 19}
    assert decide(pep2, req("reservation_hold", **ctx), ENTITIES).kind == "deny"
    assert decide(pep2, req("waitlist_watch", **ctx), ENTITIES).kind == "allow"


# ------------------------------------------------------------------ D2: S3b cancel with a fee
def test_d2_s3b_cancel_with_fee_needs_step_up(pep2):
    d = decide(pep2, req("reservation_manage", cancel_fee_cents=2500), ENTITIES)
    assert d == Decision("step_up", ("S3b_cancel_fee_needs_ack",))


def test_d2_s3b_cancel_with_fee_acknowledged_is_allowed(pep2):
    d = decide(pep2, req("reservation_manage", cancel_fee_cents=2500, cancel_fee_acknowledged=True), ENTITIES)
    assert d == Decision("allow", ("P0_base",))


def test_d2_s3b_free_cancel_view_and_modify_need_no_step_up(pep2):
    assert decide(pep2, req("reservation_manage", cancel_fee_cents=0), ENTITIES).kind == "allow"


def test_d2_s3b_only_applies_to_reservation_manage(pep2):
    # A fee in the context of another action is irrelevant to S3b.
    assert decide(pep2, req("reservation_hold", cancel_fee_cents=2500), ENTITIES).kind == "allow"


def test_d2_s3b_unverified_agent_still_has_no_permit(pep2):
    d = decide(pep2, req("reservation_manage", agent_tier="unverified", cancel_fee_cents=0), ENTITIES)
    assert d == Decision("deny", ("no_permit",))


def test_missing_context_attribute_is_an_error_not_a_crash(pep2):
    """A forbid whose condition errors is skipped and reported in diagnostics.errors."""
    ctx = {k: v for k, v in BASE_CTX.items() if k != "active_holds_user_venue"}
    r = {**req("reservation_hold"), "context": ctx}
    res = cedarpy.is_authorized(r, pep2, ENTITIES)
    assert res.diagnostics.errors, "expected an evaluation error for the missing attribute"
    assert res.allowed  # the erroring forbid was skipped: this is why contexts must be complete


def test_prebuilt_policyset_handle_gives_same_result(pep2):
    handle = cedarpy.PolicySet.from_str(pep2)
    res = cedarpy.is_authorized(req("reservation_hold", active_holds_user_venue=2), handle, ENTITIES)
    assert res.decision == cedarpy.Decision.Deny


# --------------------------------------------------------------------------- G4 has-guard (design 6.1)
G2_SCOPE_ONLY = """
@id("G2") permit (principal, action, resource)
when { principal has scope && principal.scope == "fairtable/book" };
"""
G4_NAIVE = """
@id("G4") forbid (principal, action, resource)
when { principal.agent_tier != "verified" };
"""
G4_GUARDED = """
@id("G4") forbid (principal, action, resource)
unless { principal has agent_tier && principal.agent_tier == "verified" };
"""
G2_FULL = """
@id("G2") permit (principal, action, resource)
when { principal has username && principal has scope && principal.scope == "fairtable/book" };
"""


def _client_entities(**attrs):
    return [
        {"uid": {"type": "Client", "id": "c1"}, "attrs": attrs, "parents": []},
        {"uid": {"type": "Venue", "id": "luna"}, "attrs": {}, "parents": []},
    ]


def _pep1_request():
    return {"principal": 'Client::"c1"', "action": 'Action::"reservation_hold"',
            "resource": 'Venue::"luna"', "context": {}}


def test_g4_naive_lets_a_token_without_agent_tier_through():
    """Design 6.1: token with scope but no agent_tier -> naive G4 errors, is skipped, permit wins."""
    ents = _client_entities(scope="fairtable/book")
    res = cedarpy.is_authorized(_pep1_request(), G2_SCOPE_ONLY + G4_NAIVE, ents)
    assert res.allowed, "naive G4 should (wrongly) allow"
    assert res.diagnostics.errors, "naive G4 should report an evaluation error"


def test_g4_has_guard_denies_a_token_without_agent_tier():
    ents = _client_entities(scope="fairtable/book")
    res = cedarpy.is_authorized(_pep1_request(), G2_SCOPE_ONLY + G4_GUARDED, ents)
    assert res.decision == cedarpy.Decision.Deny
    assert res.diagnostics.errors == []


@pytest.mark.parametrize("tier,expected", [("verified", True), ("unverified", False)])
def test_g4_guarded_with_the_claim_present(tier, expected):
    ents = _client_entities(scope="fairtable/book", agent_tier=tier)
    res = cedarpy.is_authorized(_pep1_request(), G2_SCOPE_ONLY + G4_GUARDED, ents)
    assert res.allowed is expected


def test_g2_full_denies_m2m_bot_without_username_even_if_g4_would_pass():
    ents = _client_entities(scope="fairtable/book", agent_tier="verified")  # no username
    res = cedarpy.is_authorized(_pep1_request(), G2_FULL + G4_GUARDED, ents)
    assert res.decision == cedarpy.Decision.Deny
