"""P3-9: our server against the requests the Alexa+ MCP client makes.

The payloads are the ones on Amazon's "Alexa+ MCP Client and App Lifecycle" page (read 2026-10-02): an
`initialize` with protocol 2025-03-26 and only the `roots` capability, then ordinary calls with no MCP session
("the session is based on the customer's previous conversations with Alexa+ rather than an explicit identifier").
This does not prove that Alexa+ can call the server (nobody outside Amazon can try that); it rules out
incompatibilities of our own making. No database is needed: nothing here reaches a tool that touches it.
See docs/alexa-plus-addon-notes.md."""

import asyncio
import time

import httpx
import pytest
import uvicorn
from joserfc import jwt
from joserfc.jwk import KeySet, RSAKey

from server.app import build_deps, create_app
from server.identity import StaticJwks
from test_server_stateless import HEADERS, body_of, free_port, settings

ALEXA_INITIALIZE = {
    "jsonrpc": "2.0", "method": "initialize", "id": "4e3bdaee-0",
    "params": {"protocolVersion": "2025-03-26", "capabilities": {"roots": {"listChanged": True}},
               "clientInfo": {"name": "Alexa+ MCP Client", "version": "1.0.0"}},
}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}
LIST_TOOLS = {"jsonrpc": "2.0", "id": "4e3bdaee-1", "method": "tools/list", "params": {}}
CALL_TOOL = {"jsonrpc": "2.0", "id": "4a5bda6e-2", "method": "tools/call",
             "params": {"name": "restaurant_search",
                        "arguments": {"query": "italian", "date": "2026-10-03", "party_size": 2}}}


KEY = RSAKey.generate_key(2048, auto_kid=True)


def user_token() -> str:
    """A token the test server accepts (the dev issuer's claims, signed with the key it trusts)."""
    claims = {"iss": "http://localhost:9000", "aud": "fairtable-mcp", "sub": "dev-alice", "username": "diner-alice",
              "agent_tier": "verified", "scope": "fairtable/book", "exp": int(time.time()) + 600}
    return jwt.encode({"alg": "RS256", "kid": KEY.kid}, claims, KEY)


TOKEN_HEADER = "x-ft-user-token"
BAD_ARGUMENTS = {"jsonrpc": "2.0", "id": "4a5bda6e-3", "method": "tools/call",
                 "params": {"name": "restaurant_search", "arguments": {"party_size": "two"}}}


@pytest.fixture
async def url():
    started = []

    async def start(stateless: bool) -> str:
        deps = build_deps(settings(MCP_STATELESS="true" if stateless else "false"),
                          jwks=StaticJwks(KeySet([KEY]).as_dict(private=False)))
        port = free_port()
        server = uvicorn.Server(uvicorn.Config(create_app(deps), host="127.0.0.1", port=port, log_level="warning"))
        task = asyncio.create_task(server.serve())
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.05)
        assert server.started
        started.append((server, task))
        return f"http://127.0.0.1:{port}/mcp"

    yield start
    for server, task in started:
        server.should_exit = True
        await task


async def test_initialize_with_the_alexa_payload_negotiates_the_older_protocol_and_lists_tools_and_resources(url):
    async with httpx.AsyncClient() as http:
        r = await http.post(await url(True), headers=HEADERS, json=ALEXA_INITIALIZE)
    assert r.status_code == 200
    result = body_of(r)["result"]
    assert body_of(r)["id"] == "4e3bdaee-0"  # a string id comes back unchanged
    assert result["protocolVersion"] == "2025-03-26"  # the server answers with the client's version
    assert "tools" in result["capabilities"] and "resources" in result["capabilities"]
    assert result["serverInfo"]["name"]


async def test_the_follow_up_calls_work_without_any_mcp_session(url):
    base = await url(True)
    async with httpx.AsyncClient() as http:
        await http.post(base, headers=HEADERS, json=ALEXA_INITIALIZE)
        assert (await http.post(base, headers=HEADERS, json=INITIALIZED)).status_code == 202
        listed = await http.post(base, headers=HEADERS, json=LIST_TOOLS)
        called = await http.post(base, headers={**HEADERS, TOKEN_HEADER: user_token()}, json=BAD_ARGUMENTS)
        unlinked = await http.post(base, headers=HEADERS, json=CALL_TOOL)
    assert listed.status_code == 200 and len(body_of(listed)["result"]["tools"]) >= 7
    assert called.status_code == 200 and body_of(called)["id"] == "4a5bda6e-3"
    # A tool call with no token: HTTP 401, which is what makes Alexa+ start account linking (requirement 6).
    assert unlinked.status_code == 401 and unlinked.json()["error"] == "unauthorized"


async def test_a_tool_result_has_structured_content_and_a_text_form_like_the_alexa_sample(url):
    async with httpx.AsyncClient() as http:
        r = await http.post(await url(True), headers={**HEADERS, TOKEN_HEADER: user_token()}, json=BAD_ARGUMENTS)
    result = body_of(r)["result"]
    assert result["isError"] is True  # a bad argument is an error result with the usual shape, not a crash
    assert isinstance(result["structuredContent"], dict)
    assert "pydantic" not in result["content"][0]["text"]
    assert result["content"] and result["content"][0]["type"] == "text" and result["content"][0]["text"]


async def test_every_tool_has_a_json_schema_for_its_input(url):
    async with httpx.AsyncClient() as http:
        r = await http.post(await url(True), headers=HEADERS, json=LIST_TOOLS)
    for tool in body_of(r)["result"]["tools"]:
        schema = tool["inputSchema"]
        assert schema["type"] == "object" and "properties" in schema, tool["name"]
        assert tool["description"], tool["name"]  # requirement 13: clear descriptions


async def test_the_protocol_version_header_of_the_alexa_client_is_accepted_and_an_unknown_one_is_refused(url):
    base = await url(True)
    async with httpx.AsyncClient() as http:
        ok = await http.post(base, headers={**HEADERS, "MCP-Protocol-Version": "2025-03-26"}, json=LIST_TOOLS)
        bad = await http.post(base, headers={**HEADERS, "MCP-Protocol-Version": "2024-01-01"}, json=LIST_TOOLS)
    assert ok.status_code == 200
    assert bad.status_code == 400 and "2025-03-26" in bad.json()["error"]["message"]  # the supported list names it


async def test_the_stateful_mode_needs_a_session_id_so_alexa_plus_must_be_served_statelessly(url):
    """Known limit, kept as a test so that nobody turns the stateful mode on for Alexa+ by accident. Amazon's page
    shows no session id on the follow-up calls; a stateful server (MCP_STATELESS=false) answers them with 400
    "Missing session ID". Stateless is the default in every profile since P3-10 (D-054)."""
    base = await url(False)
    async with httpx.AsyncClient() as http:
        init = await http.post(base, headers=HEADERS, json=ALEXA_INITIALIZE)
        follow_up = await http.post(base, headers=HEADERS, json=LIST_TOOLS)
    assert init.status_code == 200 and init.headers.get("mcp-session-id")
    assert follow_up.status_code == 400 and "session" in follow_up.json()["error"]["message"].lower()


async def test_the_default_settings_serve_statelessly():
    from server.config import Settings

    assert Settings.from_env({}).stateless_http
