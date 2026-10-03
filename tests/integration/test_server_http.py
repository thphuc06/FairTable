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


async def refused_with_401(url: str, token: str | None = None, **headers) -> bool:
    """A `tools/call` that the transport answers with HTTP 401 (Alexa+ starts account linking on it)."""
    if token:
        headers["x-ft-user-token"] = token
    call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "restaurant_search", "arguments": {}}}
    async with httpx.AsyncClient() as http:
        r = await http.post(url, json=call, headers={**MCP_HEADERS, **headers})
    return r.status_code == 401 and r.json()["error"] == "unauthorized"


async def test_protocol_version_and_tool_surface(running):
    world, url = await running()
    async with client(url, world.token("alice")) as c:
        assert c.initialize_result.protocolVersion == "2025-11-25"
        tools = {t.name: t for t in await c.list_tools()}
    reads = {"restaurant_search", "availability_check"}
    writes = {"reservation_hold", "reservation_confirm", "reservation_manage", "waitlist_watch", "waitlist_status"}
    assert set(tools) == reads | writes  # the seven tools (D-053)
    assert all(tools[n].annotations.readOnlyHint for n in reads)
    assert not any(tools[n].annotations.readOnlyHint for n in writes)
    assert all(tools[n].annotations.idempotentHint for n in writes)  # safe to retry with the same key
    assert tools["reservation_manage"].annotations.destructiveHint  # cancel is destructive
    assert "offer_id" in tools["availability_check"].description  # written for the model


async def test_identity_comes_from_the_x_ft_user_token_header(running):
    world, url = await running()
    async with client(url, world.token("alice")) as c:
        slots = await c.call_tool_mcp("availability_check", {
            "restaurant_id": "luna-trattoria", "date": "2026-10-03", "time_window": "19:00-19:00", "party_size": 2})
        hold = await c.call_tool_mcp("reservation_hold", {
            "offer_id": slots.structuredContent["slots"][0]["offer_id"], "idempotency_key": "key-http-0001"})
    assert not hold.isError
    async with client(url, world.token("bob")) as c:  # Bob cannot read Alice's hold through his own token
        other = await c.call_tool_mcp("reservation_confirm", {
            "hold_id": hold.structuredContent["hold_id"], "idempotency_key": "key-http-0002"})
    assert other.isError and other.structuredContent["error"] == "NOT_FOUND"


@pytest.mark.parametrize("token", [None, "garbage", "a.b.c"])
async def test_missing_or_garbage_tokens_are_refused(running, token):
    _, url = await running()
    assert await refused_with_401(url, token)


async def test_a_bearer_header_is_an_identity_when_it_carries_a_valid_token(running):
    """MCP clients, Alexa+ included, send `Authorization: Bearer`; the token is verified exactly like x-ft-user-token (D-065)."""
    world, url = await running()
    async with Client(StreamableHttpTransport(url, headers={"Authorization": f"Bearer {world.token('alice')}"})) as c:
        result = await c.call_tool_mcp("restaurant_search", {})
    assert not result.isError and len(result.structuredContent["restaurants"]) == 3
    assert await refused_with_401(url, Authorization="Bearer garbage")
    assert await refused_with_401(url, Authorization="Basic " + world.token("alice"))  # not the Bearer scheme


async def test_the_gateway_header_wins_over_a_bearer_header(running):
    world, url = await running()
    async with Client(StreamableHttpTransport(url, headers={
            "x-ft-user-token": world.token("alice"), "Authorization": f"Bearer {world.token('bob')}"})) as c:
        slots = await c.call_tool_mcp("availability_check", {
            "restaurant_id": "luna-trattoria", "date": "2026-10-03", "time_window": "19:00-19:00", "party_size": 2})
        hold = await c.call_tool_mcp("reservation_hold", {
            "offer_id": slots.structuredContent["slots"][0]["offer_id"], "idempotency_key": "key-http-0003"})
    assert world.store.get_hold(hold.structuredContent["hold_id"]).sub == "dev-alice"


async def test_the_oauth_metadata_is_public_and_a_401_points_to_it(running):
    _world, url = await running()
    origin = url.rsplit("/mcp", 1)[0]
    async with httpx.AsyncClient() as http:
        root = await http.get(origin + "/.well-known/oauth-protected-resource")
        with_path = await http.get(origin + "/.well-known/oauth-protected-resource/mcp")
        call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "restaurant_search", "arguments": {}}}
        refused = await http.post(url, json=call, headers=MCP_HEADERS)
    assert root.status_code == 200 and root.json() == with_path.json()
    assert root.json()["authorization_servers"] == ["http://localhost:9000"]
    assert root.json()["scopes_supported"] == ["fairtable/book"] and root.json()["resource"].endswith("/mcp")
    assert refused.status_code == 401 and 'resource_metadata="' in refused.headers["www-authenticate"]


async def test_a_service_token_reads_but_a_write_tool_gets_403(running):
    """Alexa+ calls with its service-level token until the diner has linked an account; a 403 is what makes it start linking."""
    world, url = await running()
    bot = world.token("bot")
    async with client(url, bot) as c:
        read = await c.call_tool_mcp("restaurant_search", {})
    assert not read.isError
    write = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "reservation_hold", "arguments": {
        "offer_id": "abcd1234", "idempotency_key": "key-http-0004"}}}
    async with httpx.AsyncClient() as http:
        r = await http.post(url, json=write, headers={**MCP_HEADERS, "Authorization": f"Bearer {bot}"})
    assert r.status_code == 403 and r.json()["error"] == "forbidden"
    assert 'error="insufficient_scope"' in r.headers["www-authenticate"]


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
    assert await refused_with_401(url, forged)


async def test_an_expired_token_is_refused(running, clock):
    world, url = await running()
    token = world.token("alice")
    clock.advance(seconds=3600 + 60)
    assert await refused_with_401(url, token)


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


async def test_only_tool_calls_need_a_token_and_a_valid_token_goes_through(running):
    """Alexa+ discovers the tools with its service-level token and starts account linking on a 401 to a tool call."""
    world, url = await running()
    async with httpx.AsyncClient() as http:
        assert (await http.post(url, json=INIT, headers=MCP_HEADERS)).status_code == 200  # initialize: no token
    async with client(url) as c:
        assert len(await c.list_tools()) == 7  # tools/list: no token
    assert not await refused_with_401(url, world.token("alice"))  # a valid token reaches the tool
    async with client(url, world.token("alice")) as c:
        r = await c.call_tool_mcp("restaurant_search", {})
    assert not r.isError and r.structuredContent["restaurants"]
