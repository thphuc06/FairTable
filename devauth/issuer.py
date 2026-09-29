"""Token minting: the plain-Python counterpart of Cognito plus its pre-token trigger."""

import json
import secrets
from dataclasses import dataclass
from pathlib import Path

from joserfc import jwt
from joserfc.jwk import KeySet, RSAKey

from devauth.accounts import DevClient, DevUser
from server.domain.clock import Clock, epoch_seconds


@dataclass(frozen=True)
class IssuerSettings:
    issuer: str = "http://localhost:9000"
    audience: str = "fairtable-mcp"
    ttl_s: int = 3600


def load_or_create_key(path: Path | None) -> RSAKey:
    """Persist the signing key when a path is given (so tokens survive a restart); else ephemeral."""
    if path is not None and path.exists():
        return RSAKey.import_key(json.loads(path.read_text(encoding="utf-8")))
    key = RSAKey.generate_key(2048, parameters={"use": "sig", "alg": "RS256"}, auto_kid=True)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(key.as_dict(private=True)), encoding="utf-8")
    return key


class TokenIssuer:
    def __init__(self, settings: IssuerSettings, key: RSAKey, clock: Clock) -> None:
        self.settings = settings
        self._key = key
        self._clock = clock

    @property
    def jwks(self) -> dict:
        return KeySet([self._key]).as_dict(private=False)

    def _base_claims(self, client: DevClient, sub: str, scopes: frozenset[str]) -> dict:
        now = epoch_seconds(self._clock)
        return {
            "iss": self.settings.issuer,
            "sub": sub,
            "aud": self.settings.audience,
            "client_id": client.client_id,
            "token_use": "access",
            "scope": " ".join(sorted(scopes)),
            "iat": now,
            "exp": now + self.settings.ttl_s,
            "jti": secrets.token_hex(8),
        }

    def _sign(self, claims: dict) -> str:
        return jwt.encode({"alg": "RS256", "kid": self._key.kid, "typ": "JWT"}, claims, self._key)

    def issue_user_token(self, user: DevUser, client: DevClient, scopes: frozenset[str]) -> str:
        """Pre-token V2: a signed-in user's token gets the agent claims of the client used."""
        claims = self._base_claims(client, user.sub, scopes)
        claims["username"] = user.username
        if user.groups:
            claims["cognito:groups"] = list(user.groups)
        if client.agent_tier:
            claims["agent_tier"] = client.agent_tier
        if client.agent_id:
            claims["agent_id"] = client.agent_id
        return self._sign(claims)

    def issue_m2m_token(self, client: DevClient, scopes: frozenset[str]) -> str:
        """No `username`. The agent claims are added only for V3-style clients."""
        claims = self._base_claims(client, client.client_id, scopes)
        if client.add_claims_to_m2m:
            if client.agent_tier:
                claims["agent_tier"] = client.agent_tier
            if client.agent_id:
                claims["agent_id"] = client.agent_id
        return self._sign(claims)
