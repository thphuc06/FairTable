"""P1-4: token verification. Every bad token is UNAUTHENTICATED; the agent never learns why."""

import base64
import json

import pytest
from joserfc import jwt
from joserfc.jwk import OctKey
from token_env import AUDIENCE, ISSUER

from server.domain.errors import ErrorCode, FairTableError
from server.domain.models import Identity
from server.identity import TokenVerifier, VerifierConfig


def rejected(verifier: TokenVerifier, token) -> FairTableError:
    with pytest.raises(FairTableError) as exc:
        verifier.verify(token)
    assert exc.value.code is ErrorCode.UNAUTHENTICATED
    return exc.value


# ---------------------------------------------------------------- happy paths
def test_valid_user_token_becomes_an_identity(verifier, mint):
    assert verifier.verify(mint()) == Identity(
        sub="user-1",
        username="alice",
        agent_tier="verified",
        agent_id="alexa-plus-sim",
        scopes=frozenset({"fairtable/book"}),
    )


def test_m2m_bot_token_has_no_username_and_no_agent_tier(verifier, mint):
    """RT1/RT3: a client_credentials token carries neither claim."""
    token = mint(sub="bot-client", username=None, agent_tier=None, agent_id=None)
    ident = verifier.verify(token)
    assert (ident.username, ident.agent_tier, ident.is_user) == (None, None, False)
    assert ident.has_scope("fairtable/book")


def test_scope_may_be_a_list_or_missing(verifier, mint):
    assert verifier.verify(mint(scope=["a", "b"])).scopes == {"a", "b"}
    assert verifier.verify(mint(scope="a  b")).scopes == {"a", "b"}
    assert verifier.verify(mint(scope=None)).scopes == frozenset()


def test_wrongly_typed_optional_claims_are_dropped_not_trusted(verifier, mint):
    ident = verifier.verify(mint(agent_tier=5, username="", agent_id=["x"]))
    assert (ident.agent_tier, ident.username, ident.agent_id) == (None, None, None)


def test_audience_may_be_a_list(verifier, mint):
    assert verifier.verify(mint(aud=["other", AUDIENCE])).sub == "user-1"


def test_audience_claim_can_be_client_id_for_cognito_style_tokens(jwks, clock, mint):
    cfg = VerifierConfig(issuer=ISSUER, audience="app-client", audience_claim="client_id")
    v = TokenVerifier(cfg, jwks, clock)
    assert v.verify(mint(aud=None, client_id="app-client")).sub == "user-1"
    assert rejected(v, mint(aud=AUDIENCE, client_id=None)).reason.startswith("missing_claim")


def test_whitespace_around_the_token_is_ignored(verifier, mint):
    assert verifier.verify(f"  {mint()}\n").sub == "user-1"


def test_headers_helper_reads_x_ft_user_token(verifier, mint):
    assert verifier.verify_headers({"x-ft-user-token": mint()}).sub == "user-1"
    assert rejected(verifier, None).reason == "missing"
    with pytest.raises(FairTableError):
        verifier.verify_headers({"authorization": "Bearer " + mint()})  # wrong header: ignored


# ---------------------------------------------------------------- time
def test_expired_token_is_rejected(verifier, mint, clock):
    token = mint()
    clock.advance(seconds=600 + 30)  # exp + leeway is still accepted
    assert verifier.verify(token).sub == "user-1"
    clock.advance(seconds=1)
    assert rejected(verifier, token).reason == "expired"


def test_token_not_valid_yet_is_rejected(verifier, mint, clock):
    from server.domain.clock import epoch_seconds

    early = mint(nbf=epoch_seconds(clock) + 300)
    assert rejected(verifier, early).reason.startswith("invalid_claim")
    clock.advance(seconds=300)
    assert verifier.verify(early).sub == "user-1"


def test_token_issued_in_the_future_is_rejected(verifier, mint, clock):
    from server.domain.clock import epoch_seconds

    assert rejected(verifier, mint(iat=epoch_seconds(clock) + 3600)).reason.startswith("invalid_claim")


# ---------------------------------------------------------------- claims
@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"iss": "http://evil.example"}, "invalid_claim"),
        ({"aud": "someone-else"}, "invalid_claim"),
        ({"iss": None}, "missing_claim"),
        ({"aud": None}, "missing_claim"),
        ({"exp": None}, "missing_claim"),
        ({"sub": None}, "missing_claim"),
        ({"sub": ""}, "invalid_claim"),
    ],
)
def test_bad_or_missing_essential_claims_are_rejected(verifier, mint, overrides, reason):
    assert rejected(verifier, mint(**overrides)).reason.startswith(reason)


# ---------------------------------------------------------------- forged tokens (RT4, server side)
def test_token_signed_by_another_key_is_rejected(verifier, mint, attacker_key):
    forged = mint(_key=attacker_key)  # same kid, different key material
    assert rejected(verifier, forged).reason == "bad_signature"


def test_unknown_kid_is_rejected_after_one_refresh_attempt(verifier, mint, attacker_key):
    assert rejected(verifier, mint(_key=attacker_key, _header={"kid": "nope"})).reason == "unknown_kid"


def test_tampered_payload_is_rejected(verifier, mint):
    head, payload, sig = mint().split(".")
    body = json.loads(base64.urlsafe_b64decode(payload + "=="))
    body["agent_tier"] = "verified"
    body["sub"] = "someone-else"
    forged = base64.urlsafe_b64encode(json.dumps(body).encode()).rstrip(b"=").decode()
    assert rejected(verifier, f"{head}.{forged}.{sig}").reason == "bad_signature"


def test_alg_none_is_rejected(verifier):
    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    token = f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64({'sub': 'x', 'iss': ISSUER})}."
    assert rejected(verifier, token).reason == "bad_algorithm"


@pytest.mark.filterwarnings("ignore:This key should not be used as an oct key")
def test_hs256_signed_with_public_material_is_rejected(verifier, signing_key):
    """Algorithm-confusion attack: HMAC-sign with the public key as the shared secret."""
    public_pem = signing_key.as_pem(private=False)
    token = jwt.encode(
        {"alg": "HS256", "kid": "k1"},
        {"iss": ISSUER, "aud": AUDIENCE, "sub": "x", "exp": 9999999999},
        OctKey.import_key(public_pem),
    )
    assert rejected(verifier, token).reason == "bad_algorithm"


@pytest.mark.parametrize("garbage", ["", "   ", None, "abc", "a.b.c", "e30.e30.e30", 5, "x" * 9000])
def test_garbage_never_crashes_and_is_unauthenticated(verifier, garbage):
    rejected(verifier, garbage)


def test_the_reason_stays_server_side(verifier, mint):
    err = rejected(verifier, mint(aud="wrong"))
    payload = err.to_payload()
    assert err.reason and "aud" in err.reason
    assert "aud" not in json.dumps(payload) and "invalid_claim" not in json.dumps(payload)
    assert payload["error"] == "UNAUTHENTICATED"
