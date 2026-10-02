"""P1-23: the whole local profile (``docker compose up``) driven from the host over real HTTP.

Needs Docker and builds the image, so it only runs when selected: ``pytest -m docker``.
The test owns the stack: it starts it (or reuses one that is already up) and shuts it down afterwards.
Fixed host ports (8000, 8001, 8080, 9000) must be free.
"""

import re
import time
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

pytestmark = pytest.mark.docker

ROOT = Path(__file__).resolve().parents[2]
ISSUER, MCP, WEB = "http://localhost:9000", "http://localhost:8000/mcp", "http://localhost:8080"


def compose(*args: str, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, capture_output=True, encoding="utf-8",
                          errors="replace", timeout=timeout, check=False)


@pytest.fixture(scope="module")
def stack():
    up = compose("up", "-d", "--build", "--wait")
    if up.returncode != 0:
        logs = compose("logs", "--no-color", "--tail", "40").stdout
        pytest.fail(f"docker compose up failed:\n{up.stderr[-1500:]}\n{logs[-3000:]}")
    yield
    compose("down", "-v")


def token(username: str, password: str, client_id: str = "alexa-plus-sim") -> str:
    r = httpx.post(f"{ISSUER}/token", data={"grant_type": "password", "client_id": client_id,
                                            "username": username, "password": password})
    r.raise_for_status()
    return r.json()["access_token"]


def browser() -> httpx.Client:
    return httpx.Client(base_url=WEB, follow_redirects=False, timeout=60)


def sign_in(b: httpx.Client, username: str, password: str, next_path: str) -> None:
    r = b.post("/login", data={"username": username, "password": password, "next": next_path})
    assert r.status_code == 303, r.text


def csrf(html: str) -> str:
    return re.search(r"name='csrf' value='([^']+)'", html).group(1)


def test_every_service_is_up_and_only_on_loopback(stack):
    ps = compose("ps", "--format", "{{.Service}} {{.Status}} {{.Publishers}}").stdout
    for service in ("dynamodb", "devauth", "server", "web"):
        assert service in ps
    assert "0.0.0.0" not in ps and "[::]" not in ps  # nothing is published beyond this machine
    assert httpx.get(f"{ISSUER}/.well-known/jwks.json").status_code == 200
    assert httpx.get(f"{WEB}/healthz").json() == {"status": "ok"}


async def test_the_mcp_server_offers_the_seven_tools_to_a_signed_in_diner(stack):
    headers = {"x-ft-user-token": token("diner-alice", "alice-dev-pass")}
    async with Client(StreamableHttpTransport(MCP, headers=headers)) as c:
        assert c.initialize_result.protocolVersion == "2025-11-25"
        tools = {t.name for t in await c.list_tools()}
        found = await c.call_tool_mcp("restaurant_search", {})
    assert tools == {"restaurant_search", "availability_check", "reservation_hold",
                     "reservation_confirm", "reservation_manage", "waitlist_watch", "waitlist_status"}
    assert {r["restaurant_id"] for r in found.structuredContent["restaurants"]} == {
        "luna-trattoria", "ember-grill", "sakura-counter"}


async def test_the_server_refuses_a_missing_token_and_a_foreign_host_name(stack):
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "restaurant_search", "arguments": {}}}
    async with httpx.AsyncClient() as http:
        unlinked = await http.post(MCP, headers={"Content-Type": "application/json",
                                                 "Accept": "application/json, text/event-stream"}, json=call)
    assert unlinked.status_code == 401  # no token: what makes Alexa+ start account linking
    async with httpx.AsyncClient() as http:
        hostile = await http.post(MCP, headers={"Host": "evil.example", "Content-Type": "application/json",
                                                "Accept": "application/json, text/event-stream"}, json={})
    assert hostile.status_code == 421


def test_a_diner_books_through_the_chat_by_saying_yes_after_the_read_back(stack):
    """The demo path, with the built-in mock assistant: no key, no AWS. Real time passes, so the 3 s pause is real."""
    day = (datetime.now(UTC) + timedelta(days=2)).date().isoformat()
    b = browser()
    assert b.get("/").status_code == 200
    sign_in(b, "diner-bob", "bob-dev-pass", "/chat")
    page = b.get("/chat").text
    sent = b.post("/chat", data={"message": f"Book a table at Luna Trattoria for 2 on {day} at 7pm", "csrf": csrf(page)})
    assert sent.status_code == 303
    page = b.get("/chat").text
    assert "shall i book it" in page.lower() and "/consent/" not in page  # asked, with no link and no second device
    assert b.get("/consent/anything").status_code == 404
    time.sleep(4)  # the diner listens and answers: longer than the server's 3 s pause
    b.post("/chat", data={"message": "Yes, please", "csrf": csrf(b.get("/chat").text)})
    assert "booked" in b.get("/chat").text.lower()


def test_the_owner_console_lowers_the_agent_share(stack):
    b = browser()
    sign_in(b, "owner-luna", "luna-dev-pass", "/owner")
    page = b.get("/owner")
    assert page.status_code == 200 and "Luna Trattoria" in page.text
    assert b.post("/owner/agent-share", data={"pct": "10", "csrf": csrf(page.text)}).status_code == 303
    assert "<b>10%</b>" in b.get("/owner").text
    diner = browser()
    sign_in(diner, "diner-alice", "alice-dev-pass", "/chat")
    assert diner.get("/owner").status_code == 403
