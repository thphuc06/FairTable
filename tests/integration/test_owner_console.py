"""P1-17: the owner console. Only the restaurant's owner reaches it, and a cap change reaches rule S2."""

import re
from datetime import timedelta

import pytest
from ddb_env import ENDPOINT
from world import World

from web.session import COOKIE_NAME

pytestmark = pytest.mark.ddb


@pytest.fixture
def world(ddb_client, table_name, clock):
    w = World(ddb_client, table_name, ENDPOINT, clock)
    ids = iter(range(1, 100_000))
    w.deps.new_id = lambda: f"id{next(ids):05d}"
    return w


def sign_in(browser, username: str, password: str, next_path: str = "/owner"):
    return browser.post("/login", data={"username": username, "password": password, "next": next_path})


def csrf_of(html: str) -> str:
    return re.search(r"name='csrf' value='([^']+)'", html).group(1)


def owner_browser(world: World):
    browser = world.web()
    assert sign_in(browser, "owner-luna", "luna-dev-pass").status_code == 303
    return browser


def test_owner_page_needs_a_login(world):
    r = world.web().get("/owner")
    assert r.status_code == 303 and r.headers["location"] == "/login?next=/owner"


def test_a_diner_cannot_open_the_owner_page(world):
    browser = world.web()
    sign_in(browser, "diner-alice", "alice-dev-pass")
    assert browser.get("/owner").status_code == 403
    r = browser.post("/owner/agent-share", data={"pct": "0", "csrf": "x"})
    assert r.status_code == 403
    assert world.store.get_venue("luna-trattoria").agent_share_pct != 0


def test_owner_sees_share_rules_and_audit(world):
    r = owner_browser(world).get("/owner")
    assert r.status_code == 200
    assert "Luna Trattoria" in r.text and "Agent share" in r.text
    assert "Booking rules at Luna Trattoria" in r.text
    assert "Cache-Control" in r.headers and r.headers["X-Frame-Options"] == "DENY"


def test_owner_changes_the_share_and_it_is_audited(world):
    browser = owner_browser(world)
    csrf = csrf_of(browser.get("/owner").text)
    before = world.store.get_venue("luna-trattoria").agent_share_pct
    r = browser.post("/owner/agent-share", data={"pct": "25", "csrf": csrf})
    assert r.status_code == 303
    venue = world.store.get_venue("luna-trattoria")
    assert venue.agent_share_pct == 25
    entries = world.store.list_audit("luna-trattoria", world.clock.now().date().isoformat())
    changed = [e for e in entries if e["tool"] == "owner_console"]
    assert changed and changed[0]["detail"]["agent_share_pct_from"] == before
    assert changed[0]["detail"]["agent_share_pct_to"] == 25
    assert "owner_console" in browser.get("/owner").text


@pytest.mark.parametrize("value", ["", "abc", "-1", "101", "1.5", "  ", "1000"])
def test_bad_share_values_are_refused(world, value):
    browser = owner_browser(world)
    csrf = csrf_of(browser.get("/owner").text)
    before = world.store.get_venue("luna-trattoria").agent_share_pct
    r = browser.post("/owner/agent-share", data={"pct": value, "csrf": csrf})
    assert r.status_code == 400
    assert world.store.get_venue("luna-trattoria").agent_share_pct == before


def test_a_form_without_the_right_csrf_token_is_refused(world):
    browser = owner_browser(world)
    before = world.store.get_venue("luna-trattoria").agent_share_pct
    assert browser.post("/owner/agent-share", data={"pct": "0", "csrf": "nope"}).status_code == 403
    assert browser.post("/owner/agent-share", data={"pct": "0"}).status_code == 403
    assert world.store.get_venue("luna-trattoria").agent_share_pct == before


def test_a_forged_cookie_is_not_an_owner(world):
    browser = world.web()
    browser.cookies.set(COOKIE_NAME, "e30.AAAA")
    assert browser.get("/owner").status_code == 303


def test_a_diner_session_csrf_token_does_not_work_for_the_owner_form(world):
    """CSRF tokens are bound to the user: a token minted for another person is worthless."""
    owner = owner_browser(world)
    csrf = csrf_of(owner.get("/owner").text)
    other = world.web()
    sign_in(other, "diner-alice", "alice-dev-pass")
    assert other.post("/owner/agent-share", data={"pct": "0", "csrf": csrf}).status_code == 403


@pytest.mark.asyncio
async def test_lowering_the_share_flips_the_next_hold_to_s2(world):
    """The demo moment: the same hold succeeds, the owner drops the share, the same request is refused."""
    date = (world.clock.now().date() + timedelta(days=2)).isoformat()

    async def try_hold(who: str, key: str):
        world.as_(who)
        async with world.client() as c:
            a = await c.call_tool_mcp("availability_check", {
                "restaurant_id": "luna-trattoria", "date": date, "time_window": "19:00-19:00", "party_size": 2})
            token = a.structuredContent["slots"][0]["offer_id"]
            return await c.call_tool_mcp("reservation_hold", {"offer_id": token, "idempotency_key": key})

    ok = await try_hold("alice", "key-owner-1")
    assert not ok.isError, ok.structuredContent

    browser = owner_browser(world)
    csrf = csrf_of(browser.get("/owner").text)
    assert browser.post("/owner/agent-share", data={"pct": "0", "csrf": csrf}).status_code == 303

    denied = await try_hold("bob", "key-owner-2")
    assert denied.isError
    assert denied.structuredContent["rule_id"] == "S2_agent_share_of_covers"
