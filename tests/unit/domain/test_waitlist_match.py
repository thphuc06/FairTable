"""P1-14: which watcher gets a freed table (pure)."""

from server.domain.models import Slot
from server.domain.waitlist import (
    WATCH_MATCHED,
    WATCH_WAITING,
    Watch,
    effective_status,
    in_arrival_order,
    watch_fits,
)

TODAY = "2026-10-01"


def watch(wid="w1", *, venue="luna-trattoria", date="2026-10-02", start="18:00", end="21:00", party=2,
          status=WATCH_WAITING, created="2026-10-01T12:00:00Z") -> Watch:
    return Watch(wid, f"sub-{wid}", "user", "verified", "sim", frozenset({"fairtable/book"}), venue, date,
                 start, end, party, status, created)


def slot(time="19:00", seats=4, venue="luna-trattoria", date="2026-10-02", drop=None) -> Slot:
    return Slot(venue, date, time, "T4", seats, drop_id=drop)


def test_a_freed_table_that_fits_matches():
    assert watch_fits(watch(), slot(), TODAY)


def test_each_mismatch_rules_a_watcher_out():
    assert not watch_fits(watch(venue="ember-grill"), slot(), TODAY)
    assert not watch_fits(watch(date="2026-10-03"), slot(), TODAY)
    assert not watch_fits(watch(), slot(time="17:30"), TODAY)  # before the window
    assert not watch_fits(watch(), slot(time="21:30"), TODAY)  # after the window
    assert not watch_fits(watch(party=5), slot(seats=4), TODAY)  # table too small
    assert not watch_fits(watch(status=WATCH_MATCHED), slot(), TODAY)


def test_window_edges_are_inclusive_and_bigger_tables_are_fine():
    assert watch_fits(watch(), slot(time="18:00"), TODAY) and watch_fits(watch(), slot(time="21:00"), TODAY)
    assert watch_fits(watch(party=2), slot(seats=6), TODAY)


def test_drop_seats_never_go_to_a_standing_watch():
    assert not watch_fits(watch(), slot(drop="drop-x"), TODAY)


def test_a_watch_for_a_past_date_has_expired():
    old = watch(date="2026-09-30")
    assert effective_status(old, TODAY) == "expired" and not watch_fits(old, slot(date="2026-09-30"), TODAY)
    assert effective_status(watch(date=TODAY), TODAY) == WATCH_WAITING
    assert effective_status(watch(status="cancelled", date="2026-09-01"), TODAY) == "cancelled"


def test_watchers_are_served_first_come_first_served_with_a_stable_tiebreak():
    a = watch("a", created="2026-10-01T12:00:02Z")
    b = watch("b", created="2026-10-01T12:00:01Z")
    c = watch("c", created="2026-10-01T12:00:01Z")
    assert [w.watch_id for w in in_arrival_order([a, c, b])] == ["b", "c", "a"]


def test_the_stored_identity_is_rebuilt_for_the_matcher():
    ident = watch().identity()
    assert (ident.sub, ident.username, ident.agent_tier, ident.agent_id) == ("sub-w1", "user", "verified", "sim")
    assert ident.has_scope("fairtable/book") and ident.is_verified_agent
