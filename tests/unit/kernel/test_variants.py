"""P1-21, P3-10: the ablation kernels (A0 open store, A2 no voice guards) differ from the real kernel in exactly one way each."""

from dataclasses import replace

import pytest

from server.domain.models import Identity
from server.domain.tool_names import ToolName
from server.kernel import (
    DecisionKind,
    Pep2,
    PolicyContext,
    TrustKernel,
    VenueRef,
    default_policy_dir,
)

VENUE = VenueRef("luna", agent_cover_cap=20)
BASE = PolicyContext(
    agent_tier="verified", active_holds_user_venue=0, agent_covers_booked=0, party_size=2,
    slot_is_drop_controlled=False, read_back_required=False, read_back_matches=False, pause_elapsed=False,
    user_confirmed=False,
)
# a confirm with nothing behind it: no read-back token, no pause, no yes
UNGUARDED = {"read_back_required": True}
BOT = Identity(sub="bot")  # a machine token: no username, no agent tier, no scope
DINER = Identity(sub="alice", username="diner-alice", agent_tier="verified", agent_id="a",
                 scopes=frozenset({"fairtable/book"}))


def pep2_decide(pep2, action, **overrides):
    return pep2.decide(action=action, diner_id="alice", venue=VENUE, ctx=replace(BASE, **overrides))


@pytest.fixture(scope="module")
def real() -> TrustKernel:
    return TrustKernel.load()


def test_the_open_store_allows_a_bot_a_giant_party_and_a_drop_seat():
    kernel = TrustKernel.open_store()
    assert kernel.pep1.decide(identity=BOT, action=ToolName.RESERVATION_HOLD, party_size=50).allowed
    d = pep2_decide(kernel.pep2, ToolName.RESERVATION_HOLD, slot_is_drop_controlled=True,
                    active_holds_user_venue=9, agent_covers_booked=999)
    assert d.allowed and d.kind is DecisionKind.ALLOW and d.rule_id == "A0_open_store"


def test_the_real_kernel_refuses_the_same_requests(real):
    assert not real.pep1.decide(identity=BOT, action=ToolName.RESERVATION_HOLD, party_size=2).allowed
    assert not real.pep1.decide(identity=DINER, action=ToolName.RESERVATION_HOLD, party_size=50).allowed
    assert not pep2_decide(real.pep2, ToolName.RESERVATION_HOLD, slot_is_drop_controlled=True).allowed


def test_without_the_voice_guards_a_confirm_with_nothing_behind_it_is_simply_allowed():
    kernel = TrustKernel.without_voice_guards()
    real = Pep2.from_dir(default_policy_dir())
    refused = pep2_decide(real, ToolName.RESERVATION_CONFIRM, **UNGUARDED)
    assert refused.kind is DecisionKind.DENY and "S5a_confirm_needs_read_back" in refused.rule_ids
    d = pep2_decide(kernel.pep2, ToolName.RESERVATION_CONFIRM, **UNGUARDED)
    assert d.kind is DecisionKind.ALLOW and d.rule_ids == ("P0_base",)  # judged as if the guards were satisfied


def test_without_the_voice_guards_a_cancel_with_a_fee_needs_no_read_back_either():
    kernel = TrustKernel.without_voice_guards()
    assert pep2_decide(kernel.pep2, ToolName.RESERVATION_MANAGE, **UNGUARDED).allowed


def test_without_the_voice_guards_an_unverified_agent_is_still_refused():
    """A forbid hides a missing permit: the real kernel names only the S5 rules for this request. The ablation
    must not let it through because those rules are switched off."""
    real = Pep2.from_dir(default_policy_dir())
    kernel = TrustKernel.without_voice_guards()
    both = pep2_decide(real, ToolName.RESERVATION_CONFIRM, agent_tier="unverified", **UNGUARDED)
    assert both.kind is DecisionKind.DENY and all(r.startswith("S5") for r in both.rule_ids)
    d = pep2_decide(kernel.pep2, ToolName.RESERVATION_CONFIRM, agent_tier="unverified", **UNGUARDED)
    assert d.kind is DecisionKind.DENY and d.rule_ids == ("no_permit",)


@pytest.mark.parametrize("overrides,rule", [
    ({"active_holds_user_venue": 2}, "S1_max_active_holds"),
    ({"agent_covers_booked": 19, "party_size": 2}, "S2_agent_share_of_covers"),
    ({"slot_is_drop_controlled": True}, "S4_drop_slots_via_waitlist"),
    ({"agent_tier": "unverified"}, "no_permit"),  # no permit matches: P0 is the missing one
])
def test_without_the_voice_guards_every_other_denial_still_holds(overrides, rule):
    kernel = TrustKernel.without_voice_guards()
    d = pep2_decide(kernel.pep2, ToolName.RESERVATION_HOLD, **overrides)
    assert d.kind is DecisionKind.DENY and d.rule_ids == (rule,)


def test_without_the_voice_guards_pep1_is_the_real_one():
    kernel = TrustKernel.without_voice_guards()
    assert not kernel.pep1.decide(identity=BOT, action=ToolName.RESERVATION_HOLD, party_size=2).allowed
    assert kernel.pep1.decide(identity=DINER, action=ToolName.RESERVATION_HOLD, party_size=2).allowed
