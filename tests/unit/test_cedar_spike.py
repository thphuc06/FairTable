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
    kind: str  # "allow" | "deny"
    rule_ids: tuple[str, ...] = ()


def decide(policy_text, request, entities) -> Decision:
    """A matching forbid -> deny; no matching permit -> deny (rule 'no_permit')."""
    table = rule_table(policy_text)
    res = cedarpy.is_authorized(request, policy_text, entities)
    assert res.diagnostics.errors == [], res.diagnostics.errors
    matched = [table[r] for r in res.diagnostics.reasons]
    if res.allowed:
        return Decision("allow", tuple(rid for rid, _ in matched))
    if not matched:
        return Decision("deny", ("no_permit",))
    return Decision("deny", tuple(rid for rid, od in matched if od == "deny"))


ENTITIES = [
    {"uid": {"type": "Diner", "id": "alice"}, "attrs": {}, "parents": []},
    {"uid": {"type": "Venue", "id": "luna"}, "attrs": {"agent_cover_cap": 20}, "parents": []},
]

BASE_CTX = {
    "agent_tier": "verified",
    "active_holds_user_venue": 0,
    "agent_covers_booked": 0,
    "party_size": 2,
    "slot_is_drop_controlled": False,
    "read_back_required": False,
    "read_back_matches": False,
    "pause_elapsed": False,
    "user_confirmed": False,
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
    assert len(table) == 7
    assert all(k.startswith("policy") for k in table)
    assert sorted(v[0] for v in table.values()) == [
        "P0_base",
        "S1_max_active_holds",
        "S2_agent_share_of_covers",
        "S4_drop_slots_via_waitlist",
        "S5a_confirm_needs_read_back",
        "S5b_confirm_needs_the_diners_answer",
        "S5c_confirm_needs_an_explicit_yes",
    ]
    assert {v[0]: v[1] for v in table.values()} == {
        "P0_base": None,
        "S1_max_active_holds": "deny",
        "S2_agent_share_of_covers": "deny",
        "S4_drop_slots_via_waitlist": "deny",
        "S5a_confirm_needs_read_back": "deny",
        "S5b_confirm_needs_the_diners_answer": "deny",
        "S5c_confirm_needs_an_explicit_yes": "deny",
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


SPOKEN = {"read_back_required": True, "read_back_matches": True, "pause_elapsed": True, "user_confirmed": True}


def test_scenario_4_s5_confirm_without_the_read_back_is_denied(pep2):
    d = decide(pep2, req("reservation_confirm", **{**SPOKEN, "read_back_matches": False}), ENTITIES)
    assert d == Decision("deny", ("S5a_confirm_needs_read_back",))


def test_scenario_5_s5_confirm_after_the_read_back_the_pause_and_a_yes_is_allowed(pep2):
    d = decide(pep2, req("reservation_confirm", **SPOKEN), ENTITIES)
    assert d == Decision("allow", ("P0_base",))


def test_scenario_6_s4_drop_slot_only_via_waitlist(pep2):
    d = decide(pep2, req("reservation_hold", slot_is_drop_controlled=True), ENTITIES)
    assert d == Decision("deny", ("S4_drop_slots_via_waitlist",))


def test_scenario_7_unverified_agent_has_no_matching_permit(pep2):
    d = decide(pep2, req("reservation_hold", agent_tier="unverified"), ENTITIES)
    assert d == Decision("deny", ("no_permit",))


# --------------------------------------------------------------------------- edges
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


# ------------------------------------------------------------------ S5 on a cancel (D-051)
def test_s5_cancel_with_a_fee_needs_the_read_back_the_pause_and_a_yes(pep2):
    assert decide(pep2, req("reservation_manage", read_back_required=True), ENTITIES).kind == "deny"
    assert decide(pep2, req("reservation_manage", **SPOKEN), ENTITIES) == Decision("allow", ("P0_base",))


def test_s5_free_cancel_view_and_modify_need_no_read_back(pep2):
    assert decide(pep2, req("reservation_manage"), ENTITIES).kind == "allow"


def test_s5_does_not_apply_to_a_hold(pep2):
    assert decide(pep2, req("reservation_hold", read_back_required=True), ENTITIES).kind == "allow"


def test_s5_unverified_agent_still_has_no_permit(pep2):
    d = decide(pep2, req("reservation_manage", agent_tier="unverified"), ENTITIES)
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
