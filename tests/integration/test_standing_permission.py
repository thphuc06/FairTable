"""D-033: ticking the box on the approval page turns one approval into a standing permission, exactly as
wide as the page says, revocable under Permissions. Real DynamoDB Local, the real MCP tools and web app."""

import dataclasses
import re
from datetime import timedelta

import pytest
from ddb_env import ENDPOINT
from world import SUBS, World

from server.domain.grant import build_mandate
from server.domain.mandate import is_active
from simulator.model import ScriptedModel
from web.chat import ChatService

pytestmark = pytest.mark.ddb

PASSWORDS = {"bob": ("diner-bob", "bob-dev-pass"), "alice": ("diner-alice", "alice-dev-pass"),
             "carol": ("diner-carol", "carol-dev-pass")}
LUNA, EMBER = "luna-trattoria", "ember-grill"


@pytest.fixture
def world(ddb_client, table_name, clock):
    w = World(ddb_client, table_name, ENDPOINT, clock)
    ids = iter(range(1, 100_000))
    w.deps.new_id = lambda: f"id{next(ids):05d}"
    return w


def day(world: World, offset: int = 2) -> str:
    return (world.clock.now().date() + timedelta(days=offset)).isoformat()


async def call(world: World, tool: str, **args):
    async with world.client() as c:
        return await c.call_tool_mcp(tool, args)


async def hold_and_confirm(world: World, who: str, venue: str = LUNA, time: str = "19:00", party: int = 2,
                           tag: str = "1", offset: int = 2):
    """Hold and confirm as ``who``; returns (hold id, the confirm result: a booking or a request for approval)."""
    world.as_(who)
    a = await call(world, "availability_check", restaurant_id=venue, date=day(world, offset),
                   time_window=f"{time}-{time}", party_size=party)
    slot = a.structuredContent["slots"][0]["slot_token"]
    h = await call(world, "reservation_hold", slot_token=slot, idempotency_key=f"key-perm-hold-{tag}")
    hold_id = h.structuredContent["hold_id"]
    return hold_id, await call(world, "reservation_confirm", hold_id=hold_id, idempotency_key=f"key-perm-conf-{tag}")


async def book(world: World, who: str, venue: str = LUNA, time: str = "19:00", party: int = 2, tag: str = "1"):
    return (await hold_and_confirm(world, who, venue, time, party, tag))[1]


async def retry_confirm(world: World, hold_id: str, tag: str = "1"):
    """The assistant's retry after the diner answered: the same hold and the same key."""
    return await call(world, "reservation_confirm", hold_id=hold_id, idempotency_key=f"key-perm-conf-{tag}")


def link_of(result) -> str:
    assert result.structuredContent["error"] == "CONSENT_REQUIRED", result.structuredContent
    return result.structuredContent["consent_url"].removeprefix("http://localhost:8080")


def sign_in(browser, who: str, next_path: str = "/"):
    user, password = PASSWORDS[who]
    r = browser.post("/login", data={"username": user, "password": password, "next": next_path})
    assert r.status_code == 303


def csrf_of(html: str) -> str:
    return re.search(r"name='csrf' value='([^']+)'", html).group(1)


def approve(browser, path: str, *, tick: bool, days: str = "30", decision: str = "approve"):
    page = browser.get(path)
    data = {"decision": decision, "csrf": csrf_of(page.text)}
    if tick:
        data.update(remember="1", days=days)
    return browser.post(f"{path}/decision", data=data)


def mandate(world: World, who: str, venue: str = LUNA):
    return world.store.get_mandate(SUBS[who], venue)


async def ask_and_tick(world, browser, who, venue=LUNA, time="19:00", party=2, tag="1", days="30"):
    """The assistant asks, the diner approves with the box ticked. Returns the hold id (to retry the confirm)."""
    hold_id, result = await hold_and_confirm(world, who, venue, time, party, tag)
    assert approve(browser, link_of(result), tick=True, days=days).status_code == 303
    return hold_id


# ---------------------------------------------------------------------------------- the offer
async def test_bob_is_offered_the_tick_box_with_the_exact_limits(world):
    browser = world.web()
    sign_in(browser, "bob")
    page = browser.get(link_of(await book(world, "bob"))).text
    assert "type='checkbox' name='remember'" in page and "name='days'" in page
    assert "Let my assistant book at Luna Trattoria without asking me again, for the next" in page
    for days in ("7", "30", "90"):
        assert f"<option value='{days}'" in page
    assert "<option value='30' selected>" in page
    assert "up to 4 people, any time, no cancellation fee" in page and "&#x27;alexa-plus-sim&#x27;" in page


