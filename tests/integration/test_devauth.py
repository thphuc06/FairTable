"""P1-5: the dev issuer. Tokens it issues must pass the same verifier the server uses for Cognito,
and the M2M bot must reproduce RT1/RT3 (no username, no agent_tier)."""

import pytest
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import KeySet

from devauth.accounts import CLIENTS, USERS
from devauth.app import create_app
from devauth.issuer import IssuerSettings, load_or_create_key
from server.domain.clock import FakeClock
from server.domain.errors import ErrorCode, FairTableError
from server.domain.tool_names import ToolName
from server.identity import StaticJwks, TokenVerifier, VerifierConfig
from server.kernel import Pep1, default_policy_dir

SETTINGS = IssuerSettings(issuer="http://localhost:9000", audience="fairtable-mcp", ttl_s=3600)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def client(clock):
    key = load_or_create_key(None)
    return TestClient(create_app(SETTINGS, clock=clock, key=key))


@pytest.fixture
def verifier(client, clock):
    jwks = StaticJwks(client.get("/.well-known/jwks.json").json())
    return TokenVerifier(VerifierConfig(SETTINGS.issuer, SETTINGS.audience), jwks, clock)


@pytest.fixture(scope="module")
def pep1():
    return Pep1.from_dir(default_policy_dir())


def login(client, username="diner-alice", password="alice-dev-pass", client_id="alexa-plus-sim", **extra):
    return client.post(
        "/token",
        data={"grant_type": "password", "client_id": client_id, "username": username,
              "password": password, **extra},
    )


def m2m(client, client_id="bot-m2m", secret="bot-m2m-dev-secret", basic=False):
    if basic:
        return client.post("/token", data={"grant_type": "client_credentials"}, auth=(client_id, secret))
    return client.post(
        "/token",
        data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": secret},
    )


# ---------------------------------------------------------------- discovery
def test_metadata_and_jwks_are_published(client):
    meta = client.get("/.well-known/openid-configuration").json()
    assert meta["issuer"] == SETTINGS.issuer
    assert meta["jwks_uri"].endswith("/.well-known/jwks.json")
    keys = KeySet.import_key_set(client.get(meta["jwks_uri"].replace(SETTINGS.issuer, "")).json())
    assert len(keys.keys) == 1
    assert client.get("/healthz").json() == {"status": "ok"}


def test_jwks_never_contains_private_material(client):
    for key in client.get("/.well-known/jwks.json").json()["keys"]:
        assert not {"d", "p", "q", "dp", "dq", "qi"} & set(key)


# ---------------------------------------------------------------- user tokens
def test_alice_gets_a_verified_agent_token_the_server_accepts(client, verifier):
    body = login(client).json()
    assert body["token_type"] == "Bearer" and body["expires_in"] == 3600
    ident = verifier.verify(body["access_token"])
    assert (ident.sub, ident.username) == ("dev-alice", "diner-alice")
    assert (ident.agent_tier, ident.agent_id) == ("verified", "alexa-plus-sim")
    assert ident.scopes == {"fairtable/book"}


def test_agent_claims_follow_the_client_not_the_user(client, verifier):
    ident = verifier.verify(login(client, client_id="shady-agent").json()["access_token"])
    assert (ident.username, ident.agent_tier) == ("diner-alice", "unverified")


def test_owner_token_carries_the_owners_group(client):
    token = login(client, "owner-luna", "luna-dev-pass").json()["access_token"]
    claims = jwt.decode(token, KeySet.import_key_set(client.get("/.well-known/jwks.json").json())).claims
    assert claims["cognito:groups"] == ["owners"]


def test_token_carries_audience_and_client_id_for_both_verifier_styles(client):
    token = login(client).json()["access_token"]
    keys = KeySet.import_key_set(client.get("/.well-known/jwks.json").json())
    claims = jwt.decode(token, keys).claims
    assert claims["aud"] == "fairtable-mcp" and claims["client_id"] == "alexa-plus-sim"


# ---------------------------------------------------------------- machine tokens (RT1, RT3)
@pytest.mark.parametrize("basic", [False, True])
def test_bot_token_has_no_username_and_no_agent_tier(client, verifier, basic):
    ident = verifier.verify(m2m(client, basic=basic).json()["access_token"])
    assert (ident.username, ident.agent_tier, ident.agent_id) == (None, None, None)
    assert ident.has_scope("fairtable/book") and not ident.is_user


