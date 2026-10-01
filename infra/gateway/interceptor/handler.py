"""AgentCore Gateway REQUEST interceptor (plan task P2-5).

The Gateway has already checked the caller's bearer token (`CUSTOM_JWT`, the Cognito pool). The MCP server
reads the user's identity from the header `x-ft-user-token`, never from `Authorization`: the Gateway signs its
own request to the Runtime with SigV4, and an `Authorization` header returned by an interceptor would be
forwarded to the target and clash with that signature.

So this function:
* copies the bearer token of the incoming request into `x-ft-user-token`;
* returns that header and nothing else, which also replaces anything a client sent under that name (headers
  from an interceptor take precedence over the client's, "Header propagation with Gateway");
* answers 401 itself, and forwards nothing, when there is no usable bearer token: a header the client
  forged must never reach the server just because the real one is missing.

The server verifies the token again with the same keys (defence in depth). The token is never logged.

Sources: docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-interceptors-types.html (event and
output shape), gateway-headers.html (precedence, `Authorization`, allowlist), gateway-interceptors.html
(do not log the headers).
"""

import logging

log = logging.getLogger("fairtable.interceptor")

USER_TOKEN_HEADER = "x-ft-user-token"
MAX_TOKEN_CHARS = 8192  # the server refuses longer tokens too (server/identity/verifier.py)
UNAUTHENTICATED = -32001


def _header(headers: dict, name: str) -> str:
    wanted = name.lower()
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == wanted and isinstance(value, str):
            return value
    return ""


def bearer_token(headers: dict) -> str | None:
    parts = _header(headers, "authorization").split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token if token and len(token) <= MAX_TOKEN_CHARS else None


def _refuse(body: dict) -> dict:
    request_id = body.get("id") if isinstance(body, dict) else None
    return {
        "interceptorOutputVersion": "1.0",
        "mcp": {
            "transformedGatewayResponse": {
                "statusCode": 401,
                "body": {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": UNAUTHENTICATED, "message": "Missing or invalid bearer token."},
                },
            }
        },
    }


def lambda_handler(event, context=None):
    request = event.get("mcp", {}).get("gatewayRequest", {})
    body = request.get("body", {})
    token = bearer_token(request.get("headers") or {})
    method = body.get("method") if isinstance(body, dict) else None
    if token is None:
        log.warning("refused: no usable bearer token (method=%s)", method)
        return _refuse(body)
    log.info("forwarding with the user token header (method=%s)", method)
    return {
        "interceptorOutputVersion": "1.0",
        "mcp": {"transformedGatewayRequest": {"headers": {USER_TOKEN_HEADER: token}, "body": body}},
    }