async def test_no_box_when_the_diner_already_has_a_live_permission_there(world):
    browser = world.web()
    sign_in(browser, "alice")  # Alice has a seeded permission at Luna; a party of 5 is outside it
    page = browser.get(link_of(await book(world, "alice", party=5))).text
    assert "Approve" in page and "name='remember'" not in page


async def test_no_box_for_a_cancellation_fee_approval(world):
    carol = world.web()
    sign_in(carol, "carol")
    hold_id, r = await hold_and_confirm(world, "carol", EMBER, offset=1)  # inside Ember's 48 hours: a fee applies
    assert approve(carol, link_of(r), tick=False).status_code == 303
    booked = await retry_confirm(world, hold_id)
    manage = await call(world, "reservation_manage", action="cancel", reservation_id=booked.structuredContent["reservation_id"],
                        idempotency_key="key-perm-cancel-1")
    assert manage.structuredContent["error"] == "FEE_APPLIES"
    page = carol.get(manage.structuredContent["consent_url"].removeprefix("http://localhost:8080")).text
    assert "Cancel this booking" in page and "name='remember'" not in page


# ---------------------------------------------------------------------------------- granting
async def test_ticking_the_box_grants_exactly_what_was_shown_and_the_next_booking_needs_no_approval(world):
    browser = world.web()
    sign_in(browser, "bob")
    assert mandate(world, "bob") is None
    hold_id = await ask_and_tick(world, browser, "bob", tag="1")
    m = mandate(world, "bob")
    assert (m.party_size_max, m.days_ahead_max, m.max_cancel_fee_cents) == (4, 30, 0)
    assert (m.window_start, m.window_end) == ("00:00", "23:59") and m.agent_ids == frozenset({"alexa-plus-sim"})
    assert m.status == "active" and m.venue_id == LUNA

    first = await retry_confirm(world, hold_id)
    assert not first.isError  # this booking is finished with the approval just given

    second = await book(world, "bob", time="20:00", tag="2")  # a similar booking: no link, no approval
    assert not second.isError and second.structuredContent["code"].startswith("LUN-")


async def test_outside_the_grant_the_diner_is_still_asked(world):
    browser = world.web()
    sign_in(browser, "bob")
    await ask_and_tick(world, browser, "bob", tag="1")
    assert (await book(world, "bob", party=5, time="18:00", tag="big")).structuredContent["error"] == "CONSENT_REQUIRED"
    assert (await book(world, "bob", EMBER, time="18:00", tag="ember")).structuredContent["error"] == "CONSENT_REQUIRED"


async def test_a_restaurant_with_a_fee_grants_that_fee_and_says_so(world):
    browser = world.web()
    sign_in(browser, "bob")
    path = link_of(await book(world, "bob", EMBER, tag="e1"))
    assert "a cancellation fee of up to $25.00 may apply" in browser.get(path).text
    assert approve(browser, path, tick=True, days="7").status_code == 303
    m = mandate(world, "bob", EMBER)
    assert m.max_cancel_fee_cents == 2500 and m.days_ahead_max == 7
    ok = await book(world, "bob", EMBER, time="18:30", tag="e2")
    assert not ok.isError  # covered: the fee is within what was shown


async def test_approving_without_the_tick_grants_nothing(world):
    browser = world.web()
    sign_in(browser, "bob")
    path = link_of(await book(world, "bob"))
    assert approve(browser, path, tick=False).status_code == 303
    assert mandate(world, "bob") is None
    assert (await book(world, "bob", time="20:00", tag="2")).structuredContent["error"] == "CONSENT_REQUIRED"


async def test_declining_with_the_tick_grants_nothing(world):
    browser = world.web()
    sign_in(browser, "bob")
    path = link_of(await book(world, "bob"))
    assert approve(browser, path, tick=True, decision="decline").status_code == 303
    assert mandate(world, "bob") is None
    assert "You declined this" in browser.get(path).text


@pytest.mark.parametrize("days", ["", "0", "14", "365", "abc", "-7", "30.5"])
async def test_only_the_offered_lengths_are_accepted(world, days):
    browser = world.web()
    sign_in(browser, "bob")
    path = link_of(await book(world, "bob"))
    assert approve(browser, path, tick=True, days=days).status_code == 400
    assert mandate(world, "bob") is None
    assert "Approve" in browser.get(path).text  # still waiting: nothing was answered


async def test_a_double_submit_creates_one_permission(world):
    browser = world.web()
    sign_in(browser, "bob")
    path = link_of(await book(world, "bob"))
    page = browser.get(path)
    data = {"decision": "approve", "csrf": csrf_of(page.text), "remember": "1", "days": "30"}
    assert browser.post(f"{path}/decision", data=data).status_code == 303
    first = mandate(world, "bob")
    assert browser.post(f"{path}/decision", data=data).status_code == 303
    assert mandate(world, "bob") == first and first.version == 1


