"""P3-21 (D-067): the owner console changes the cancellation terms and releases a seat through a Fair Drop."""

import hashlib
import re
from datetime import timedelta

import pytest
from ddb_env import ENDPOINT
from flows import book, call, hold_table
from test_owner_console import owner_browser, sign_in
from world import World

from server.domain.booking import starts_at

pytestmark = pytest.mark.ddb
LUNA = "luna-trattoria"


@pytest.fixture
def world(ddb_client, table_name, clock):
    w = World(ddb_client, table_name, ENDPOINT, clock)
    ids = iter(range(1, 100_000))
    w.deps.new_id = lambda: f"id{next(ids):05d}"
    return w


def csrf_for(html: str, action: str) -> str:
    """The token of the form that posts to ``action`` (the page has one token per form)."""
    return re.search(rf"action='{re.escape(action)}'>\s*<input type='hidden' name='csrf' value='([^']+)'", html).group(1)


def seat_values(html: str) -> list[str]:
    return re.findall(r"<option value='(\d{4}-\d{2}-\d{2}\|[^']+)'>", html)


def owner_audit(world: World) -> list[dict]:
    return [e for e in world.store.list_audit(LUNA, world.clock.now().date().isoformat()) if e["tool"] == "owner_console"]


# ---------------------------------------------------------------- the page
def test_the_owner_page_has_the_terms_and_the_drops(world):
    html = owner_browser(world).get("/owner").text
    assert "Cancellation terms" in html and "Fair Drops" in html and "/owner/terms" in html and "/owner/drops" in html
    assert seat_values(html)  # there are seats the owner can release through a lottery


# ---------------------------------------------------------------- cancellation terms
def test_the_owner_changes_the_cancellation_terms_and_it_is_audited(world):
    browser = owner_browser(world)
    before = world.store.get_venue(LUNA)
    csrf = csrf_for(browser.get("/owner").text, "/owner/terms")
    assert browser.post("/owner/terms", data={"fee": "30", "hours": "12", "csrf": csrf}).status_code == 303
    venue = world.store.get_venue(LUNA)
    assert (venue.cancel_fee_cents, venue.free_cancel_hours) == (3000, 12)
    entry = [e for e in owner_audit(world) if "cancel_fee_cents_to" in e["detail"]][0]
    assert entry["detail"]["cancel_fee_cents_from"] == before.cancel_fee_cents
    assert entry["detail"]["free_cancel_hours_to"] == 12
    assert "$30" in browser.get("/owner").text


def test_a_decimal_fee_is_kept_in_cents(world):
    browser = owner_browser(world)
    csrf = csrf_for(browser.get("/owner").text, "/owner/terms")
    assert browser.post("/owner/terms", data={"fee": "12.50", "hours": "0", "csrf": csrf}).status_code == 303
    venue = world.store.get_venue(LUNA)
    assert (venue.cancel_fee_cents, venue.free_cancel_hours) == (1250, 0)


@pytest.mark.parametrize("fee,hours", [("", "24"), ("abc", "24"), ("-1", "24"), ("201", "24"), ("12.345", "24"),
                                      ("25", ""), ("25", "x"), ("25", "-1"), ("25", "169"), ("25", "1.5")])
def test_bad_terms_are_refused_and_nothing_changes(world, fee, hours):
    browser = owner_browser(world)
    before = world.store.get_venue(LUNA)
    csrf = csrf_for(browser.get("/owner").text, "/owner/terms")
    assert browser.post("/owner/terms", data={"fee": fee, "hours": hours, "csrf": csrf}).status_code == 400
    after = world.store.get_venue(LUNA)
    assert (after.cancel_fee_cents, after.free_cancel_hours) == (before.cancel_fee_cents, before.free_cancel_hours)


def test_the_token_of_another_form_does_not_work_on_the_terms_form(world):
    browser = owner_browser(world)
    html = browser.get("/owner").text
    before = world.store.get_venue(LUNA).cancel_fee_cents
    assert browser.post("/owner/terms", data={"fee": "99", "hours": "1",
                                              "csrf": csrf_for(html, "/owner/agent-share")}).status_code == 403
    assert world.store.get_venue(LUNA).cancel_fee_cents == before


