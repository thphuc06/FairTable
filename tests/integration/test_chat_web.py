"""P1-19, P3-10: the chat page. The diner answers the read-back by typing yes; the assistant is the simulator's."""

import re
from datetime import timedelta

import pytest
from world import World

from simulator.model import ScriptedModel
from web.chat import ChatService

pytestmark = pytest.mark.ddb

ACCOUNTS = {"alice": ("diner-alice", "alice-dev-pass"), "bob": ("diner-bob", "bob-dev-pass"),
            "luna": ("owner-luna", "luna-dev-pass")}


def day(world: World) -> str:
    return (world.clock.now().date() + timedelta(days=2)).isoformat()


def chat_service(world: World, url: str) -> ChatService:
    return ChatService(url, lambda: ScriptedModel(today=world.clock.now().date()), world.clock)


def sign_in(browser, who: str, next_path: str = "/chat") -> None:
    user, password = ACCOUNTS[who]
    r = browser.post("/login", data={"username": user, "password": password, "next": next_path})
    assert r.status_code == 303 and r.headers["location"] == next_path


def csrf_of(html: str) -> str:
    return re.search(r"name='csrf' value='([^']+)'", html).group(1)


def yes(world: World, browser) -> str:
    """The diner has heard the details and answers: a few seconds pass, then the yes."""
    world.clock.advance(8)
    return say(browser, "Yes, please")


def say(browser, text: str):
    csrf = csrf_of(browser.get("/chat").text)
    r = browser.post("/chat", data={"message": text, "csrf": csrf})
    assert r.status_code == 303 and r.headers["location"] == "/chat"
    return browser.get("/chat").text


@pytest.fixture
def chat_env(live):
    world, url = live
    service = chat_service(world, url)
    yield world, world.web(chat=service), service
    service.close()


def test_the_chat_page_needs_a_sign_in(chat_env):
    _, browser, _ = chat_env
    r = browser.get("/chat")
    assert r.status_code == 303 and r.headers["location"] == "/login?next=/chat"
    assert browser.post("/chat", data={"message": "hi", "csrf": "x"}).status_code == 303
    landing = browser.get("/")  # signed out: a landing page with the way in
    assert landing.status_code == 200 and "href='/chat'" in landing.text


def test_the_landing_page_sends_each_person_to_their_own_page(chat_env):
    _, browser, _ = chat_env
    sign_in(browser, "alice", "/")
    assert browser.get("/").headers["location"] == "/chat"
    owner = chat_env[0].web(chat=chat_env[2])
    sign_in(owner, "luna", "/")
    assert owner.get("/").headers["location"] == "/owner"


async def test_a_diner_books_a_table_by_chatting(chat_env):
    world, browser, _ = chat_env
    sign_in(browser, "alice")
    html = say(browser, f"Book a table at Luna Trattoria for 2 on {day(world)} at 7pm")
    assert "Assistant:" in html and "shall i book it" in html.lower()
    assert not world.store.reservations_of_user(world_sub(world, "alice"))  # asked, not booked
    html = yes(world, browser)
    assert "booked" in html.lower()
    assert len(world.store.reservations_of_user(world_sub(world, "alice"))) == 1


async def test_one_conversation_can_make_several_different_requests(chat_env):
    """Each new request starts a new task: two bookings in one chat are two reservations, not a repeat."""
    world, browser, _ = chat_env
    sign_in(browser, "alice")
    say(browser, f"Book a table at Luna Trattoria for 2 on {day(world)} at 7pm")
    yes(world, browser)
    say(browser, f"Book a table at Luna Trattoria for 4 on {day(world)} at 8pm")
    html = yes(world, browser)
    assert html.lower().count("booked") >= 2
    reservations = world.store.reservations_of_user(world_sub(world, "alice"))
    assert sorted((r.time, r.party_size) for r in reservations) == [("19:00", 2), ("20:00", 4)]


def world_sub(world: World, who: str) -> str:
    from world import SUBS

    return SUBS[who]


async def test_every_diner_just_says_yes_there_is_no_page_to_visit(chat_env):
    """Bob has no standing permission and needs none: the assistant reads the details back, he answers in the chat."""
    world, browser, _ = chat_env
    sign_in(browser, "bob")
    html = say(browser, f"Book a table at Luna Trattoria for 2 on {day(world)} at 7pm")
    assert "shall i book it" in html.lower() and "/consent/" not in html and "Approve" not in html
    assert browser.get("/consent/anything").status_code == 404
    assert "booked" in yes(world, browser).lower()
    assert len(world.store.reservations_of_user(world_sub(world, "bob"))) == 1


