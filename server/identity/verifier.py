"""Server-side token verification with ``joserfc`` (same code for the dev issuer and Cognito).

Verified against joserfc 1.7.5 (docs/PLAN.md section 3a): ``jwt.decode(token, key_set,
algorithms=[...])`` picks the key by ``kid`` and refuses algorithms outside the list (HS256 and
``none`` are rejected); ``JWTClaimsRegistry`` checks ``iss`` / ``aud`` / ``exp`` / ``nbf``.

No write tool may run without an ``Identity`` from here. Every failure is ``UNAUTHENTICATED`` with a
server-side ``reason``; the agent never learns which check failed.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from joserfc import jwt
from joserfc.errors import (
    BadSignatureError,
    DecodeError,
    ExpiredTokenError,
    InvalidClaimError,
    InvalidKeyIdError,
    JoseError,
    MissingClaimError,
    UnsupportedAlgorithmError,
)

from server.domain.clock import Clock, epoch_seconds
from server.domain.errors import ErrorCode, FairTableError
from server.domain.models import Identity
from server.identity.jwks import JwksProvider

USER_TOKEN_HEADER = "x-ft-user-token"
MAX_TOKEN_CHARS = 8192


@dataclass(frozen=True)
class VerifierConfig:
    issuer: str
    audience: str
    # Cognito access tokens carry `client_id` instead of `aud`; set "client_id" for those (Phase 2).
    audience_claim: str = "aud"
    algorithms: tuple[str, ...] = ("RS256",)
    leeway_s: int = 30


def _unauthenticated(reason: str) -> FairTableError:
    return FairTableError(
        ErrorCode.UNAUTHENTICATED, "Missing or invalid user token.", reason=reason
    )


def _reason_of(error: JoseError) -> str:
    if isinstance(error, ExpiredTokenError):
        return "expired"
    if isinstance(error, BadSignatureError):
        return "bad_signature"
    if isinstance(error, InvalidKeyIdError):
        return "unknown_kid"
    if isinstance(error, UnsupportedAlgorithmError):
        return "bad_algorithm"
    if isinstance(error, MissingClaimError):
        return f"missing_claim:{error.description}"
    if isinstance(error, InvalidClaimError):
        return f"invalid_claim:{error.description}"
    if isinstance(error, DecodeError):
        return "malformed"
    return f"invalid:{type(error).__name__}"


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _scopes(claim: object) -> frozenset[str]:
    if isinstance(claim, str):
        return frozenset(claim.split())
    if isinstance(claim, list):
        return frozenset(s for s in claim if isinstance(s, str) and s)
    return frozenset()


class TokenVerifier:
    def __init__(self, config: VerifierConfig, jwks: JwksProvider, clock: Clock) -> None:
        self._config = config
        self._jwks = jwks
        self._clock = clock

    def _decode(self, token: str) -> jwt.Token:
        algorithms = list(self._config.algorithms)
        try:
            return jwt.decode(token, self._jwks.key_set(), algorithms=algorithms)
        except InvalidKeyIdError:
            # Possibly a key rotation: refresh once (the provider throttles refreshes).
            return jwt.decode(token, self._jwks.key_set(refresh=True), algorithms=algorithms)

    def verify(self, token: str | None) -> Identity:
        if not isinstance(token, str) or not token.strip():
            raise _unauthenticated("missing")
        token = token.strip()
        if len(token) > MAX_TOKEN_CHARS:
            raise _unauthenticated("too_long")
        cfg = self._config
        try:
            decoded = self._decode(token)
            registry = jwt.JWTClaimsRegistry(
                now=lambda: epoch_seconds(self._clock),
                leeway=cfg.leeway_s,
                iss={"essential": True, "value": cfg.issuer},
                sub={"essential": True},
                exp={"essential": True},
                **{cfg.audience_claim: {"essential": True, "value": cfg.audience}},
            )
            registry.validate(decoded.claims)
        except JoseError as e:
            raise _unauthenticated(_reason_of(e)) from None
        claims = decoded.claims
        sub = _text(claims.get("sub"))
        if sub is None:
            raise _unauthenticated("invalid_claim:sub")
        return Identity(
            sub=sub,
            username=_text(claims.get("username")),
            agent_tier=_text(claims.get("agent_tier")),
            agent_id=_text(claims.get("agent_id")),
            scopes=_scopes(claims.get("scope")),
        )

    def verify_headers(self, headers: Mapping[str, str]) -> Identity:
        """``headers`` must have lower-cased names (as ``get_http_headers()`` returns them)."""
        return self.verify(headers.get(USER_TOKEN_HEADER))
