"""HTTP 401 for a tool call without a valid token (Alexa+ functional requirement 6, docs/alexa-plus-addon-notes.md).

Alexa+ starts account linking when a tool call is answered with HTTP 401 or 403; a tool-level error with status
200 looks like an ordinary failure to it. So the transport answers ``401`` before any tool runs when ``tools/call``
arrives with no token, an expired one or an invalid one. ``initialize``, ``tools/list`` and the rest are left alone
(Alexa+ discovers the tools with its service-level token). The tools still verify the token themselves: this
layer is only the answer Alexa+ understands, not a second place where identity is decided.

D-065 adds three things for a server that is reached directly (on AWS the AgentCore Gateway does the same for its own
endpoint): the OAuth Protected Resource Metadata document (RFC 9728) at ``/.well-known/oauth-protected-resource``, a
``WWW-Authenticate`` header on every 401 and 403, and HTTP 403 when a valid token has no signed-in diner behind it
(Alexa+'s service-level token) and the tool writes. PEP-1 decides that last point (G4 and G2 refuse such a token); this layer only gives it the
status code that makes a client start account linking.
"""

import json
import logging
from collections.abc import Mapping
from urllib.parse import urlsplit

from server.domain.errors import FairTableError
from server.domain.tool_names import WRITE_TOOLS, ToolName
from server.identity.jwks import JwksUnavailable
from server.identity.verifier import TokenVerifier

log = logging.getLogger("fairtable.http")

MAX_PEEK_BYTES = 1_048_576  # larger bodies are passed on untouched (the tools verify the token anyway)
UNAUTHORIZED_BODY = json.dumps(
    {"error": "unauthorized", "message": "Access token required to use this tool."}
).encode()
FORBIDDEN_BODY = json.dumps(
    {"error": "forbidden", "message": "A signed-in diner is required to use this tool."}
).encode()
WELL_KNOWN = "/.well-known/oauth-protected-resource"
SCOPES = ("fairtable/book",)


def metadata_document(resource: str, issuer: str) -> dict:
    """RFC 9728 Protected Resource Metadata. Alexa+ needs ``resource``, ``authorization_servers`` (it reads only the
    first) and ``scopes_supported``; MCP 2025-11-25 requires at least one authorization server."""
    return {"resource": resource, "authorization_servers": [issuer], "scopes_supported": list(SCOPES),
            "bearer_methods_supported": ["header"]}


def metadata_url(resource: str) -> str:
    """Where the document of ``resource`` lives (RFC 9728 section 3.1: the well-known path goes between host and path)."""
    parts = urlsplit(resource)
    return f"{parts.scheme}://{parts.netloc}{WELL_KNOWN}{parts.path.rstrip('/')}"


def metadata_paths(resource: str) -> frozenset[str]:
    """The root document (Alexa+ asks for it) and the one with the path of the MCP endpoint."""
    return frozenset({WELL_KNOWN, urlsplit(metadata_url(resource)).path})


def tool_calls(body: bytes) -> list[str | None]:
    """The tool name of every ``tools/call`` in the JSON-RPC body (a batch may hold several); None when it has no name."""
    try:
        data = json.loads(body)
    except ValueError:
        return []
    out: list[str | None] = []
    for m in data if isinstance(data, list) else [data]:
        if isinstance(m, dict) and m.get("method") == "tools/call":
            params = m.get("params")
            name = params.get("name") if isinstance(params, dict) else None
            out.append(name if isinstance(name, str) else None)
    return out


def calls_a_tool(body: bytes) -> bool:
    """True when the JSON-RPC body is (or, in a batch, contains) a ``tools/call``."""
    return bool(tool_calls(body))


def lower_headers(scope: Mapping) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}


class RequireToken:
    """ASGI wrapper: ``tools/call`` without a valid token gets HTTP 401, a write tool called without a signed-in diner
    gets HTTP 403, and neither reaches the tool. It also serves the OAuth metadata document (D-065).

    ``kernel`` (the PEP-1 engine) and ``resource`` (the public URL of the MCP endpoint) are optional: without them the
    403 and the metadata are off, which is how the unit tests drive the 401 alone.
    """

    def __init__(self, app, verifier: TokenVerifier, *, kernel=None, resource: str | None = None,
                 issuer: str = "") -> None:
        self.app = app
        self.verifier = verifier
        self.kernel = kernel
        self.resource = resource
        self.issuer = issuer
        self.paths = metadata_paths(resource) if resource else frozenset()
        self.challenge = f'Bearer resource_metadata="{metadata_url(resource)}"' if resource else "Bearer"

    def __getattr__(self, name):  # the wrapped app's attributes (state, router, ...) stay reachable
        return getattr(self.app, name)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and scope["method"] in ("GET", "HEAD") and scope["path"] in self.paths:
            await self._metadata(scope, send)
            return
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        chunks: list[dict] = []
        body = b""
        more = True
        while more:
            message = await receive()
            chunks.append(message)
            if message["type"] != "http.request":  # the client went away
                break
            body += message.get("body", b"")
            more = message.get("more_body", False)
            if len(body) > MAX_PEEK_BYTES:
                break

        async def replay():
            return chunks.pop(0) if chunks else await receive()

        names = tool_calls(body) if len(body) <= MAX_PEEK_BYTES else []
        if names:
            try:
                identity = self.verifier.verify_headers(lower_headers(scope))
            except FairTableError as e:
                log.info("401: tools/call refused before the tool (%s)", e.reason)
                await self._refuse(send, 401, UNAUTHORIZED_BODY, self.challenge)
                return
            except JwksUnavailable:
                identity = None  # not the caller's fault: the tool refuses it with a masked error, as before
            if identity is not None and self._needs_a_diner(identity, names):
                log.info("403: a write tool was called by a token with no signed-in diner")
                await self._refuse(send, 403, FORBIDDEN_BODY, self._insufficient_scope())
                return
        await self.app(scope, replay, send)

    def _needs_a_diner(self, identity, names: list[str | None]) -> bool:
        """True when a called write tool is refused by PEP-1 and the token has no signed-in diner behind it (it is a
        client_credentials token, like Alexa+'s service-level one). Any other refusal stays a tool result."""
        if self.kernel is None or identity.is_user:
            return False
        for name in names:
            try:
                action = ToolName(name)
            except ValueError:
                continue  # an unknown tool: the server answers that itself
            if action in WRITE_TOOLS and not self.kernel.pep1.decide(identity=identity, action=action).allowed:
                return True
        return False

    def _insufficient_scope(self) -> str:
        return f'{self.challenge}, error="insufficient_scope", scope="{" ".join(SCOPES)}"'

    @staticmethod
    async def _refuse(send, status: int, body: bytes, challenge: str) -> None:
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                                (b"www-authenticate", challenge.encode("latin-1"))]})
        await send({"type": "http.response.body", "body": body})

    async def _metadata(self, scope, send) -> None:
        body = json.dumps(metadata_document(self.resource, self.issuer)).encode()
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                                (b"cache-control", b"public, max-age=300")]})
        await send({"type": "http.response.body", "body": b"" if scope["method"] == "HEAD" else body})
