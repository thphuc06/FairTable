"""Sign-in for the web pages.

Local profile: the dev issuer's password grant (client ``alexa-plus-sim``), then the returned access
token is verified with the same verifier the MCP server uses. AWS profile: ``CognitoLogin``, Cognito's
``InitiateAuth`` with ``USER_PASSWORD_AUTH`` (docs/DECISIONS.md D-035: demo only), the same verification.
The pages only depend on this ``Login`` interface.
"""

import base64
import hashlib
import hmac

from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from botocore.exceptions import BotoCoreError, ClientError

from server.domain.errors import FairTableError
from server.domain.models import Identity
from server.identity import TokenVerifier


@dataclass(frozen=True)
class SignedIn:
    identity: Identity
    access_token: str  # kept in the web process only (the chat page acts for the user); never sent to the browser
    expires_in_s: int


class Login(Protocol):
    def sign_in(self, username: str, password: str) -> SignedIn | None: ...


class DevLogin:
    def __init__(self, http: Any, token_url: str, verifier: TokenVerifier, client_id: str = "alexa-plus-sim"):
        self._http = http  # an httpx.Client (or a Starlette TestClient in tests)
        self._token_url = token_url
        self._verifier = verifier
        self._client_id = client_id

    def sign_in(self, username: str, password: str) -> SignedIn | None:
        try:
            response = self._http.post(
                self._token_url,
                data={"grant_type": "password", "client_id": self._client_id,
                      "username": username, "password": password},
            )
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        try:
            body = response.json()
            token = body["access_token"]
            identity = self._verifier.verify(token)
            expires_in = int(body.get("expires_in", 3600))
        except (FairTableError, KeyError, ValueError, TypeError):
            return None
        return SignedIn(identity, token, expires_in) if identity.is_user else None


def secret_hash(username: str, client_id: str, client_secret: str) -> str:
    """Cognito's SECRET_HASH: base64(HMAC-SHA256(key = client secret, message = username + client id))."""
    digest = hmac.new(client_secret.encode(), (username + client_id).encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def cognito_client(region: str):
    """A Cognito client that signs nothing: ``InitiateAuth`` is an unauthenticated operation (the person's
    password is the credential), so the web pages need no AWS credentials to sign people in."""
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config

    return boto3.client(
        "cognito-idp", region_name=region,
        config=Config(signature_version=UNSIGNED, connect_timeout=5, read_timeout=15,
                      retries={"max_attempts": 2, "mode": "standard"}),
    )


class CognitoLogin:
    """Sign people in through a Cognito app client (``alexa-plus-sim``: its tokens carry the agent claims the
    chat page needs). Any refusal, challenge or oddity is just "not signed in"; why stays out of the answer and
    the logs, and neither the password nor the client secret is ever logged."""

    def __init__(self, client: Any, client_id: str, verifier: TokenVerifier, client_secret: str | None = None):
        self._client = client  # a boto3 "cognito-idp" client (or a fake in tests)
        self._client_id = client_id
        self._verifier = verifier
        self._client_secret = client_secret

    def sign_in(self, username: str, password: str) -> SignedIn | None:
        params = {"USERNAME": username, "PASSWORD": password}
        if self._client_secret:
            params["SECRET_HASH"] = secret_hash(username, self._client_id, self._client_secret)
        try:
            response = self._client.initiate_auth(
                AuthFlow="USER_PASSWORD_AUTH", ClientId=self._client_id, AuthParameters=params
            )
        except (ClientError, BotoCoreError, OSError):
            return None
        try:
            result = response["AuthenticationResult"]  # absent when Cognito answers with a challenge
            token = result["AccessToken"]
            expires_in = int(result.get("ExpiresIn", 3600))
            identity = self._verifier.verify(token)
        except (FairTableError, KeyError, ValueError, TypeError):
            return None
        return SignedIn(identity, token, expires_in) if identity.is_user else None