async def test_a_no_in_the_chat_books_nothing(chat_env):
    world, browser, _ = chat_env
    sign_in(browser, "bob")
    say(browser, f"Book a table at Luna Trattoria for 2 on {day(world)} at 7pm")
    world.clock.advance(8)
    html = say(browser, "No, thanks")
    assert "won&#x27;t book" in html  # the apostrophe is escaped on the page
    assert not world.store.reservations_of_user(world_sub(world, "bob"))


def test_the_page_escapes_what_people_and_the_assistant_write(chat_env):
    _, browser, _ = chat_env
    sign_in(browser, "alice")
    html = say(browser, "<script>alert(1)</script> <b>x</b>")
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "<b>x</b>" not in html


def test_links_in_what_people_write_are_never_live(chat_env):
    _, browser, _ = chat_env
    sign_in(browser, "alice")
    html = say(browser, "see http://evil.example/consent/abc and http://localhost:8080/consent/abc123")
    assert "href=" not in html.split("<h2>Notifications</h2>")[0].split("</form>")[-1] or "<a href='http" not in html
    assert "href='http://evil.example" not in html and "href='http://localhost:8080/consent" not in html


def test_forms_need_the_right_csrf_token(chat_env):
    world, browser, _ = chat_env
    sign_in(browser, "alice")
    assert browser.post("/chat", data={"message": "hi"}).status_code == 403
    assert browser.post("/chat", data={"message": "hi", "csrf": "nope"}).status_code == 403
    assert browser.post("/chat/reset", data={"csrf": "nope"}).status_code == 403
    other = world.web(chat=chat_env[2])
    sign_in(other, "bob")
    token = csrf_of(other.get("/chat").text)
    assert browser.post("/chat", data={"message": "hi", "csrf": token}).status_code == 403  # bound to the user


def test_start_over_clears_the_conversation(chat_env):
    _, browser, _ = chat_env
    sign_in(browser, "alice")
    assert "Assistant:" in say(browser, "hello")
    csrf = csrf_of(browser.get("/chat").text)
    assert browser.post("/chat/reset", data={"csrf": csrf}).status_code == 303
    assert "Assistant:" not in browser.get("/chat").text


def test_each_person_sees_only_their_own_conversation(chat_env):
    world, alice, _ = chat_env
    sign_in(alice, "alice")
    say(alice, "hello from alice")
    bob = world.web(chat=chat_env[2])
    sign_in(bob, "bob")
    assert "hello from alice" not in bob.get("/chat").text


def test_long_messages_are_cut(chat_env):
    _, browser, _service = chat_env
    sign_in(browser, "alice")
    html = say(browser, "x" * 2000)
    assert "x" * 501 not in html


def test_without_a_configured_assistant_the_chat_page_is_off(live):
    world, _ = live
    browser = world.web(chat=None)
    user, password = ACCOUNTS["alice"]
    browser.post("/login", data={"username": user, "password": password, "next": "/"})
    assert browser.get("/chat").status_code == 404


def test_an_owner_cannot_use_a_diner_only_page_by_accident(chat_env):
    """Owners sign in to the same app; the chat is for whoever holds a token, the owner page for owners."""
    world, _, service = chat_env
    diner = world.web(chat=service)
    sign_in(diner, "alice")
    assert diner.get("/owner").status_code == 403


def test_the_assistant_is_told_todays_date(chat_env):
    world, _, service = chat_env
    prompt = service.system_prompt()
    assert "Today is" in prompt and f"{world.clock.now():%Y-%m-%d}" in prompt


async def test_the_chat_shows_the_tool_calls_and_the_rule_behind_each_answer(chat_env):
    """The proof for a demo: what the assistant asked of the server and what the server decided."""
    world, browser, _ = chat_env
    sign_in(browser, "alice")
    say(browser, f"Book a table at Luna Trattoria for 2 on {day(world)} at 7pm")
    html = yes(world, browser)
    summaries = re.findall(r"<summary>(.*?)</summary>", html)
    assert "reservation_hold" in summaries[0] and "reservation_confirm" in summaries[1]
    assert not any("&#10007;" in s for s in summaries)  # every step succeeded

    html = say(browser, f"Book a table at Luna Trattoria for 12 on {day(world)} at 7pm")
    assert "G3_party_size_max_10" in html and "refused" in html  # the rule that stopped it, from the server
