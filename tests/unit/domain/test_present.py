"""P1-7: words for voice."""

import pytest

from server.store.seed_data import VENUES
from server.tools.present import cancel_policy_text, say_money, say_time, say_times


@pytest.mark.parametrize(
    "hhmm,spoken",
    [("00:00", "12:00 AM"), ("09:05", "9:05 AM"), ("12:00", "12:00 PM"), ("17:30", "5:30 PM"),
     ("23:59", "11:59 PM")],
)
def test_say_time(hhmm, spoken):
    assert say_time(hhmm) == spoken


def test_say_times_lists_each_time_once():
    assert say_times(["17:30", "17:30", "18:00"]) == "5:30 PM and 6:00 PM"
    assert say_times(["17:30", "17:30"]) == "5:30 PM"
    assert say_times(["17:30", "18:00", "18:30"]) == "5:30 PM, 6:00 PM and 6:30 PM"
    assert say_times(["17:30", "18:00", "18:30", "19:00", "19:30"]) == "5:30 PM, 6:00 PM, 6:30 PM and 2 more times"


def test_money_and_cancellation_wording():
    assert say_money(0) == "free" and say_money(2500) == "$25.00"
    ember = next(v for v in VENUES if v.venue_id == "ember-grill")
    assert cancel_policy_text(ember) == "Cancel at least 48 hours ahead for free; after that the fee is $25.00."
