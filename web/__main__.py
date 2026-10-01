"""Run the web pages (consent, owner console, chat): ``python -m web`` (settings from the environment, see
server/config.py).

``AUTH_PROVIDER=dev`` (default) signs people in with the dev issuer; ``AUTH_PROVIDER=cognito`` uses Cognito
(``COGNITO_CLIENT_ID``, ``COGNITO_CLIENT_SECRET`` if the app client has one, ``AWS_REGION``). With
``MCP_VIA_GATEWAY=true`` the chat page's assistant talks to an AgentCore Gateway (``MCP_URL``) with a bearer
token instead of reaching the server directly.
"""

import logging
import os
import uuid

import httpx
import uvicorn

from server.config import Settings
from server.domain.clock import SystemClock
from server.identity import HttpJwks, TokenVerifier, VerifierConfig
from server.store import Store, make_client
from simulator.model import build_model
from web.app import WebDeps, create_app
from web.auth import CognitoLogin, DevLogin, cognito_client
from web.chat import ChatService
from web.session import SessionCodec

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    clock = SystemClock()
    verifier = TokenVerifier(
        VerifierConfig(settings.issuer, settings.audience, settings.audience_claim, token_use=settings.token_use),
        HttpJwks(settings.jwks_url, clock), clock,
    )
    if settings.auth_provider == "cognito":
        login = CognitoLogin(
            cognito_client(settings.cognito_region), settings.cognito_client_id, verifier,
            client_secret=os.environ.get("COGNITO_CLIENT_SECRET") or None,
        )
    else:
        login = DevLogin(httpx.Client(timeout=3.0), settings.token_url or settings.issuer.rstrip("/") + "/token", verifier)
    prefix = settings.mcp_tool_prefix
    deps = WebDeps(
        settings=settings,
        store=Store(make_client(settings.store), settings.store.table_name),
        clock=clock,
        login=login,
        sessions=SessionCodec(settings.web_session_secret, clock),
        new_id=lambda: uuid.uuid4().hex,
        chat=ChatService(settings.mcp_url, lambda: build_model(tool_prefix=prefix), clock,
                         via_gateway=settings.mcp_via_gateway, tool_prefix=prefix),
    )
    uvicorn.run(create_app(deps), host=settings.web_host, port=settings.web_port)
