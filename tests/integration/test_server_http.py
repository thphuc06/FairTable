"""P1-7: the server over real Streamable HTTP: header identity, transport security, masked failures."""

import asyncio
import socket

import httpx
import pytest
import uvicorn
from ddb_env import ENDPOINT
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from joserfc import jwt
from joserfc.jwk import RSAKey
from world import World

from server.app import create_app
from server.identity import HttpJwks

pytestmark = pytest.mark.ddb

INIT = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-11-25", "capabilities": {},
               "clientInfo": {"name": "t", "version": "0"}},
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def running(ddb_client, table_name, clock):
    """Start the server for real. Yields (world, url); the server stops afterwards."""
    started = []

    async def start(**world_kwargs):
        world = World(ddb_client, table_name, ENDPOINT, clock, real_headers=True, **world_kwargs)
        port = free_port()
        server = uvicorn.Server(uvicorn.Config(create_app(world.deps), host="127.0.0.1", port=port,
                                               log_level="warning"))
        task = asyncio.create_task(server.serve())
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.05)
        assert server.started
        started.append((server, task))
        return world, f"http://127.0.0.1:{port}/mcp"

    yield start
    for server, task in started:
        server.should_exit = True
        await task


def client(url: str, token: str | None = None, **headers) -> Client:
    if token:
        headers["x-ft-user-token"] = token
    return Client(StreamableHttpTransport(url, headers=headers or None))


async def test_protocol_version_and_tool_surface(running):
    world, url = await running()
    async with client(url, world.token("alice")) as c:
        assert c.initialize_result.protocolVersion == "2025-11-25"
        tools = {t.name: t for t in await c.list_tools()}
    reads = {"restaurant_search", "availability_check", "mandate_status"}
    writes = {"reservation_hold", "reservation_confirm", "reservation_manage", "waitlist_watch", "waitlist_status"}
    assert set(tools) == reads | writes  # the eight tools of the design
    assert all(tools[n].annotations.readOnlyHint for n in reads)
    assert not any(tools[n].annotations.readOnlyHint for n in writes)
    assert all(tools[n].annotations.idempotentHint for n in writes)  # safe to retry with the same key
    assert tools["reservation_manage"].annotations.destructiveHint  # cancel is destructive
    assert "slot_token" in tools["availability_check"].description  # written for the model


async def test_identity_comes_from_the_x_ft_user_token_header(running):
    world, url = await running()
    async with client(url, world.token("alice")) as c:
        ok = await c.call_tool_mcp("mandate_status", {"restaurant_id": "luna-trattoria"})
    assert ok.structuredContent["mandate_state"] == "active"  # Alice's own mandate
    async with client(url, world.token("bob")) as c:
        other = await c.call_tool_mcp("mandate_status", {"restaurant_id": "luna-trattoria"})
    assert other.structuredContent["mandate_state"] == "none"  # a different user sees hers, not Alice's


@pytest.mark.parametrize("token", [None, "garbage", "a.b.c"])
async def test_missing_or_garbage_tokens_are_refused(running, token):
    _, url = await running()
    async with client(url, token) as c:
        r = await c.call_tool_mcp("restaurant_search", {})
    assert r.isError and r.structuredContent["error"] == "UNAUTHENTICATED"


async def test_a_bearer_header_alone_is_not_an_identity(running):
    """Only the gateway-verified x-ft-user-token counts; a plain Authorization header does not."""
    world, url = await running()
    async with client(url, Authorization=f"Bearer {world.token('alice')}") as c:
        r = await c.call_tool_mcp("restaurant_search", {})
    assert r.isError and r.structuredContent["error"] == "UNAUTHENTICATED"


async def test_rt4_a_forged_user_token_is_refused(running):
    world, url = await running()
    attacker = RSAKey.generate_key(2048, parameters={"kid": world.jwks.key_set().keys[0].kid})
    forged = jwt.encode(
        {"alg": "RS256", "kid": attacker.kid},
        {"iss": "http://localhost:9000", "aud": "fairtable-mcp", "sub": "dev-alice",
         "username": "diner-alice", "agent_tier": "verified", "scope": "fairtable/book",
         "exp": int(world.clock.now().timestamp()) + 600},
        attacker,
    )
    async with client(url, forged) as c:
        r = await c.call_tool_mcp("mandate_status", {"restaurant_id": "luna-trattoria"})
    assert r.isError and r.structuredContent["error"] == "UNAUTHENTICATED"


async def test_an_expired_token_is_refused(running, clock):
    world, url = await running()
    token = world.token("alice")
    clock.advance(seconds=3600 + 60)
    async with client(url, token) as c:
        r = await c.call_tool_mcp("restaurant_search", {})
    assert r.isError and r.structuredContent["error"] == "UNAUTHENTICATED"


async def test_hostile_origin_and_host_are_rejected_but_plain_clients_work(running):
    _world, url = await running()
    async with httpx.AsyncClient() as c:
        bad_origin = await c.post(url, json=INIT, headers={**MCP_HEADERS, "Origin": "http://evil.example"})
        bad_host = await c.post(url, json=INIT, headers={**MCP_HEADERS, "Host": "evil.example"})
        plain = await c.post(url, json=INIT, headers=MCP_HEADERS)
    assert bad_origin.status_code == 403
    assert bad_host.status_code in (403, 421)
    assert plain.status_code == 200


async def test_a_key_server_outage_refuses_the_request_without_leaking_why(running, clock):
    down = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    working, _ = await running()  # only used to mint a well-formed token
    _broken, url = await running(jwks=HttpJwks("http://issuer.invalid/jwks.json", clock, client=down))
    async with client(url, working.token("alice")) as c:
        r = await c.call_tool_mcp("restaurant_search", {})
    assert r.isError
    text = r.content[0].text
    assert "JWKS" not in text and "503" not in text and "issuer.invalid" not in text
    assert r.structuredContent is None or "error" not in (r.structuredContent or {})


async def test_unexpected_exceptions_are_masked(running):
    world, url = await running()
    world.deps.store.get_venue = lambda _id: 1 / 0  # simulate a bug inside a tool
    async with client(url, world.token("alice")) as c:
        r = await c.call_tool_mcp("mandate_status", {"restaurant_id": "luna-trattoria"})
    assert r.isError and "division" not in r.content[0].text.lower()