async def test_a_permission_that_appeared_meanwhile_is_kept_and_the_answer_is_still_recorded(world):
    browser = world.web()
    sign_in(browser, "bob")
    path = link_of(await book(world, "bob"))
    page = browser.get(path)
    assert "name='remember'" in page.text
    existing = dataclasses.replace(
        build_mandate(sub=SUBS["bob"], venue=world.store.get_venue(LUNA), agent_id="alexa-plus-sim", days=90,
                      now=world.clock.now()), party_size_max=3)
    world.store.put_mandate(existing)  # granted elsewhere between showing the page and pressing Approve
    data = {"decision": "approve", "csrf": csrf_of(page.text), "remember": "1", "days": "7"}
    assert browser.post(f"{path}/decision", data=data).status_code == 303
    assert mandate(world, "bob") == existing  # not replaced, not narrowed
    assert "You approved this" in browser.get(path).text


async def test_a_grant_is_recorded_in_the_audit_trail(world):
    browser = world.web()
    sign_in(browser, "bob")
    await ask_and_tick(world, browser, "bob", days="90")
    entries = [e for e in world.store.list_audit(LUNA, world.clock.now().date().isoformat()) if e["tool"] == "consent_page"]
    assert entries and entries[0]["detail"]["granted_days"] == 90


async def test_the_permission_ends_after_its_days_and_the_box_comes_back(world):
    browser = world.web()
    sign_in(browser, "bob")
    await ask_and_tick(world, browser, "bob", days="7")
    world.clock.advance(days=8)
    world._tokens.clear()  # the old tokens have expired with the clock
    assert not is_active(mandate(world, "bob"), world.clock.now())
    browser = world.web()
    sign_in(browser, "bob")
    a = await call(world.as_("bob"), "availability_check", restaurant_id=LUNA, date=day(world), time_window="19:00-19:00", party_size=2)
    h = await call(world, "reservation_hold", slot_token=a.structuredContent["slots"][0]["slot_token"], idempotency_key="key-perm-after")
    c = await call(world, "reservation_confirm", hold_id=h.structuredContent["hold_id"], idempotency_key="key-perm-after-c")
    assert c.structuredContent["error"] == "CONSENT_REQUIRED"
    assert "name='remember'" in browser.get(link_of(c)).text


# ---------------------------------------------------------------------------------- Permissions and revoking
async def test_permissions_page_needs_a_login_and_lists_the_live_permissions(world):
    browser = world.web()
    assert browser.get("/permissions").headers["location"] == "/login?next=/permissions"
    sign_in(browser, "bob")
    assert "None. Your assistant asks you before every booking." in browser.get("/permissions").text
    await ask_and_tick(world, browser, "bob")
    page = browser.get("/permissions").text
    assert "Luna Trattoria: up to 4 people, any time, within 30 days, no cancellation fee" in page
    assert "Revoke" in page


async def test_revoking_takes_the_permission_back_at_once(world):
    browser = world.web()
    sign_in(browser, "bob")
    await ask_and_tick(world, browser, "bob")
    token = csrf_of(browser.get("/permissions").text)
    r = browser.post("/permissions/revoke", data={"venue_id": LUNA, "csrf": token})
    assert r.status_code == 303
    m = mandate(world, "bob")
    assert m.status == "revoked" and m.version == 2
    assert "None." in browser.get("/permissions").text
    assert (await book(world, "bob", time="20:00", tag="2")).structuredContent["error"] == "CONSENT_REQUIRED"
    entries = [e for e in world.store.list_audit(LUNA, world.clock.now().date().isoformat()) if e["tool"] == "permissions"]
    assert entries and entries[0]["decision"] == "revoked"
    again = browser.post("/permissions/revoke", data={"venue_id": LUNA, "csrf": token})
    assert "already gone" in again.text


async def test_a_seeded_permission_can_be_revoked_too(world):
    browser = world.web()
    sign_in(browser, "alice")
    page = browser.get("/permissions")
    assert "17:00 and 22:00" in page.text  # Alice's own, narrower permission is described as it is
    browser.post("/permissions/revoke", data={"venue_id": LUNA, "csrf": csrf_of(page.text)})
    assert mandate(world, "alice").status == "revoked"
    assert (await book(world, "alice")).structuredContent["error"] == "CONSENT_REQUIRED"


