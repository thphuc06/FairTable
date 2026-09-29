"""P1-11: the consent page, alone and together with the MCP tools."""

import re
from dataclasses import replace
from datetime import timedelta

import pytest
from ddb_env import ENDPOINT
from world import World

from server.domain.clock import iso_z
from web.session import COOKIE_NAME

pytestmark = pytest.mark.ddb

PASSWORDS = {"bob": ("diner-bob", "bob-dev-pass"), "alice": ("diner-alice", "alice-dev-pass"),
             "luna": ("owner-luna", "luna-dev-pass")}


@pytest.fixture
def world(ddb_client, table_name, clock):
    w = World(ddb_client, table_name, ENDPOINT, clock)
    ids = iter(range(1, 100_000))
    w.deps.new_id = lambda: f"id{next(ids):05d}"
    return w


def day(world: World) -> str:
    return (world.clock.now().date() + timedelta(days=2)).isoformat()


async def call(world: World, tool: str, **args):
    async with world.client() as c:
        return await c.call_tool_mcp(tool, args)


async def waiting_for_bob(world: World, time: str = "19:00", tag: str = "1") -> str:
    """Bob's assistant holds a table and asks to confirm; returns the consent path."""
    world.as_("bob")
    r = await call(world, "availability_check", restaurant_id="luna-trattoria", date=day(world),
                   time_window=f"{time}-{time}", party_size=2)
    token = r.structuredContent["slots"][0]["slot_token"]
    h = await call(world, "reservation_hold", slot_token=token, idempotency_key=f"key-web-hold{tag}")
    hold_id = h.structuredContent["hold_id"]
    c = await call(world, "reservation_confirm", hold_id=hold_id, idempotency_key=f"key-web-conf{tag}")
    assert c.structuredContent["error"] == "CONSENT_REQUIRED"
    url = c.structuredContent["consent_url"]
    assert url.startswith("http://localhost:8080/")
    return url.removeprefix("http://localhost:8080")


def sign_in(browser, who: str, next_path: str = "/") -> None:
    username, password = PASSWORDS[who]
    r = browser.post("/login", data={"username": username, "password": password, "next": next_path})
    assert r.status_code == 303 and COOKIE_NAME in browser.cookies


def csrf_of(html: str) -> str:
    return re.search(r"name='csrf' value='([^']+)'", html).group(1)


# ---------------------------------------------------------------- signing in
async def test_visiting_the_link_without_signing_in_leads_to_the_login_page(world):
    path = await waiting_for_bob(world)
    browser = world.web()
    r = browser.get(path)
    assert r.status_code == 303 and r.headers["location"] == f"/login?next={path}"
    assert "Sign in" in browser.get(r.headers["location"]).text


async def test_a_wrong_password_is_refused_and_sets_no_cookie(world):
    browser = world.web()
    r = browser.post("/login", data={"username": "diner-bob", "password": "nope", "next": "/"})
    assert r.status_code == 401 and "Wrong username or password" in r.text
    assert COOKIE_NAME not in browser.cookies


async def test_the_session_cookie_is_locked_down(world):
    r = world.web().post("/login", data={"username": "diner-bob", "password": "bob-dev-pass", "next": "/"})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie


@pytest.mark.parametrize("evil", ["https://evil.example/", "//evil.example", "/consent/../../x", "javascript:alert(1)"])
async def test_login_never_redirects_to_another_site(world, evil):
    r = world.web().post("/login", data={"username": "diner-bob", "password": "bob-dev-pass", "next": evil})
    assert r.status_code == 303 and r.headers["location"] == "/"


async def test_a_forged_or_expired_session_counts_as_signed_out(world):
    path = await waiting_for_bob(world)
    browser = world.web()
    browser.cookies.set(COOKIE_NAME, "forged.value")
    assert browser.get(path).status_code == 303
    browser.cookies.clear()
    sign_in(browser, "bob", path)
    assert browser.get(path).status_code == 200
    world.clock.advance(hours=2)  # sessions last an hour
    assert browser.get(path).status_code == 303


# ---------------------------------------------------------------- the page
async def test_the_page_shows_the_terms_and_two_choices_and_cannot_be_framed(world):
    path = await waiting_for_bob(world)
    browser = world.web()
    sign_in(browser, "bob")
    r = browser.get(path)
    assert r.status_code == 200
    for expected in ("Confirm this booking?", "Luna Trattoria", "7:00 PM", "Cancellation is free", "Approve", "Decline"):
        assert expected in r.text
    assert "csrf" in r.text and "Signed in as" in r.text
    assert r.headers["x-frame-options"] == "DENY" and r.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert "referrer-policy" in r.headers


