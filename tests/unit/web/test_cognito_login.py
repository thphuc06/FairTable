"""P2-10: sign-in of the web pages through Cognito (`USER_PASSWORD_AUTH`), checked against a fake Cognito client.

The password goes to Cognito and nowhere else; the access token that comes back is verified with the same
verifier the MCP server uses (issuer, client ids, `client_id` claim, `token_use`)."""

import base64
import hashlib
import hmac
import logging

import pytest
from botocore.exceptions import ClientError
from joserfc import jwt
from joserfc.jwk import KeySet, RSAKey

from server.domain.clock import FakeClock, epoch_seconds
from server.identity import StaticJwks, TokenVerifier, VerifierConfig
from web.auth import CognitoLogin

ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_pool"
CLIENT = "client-abc"
SECRET = "s3cr3t-of-the-app-client"


@pytest.fixture(scope="module")
def key():
    return RSAKey.generate_key(2048, parameters={"kid": "k1", "use": "sig", "alg": "RS256"})


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def verifier(key, clock):
    jwks = StaticJwks(KeySet([key]).as_dict(private=False))
    config = VerifierConfig(ISSUER, (CLIENT, "other-client"), "client_id", token_use="access")
    return TokenVerifier(config, jwks, clock)


@pytest.fixture
def mint(key, clock):
    def _mint(**overrides):
        now = epoch_seconds(clock)
        claims = {"iss": ISSUER, "sub": "uuid-1", "client_id": CLIENT, "token_use": "access", "username": "diner-alice",
                  "scope": "fairtable/book", "agent_tier": "verified", "agent_id": "alexa-plus-sim",
                  "iat": now, "exp": now + 3600}
        claims.update(overrides)
        return jwt.encode({"alg": "RS256", "kid": "k1"}, {k: v for k, v in claims.items() if v is not None}, key)

    return _mint


class FakeCognito:
    def __init__(self, result=None, error: str | None = None):
        self.result, self.error, self.calls = result, error, []

    def initiate_auth(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise ClientError({"Error": {"Code": self.error, "Message": "x"}}, "InitiateAuth")
        return self.result


def ok(token, expires=3600):
    return {"AuthenticationResult": {"AccessToken": token, "IdToken": "id.jwt.x", "ExpiresIn": expires}}


def login(client, verifier, secret=SECRET):
    return CognitoLogin(client, CLIENT, verifier, client_secret=secret)


def test_a_valid_sign_in_gives_the_verified_identity_and_the_access_token(verifier, mint):
    token = mint()
    signed = login(FakeCognito(ok(token)), verifier).sign_in("diner-alice", "pw")
    assert signed.identity.username == "diner-alice" and signed.identity.agent_tier == "verified"
    assert signed.access_token == token and signed.expires_in_s == 3600


def test_the_request_uses_the_password_flow_with_the_secret_hash(verifier, mint):
    fake = FakeCognito(ok(mint()))
    login(fake, verifier).sign_in("diner-alice", "pw-123")
    (call,) = fake.calls
    assert call["AuthFlow"] == "USER_PASSWORD_AUTH" and call["ClientId"] == CLIENT
    params = call["AuthParameters"]
    assert params["USERNAME"] == "diner-alice" and params["PASSWORD"] == "pw-123"
    digest = hmac.new(SECRET.encode(), ("diner-alice" + CLIENT).encode(), hashlib.sha256).digest()
    assert params["SECRET_HASH"] == base64.b64encode(digest).decode()  # the formula in the Cognito documentation


def test_a_client_without_a_secret_sends_no_hash(verifier, mint):
    fake = FakeCognito(ok(mint()))
    CognitoLogin(fake, CLIENT, verifier).sign_in("diner-alice", "pw")
    assert "SECRET_HASH" not in fake.calls[0]["AuthParameters"]


@pytest.mark.parametrize("code", ["NotAuthorizedException", "UserNotFoundException", "PasswordResetRequiredException",
                                  "UserNotConfirmedException", "TooManyRequestsException", "InternalErrorException"])
def test_every_cognito_refusal_is_just_a_failed_sign_in(verifier, code):
    assert login(FakeCognito(error=code), verifier).sign_in("diner-alice", "wrong") is None


def test_a_challenge_instead_of_tokens_is_a_failed_sign_in(verifier):
    challenge = {"ChallengeName": "NEW_PASSWORD_REQUIRED", "Session": "s"}
    assert login(FakeCognito(challenge), verifier).sign_in("diner-alice", "temp") is None


def test_a_network_failure_is_a_failed_sign_in(verifier):
    class Down:
        def initiate_auth(self, **_):
            raise OSError("no route")

    assert login(Down(), verifier).sign_in("diner-alice", "pw") is None


@pytest.mark.parametrize("claims", [
    {"token_use": "id"},  # an ID token is not an access token
    {"client_id": "unknown-client"},
    {"iss": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_other"},
    {"username": None},  # a machine token has no username: the web pages are for people
])
def test_a_token_the_verifier_refuses_is_a_failed_sign_in(verifier, mint, claims):
    assert login(FakeCognito(ok(mint(**claims))), verifier).sign_in("diner-alice", "pw") is None


def test_a_token_signed_by_another_key_is_a_failed_sign_in(verifier):
    other = RSAKey.generate_key(2048, parameters={"kid": "k1"})
    now = 1_700_000_000
    forged = jwt.encode({"alg": "RS256", "kid": "k1"}, {"iss": ISSUER, "sub": "x", "client_id": CLIENT, "token_use": "access",
                                                       "username": "diner-alice", "exp": now + 10**9}, other)
    assert login(FakeCognito(ok(forged)), verifier).sign_in("diner-alice", "pw") is None


def test_missing_fields_in_the_answer_are_a_failed_sign_in(verifier):
    assert login(FakeCognito({"AuthenticationResult": {}}), verifier).sign_in("diner-alice", "pw") is None
    assert login(FakeCognito({}), verifier).sign_in("diner-alice", "pw") is None


def test_the_password_and_the_secret_are_never_logged(verifier, mint, caplog):
    with caplog.at_level(logging.DEBUG):
        login(FakeCognito(ok(mint())), verifier).sign_in("diner-alice", "hunter2-password")
        login(FakeCognito(error="NotAuthorizedException"), verifier).sign_in("diner-alice", "hunter2-password")
    text = " ".join(caplog.messages)
    assert "hunter2-password" not in text and SECRET not in text


def test_the_owner_token_carries_the_group_and_the_venue(verifier, mint):
    token = mint(username="owner-luna", **{"cognito:groups": ["owners"], "custom:venue_id": "luna-trattoria"})
    signed = login(FakeCognito(ok(token)), verifier).sign_in("owner-luna", "pw")
    assert "owners" in signed.identity.groups and signed.identity.venue_id == "luna-trattoria"
