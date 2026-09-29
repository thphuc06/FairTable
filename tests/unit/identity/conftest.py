"""Fixtures for token tests: a signing key, a minting helper and a verifier wired to a fake clock."""

import pytest
from joserfc import jwt
from joserfc.jwk import KeySet, RSAKey
from token_env import AUDIENCE, ISSUER

from server.domain.clock import FakeClock, epoch_seconds
from server.identity import StaticJwks, TokenVerifier, VerifierConfig


@pytest.fixture(scope="session")
def signing_key() -> RSAKey:
    return RSAKey.generate_key(2048, parameters={"kid": "k1", "use": "sig", "alg": "RS256"})


@pytest.fixture(scope="session")
def attacker_key() -> RSAKey:
    return RSAKey.generate_key(2048, parameters={"kid": "k1"})  # same kid, different key


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def jwks(signing_key) -> StaticJwks:
    return StaticJwks(KeySet([signing_key]).as_dict(private=False))


@pytest.fixture
def verifier(jwks, clock) -> TokenVerifier:
    return TokenVerifier(VerifierConfig(issuer=ISSUER, audience=AUDIENCE), jwks, clock)


@pytest.fixture
def mint(signing_key, clock):
    """mint(**overrides) -> JWT string. Pass a claim as None to drop it; ``_key`` / ``_header`` to
    change the signing key or header."""

    def _mint(_key=None, _header=None, **overrides) -> str:
        now = epoch_seconds(clock)
        claims = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "user-1",
            "username": "alice",
            "agent_tier": "verified",
            "agent_id": "alexa-plus-sim",
            "scope": "fairtable/book",
            "iat": now,
            "exp": now + 600,
        }
        claims.update(overrides)
        claims = {k: v for k, v in claims.items() if v is not None}
        header = {"alg": "RS256", "kid": "k1", **(_header or {})}
        return jwt.encode(header, claims, _key or signing_key)

    return _mint
