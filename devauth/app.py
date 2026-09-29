"""Dev JWT issuer (FastAPI). DEVELOPMENT ONLY: stands in for Amazon Cognito in the local profile.

Endpoints: ``GET /.well-known/openid-configuration``, ``GET /.well-known/jwks.json``,
``POST /token`` (grants ``password`` for seeded users and ``client_credentials`` for machine
clients), ``GET /healthz``. Errors follow RFC 6749 (``{"error": "invalid_grant"}``).
"""

import base64
import hmac
import os
from pathlib import Path

from fastapi import FastAPI, Form, Header
from fastapi.responses import JSONResponse
from joserfc.jwk import RSAKey

from devauth.accounts import CLIENTS_BY_ID, USERS_BY_NAME, DevClient
from devauth.issuer import IssuerSettings, TokenIssuer, load_or_create_key
from server.domain.clock import Clock, SystemClock


def _error(status: int, error: str, description: str) -> JSONResponse:
    return JSONResponse(
        {"error": error, "error_description": description},
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


def _same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def _basic_credentials(authorization: str | None) -> tuple[str, str] | None:
    if not authorization or not authorization.lower().startswith("basic "):
        return None
    try:
        raw = base64.b64decode(authorization[6:].strip()).decode()
        client_id, _, secret = raw.partition(":")
        return client_id, secret
    except ValueError:
        return None


def create_app(
    settings: IssuerSettings | None = None,
    clock: Clock | None = None,
    key: RSAKey | None = None,
) -> FastAPI:
    settings = settings or IssuerSettings(
        issuer=os.environ.get("DEVAUTH_ISSUER", "http://localhost:9000"),
        audience=os.environ.get("DEVAUTH_AUDIENCE", "fairtable-mcp"),
    )
    if key is None:
        key_file = os.environ.get("DEVAUTH_KEY_FILE")
        key = load_or_create_key(Path(key_file) if key_file else None)
    issuer = TokenIssuer(settings, key, clock or SystemClock())
    app = FastAPI(title="FairTable dev issuer (development only)")

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/.well-known/openid-configuration")
    def metadata() -> dict:
        base = settings.issuer.rstrip("/")
        return {
            "issuer": settings.issuer,
            "jwks_uri": f"{base}/.well-known/jwks.json",
            "token_endpoint": f"{base}/token",
            "grant_types_supported": ["password", "client_credentials"],
            "token_endpoint_auth_methods_supported": [
                "none",
                "client_secret_post",
                "client_secret_basic",
            ],
            "id_token_signing_alg_values_supported": ["RS256"],
            "scopes_supported": ["fairtable/book"],
        }

    @app.get("/.well-known/jwks.json")
    def jwks() -> dict:
        return issuer.jwks

    def authenticate_client(
        client_id: str | None,
        client_secret: str | None,
        authorization: str | None,
        *,
        secret_required: bool,
    ) -> DevClient | None:
        """A secret is mandatory for client_credentials; for the user (password) flow the client
        is public, but a secret that is sent must still be right."""
        basic = _basic_credentials(authorization)
        if basic:
            client_id, client_secret = basic
        client = CLIENTS_BY_ID.get(client_id or "")
        if client is None:
            return None
        needs_check = client.secret is not None and (secret_required or bool(client_secret))
        if needs_check and not _same(client.secret or "", client_secret or ""):
            return None
        return client

    def granted_scopes(client: DevClient, requested: str | None) -> frozenset[str] | None:
        if not requested:
            return client.scopes
        wanted = frozenset(requested.split())
        return wanted if wanted <= client.scopes else None

    @app.post("/token")
    def token(
        grant_type: str = Form(...),
        client_id: str | None = Form(None),
        client_secret: str | None = Form(None),
        username: str | None = Form(None),
        password: str | None = Form(None),
        scope: str | None = Form(None),
        authorization: str | None = Header(None),
    ) -> JSONResponse:
        if grant_type not in ("password", "client_credentials"):
            return _error(400, "unsupported_grant_type", "Use password or client_credentials.")
        client = authenticate_client(
            client_id, client_secret, authorization, secret_required=grant_type == "client_credentials"
        )
        if client is None:
            return _error(401, "invalid_client", "Unknown client or wrong secret.")
        if grant_type not in client.grants:
            return _error(400, "unauthorized_client", "This client may not use that grant.")
        scopes = granted_scopes(client, scope)
        if scopes is None:
            return _error(400, "invalid_scope", "Scope not allowed for this client.")

        if grant_type == "password":
            user = USERS_BY_NAME.get(username or "")
            if user is None or not _same(user.password, password or ""):
                return _error(400, "invalid_grant", "Wrong username or password.")
            access_token = issuer.issue_user_token(user, client, scopes)
        else:
            access_token = issuer.issue_m2m_token(client, scopes)

        return JSONResponse(
            {
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": settings.ttl_s,
                "scope": " ".join(sorted(scopes)),
            },
            headers={"Cache-Control": "no-store"},
        )

    return app
