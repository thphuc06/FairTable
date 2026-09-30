"""The standing permission a diner can grant on the approval page: never wider than what the page shows."""

from datetime import UTC, date, datetime, timedelta

import pytest

from server.domain.grant import (
    DEFAULT_GRANT_DAYS,
    GRANT_DAYS,
    GRANT_PARTY_MAX,
    build_mandate,
    can_offer,
    describe_mandate,
    offer_parts,
)
from server.domain.mandate import check_mandate
from server.domain.models import MANDATE_REVOKED, Venue

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
FREE = Venue("luna-trattoria", "Luna Trattoria", "Italian", "Riverside", "d", 60, 40, 0, 0)
FEE = Venue("ember-grill", "Ember Grill", "Steakhouse", "Old Town", "d", 40, 25, 2500, 48)


def covered(m, *, party=2, on=date(2026, 10, 3), time="19:00", agent="alexa-plus-sim", fee=0, now=NOW):
    return check_mandate(m, now=now, agent_id=agent, party_size=party, day=on, time=time, cancel_fee_cents=fee)


def test_the_grant_has_exactly_the_limits_the_page_promises():
    m = build_mandate(sub="dev-bob", venue=FREE, agent_id="alexa-plus-sim", days=30, now=NOW)
    assert (m.party_size_max, m.days_ahead_max, m.max_cancel_fee_cents) == (GRANT_PARTY_MAX, 30, 0)
    assert (m.window_start, m.window_end) == ("00:00", "23:59")
    assert m.agent_ids == frozenset({"alexa-plus-sim"}) and m.venue_id == "luna-trattoria"
    assert m.expires_at == "2026-10-31T12:00:00Z" and m.approved_at == "2026-10-01T12:00:00Z" and m.status == "active"
    assert m.allow_auto_confirm and "confirm" in m.actions


def test_what_the_page_says_matches_what_is_stored():
    before, after, limits = offer_parts(FREE, "alexa-plus-sim")
    assert before.endswith("for the next") and after == "days." and FREE.name in before
    assert f"up to {GRANT_PARTY_MAX} people" in limits and "any time" in limits and "no cancellation fee" in limits
    assert "'alexa-plus-sim'" in limits and "Permissions" in limits
    assert DEFAULT_GRANT_DAYS in GRANT_DAYS


def test_a_restaurant_with_a_fee_says_so_and_the_cap_is_that_fee():
    _, _, limits = offer_parts(FEE, "alexa-plus-sim")
    assert "$25.00" in limits and "no cancellation fee" not in limits
    m = build_mandate(sub="dev-bob", venue=FEE, agent_id="alexa-plus-sim", days=7, now=NOW)
    assert m.max_cancel_fee_cents == 2500


def test_inside_the_grant_a_booking_is_covered():
    m = build_mandate(sub="s", venue=FREE, agent_id="alexa-plus-sim", days=30, now=NOW)
    assert covered(m).covered
    assert covered(m, party=4, time="00:00").covered and covered(m, time="23:59").covered  # any time of day
    assert covered(m, on=date(2026, 10, 31)).covered  # the last day of the window


@pytest.mark.parametrize("change,reason", [
    ({"party": 5}, "larger than 4"),
    ({"on": date(2026, 11, 1)}, "more than 30 days"),
    ({"on": date(2026, 9, 30)}, "more than 30 days"),  # the past
    ({"agent": "shady-agent"}, "agent is not on"),
    ({"agent": None}, "agent is not on"),
    ({"fee": 100}, "cancellation fee is above"),
])
def test_outside_the_grant_the_diner_is_asked(change, reason):
    m = build_mandate(sub="s", venue=FREE, agent_id="alexa-plus-sim", days=30, now=NOW)
    result = covered(m, **change)
    assert not result.covered and any(reason in r for r in result.reasons)


def test_a_fee_raised_after_the_grant_needs_a_new_approval():
    m = build_mandate(sub="s", venue=FEE, agent_id="alexa-plus-sim", days=30, now=NOW)
    assert covered(m, fee=2500).covered
    assert not covered(m, fee=5000).covered


def test_after_the_days_are_over_it_no_longer_covers():
    m = build_mandate(sub="s", venue=FREE, agent_id="alexa-plus-sim", days=7, now=NOW)
    later = NOW + timedelta(days=8)
    assert not covered(m, now=later, on=later.date() + timedelta(days=1)).covered


def test_a_revoked_grant_covers_nothing():
    m = build_mandate(sub="s", venue=FREE, agent_id="alexa-plus-sim", days=30, now=NOW)
    revoked = type(m)(**{**m.__dict__, "status": MANDATE_REVOKED})
    assert not covered(revoked).covered


def test_only_the_offered_lengths_and_a_named_assistant_are_accepted():
    for days in (0, 1, 14, 365, -7):
        with pytest.raises(ValueError, match="days"):
            build_mandate(sub="s", venue=FREE, agent_id="a", days=days, now=NOW)
    with pytest.raises(ValueError, match="named assistant"):
        build_mandate(sub="s", venue=FREE, agent_id="", days=30, now=NOW)


def test_a_grant_is_offered_only_when_no_live_permission_exists():
    live = build_mandate(sub="s", venue=FREE, agent_id="a", days=30, now=NOW)
    assert can_offer(None, NOW)
    assert not can_offer(live, NOW)  # it never narrows or replaces a live permission
    assert can_offer(live, NOW + timedelta(days=31))  # expired
    assert can_offer(type(live)(**{**live.__dict__, "status": MANDATE_REVOKED}), NOW)


def test_the_stored_permission_can_be_described_in_one_line():
    m = build_mandate(sub="s", venue=FEE, agent_id="alexa-plus-sim", days=30, now=NOW)
    line = describe_mandate(m, "Ember Grill")
    assert line == ("Ember Grill: up to 4 people, any time, within 30 days, a cancellation fee of up to $25.00 "
                    "· only for 'alexa-plus-sim' · until 2026-10-31")
    seeded = type(m)(**{**m.__dict__, "window_start": "17:00", "window_end": "22:00", "max_cancel_fee_cents": 0})
    assert "between 17:00 and 22:00" in describe_mandate(seeded, "Luna") and "no cancellation fee" in describe_mandate(seeded, "Luna")
