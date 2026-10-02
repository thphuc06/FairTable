"""P1-7: pure logic behind the read tools: token bucket, slot selection."""

from datetime import UTC, datetime

import pytest

from server.domain.availability import (
    MAX_SLOTS_RETURNED,
    check_party_size,
    offered_slots,
    parse_date,
    parse_time,
    parse_window,
)
from server.domain.errors import ErrorCode, FairTableError
from server.domain.models import Slot
from server.domain.ratelimit import BucketState, consume

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
TODAY = NOW.date()


# ---------------------------------------------------------------- token bucket
def test_new_bucket_is_full_and_drains():
    state, allowed, retry = consume(None, 1000.0, capacity=3, per_hour=3)
    assert (allowed, retry, state.tokens) == (True, 0, 2.0)
    for _ in range(2):
        state, allowed, _ = consume(state, 1000.0, capacity=3, per_hour=3)
        assert allowed
    state, allowed, retry = consume(state, 1000.0, capacity=3, per_hour=3)
    assert not allowed and retry == 1200  # 3 per hour = one token every 20 minutes


def test_bucket_refills_over_time_but_not_past_capacity():
    empty = BucketState(0.0, 0.0)
    _, allowed, _ = consume(empty, 1200.0, capacity=3, per_hour=3)  # 20 minutes later
    assert allowed
    full, _, _ = consume(empty, 10**9, capacity=3, per_hour=3)
    assert full.tokens == 2.0  # capped at 3, minus the one just taken


def test_refusal_does_not_take_a_token_and_time_never_runs_backwards():
    state = BucketState(0.5, 100.0)
    new, allowed, retry = consume(state, 90.0, capacity=3, per_hour=3600)  # clock skew
    assert not allowed and new.tokens == 0.5 and retry == 1


def test_bucket_rejects_nonsense_settings():
    for kwargs in ({"capacity": 0, "per_hour": 1}, {"capacity": 1, "per_hour": 0}):
        with pytest.raises(ValueError):
            consume(None, 0.0, **kwargs)


# ---------------------------------------------------------------- input validation
def invalid(fn, *args, **kwargs):
    with pytest.raises(FairTableError) as exc:
        fn(*args, **kwargs)
    assert exc.value.code is ErrorCode.INVALID_INPUT
    return exc.value


def test_dates():
    assert parse_date("2026-10-01", today=TODAY) == TODAY
    for bad in ("2026-9-1x", "tomorrow", "", None, "2026-09-30", "2027-06-01"):
        invalid(parse_date, bad, today=TODAY)


def test_times_and_windows():
    assert parse_time("7:05") == "07:05"
    assert parse_window("17:00-22:00") == ("17:00", "22:00")
    assert parse_window(" 18:30 - 20:00 ") == ("18:30", "20:00")
    for bad in ("17:00", "22:00-17:00", "25:00-26:00", "a-b", ""):
        invalid(parse_window, bad)


def test_party_size():
    assert check_party_size(4, required=True) == 4
    assert check_party_size(None, required=False) == 0
    for bad in (0, -1, 51, True, "2", 2.5, None):
        invalid(check_party_size, bad, required=True)


# ---------------------------------------------------------------- slot selection
def slot(time="19:00", group="T4", seats=4, **over) -> Slot:
    return Slot("luna", "2026-10-02", time, group, seats, **over)


def test_only_fitting_open_slots_inside_the_window_are_offered():
    slots = [slot("18:00", "T2", 2), slot("19:00", "T4", 4), slot("19:00", "T6", 6),
             slot("21:30", "T4", 4), slot("19:30", "T4", 4, status="confirmed")]
    got = offered_slots(slots, party_size=3, window=("18:00", "21:00"), now=NOW)
    assert [(s.time, s.table_group) for s in got] == [("19:00", "T4"), ("19:00", "T6")]


def test_tightest_table_comes_first_within_a_time():
    slots = [slot("19:00", "T6", 6), slot("19:00", "T4", 4)]
    got = offered_slots(slots, party_size=2, window=("00:00", "23:59"), now=NOW)
    assert [s.table_group for s in got] == ["T4", "T6"]


def test_expired_holds_count_as_open_but_live_holds_do_not():
    live = slot("19:00", status="held", held_until="2026-10-01T12:05:00Z")
    stale = slot("19:30", status="held", held_until="2026-10-01T11:55:00Z")
    got = offered_slots([live, stale], party_size=2, window=("00:00", "23:59"), now=NOW)
    assert [s.time for s in got] == ["19:30"]


def test_times_already_past_today_are_dropped():
    today_slots = [Slot("luna", "2026-10-01", t, "T2", 2) for t in ("11:00", "12:00", "13:00")]
    got = offered_slots(today_slots, party_size=1, window=("00:00", "23:59"), now=NOW)
    assert [s.time for s in got] == ["12:00", "13:00"]


def test_result_is_capped():
    many = [Slot("luna", "2026-10-02", f"{h:02d}:00", "T2", 2) for h in range(10, 24)]
    many += [Slot("luna", "2026-10-02", f"{h:02d}:30", "T2", 2) for h in range(10, 24)]
    assert len(offered_slots(many, party_size=1, window=("00:00", "23:59"), now=NOW)) == MAX_SLOTS_RETURNED
