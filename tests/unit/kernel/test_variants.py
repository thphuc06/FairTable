"""P1-21: the ablation kernels (A0 open store, A2 no step-up) differ from the real kernel in exactly one way each."""

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
    mandate_covers_booking=True, slot_is_drop_controlled=False, cancel_fee_cents=0, cancel_fee_acknowledged=False,
)
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


def test_without_step_up_an_unapproved_confirm_is_simply_allowed():
    kernel = TrustKernel.without_step_up()
    real = Pep2.from_dir(default_policy_dir())
    outside = {"mandate_covers_booking": False}
    assert pep2_decide(real, ToolName.RESERVATION_CONFIRM, **outside).kind is DecisionKind.STEP_UP
    d = pep2_decide(kernel.pep2, ToolName.RESERVATION_CONFIRM, **outside)
    assert d.kind is DecisionKind.ALLOW and d.rule_ids == ("S3_confirm_needs_mandate",)  # the rule is still named


def test_without_step_up_a_cancel_fee_needs_no_acknowledgement_either():
    kernel = TrustKernel.without_step_up()
    d = pep2_decide(kernel.pep2, ToolName.RESERVATION_MANAGE, cancel_fee_cents=2500)
    assert d.allowed


@pytest.mark.parametrize("overrides,rule", [
    ({"active_holds_user_venue": 2}, "S1_max_active_holds"),
    ({"agent_covers_booked": 19, "party_size": 2}, "S2_agent_share_of_covers"),
    ({"slot_is_drop_controlled": True}, "S4_drop_slots_via_waitlist"),
    ({"agent_tier": "unverified"}, "no_permit"),  # no permit matches: P0 is the missing one
])
def test_without_step_up_every_denial_still_holds(overrides, rule):
    kernel = TrustKernel.without_step_up()
    d = pep2_decide(kernel.pep2, ToolName.RESERVATION_HOLD, **overrides)
    assert d.kind is DecisionKind.DENY and d.rule_ids == (rule,)


def test_without_step_up_pep1_is_the_real_one():
    kernel = TrustKernel.without_step_up()
    assert not kernel.pep1.decide(identity=BOT, action=ToolName.RESERVATION_HOLD, party_size=2).allowed
    assert kernel.pep1.decide(identity=DINER, action=ToolName.RESERVATION_HOLD, party_size=2).allowed