async def test_someone_elses_link_is_forbidden_and_nothing_changes(world):
    path = await waiting_for_bob(world)
    browser = world.web()
    sign_in(browser, "alice")
    r = browser.get(path)
    assert r.status_code == 403 and "Approve" not in r.text and "Luna Trattoria" not in r.text
    subject = path.rsplit("/", 1)[1]
    post = browser.post(f"{path}/decision", data={"decision": "approve", "csrf": "x"})
    assert post.status_code == 403
    assert world.store.get_approval(subject).status == "pending"


async def test_unknown_and_malformed_ids_are_404_not_errors(world):
    browser = world.web()
    sign_in(browser, "bob")
    for path in ("/consent/does-not-exist", "/consent/..%2F..%2Fetc", "/consent/" + "x" * 300):
        assert browser.get(path).status_code == 404, path


async def test_markup_in_the_terms_is_escaped(world):
    path = await waiting_for_bob(world)
    subject = path.rsplit("/", 1)[1]
    approval = world.store.get_approval(subject)
    world.store.replace_approval(replace(approval, terms={**approval.terms, "restaurant": "<script>alert(1)</script>"}))
    browser = world.web()
    sign_in(browser, "bob")
    html = browser.get(path).text
    assert "<script>alert(1)" not in html and "&lt;script&gt;" in html


# ---------------------------------------------------------------- approving, declining, end to end
async def test_approving_on_the_page_lets_the_assistant_finish_the_booking(world):
    path = await waiting_for_bob(world)
    subject = path.rsplit("/", 1)[1]
    browser = world.web()
    sign_in(browser, "bob", path)
    page = browser.get(path)
    r = browser.post(f"{path}/decision", data={"decision": "approve", "csrf": csrf_of(page.text)})
    assert r.status_code == 303 and r.headers["location"] == path
    assert "You approved this" in browser.get(path).text
    approval = world.store.get_approval(subject)
    assert (approval.status, approval.decided_at) == ("approved", iso_z(world.clock.now()))
    audit = world.store.list_audit("luna-trattoria", world.clock.now().date().isoformat())
    assert [e["decision"] for e in audit if e["tool"] == "consent_page"] == ["approved"]

    # back in the conversation: the same call as before now succeeds
    world.as_("bob")
    done = await call(world, "reservation_confirm", hold_id=subject, idempotency_key="key-web-conf1")
    assert not done.isError and done.structuredContent["approved_by_user"] is True
    assert world.store.get_approval(subject).status == "used"


async def test_declining_tells_the_assistant_not_to_ask_again(world):
    path = await waiting_for_bob(world)
    subject = path.rsplit("/", 1)[1]
    browser = world.web()
    sign_in(browser, "bob")
    csrf = csrf_of(browser.get(path).text)
    browser.post(f"{path}/decision", data={"decision": "decline", "csrf": csrf})
    assert "You declined this" in browser.get(path).text
    world.as_("bob")
    r = await call(world, "reservation_confirm", hold_id=subject, idempotency_key="key-web-conf1")
    assert r.structuredContent["error"] == "CONSENT_DECLINED"
    assert world.store.get_hold(subject).status == "held"  # nothing was booked


async def test_a_double_click_or_a_later_change_of_mind_does_not_change_the_answer(world):
    path = await waiting_for_bob(world)
    subject = path.rsplit("/", 1)[1]
    browser = world.web()
    sign_in(browser, "bob")
    csrf = csrf_of(browser.get(path).text)
    browser.post(f"{path}/decision", data={"decision": "approve", "csrf": csrf})
    again = browser.post(f"{path}/decision", data={"decision": "decline", "csrf": csrf})
    assert again.status_code == 303
    assert world.store.get_approval(subject).status == "approved"  # the first answer stands


async def test_a_missing_or_wrong_csrf_token_is_refused(world):
    path = await waiting_for_bob(world)
    subject = path.rsplit("/", 1)[1]
    browser = world.web()
    sign_in(browser, "bob")
    for bad in ({"decision": "approve"}, {"decision": "approve", "csrf": "wrong"}):
        assert browser.post(f"{path}/decision", data=bad).status_code == 403
    assert world.store.get_approval(subject).status == "pending"


async def test_a_csrf_token_for_one_request_does_not_work_on_another(world):
    first = await waiting_for_bob(world, "19:00", "1")
    second = await waiting_for_bob(world, "19:30", "2")
    browser = world.web()
    sign_in(browser, "bob")
    csrf_first = csrf_of(browser.get(first).text)
    r = browser.post(f"{second}/decision", data={"decision": "approve", "csrf": csrf_first})
    assert r.status_code == 403
    assert world.store.get_approval(second.rsplit("/", 1)[1]).status == "pending"
    assert world.store.get_approval(first.rsplit("/", 1)[1]).status == "pending"


