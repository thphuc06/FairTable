"""P0-3: FastMCP 3.4.7 / mcp 1.30.0 spike.

Verified against the installed source and by running it:

(a) isError + structured content     -> ``fastmcp.tools.ToolResult(..., is_error=True)``.
(b) JSON-RPC -32042                  -> ``mcp.shared.exceptions.UrlElicitationRequiredError``.
    FastMCP's ``call_tool`` wraps every non-FastMCPError exception in ``ToolError`` (server.py,
    ``except Exception``), which turns it into ``isError=True`` text. A one-method middleware
    (``on_call_tool``) re-raises the original ``__cause__``; the mcp low-level handler then sends a
    real JSON-RPC error with code -32042 and the elicitation payload in ``error.data``.
(c) header inside a tool             -> ``fastmcp.server.dependencies.get_http_headers()``
    (lower-cased names; ``authorization`` is stripped by default, ``x-ft-user-token`` is kept).
(d) ``task=True`` + pydocket ``memory://`` -> needs the optional ``pydocket`` package.
(e) sessions                         -> ``Context.session_id`` (one per client session over HTTP).

The middleware below is spike code; the production copy is built in plan task P1-10.
"""

import asyncio
import socket

import httpx
import pytest
import uvicorn
from fastmcp import Client, Context, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware
from fastmcp.tools import ToolResult
from mcp import McpError
from mcp.shared.exceptions import UrlElicitationRequiredError
from mcp.types import URL_ELICITATION_REQUIRED, ElicitRequestURLParams

CONSENT_URL = "http://localhost:8080/consent/hold-1"


class UnwrapStepUp(Middleware):
    """Re-raise UrlElicitationRequiredError that FastMCP wrapped into ToolError."""

    async def on_call_tool(self, context, call_next):
        try:
            return await call_next(context)
        except ToolError as e:
            if isinstance(e.__cause__, UrlElicitationRequiredError):
                raise e.__cause__ from None
            raise


def build_server(**kwargs) -> FastMCP:
    mcp = FastMCP("fairtable-spike", middleware=[UnwrapStepUp()], **kwargs)

    @mcp.tool
    def ok(x: int) -> dict:
        return {"x": x, "spoken_summary": "Done."}

    @mcp.tool
    def slot_taken() -> ToolResult:
        return ToolResult(
            content="That slot was just taken.",
            structured_content={"code": "SLOT_TAKEN", "next_step": "availability_check"},
            is_error=True,
        )

    @mcp.tool
    def needs_consent() -> dict:
        raise UrlElicitationRequiredError(
            [
                ElicitRequestURLParams(
                    mode="url",
                    message="Approve this booking",
                    url=CONSENT_URL,
                    elicitationId="hold-1",
                )
            ]
        )

    @mcp.tool
    def crash() -> dict:
        raise RuntimeError("internal detail")

    @mcp.tool
    def read_token() -> dict:
        h = get_http_headers()
        return {"token": h.get("x-ft-user-token"), "has_authorization": "authorization" in h}

    @mcp.tool
    async def whoami(ctx: Context) -> dict:
        return {"session_id": ctx.session_id}

    @mcp.tool(task=True)
    async def slow_job(n: int) -> dict:
        await asyncio.sleep(0.2)
        return {"n": n, "spoken_summary": "Finished."}

    return mcp


# ------------------------------------------------------------------ in-process client
async def test_a_is_error_with_structured_content():
    async with Client(build_server()) as c:
        r = await c.call_tool_mcp("slot_taken", {})
    assert r.isError is True
    assert r.structuredContent == {"code": "SLOT_TAKEN", "next_step": "availability_check"}
    assert r.content[0].text == "That slot was just taken."


async def test_a_success_returns_structured_content():
    async with Client(build_server()) as c:
        r = await c.call_tool_mcp("ok", {"x": 3})
    assert r.isError is False
    assert r.structuredContent == {"x": 3, "spoken_summary": "Done."}