def test_a_diner_cannot_change_terms_or_create_a_drop(world):
    html = owner_browser(world).get("/owner").text
    diner = world.web()
    sign_in(diner, "diner-alice", "alice-dev-pass")
    assert diner.post("/owner/terms", data={"fee": "0", "hours": "0",
                                            "csrf": csrf_for(html, "/owner/terms")}).status_code == 403
    assert diner.post("/owner/drops", data={"seat": seat_values(html)[0], "hours_before": "24",
                                            "csrf": csrf_for(html, "/owner/drops")}).status_code == 403


@pytest.mark.asyncio
async def test_a_new_hold_reads_the_new_terms_and_an_old_booking_keeps_its_own(world):
    old = await book(world, "alice", LUNA, "19:00", offset=3, tag="1")
    browser = owner_browser(world)
    csrf = csrf_for(browser.get("/owner").text, "/owner/terms")
    assert browser.post("/owner/terms", data={"fee": "40", "hours": "72", "csrf": csrf}).status_code == 303
    held = await hold_table(world, "bob", LUNA, "19:00", offset=2, key="key-terms-0001")
    assert world.store.get_hold(held["hold_id"]).terms["cancel_fee_cents"] == 4000
    assert world.store.get_reservation(old["reservation_id"]).terms_snapshot["cancel_fee_cents"] != 4000


# ---------------------------------------------------------------- Fair Drop
@pytest.mark.asyncio
async def test_the_owner_creates_a_fair_drop_and_the_seat_leaves_direct_booking(world):
    browser = owner_browser(world)
    html = browser.get("/owner").text
    seat = seat_values(html)[0]
    date, time_, group = seat.split("|")
    r = browser.post("/owner/drops", data={"seat": seat, "hours_before": "2", "csrf": csrf_for(html, "/owner/drops")})
    assert r.status_code == 303
    slot = world.store.get_slot(LUNA, date, time_, group)
    assert slot.drop_controlled and slot.hot
    drop = world.store.get_drop(slot.drop_id)
    assert drop.status == "open" and drop.slot_keys == (slot.slot_key,) and drop.capacity == 1
    assert drop.commitment == hashlib.sha256(bytes.fromhex(drop.seed_hex)).hexdigest()  # only the fingerprint is public
    page = browser.get("/owner").text
    assert drop.commitment[:16] in page and seat not in seat_values(page)  # listed, and it cannot be released twice
    entry = [e for e in owner_audit(world) if "fair_drop" in e["detail"]][0]
    assert entry["detail"]["commitment"] == drop.commitment and drop.seed_hex not in str(entry["detail"])
    # a diner cannot book the seat directly any more (S4), and can enter the draw
    world.as_("alice")
    avail = await call(world, "availability_check", restaurant_id=LUNA, date=date,
                       time_window=f"{time_}-{time_}", party_size=2)
    offer = next(s for s in avail.structuredContent["slots"] if s.get("drop_id") == slot.drop_id)
    held = await call(world, "reservation_hold", offer_id=offer["offer_id"], idempotency_key="key-owner-drop-1")
    assert held.isError and held.structuredContent["error"] == "DROP_CONTROLLED"
    entered = await call(world, "waitlist_watch", drop_id=slot.drop_id, party_size=2, idempotency_key="key-owner-drop-2")
    assert not entered.isError and entered.structuredContent["commitment"] == drop.commitment


@pytest.mark.parametrize("seat", ["", "nonsense", "2026-01-01|19:00|T2", "a|b|c|d", "2026-10-06|19:00|T#2"])
def test_a_drop_for_a_seat_that_is_not_there_is_refused(world, seat):
    browser = owner_browser(world)
    csrf = csrf_for(browser.get("/owner").text, "/owner/drops")
    assert browser.post("/owner/drops", data={"seat": seat, "hours_before": "24", "csrf": csrf}).status_code == 400


def test_a_draw_time_that_is_not_one_of_the_choices_is_refused(world):
    browser = owner_browser(world)
    html = browser.get("/owner").text
    seat = seat_values(html)[0]
    for hours in ("", "3", "-2", "abc"):
        r = browser.post("/owner/drops", data={"seat": seat, "hours_before": hours, "csrf": csrf_for(html, "/owner/drops")})
        assert r.status_code == 400
    assert not world.store.get_slot(LUNA, *seat.split("|")).drop_controlled