def test_v3_style_client_gets_agent_claims_but_still_no_username(client, verifier):
    ident = verifier.verify(m2m(client, "alexa-plus-sim", "alexa-sim-dev-secret").json()["access_token"])
    assert (ident.username, ident.agent_tier) == (None, "verified")


# ---------------------------------------------------------------- the kernel accepts / refuses them
def test_tokens_drive_the_pep1_decisions_end_to_end(client, verifier, pep1):
    def decide(token, tool, party=2):
        return pep1.decide(identity=verifier.verify(token), action=tool, party_size=party)

    alice = login(client).json()["access_token"]
    bot = m2m(client).json()["access_token"]
    shady = login(client, client_id="shady-agent").json()["access_token"]
    v3 = m2m(client, "alexa-plus-sim", "alexa-sim-dev-secret").json()["access_token"]

    assert decide(alice, ToolName.RESERVATION_HOLD).allowed
    assert decide(bot, ToolName.RESTAURANT_SEARCH, 0).allowed  # bots may read
    assert decide(bot, ToolName.RESERVATION_HOLD).rule_ids == ("G4_verified_agent_only",)  # RT1
    assert decide(shady, ToolName.RESERVATION_HOLD).rule_ids == ("G4_verified_agent_only",)
    assert decide(v3, ToolName.RESERVATION_HOLD).rule_ids == ("no_permit",)  # RT3: no human behind it


# ---------------------------------------------------------------- refusals
@pytest.mark.parametrize(
    "call,status,error",
    [
        (lambda c: login(c, password="wrong"), 400, "invalid_grant"),
        (lambda c: login(c, username="nobody"), 400, "invalid_grant"),
        (lambda c: login(c, client_id="ghost"), 401, "invalid_client"),
        (lambda c: m2m(c, secret="wrong"), 401, "invalid_client"),
        (lambda c: m2m(c, "ghost", "x"), 401, "invalid_client"),
        (lambda c: login(c, scope="admin"), 400, "invalid_scope"),
        (lambda c: login(c, client_secret="wrong"), 401, "invalid_client"),  # a sent secret must be right
        (lambda c: c.post("/token", data={"grant_type": "client_credentials", "client_id": "bot-m2m"}),
         401, "invalid_client"),  # machine flow needs the secret
        (lambda c: c.post("/token", data={"grant_type": "authorization_code", "client_id": "alexa-plus-sim"}),
         400, "unsupported_grant_type"),
    ],
)
def test_bad_requests_get_oauth_errors(client, call, status, error):
    response = call(client)
    assert (response.status_code, response.json()["error"]) == (status, error)
    assert response.headers["cache-control"] == "no-store"
    assert "access_token" not in response.text


def test_client_may_only_use_its_own_grants(client):
    response = client.post(
        "/token",
        data={"grant_type": "password", "client_id": "bot-m2m", "client_secret": "bot-m2m-dev-secret",
              "username": "diner-alice", "password": "alice-dev-pass"},
    )
    assert response.json()["error"] == "unauthorized_client"


# ---------------------------------------------------------------- lifetime and keys
def test_tokens_expire_with_the_clock(client, verifier, clock):
    token = login(client).json()["access_token"]
    clock.advance(seconds=3600 + 31)
    with pytest.raises(FairTableError) as exc:
        verifier.verify(token)
    assert exc.value.code is ErrorCode.UNAUTHENTICATED and exc.value.reason == "expired"


def test_signing_key_is_stable_across_restarts_when_a_file_is_given(tmp_path):
    path = tmp_path / "keys" / "devauth.jwk"
    first = load_or_create_key(path)
    second = load_or_create_key(path)
    assert first.kid == second.kid
    assert load_or_create_key(None).kid != first.kid  # ephemeral keys differ


def test_seeded_accounts_are_the_documented_ones():
    assert {u.username for u in USERS} == {"diner-alice", "diner-bob", "diner-carol", "owner-luna"}
    assert {c.client_id for c in CLIENTS} == {"alexa-plus-sim", "shady-agent", "bot-m2m"}