async def test_b_without_middleware_32042_is_swallowed_into_is_error():
    """Documents WHY the middleware is needed (FastMCP 3.4.7 behaviour)."""
    mcp = FastMCP("no-middleware")

    @mcp.tool
    def needs_consent() -> dict:
        raise UrlElicitationRequiredError(
            [ElicitRequestURLParams(mode="url", message="m", url=CONSENT_URL, elicitationId="e")]
        )

    async with Client(mcp) as c:
        r = await c.call_tool_mcp("needs_consent", {})
    assert r.isError is True
    assert "URL elicitation required" in r.content[0].text


async def test_b_with_middleware_client_gets_json_rpc_32042_with_url():
    async with Client(build_server()) as c:
        with pytest.raises(McpError) as exc:
            await c.call_tool_mcp("needs_consent", {})
    err = exc.value.error
    assert err.code == URL_ELICITATION_REQUIRED == -32042
    [elicit] = err.data["elicitations"]
    assert elicit["mode"] == "url"
    assert elicit["url"] == CONSENT_URL
    assert elicit["elicitationId"] == "hold-1"
    # The client SDK can rebuild the typed error from the wire error.
    typed = UrlElicitationRequiredError.from_error(err)
    assert typed.elicitations[0].url == CONSENT_URL


async def test_b_other_exceptions_still_become_is_error():
    async with Client(build_server()) as c:
        r = await c.call_tool_mcp("crash", {})
    assert r.isError is True


async def test_b_mask_error_details_hides_internal_messages():
    async with Client(build_server(mask_error_details=True)) as c:
        r = await c.call_tool_mcp("crash", {})
        soft = await c.call_tool_mcp("slot_taken", {})
        with pytest.raises(McpError):  # -32042 is not masked
            await c.call_tool_mcp("needs_consent", {})
    assert "internal detail" not in r.content[0].text
    assert soft.structuredContent["code"] == "SLOT_TAKEN"  # our structured errors are untouched


async def test_c_in_process_transport_has_no_http_headers():
    async with Client(build_server()) as c:
        r = await c.call_tool_mcp("read_token", {})
    assert r.structuredContent["token"] is None


async def test_d_tasks_with_pydocket_memory_backend():
    pytest.importorskip("docket")
    async with Client(build_server()) as c:
        task = await c.call_tool("slow_job", {"n": 7}, task=True)
        assert task.returned_immediately is False
        result = await task.result()
    assert result.structured_content == {"n": 7, "spoken_summary": "Finished."}


async def test_d_tool_without_task_flag_is_unaffected():
    async with Client(build_server()) as c:
        r = await c.call_tool("ok", {"x": 1})
    assert r.structured_content["x"] == 1


# ------------------------------------------------------------------ real Streamable HTTP
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def http_url():
    port = _free_port()
    app = build_server().http_app()  # default path: /mcp (settings.streamable_http_path)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.05)
    assert server.started, "uvicorn did not start"
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    await task


def _client(url, **headers):
    return Client(StreamableHttpTransport(url, headers=headers or None))


async def test_c_tool_reads_x_ft_user_token_header_over_http(http_url):
    async with _client(http_url, **{"x-ft-user-token": "jwt-abc"}) as c:
        r = await c.call_tool_mcp("read_token", {})
    assert r.structuredContent == {"token": "jwt-abc", "has_authorization": False}


async def test_c_authorization_header_is_stripped_by_default(http_url):
    """get_http_headers() hides Authorization; identity must come from x-ft-user-token."""
    async with _client(http_url, **{"Authorization": "Bearer gw", "x-ft-user-token": "u"}) as c:
        r = await c.call_tool_mcp("read_token", {})
    assert r.structuredContent == {"token": "u", "has_authorization": False}


async def test_c_missing_header_is_none_not_an_error(http_url):
    async with _client(http_url) as c:
        r = await c.call_tool_mcp("read_token", {})
    assert r.structuredContent["token"] is None


async def test_b_32042_over_streamable_http(http_url):
    async with _client(http_url) as c:
        with pytest.raises(McpError) as exc:
            await c.call_tool_mcp("needs_consent", {})
    assert exc.value.error.code == -32042
    assert exc.value.error.data["elicitations"][0]["url"] == CONSENT_URL


