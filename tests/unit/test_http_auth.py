"""P3-9: the 401 layer in front of the MCP app (Alexa+ functional requirement 6)."""

import json

import pytest

from server.domain.errors import ErrorCode, FairTableError
from server.domain.models import Identity
from server.http_auth import (
    MAX_PEEK_BYTES, RequireToken, calls_a_tool, metadata_document, metadata_paths, metadata_url, tool_calls,
)
from server.kernel import TrustKernel
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
    def __init__(self, outcome=None, identity=None):
        self.outcome = outcome
        self.identity = identity
        self.seen = []

    def verify_headers(self, headers):
        self.seen.append(headers.get("x-ft-user-token"))
        if self.outcome is not None:
            raise self.outcome
        return self.identity


async def drive(verifier, body: bytes, *, method="POST", chunks=None, headers=None, path="/mcp", **wrapper):
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

    scope = {"type": "http", "method": method, "path": path, "headers": headers or [(b"x-ft-user-token", b"abc")]}
    await RequireToken(app, verifier, **wrapper)(scope, receive, send)
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


# ---------------------------------------------------------------- D-065: challenge, 403, metadata
RESOURCE = "https://mcp.example.com/mcp"
KERNEL = TrustKernel.load()
DINER = Identity(sub="u1", username="diner-alice", agent_tier="verified", scopes=frozenset({"fairtable/book"}))
SERVICE = Identity(sub="bot", scopes=frozenset({"fairtable/book"}))  # a client_credentials token: no username
WRITE = {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "reservation_hold", "arguments": {}}}


def header(sent, name: bytes):
    return dict(sent[0]["headers"]).get(name)


def test_the_tool_names_of_a_batch_are_listed_and_a_nameless_call_is_none():
    nameless = {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {}}
    assert tool_calls(json.dumps([CALL, LIST, WRITE, nameless]).encode()) == ["restaurant_search", "reservation_hold", None]
    assert tool_calls(b"{}") == [] and tool_calls(b"nope") == []


def test_the_metadata_names_the_resource_the_first_authorization_server_and_the_scope():
    doc = metadata_document(RESOURCE, "https://auth.example.com")
    assert doc == {"resource": RESOURCE, "authorization_servers": ["https://auth.example.com"],
                   "scopes_supported": ["fairtable/book"], "bearer_methods_supported": ["header"]}
    assert metadata_url(RESOURCE) == "https://mcp.example.com/.well-known/oauth-protected-resource/mcp"
    assert metadata_paths(RESOURCE) == {"/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"}


@pytest.mark.parametrize("path", ["/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"])
async def test_the_metadata_document_needs_no_token_and_is_served_on_both_paths(path):
    verifier = Verifier(FairTableError(ErrorCode.UNAUTHENTICATED, "Please sign in again.", reason="missing"))
    status, received, sent = await drive(verifier, b"", method="GET", path=path, headers=[],
                                         resource=RESOURCE, issuer="https://auth.example.com")
    assert status == 200 and received == [] and verifier.seen == []  # answered here, never asked about a token
    assert json.loads(sent[1]["body"])["resource"] == RESOURCE
    status, _, sent = await drive(verifier, b"", method="HEAD", path=path, headers=[], resource=RESOURCE, issuer="x")
    assert status == 200 and sent[1]["body"] == b""


async def test_another_path_or_a_post_to_the_metadata_path_is_not_the_document():
    verifier = Verifier()
    for method, path in (("GET", "/mcp"), ("GET", "/.well-known/other"), ("POST", "/.well-known/oauth-protected-resource")):
        status, received, _ = await drive(verifier, json.dumps(LIST).encode(), method=method, path=path,
                                          resource=RESOURCE, issuer="x")
        assert status == 200 and received, (method, path)  # passed on to the app


async def test_a_401_carries_the_challenge_that_points_to_the_metadata():
    verifier = Verifier(FairTableError(ErrorCode.UNAUTHENTICATED, "Please sign in again.", reason="missing"))
    status, _, sent = await drive(verifier, json.dumps(CALL).encode(), resource=RESOURCE, issuer="x")
    assert status == 401
    assert header(sent, b"www-authenticate") == \
        b'Bearer resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource/mcp"'
    status, _, sent = await drive(verifier, json.dumps(CALL).encode())  # no resource configured: a bare challenge
    assert status == 401 and header(sent, b"www-authenticate") == b"Bearer"


async def test_a_write_tool_called_with_a_service_token_gets_403_and_a_scope_challenge():
    status, received, sent = await drive(Verifier(identity=SERVICE), json.dumps(WRITE).encode(),
                                         kernel=KERNEL, resource=RESOURCE, issuer="x")
    assert status == 403 and received == []
    assert json.loads(sent[1]["body"]) == {"error": "forbidden", "message": "A signed-in diner is required to use this tool."}
    challenge = header(sent, b"www-authenticate").decode()
    assert 'error="insufficient_scope"' in challenge and 'scope="fairtable/book"' in challenge
    assert 'resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource/mcp"' in challenge


async def test_a_service_token_may_still_read_and_a_diner_may_write():
    status, received, _ = await drive(Verifier(identity=SERVICE), json.dumps(CALL).encode(), kernel=KERNEL)
    assert status == 200 and received  # reads are open to any valid token (G1)
    status, received, _ = await drive(Verifier(identity=DINER), json.dumps(WRITE).encode(), kernel=KERNEL)
    assert status == 200 and received


async def test_other_refusals_stay_with_the_tool_not_the_transport():
    """Only a token with no diner behind it becomes a status code; a diner whose agent or scope is refused gets a tool result."""
    unverified = Identity(sub="u2", username="diner-bob", agent_tier="unverified", scopes=frozenset({"fairtable/book"}))
    no_scope = Identity(sub="u3", username="diner-carol", agent_tier="verified")
    for who in (unverified, no_scope):
        status, received, _ = await drive(Verifier(identity=who), json.dumps(WRITE).encode(), kernel=KERNEL)
        assert status == 200 and received, who
    unknown = {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "no_such_tool", "arguments": {}}}
    status, received, _ = await drive(Verifier(identity=SERVICE), json.dumps(unknown).encode(), kernel=KERNEL)
    assert status == 200 and received  # an unknown tool is answered by the server


async def test_without_a_kernel_there_is_no_403():
    status, received, _ = await drive(Verifier(identity=SERVICE), json.dumps(WRITE).encode())
    assert status == 200 and received


async def test_a_batch_with_one_write_by_a_service_token_is_refused_whole():
    status, received, _ = await drive(Verifier(identity=SERVICE), json.dumps([CALL, WRITE]).encode(), kernel=KERNEL)
    assert status == 403 and received == []