async def test_nobody_can_revoke_someone_elses_permission(world):
    bob = world.web()
    sign_in(bob, "bob")
    await ask_and_tick(world, bob, "bob")
    alice = world.web()
    sign_in(alice, "alice")
    page = alice.get("/permissions")
    alice.post("/permissions/revoke", data={"venue_id": LUNA, "csrf": csrf_of(page.text)})  # her own
    assert mandate(world, "bob").status == "active"  # the key is built from the session, not the form
    assert alice.post("/permissions/revoke", data={"venue_id": LUNA, "csrf": csrf_of(bob.get("/permissions").text)}).status_code == 403


async def test_revoking_needs_the_csrf_token_and_a_sane_venue_id(world):
    browser = world.web()
    sign_in(browser, "bob")
    await ask_and_tick(world, browser, "bob")
    assert browser.post("/permissions/revoke", data={"venue_id": LUNA}).status_code == 403
    assert browser.post("/permissions/revoke", data={"venue_id": LUNA, "csrf": "nope"}).status_code == 403
    token = csrf_of(browser.get("/permissions").text)
    assert browser.post("/permissions/revoke", data={"venue_id": "../x", "csrf": token}).status_code == 400
    assert mandate(world, "bob").status == "active"


# ---------------------------------------------------------------------------------- through the chat
async def test_in_the_chat_the_second_booking_needs_no_approval_after_ticking_the_box(live):
    world, url = live
    service = ChatService(url, lambda: ScriptedModel(today=world.clock.now().date()), world.clock)
    try:
        browser = world.web(chat=service)
        sign_in(browser, "bob", "/chat")

        def say(text: str) -> str:
            page = browser.get("/chat").text
            browser.post("/chat", data={"message": text, "csrf": csrf_of(page)})
            return browser.get("/chat").text

        html = say(f"Book a table at Luna Trattoria for 2 on {day(world)} at 7pm")
        path = re.findall(r"href='http://localhost:8080(/consent/[A-Za-z0-9_-]+)'", html)[-1]
        assert approve(browser, path, tick=True).status_code == 303
        assert "Booked" in say("I approved it")

        html = say(f"Book a table at Luna Trattoria for 2 on {day(world)} at 8pm")
        assert html.lower().count("booked") >= 2 and "consent/" not in html.split("8pm")[-1]  # no new link
        summary = re.findall(r"<summary>(.*?)</summary>", html)[-1]
        assert "reservation_confirm &#10003;" in summary and "&#10007;" not in summary
        assert len(world.store.reservations_of_user(SUBS["bob"])) == 2
    finally:
        service.close()


async def test_a_booking_made_under_a_permission_stays_valid_after_it_is_revoked(world):
    """The invariant checker must judge a booking by the permission that was live when it was made."""
    from server.domain.clock import iso_z
    from server.invariants import check_invariants

    browser = world.web()
    sign_in(browser, "bob")
    await ask_and_tick(world, browser, "bob")
    assert not (await book(world, "bob", time="20:00", tag="2")).isError  # booked under the permission
    assert check_invariants(world.store, iso_z(world.clock.now())) == []
    world.clock.advance(minutes=5)
    world._tokens.clear()
    browser.post("/permissions/revoke", data={"venue_id": LUNA, "csrf": csrf_of(browser.get("/permissions").text)})
    assert mandate(world, "bob").status == "revoked"
    assert check_invariants(world.store, iso_z(world.clock.now())) == []


async def test_a_booking_made_after_the_revocation_without_approval_is_still_flagged(world):
    """The relaxation is only for bookings made while the permission was live."""
    from server.domain.booking import Reservation
    from server.domain.clock import iso_z
    from server.invariants import check_invariants
    from server.store.mappers import hold_to_item, reservation_to_item

    browser = world.web()
    sign_in(browser, "bob")
    await ask_and_tick(world, browser, "bob")
    world.clock.advance(minutes=5)
    world._tokens.clear()
    browser.post("/permissions/revoke", data={"venue_id": LUNA, "csrf": csrf_of(browser.get("/permissions").text)})
    world.clock.advance(minutes=5)
    world._tokens.clear()
    hold_id, result = await hold_and_confirm(world, "bob", time="20:00", tag="late")
    assert result.structuredContent["error"] == "CONSENT_REQUIRED"  # the server refuses without the permission
    hold = world.store.get_hold(hold_id)
    sneaky = Reservation("res-late", "LUN-9999", hold.hold_id, SUBS["bob"], "alexa-plus-sim", LUNA, hold.date, hold.time,
                         hold.table_group, 2, "confirmed", hold.terms, iso_z(world.clock.now()))
    world.store.put_item(reservation_to_item(sneaky))  # as if something had bypassed the server
    world.store.put_item(hold_to_item(dataclasses.replace(hold, status="confirmed")))
    assert "I1" in {v.code for v in check_invariants(world.store, iso_z(world.clock.now()))}
