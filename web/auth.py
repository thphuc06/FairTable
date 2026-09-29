"""Sign-in for the web pages.

Local profile: the dev issuer's password grant (client ``alexa-plus-sim``), then the returned access
token is verified with the same verifier the MCP server uses. The AWS profile would send the user
through Cognito's hosted login instead (scaffold only until "wire AWS", docs/DECISIONS.md D-016);
the pages only depend on this ``Login`` interface.
"""

from typing import Any, Protocol

import httpx

from server.domain.errors import FairTableError
from server.domain.models import Identity
from server.identity import TokenVerifier


class Login(Protocol):
    def login(self, username: str, password: str) -> Identity | None: ...


class DevLogin:
    def __init__(self, http: Any, token_url: str, verifier: TokenVerifier, client_id: str = "alexa-plus-sim"):
        self._http = http  # an httpx.Client (or a Starlette TestClient in tests)
        self._token_url = token_url
        self._verifier = verifier
        self._client_id = client_id

    def login(self, username: str, password: str) -> Identity | None:
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
            identity = self._verifier.verify(response.json()["access_token"])
        except (FairTableError, KeyError, ValueError):
            return None
        return identity if identity.is_user else None
