"""HTTP 401 for a tool call without a valid token (Alexa+ functional requirement 6, docs/alexa-plus-addon-notes.md).

Alexa+ starts account linking when a tool call is answered with HTTP 401 or 403; a tool-level error with status
200 looks like an ordinary failure to it. So the transport answers ``401`` before any tool runs when ``tools/call``
arrives with no token, an expired one or an invalid one. ``initialize``, ``tools/list`` and the rest are left alone
(Alexa+ discovers the tools with its service-level token). The tools still verify the token themselves: this
layer is only the answer Alexa+ understands, not a second place where identity is decided.
"""

import json
import logging
from collections.abc import Mapping

from server.domain.errors import FairTableError
from server.identity.jwks import JwksUnavailable
from server.identity.verifier import TokenVerifier

log = logging.getLogger("fairtable.http")

MAX_PEEK_BYTES = 1_048_576  # larger bodies are passed on untouched (the tools verify the token anyway)
UNAUTHORIZED_BODY = json.dumps(
    {"error": "unauthorized", "message": "Access token required to use this tool."}
).encode()


def calls_a_tool(body: bytes) -> bool:
    """True when the JSON-RPC body is (or, in a batch, contains) a ``tools/call``."""
    try:
        data = json.loads(body)
    except ValueError:
        return False
    messages = data if isinstance(data, list) else [data]
    return any(isinstance(m, dict) and m.get("method") == "tools/call" for m in messages)


def lower_headers(scope: Mapping) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}


class RequireToken:
    """ASGI wrapper: ``tools/call`` without a valid user token gets HTTP 401 and never reaches the tool."""

    def __init__(self, app, verifier: TokenVerifier) -> None:
        self.app = app
        self.verifier = verifier

    def __getattr__(self, name):  # the wrapped app's attributes (state, router, ...) stay reachable
        return getattr(self.app, name)

    async def __call__(self, scope, receive, send) -> None:
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

        if len(body) <= MAX_PEEK_BYTES and calls_a_tool(body):
            try:
                self.verifier.verify_headers(lower_headers(scope))
            except FairTableError as e:
                log.info("401: tools/call refused before the tool (%s)", e.reason)
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json"),
                                        (b"content-length", str(len(UNAUTHORIZED_BODY)).encode())]})
                await send({"type": "http.response.body", "body": UNAUTHORIZED_BODY})
                return
            except JwksUnavailable:
                pass  # not the caller's fault: the tool refuses it with a masked error, as before
        await self.app(scope, replay, send)
