"""P1-4: JWKS caching, rotation and outage behaviour (no network: httpx MockTransport)."""

import httpx
import pytest
from joserfc.jwk import KeySet, RSAKey
from token_env import AUDIENCE, ISSUER

from server.domain.errors import FairTableError
from server.identity import HttpJwks, JwksUnavailable, TokenVerifier, VerifierConfig

URL = "http://issuer.test/jwks.json"


class Issuer:
    """A fake JWKS endpoint whose key set and health can change between requests."""

    def __init__(self, *keys: RSAKey) -> None:
        self.keys = list(keys)
        self.hits = 0
        self.fail = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.hits += 1
        if self.fail:
            return httpx.Response(503)
        return httpx.Response(200, json=KeySet(self.keys).as_dict(private=False))

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def issuer(signing_key):
    return Issuer(signing_key)


@pytest.fixture
def provider(issuer, clock):
    return HttpJwks(URL, clock, ttl_s=600, min_refresh_s=30, client=issuer.client())


def test_keys_are_cached_until_the_ttl(provider, issuer, clock):
    provider.key_set()
    provider.key_set()
    assert issuer.hits == 1
    clock.advance(seconds=601)
    provider.key_set()
    assert issuer.hits == 2


def test_forced_refresh_is_throttled(provider, issuer, clock):
    provider.key_set()
    provider.key_set(refresh=True)  # too soon after the first fetch
    assert issuer.hits == 1
    clock.advance(seconds=31)
    provider.key_set(refresh=True)
    assert issuer.hits == 2


def test_stale_keys_are_served_during_an_outage(provider, issuer, clock):
    first = provider.key_set()
    clock.advance(seconds=601)
    issuer.fail = True
    assert provider.key_set() is first


def test_no_keys_and_no_cache_raises(issuer, clock):
    issuer.fail = True
    p = HttpJwks(URL, clock, client=issuer.client())
    with pytest.raises(JwksUnavailable):
        p.key_set()


def test_garbage_response_is_treated_as_unavailable(clock):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>")))
    with pytest.raises(JwksUnavailable):
        HttpJwks(URL, clock, client=client).key_set()


def test_key_rotation_is_picked_up_on_an_unknown_kid(provider, issuer, clock, signing_key, mint):
    verifier = TokenVerifier(VerifierConfig(issuer=ISSUER, audience=AUDIENCE), provider, clock)
    assert verifier.verify(mint()).sub == "user-1"  # primes the cache with key k1

    new_key = RSAKey.generate_key(2048, parameters={"kid": "k2", "use": "sig", "alg": "RS256"})
    issuer.keys = [signing_key, new_key]
    clock.advance(seconds=31)  # past the refresh throttle
    assert verifier.verify(mint(_key=new_key, _header={"kid": "k2"})).sub == "user-1"


def test_rotation_refresh_cannot_be_used_to_hammer_the_issuer(provider, issuer, clock, mint, attacker_key):
    verifier = TokenVerifier(VerifierConfig(issuer=ISSUER, audience=AUDIENCE), provider, clock)
    verifier.verify(mint())
    hits = issuer.hits
    for _ in range(20):  # a flood of tokens with random kids
        with pytest.raises(FairTableError):
            verifier.verify(mint(_key=attacker_key, _header={"kid": "random"}))
    assert issuer.hits == hits  # all refreshes throttled


def test_outage_with_a_cold_cache_fails_closed(issuer, clock, mint):
    issuer.fail = True
    p = HttpJwks(URL, clock, client=issuer.client())
    verifier = TokenVerifier(VerifierConfig(issuer=ISSUER, audience=AUDIENCE), p, clock)
    with pytest.raises(JwksUnavailable):  # not a token error: the tools layer masks it and denies
        verifier.verify(mint())
