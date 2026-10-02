"""The web app's sign-in and session handling (kept from the consent page tests of P1-11; the consent page itself
is gone, D-051). The chat page and the owner console rely on exactly this."""

import pytest
from ddb_env import ENDPOINT
from world import World

from web.session import COOKIE_NAME

pytestmark = pytest.mark.ddb


@pytest.fixture
def world(ddb_client, table_name, clock):
    return World(ddb_client, table_name, ENDPOINT, clock)


def sign_in(browser, next_path: str = "/chat") -> None:
    r = browser.post("/login", data={"username": "diner-bob", "password": "bob-dev-pass", "next": next_path})
    assert r.status_code == 303 and COOKIE_NAME in browser.cookies


def test_a_page_that_needs_a_session_leads_to_the_login_page(world):
    r = world.web().get("/owner")
    assert r.status_code == 303 and r.headers["location"] == "/login?next=/owner"


def test_a_wrong_password_is_refused_and_sets_no_cookie(world):
    browser = world.web()
    r = browser.post("/login", data={"username": "diner-bob", "password": "nope", "next": "/"})
    assert r.status_code == 401 and "Wrong username or password" in r.text
    assert COOKIE_NAME not in browser.cookies


def test_the_session_cookie_is_locked_down(world):
    r = world.web().post("/login", data={"username": "diner-bob", "password": "bob-dev-pass", "next": "/"})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie


@pytest.mark.parametrize("evil", ["https://evil.example/", "//evil.example", "/chat/../../x", "javascript:alert(1)"])
def test_login_never_redirects_to_another_site(world, evil):
    r = world.web().post("/login", data={"username": "diner-bob", "password": "bob-dev-pass", "next": evil})
    assert r.status_code == 303 and r.headers["location"] == "/"


def test_a_forged_or_expired_session_counts_as_signed_out(world):
    browser = world.web()
    browser.cookies.set(COOKIE_NAME, "forged.value")
    assert browser.get("/owner").status_code == 303
    browser.cookies.clear()
    sign_in(browser, "/owner")
    assert browser.get("/owner").status_code in (200, 403)  # a diner is signed in; the owner page says "owners only"
    world.clock.advance(hours=2)  # sessions last an hour
    assert browser.get("/owner").status_code == 303


def test_every_page_is_uncacheable_and_cannot_be_framed(world):
    r = world.web().get("/login")
    assert r.headers["cache-control"] == "no-store" and r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]


def test_the_consent_and_permission_pages_no_longer_exist(world):
    browser = world.web()
    sign_in(browser)
    for path in ("/consent/anything", "/permissions"):
        assert browser.get(path).status_code == 404