async def test_a_choice_that_is_neither_approve_nor_decline_is_rejected(world):
    path = await waiting_for_bob(world)
    browser = world.web()
    sign_in(browser, "bob")
    csrf = csrf_of(browser.get(path).text)
    assert browser.post(f"{path}/decision", data={"decision": "maybe", "csrf": csrf}).status_code == 400


# ---------------------------------------------------------------- time
async def test_an_old_request_cannot_be_answered(world):
    path = await waiting_for_bob(world)
    subject = path.rsplit("/", 1)[1]
    browser = world.web()
    sign_in(browser, "bob")
    csrf = csrf_of(browser.get(path).text)
    world.clock.advance(minutes=16)  # past the 15 minutes (and the 10-minute hold)
    browser.cookies.clear()
    sign_in(browser, "bob")
    assert browser.get(path).status_code == 410
    r = browser.post(f"{path}/decision", data={"decision": "approve", "csrf": csrf})
    assert r.status_code in (403, 410)
    assert world.store.get_approval(subject).status == "pending"


async def test_the_hold_lives_long_enough_for_the_user_to_reach_the_page(world):
    """The step-up lengthens the hold to the whole approval window (D-022): at minute 12 the page
    still works, the user approves, and the assistant's retry at minute 13 books the table."""
    path = await waiting_for_bob(world)
    subject = path.rsplit("/", 1)[1]
    browser = world.web()
    world.clock.advance(minutes=12)  # the original 10-minute hold would be over
    sign_in(browser, "bob", path)
    page = browser.get(path)
    assert page.status_code == 200 and "Approve" in page.text
    browser.post(f"{path}/decision", data={"decision": "approve", "csrf": csrf_of(page.text)})
    world.clock.advance(minutes=1)
    world.as_("bob")
    done = await call(world, "reservation_confirm", hold_id=subject, idempotency_key="key-web-conf1")
    assert not done.isError and done.structuredContent["approved_by_user"] is True


async def test_when_the_booking_behind_the_request_is_gone_the_page_says_so(world):
    from server.lifecycle import release_expired

    path = await waiting_for_bob(world)
    subject = path.rsplit("/", 1)[1]
    world.clock.advance(minutes=16)  # past the extended hold as well
    release_expired(world.store, world.store.get_hold(subject), iso_z(world.clock.now()))
    approval = world.store.get_approval(subject)
    world.store.replace_approval(replace(approval, expires_at=iso_z(world.clock.now() + timedelta(hours=1))))
    browser = world.web()
    sign_in(browser, "bob")
    r = browser.get(path)
    assert r.status_code == 410 and "no longer active" in r.text


# ---------------------------------------------------------------- the second kind of approval: a cancellation fee
async def test_a_cancellation_fee_is_approved_on_the_page_and_then_the_cancel_goes_through(world):
    from flows import book

    booking = await book(world, "bob", "ember-grill", "18:00", offset=1)
    rid = booking["reservation_id"]
    world.as_("bob")
    asked = await call(world, "reservation_manage", action="cancel", reservation_id=rid,
                       idempotency_key="key-web-cancel")
    assert asked.structuredContent["error"] == "FEE_APPLIES"
    path = asked.structuredContent["consent_url"].removeprefix("http://localhost:8080")

    browser = world.web()
    sign_in(browser, "bob")
    page = browser.get(path)
    assert "Cancel this booking?" in page.text and "Cancellation fee" in page.text and "$25.00" in page.text
    browser.post(f"{path}/decision", data={"decision": "approve", "csrf": csrf_of(page.text)})

    done = await call(world, "reservation_manage", action="cancel", reservation_id=rid,
                      idempotency_key="key-web-cancel")
    assert not done.isError and done.structuredContent["fee_cents"] == 2500
    assert world.store.get_reservation(rid).status == "cancelled"


async def test_a_fee_approval_page_dies_with_its_booking(world):
    from flows import book

    booking = await book(world, "bob", "ember-grill", "18:00", offset=1)
    rid = booking["reservation_id"]
    world.as_("bob")
    asked = await call(world, "reservation_manage", action="cancel", reservation_id=rid,
                       idempotency_key="key-web-cancel")
    path = asked.structuredContent["consent_url"].removeprefix("http://localhost:8080")
    reservation = world.store.get_reservation(rid)
    world.store.put_item({**world.store.get_item(__import__("server.store", fromlist=["keys"]).keys.reservation(rid)),
                          "status": "cancelled"})
    browser = world.web()
    sign_in(browser, "bob")
    assert browser.get(path).status_code == 410 and reservation is not None
