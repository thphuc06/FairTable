"""Run the consent page: ``python -m web`` (settings from the environment, see server/config.py)."""

import logging
import uuid

import httpx
import uvicorn

from server.config import Settings
from server.domain.clock import SystemClock
from server.identity import HttpJwks, TokenVerifier, VerifierConfig
from server.store import Store, make_client
from simulator.model import build_model
from web.app import WebDeps, create_app
from web.auth import DevLogin
from web.chat import ChatService
from web.session import SessionCodec

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    clock = SystemClock()
    verifier = TokenVerifier(
        VerifierConfig(settings.issuer, settings.audience, settings.audience_claim),
        HttpJwks(settings.jwks_url, clock), clock,
    )
    deps = WebDeps(
        settings=settings,
        store=Store(make_client(settings.store), settings.store.table_name),
        clock=clock,
        login=DevLogin(httpx.Client(timeout=3.0), settings.token_url or settings.issuer.rstrip("/") + "/token", verifier),
        sessions=SessionCodec(settings.web_session_secret, clock),
        new_id=lambda: uuid.uuid4().hex,
        chat=ChatService(settings.mcp_url, build_model, clock),
    )
    uvicorn.run(create_app(deps), host=settings.web_host, port=settings.web_port)