def test_the_seat_list_follows_the_draw_time(world):
    """Every seat in the list can be released with the draw time chosen above it; a shorter draw time lists more seats."""
    browser = owner_browser(world)
    now = world.clock.now()
    lists = {h: seat_values(browser.get(f"/owner?draw={h}").text) for h in (24, 12, 6, 2)}
    for hours, values in lists.items():
        assert values, hours
        for value in values:
            date, time_, _group = value.split("|")
            assert starts_at(date, time_) - timedelta(hours=hours) >= now + timedelta(minutes=10), (hours, value)
    assert set(lists[24]) <= set(lists[12]) <= set(lists[6]) <= set(lists[2])
    last_day = max(v.split("|")[0] for v in lists[24])
    assert last_day >= (now.date() + timedelta(days=12)).isoformat()  # the far days are listed too, not only the first few
    assert seat_values(browser.get("/owner").text) == lists[24]  # the page opens with 24 hours


@pytest.mark.parametrize("draw", ["", "7", "-2", "abc", "2; DROP"])
def test_an_unknown_draw_time_in_the_link_means_24_hours(world, draw):
    browser = owner_browser(world)
    page = browser.get("/owner", params={"draw": draw})
    assert page.status_code == 200 and "draw 24 hours before it" in page.text
    assert seat_values(page.text) == seat_values(browser.get("/owner").text)


def test_a_draw_that_would_already_be_over_is_refused(world):
    """A seat that starts in less than 24 hours cannot have its draw 24 hours before it (the page does not offer it either)."""
    browser = owner_browser(world)
    short = browser.get("/owner?draw=2").text
    soonest = seat_values(short)[0]
    date, time_, _group = soonest.split("|")
    if starts_at(date, time_) - world.clock.now() >= timedelta(hours=24):
        pytest.skip("the earliest seat is more than a day away on this clock")
    assert soonest not in seat_values(browser.get("/owner").text)  # not offered for a 24 hour draw
    r = browser.post("/owner/drops", data={"seat": soonest, "hours_before": "24", "csrf": csrf_for(short, "/owner/drops")})
    assert r.status_code == 400 and "passed or is too close" in r.text
    assert "draw 24 hours before it" in r.text  # the page comes back on the same choice
    assert not world.store.get_slot(LUNA, *soonest.split("|")).drop_controlled


@pytest.mark.asyncio
async def test_a_seat_that_a_diner_holds_in_the_meantime_cannot_become_a_drop(world):
    browser = owner_browser(world)
    html = browser.get("/owner").text  # the owner opens the form first
    date, time_, group = seat_values(html)[0].split("|")
    world.as_("alice")
    avail = await call(world, "availability_check", restaurant_id=LUNA, date=date,
                       time_window=f"{time_}-{time_}", party_size=2)
    mine = next(s for s in avail.structuredContent["slots"] if s["table_group"] == group) \
        if "table_group" in avail.structuredContent["slots"][0] else avail.structuredContent["slots"][0]
    held = await call(world, "reservation_hold", offer_id=mine["offer_id"], idempotency_key="key-owner-race-1")
    assert not held.isError, held.structuredContent
    held_slot = world.store.get_hold(held.structuredContent["hold_id"])
    r = browser.post("/owner/drops", data={"seat": f"{date}|{held_slot.time}|{held_slot.table_group}", "hours_before": "2",
                                           "csrf": csrf_for(html, "/owner/drops")})
    assert r.status_code == 400
    assert not world.store.get_slot(LUNA, date, held_slot.time, held_slot.table_group).drop_controlled


def test_anyone_can_open_the_page_of_a_fair_drop_and_it_shows_only_the_fingerprint(world):
    """The public page of a drop that has not been drawn: the commitment, never the seed, and opening it changes nothing."""
    browser = owner_browser(world)
    html = browser.get("/owner").text
    seat = seat_values(html)[0]
    assert browser.post("/owner/drops", data={"seat": seat, "hours_before": "2",
                                              "csrf": csrf_for(html, "/owner/drops")}).status_code == 303
    date, time_, group = seat.split("|")
    drop = world.store.get_drop(world.store.get_slot(LUNA, date, time_, group).drop_id)
    assert f"/drops/{drop.drop_id}" in browser.get("/owner").text  # the console links to it
    visitor = world.web()  # no sign-in
    page = visitor.get(f"/drops/{drop.drop_id}")
    assert page.status_code == 200 and drop.commitment in page.text and "Not drawn yet" in page.text
    assert drop.seed_hex not in page.text and "Luna Trattoria" in page.text
    assert world.store.get_drop(drop.drop_id) == drop  # reading the page did not start the draw
    assert visitor.get("/drops/no-such-drop").status_code == 404
