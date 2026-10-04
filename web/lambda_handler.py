"""AWS Lambda entry point of the owner console (D-068): API Gateway HTTP API (payload 2.0) to Mangum to the same FastAPI app.

Only the sign-in and the owner console are served here. The chat page and the voice page need the simulator (Strands),
which is not in the package, so ``chat`` and ``voice`` stay off and ``/chat`` answers that no assistant is set up.
Settings come from the environment like everywhere else (``Settings.from_env``); nothing account-specific is read
from code. The dependencies are built once per container, at the first request.
"""

import logging
import os
import uuid

from server.config import Settings
from server.domain.clock import SystemClock
from server.identity import HttpJwks, TokenVerifier, VerifierConfig
from server.store import Store, make_client
from server.store.seeding import seed_provider_from_env
from web.app import WebDeps, create_app
from web.auth import CognitoLogin, cognito_client
from web.session import SessionCodec

log = logging.getLogger("fairtable.web")
log.setLevel(logging.INFO)  # this logger only: a module that changes the root level would change it for every test that imports it
_handler = None


def build_deps(env: dict[str, str] | None = None) -> WebDeps:
    env = dict(os.environ) if env is None else env
    settings = Settings.from_env(env)
    if settings.auth_provider != "cognito":
        raise RuntimeError("the hosted owner console signs people in through Cognito (AUTH_PROVIDER=cognito)")
    clock = SystemClock()
    verifier = TokenVerifier(
        VerifierConfig(settings.issuer, settings.audience, settings.audience_claim, token_use=settings.token_use),
        HttpJwks(settings.jwks_url, clock), clock,
    )
    login = CognitoLogin(
        cognito_client(settings.cognito_region), settings.cognito_client_id, verifier,
        client_secret=env.get("COGNITO_CLIENT_SECRET") or None,
    )
    return WebDeps(
        settings=settings,
        store=Store(make_client(settings.store), settings.store.table_name),
        clock=clock,
        login=login,
        sessions=SessionCodec(settings.web_session_secret, clock),
        new_id=lambda: uuid.uuid4().hex,
        seeds=seed_provider_from_env(env),
    )


def handler(event, context):
    global _handler
    if _handler is None:
        from mangum import Mangum

        _handler = Mangum(create_app(build_deps()), lifespan="off")
    return _handler(event, context)
