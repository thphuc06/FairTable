"""P3-9: the 401 layer in front of the MCP app (Alexa+ functional requirement 6)."""

import json

import pytest

from server.domain.errors import ErrorCode, FairTableError
from server.http_auth import MAX_PEEK_BYTES, RequireToken, calls_a_tool
from server.identity.jwks import JwksUnavailable

CALL = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "restaurant_search", "arguments": {}}}
LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}


@pytest.mark.parametrize("body,expected", [
    (json.dumps(CALL).encode(), True),
    (json.dumps(LIST).encode(), False),
    (json.dumps([LIST, CALL]).encode(), True),  # a batch that contains a tool call
    (b"not json", False),
    (b"", False),
    (b"[1, 2]", False),
])
def test_only_a_tools_call_is_recognised(body, expected):
    assert calls_a_tool(body) is expected


class Verifier:
    def __init__(self, outcome=None):
        self.outcome = outcome
        self.seen = []

    def verify_headers(self, headers):
        self.seen.append(headers.get("x-ft-user-token"))
        if self.outcome is not None:
            raise self.outcome


async def drive(verifier, body: bytes, *, method="POST", chunks=None, headers=None):
    """Run the wrapper over a recording app; returns (status or None, body the app received)."""
    received = []

    async def app(scope, receive, send):
        data = b""
        more = True
        while more:
            m = await receive()
            data += m.get("body", b"")
            more = m.get("more_body", False)
        received.append(data)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    parts = chunks or [body]
    queue = [{"type": "http.request", "body": p, "more_body": i < len(parts) - 1} for i, p in enumerate(parts)]

    async def receive():
        return queue.pop(0)

    sent = []

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": method, "headers": headers or [(b"x-ft-user-token", b"abc")]}
    await RequireToken(app, verifier)(scope, receive, send)
    status = next((m["status"] for m in sent if m["type"] == "http.response.start"), None)
    return status, received, sent


async def test_a_tool_call_with_a_valid_token_reaches_the_app_with_its_body_intact():
    verifier = Verifier()
    status, received, _ = await drive(verifier, b"", chunks=[json.dumps(CALL).encode()[:20], json.dumps(CALL).encode()[20:]])
    assert status == 200 and json.loads(received[0]) == CALL
    assert verifier.seen == ["abc"]


async def test_a_tool_call_without_a_valid_token_gets_401_and_never_reaches_the_app():
    verifier = Verifier(FairTableError(ErrorCode.UNAUTHENTICATED, "Please sign in again.", reason="expired"))
    status, received, sent = await drive(verifier, json.dumps(CALL).encode())
    assert status == 401 and received == []
    assert json.loads(sent[1]["body"]) == {"error": "unauthorized", "message": "Access token required to use this tool."}


async def test_other_requests_need_no_token():
    verifier = Verifier(FairTableError(ErrorCode.UNAUTHENTICATED, "Please sign in again.", reason="missing"))
    for body, method in ((json.dumps(LIST).encode(), "POST"), (b"", "GET"), (b"", "DELETE")):
        status, received, _ = await drive(verifier, body, method=method)
        assert status == 200 and received, (body, method)
    assert verifier.seen == []  # not even asked


async def test_an_unreachable_key_store_is_not_the_callers_fault():
    status, received, _ = await drive(Verifier(JwksUnavailable("down")), json.dumps(CALL).encode())
    assert status == 200 and received  # passed on: the tool refuses it with a masked error


async def test_an_oversized_body_is_passed_on_whole_without_being_judged_here():
    big = json.dumps(CALL).encode() + b" " * (MAX_PEEK_BYTES + 10)
    verifier = Verifier(FairTableError(ErrorCode.UNAUTHENTICATED, "Please sign in again.", reason="missing"))
    status, received, _ = await drive(verifier, b"", chunks=[big[:MAX_PEEK_BYTES + 5], big[MAX_PEEK_BYTES + 5:]])
    assert status == 200 and received[0] == big and verifier.seen == []