async def test_a_is_error_over_streamable_http(http_url):
    async with _client(http_url) as c:
        r = await c.call_tool_mcp("slot_taken", {})
    assert r.isError and r.structuredContent["code"] == "SLOT_TAKEN"


async def test_e_session_id_is_stable_within_a_client_and_differs_across_clients(http_url):
    async with _client(http_url) as c1:
        a = (await c1.call_tool_mcp("whoami", {})).structuredContent["session_id"]
        b = (await c1.call_tool_mcp("whoami", {})).structuredContent["session_id"]
    async with _client(http_url) as c2:
        other = (await c2.call_tool_mcp("whoami", {})).structuredContent["session_id"]
    assert a == b
    assert a != other


async def test_e_the_token_header_is_per_request_not_per_session(http_url):
    """Identity must be re-read from every request, never cached on the session."""
    async with _client(http_url, **{"x-ft-user-token": "one"}) as c:
        r1 = await c.call_tool_mcp("read_token", {})
    async with _client(http_url, **{"x-ft-user-token": "two"}) as c:
        r2 = await c.call_tool_mcp("read_token", {})
    assert (r1.structuredContent["token"], r2.structuredContent["token"]) == ("one", "two")


async def test_d_tasks_over_streamable_http(http_url):
    pytest.importorskip("docket")
    async with _client(http_url) as c:
        task = await c.call_tool("slow_job", {"n": 2}, task=True)
        assert task.returned_immediately is False  # really backgrounded, not run synchronously
        status = await task.status()
        assert status.taskId == task.task_id
        result = await task.result()
    assert result.structured_content["n"] == 2


# ------------------------------------------------------------------ spec 2025-11-25 transport security
# Streamable HTTP spec: servers MUST validate the Origin header (403 if present and invalid) and
# SHOULD bind to localhost when running locally; an invalid MCP-Protocol-Version MUST give 400.
# FastMCP 3.4.7 ships with host_origin_protection=False, so the server must switch it on itself.
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "t", "version": "0"},
    },
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


async def _serve(app):
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.05)
    assert server.started
    return server, task, f"http://127.0.0.1:{port}/mcp"


async def test_transport_default_fastmcp_does_not_check_origin():
    """Documents the default: a hostile Origin is NOT rejected unless protection is enabled."""
    server, task, url = await _serve(build_server().http_app())
    try:
        async with httpx.AsyncClient() as c:
            r = await c.post(url, json=INIT, headers={**MCP_HEADERS, "Origin": "http://evil.example"})
        assert r.status_code == 200
    finally:
        server.should_exit = True
        await task


async def test_transport_origin_protection_rejects_hostile_origin_with_403():
    server, task, url = await _serve(build_server().http_app(host_origin_protection=True))
    try:
        async with httpx.AsyncClient() as c:
            bad = await c.post(url, json=INIT, headers={**MCP_HEADERS, "Origin": "http://evil.example"})
            no_origin = await c.post(url, json=INIT, headers=MCP_HEADERS)  # server-to-server clients
            bad_host = await c.post(url, json=INIT, headers={**MCP_HEADERS, "Host": "evil.example"})
        assert bad.status_code == 403
        assert no_origin.status_code == 200  # no Origin header = not a browser, must still work
        assert bad_host.status_code in (403, 421)  # DNS-rebinding guard on Host
    finally:
        server.should_exit = True
        await task


async def test_transport_unsupported_protocol_version_header_gets_400():
    server, task, url = await _serve(build_server().http_app(host_origin_protection=True))
    try:
        async with httpx.AsyncClient() as c:
            init = await c.post(url, json=INIT, headers=MCP_HEADERS)
            sid = init.headers.get("mcp-session-id")
            hdrs = {**MCP_HEADERS, "MCP-Protocol-Version": "1999-01-01"}
            if sid:
                hdrs["mcp-session-id"] = sid
            r = await c.post(url, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=hdrs)
        assert r.status_code == 400
    finally:
        server.should_exit = True
        await task
