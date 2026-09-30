"""AgentCore Runtime runs an MCP server statelessly (docs/PLAN.md section 3a): every request stands alone, and
the platform adds an ``Mcp-Session-Id`` header that the server must not reject. No database is needed:
nothing here reaches a tool that reads or writes."""

import asyncio
import json
import socket

import httpx
import pytest
import uvicorn
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from joserfc.jwk import KeySet, RSAKey

from runtime_entry import RUNTIME_CONTRACT
from server.app import build_deps, create_app
from server.config import DEV_SESSION_SECRET, Settings
from server.identity import StaticJwks
from server.store import StoreConfig

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}}
LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def settings(**over) -> Settings:
    base = {"MCP_STATELESS": "true", "MCP_ALLOWED_HOSTS": "127.0.0.1,localhost", "TABLE_NAME": "unused",
            "DDB_ENDPOINT_URL": "http://127.0.0.1:1"}
    return Settings.from_env({**base, **over})


@pytest.fixture
async def running():
    servers = []

    async def start(**over):
        s = settings(**over)
        port = free_port()
        deps = build_deps(s, jwks=StaticJwks(KeySet([RSAKey.generate_key(2048, auto_kid=True)]).as_dict(private=False)))
        server = uvicorn.Server(uvicorn.Config(create_app(deps), host="127.0.0.1", port=port, log_level="warning"))
        task = asyncio.create_task(server.serve())
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.05)
        assert server.started
        servers.append((server, task))
        return f"http://127.0.0.1:{port}/mcp"

    yield start
    for server, task in servers:
        server.should_exit = True
        await task


def body_of(response: httpx.Response) -> dict:
    """The JSON-RPC message, whether the reply is plain JSON or one server-sent event."""
    text = response.text
    if response.headers["content-type"].startswith("text/event-stream"):
        text = next(line[5:] for line in text.splitlines() if line.startswith("data:"))
    return json.loads(text)


def test_the_setting_is_read_from_the_environment():
    assert Settings.from_env({"MCP_STATELESS": "true"}).stateless_http
    assert Settings.from_env({"MCP_STATELESS": "1"}).stateless_http
    assert not Settings.from_env({}).stateless_http and not Settings.from_env({"MCP_STATELESS": "no"}).stateless_http


def test_the_runtime_contract_is_what_the_documentation_fixes():
    assert RUNTIME_CONTRACT["MCP_HOST"] == "0.0.0.0" and RUNTIME_CONTRACT["MCP_PORT"] == "8000"
    assert RUNTIME_CONTRACT["MCP_STATELESS"] == "true"


async def test_a_stateless_server_lists_the_eight_tools_without_a_handshake(running):
    url = await running()
    async with httpx.AsyncClient() as http:
        r = await http.post(url, headers=HEADERS, json=LIST)  # no initialize first: each call stands alone
    assert r.status_code == 200
    names = {t["name"] for t in body_of(r)["result"]["tools"]}
    assert names == {"restaurant_search", "availability_check", "mandate_status", "reservation_hold",
                     "reservation_confirm", "reservation_manage", "waitlist_watch", "waitlist_status"}


async def test_a_session_id_added_by_the_platform_is_accepted(running):
    """AgentCore adds an Mcp-Session-Id to requests; a stateless server must not answer 404 or 400."""
    url = await running()
    async with httpx.AsyncClient() as http:
        r = await http.post(url, headers={**HEADERS, "Mcp-Session-Id": "runtime-generated-session-0123456789abcdef"},
                            json=LIST)
    assert r.status_code == 200 and "tools" in body_of(r)["result"]


async def test_the_default_server_still_wants_a_session(running):
    """The local profile is unchanged: without MCP_STATELESS an unknown session id is refused."""
    url = await running(MCP_STATELESS="false")
    async with httpx.AsyncClient() as http:
        r = await http.post(url, headers={**HEADERS, "Mcp-Session-Id": "made-up-session-0123456789abcdef"}, json=LIST)
    assert r.status_code in (400, 404)


async def test_the_client_library_works_against_a_stateless_server(running):
    url = await running()
    async with Client(StreamableHttpTransport(url)) as c:
        assert c.initialize_result.protocolVersion == "2025-11-25"
        assert len(await c.list_tools()) == 8
        r = await c.call_tool_mcp("restaurant_search", {})  # no token: refused before any database call
    assert r.isError and r.structuredContent["error"] == "UNAUTHENTICATED"


async def test_host_protection_still_applies_when_stateless(running):
    url = await running()
    async with httpx.AsyncClient() as http:
        r = await http.post(url, headers={**HEADERS, "Host": "evil.example"}, json=INIT)
    assert r.status_code == 421


def test_the_aws_profile_still_refuses_the_built_in_secrets():
    with pytest.raises(ValueError, match="SLOT_TOKEN_SECRET"):
        Settings.from_env({"APP_PROFILE": "aws", "WEB_SESSION_SECRET": "x" * 32})
    assert DEV_SESSION_SECRET  # the placeholder exists only for the local profile
    assert StoreConfig("t").table_name == "t"
