"""P2-2 on the real account: Cognito tokens carry the same claims as the dev issuer's, and the
server's verifier accepts them unchanged (only issuer, JWKS URL and audience differ).

Opt-in: ``pytest -m aws tests/aws/test_tokens.py`` after ``cdk deploy FairTableIdentity`` and
``python scripts/cognito_users.py``. The stack is found by name; nothing account-specific is stored.
"""

import base64
import hashlib
import hmac

import boto3
import httpx
import pytest
from botocore.exceptions import ClientError

from devauth.accounts import USERS_BY_NAME
from server.domain.clock import SystemClock
from server.domain.errors import ErrorCode, FairTableError
from server.identity import HttpJwks, TokenVerifier, VerifierConfig

pytestmark = pytest.mark.aws
STACK = "FairTableIdentity"
BOOK = "fairtable/book"


@pytest.fixture(scope="module")
def pool():
    try:
        stacks = boto3.client("cloudformation").describe_stacks(StackName=STACK)["Stacks"]
    except ClientError as e:
        pytest.skip(f"{STACK} is not deployed: {e}")
    out = {o["OutputKey"]: o["OutputValue"] for o in stacks[0]["Outputs"]}
    idp = boto3.client("cognito-idp")
    clients = {}
    for c in idp.list_user_pool_clients(UserPoolId=out["UserPoolId"], MaxResults=20)["UserPoolClients"]:
        detail = idp.describe_user_pool_client(UserPoolId=out["UserPoolId"], ClientId=c["ClientId"])["UserPoolClient"]
        clients[detail["ClientName"]] = {"id": detail["ClientId"], "secret": detail.get("ClientSecret")}
    return {"out": out, "clients": clients, "idp": idp}


def sign_in(pool, client_name, username, *, key="AccessToken"):
    client = pool["clients"][client_name]
    params = {"USERNAME": username, "PASSWORD": USERS_BY_NAME[username].password}
    if client["secret"]:
        digest = hmac.new(client["secret"].encode(), (username + client["id"]).encode(), hashlib.sha256).digest()
        params["SECRET_HASH"] = base64.b64encode(digest).decode()
    response = pool["idp"].initiate_auth(AuthFlow="USER_PASSWORD_AUTH", ClientId=client["id"], AuthParameters=params)
    return response["AuthenticationResult"][key]


def machine_token(pool, client_name):
    client = pool["clients"][client_name]
    response = httpx.post(
        pool["out"]["TokenEndpoint"], data={"grant_type": "client_credentials", "scope": BOOK},
        auth=(client["id"], client["secret"]), timeout=30,
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def verify(pool, client_name, token):
    """The server's verifier as the AWS profile configures it: every app client, `client_id`, access tokens only."""
    issuer = pool["out"]["Issuer"]
    config = VerifierConfig(
        issuer=issuer,
        audience=tuple(c["id"] for c in pool["clients"].values()),
        audience_claim="client_id",
        token_use="access",
    )
    jwks = HttpJwks(issuer + "/.well-known/jwks.json", SystemClock(), client=httpx.Client(timeout=30))
    return TokenVerifier(config, jwks, SystemClock()).verify(token)


def test_a_diner_signed_in_through_the_verified_agent(pool):
    who = verify(pool, "alexa-plus-sim", sign_in(pool, "alexa-plus-sim", "diner-alice"))
    assert who.username == "diner-alice" and BOOK in who.scopes
    assert (who.agent_tier, who.agent_id) == ("verified", "alexa-plus-sim")
    assert not who.groups and who.venue_id is None
    assert "aws.cognito.signin.user.admin" not in who.scopes  # a leaked token cannot change the user's password


def test_a_diner_signed_in_through_the_unverified_agent(pool):
    who = verify(pool, "shady-agent", sign_in(pool, "shady-agent", "diner-bob"))
    assert who.username == "diner-bob" and BOOK in who.scopes
    assert who.agent_tier == "unverified"


def test_an_owner_carries_the_group_and_the_venue(pool):
    who = verify(pool, "alexa-plus-sim", sign_in(pool, "alexa-plus-sim", "owner-luna"))
    assert "owners" in who.groups and who.venue_id == "luna-trattoria"


def test_the_verified_agent_as_a_machine_gets_agent_claims_but_no_username(pool):
    who = verify(pool, "alexa-plus-sim", machine_token(pool, "alexa-plus-sim"))
    assert who.username is None and BOOK in who.scopes
    assert (who.agent_tier, who.agent_id) == ("verified", "alexa-plus-sim")


def test_the_bot_client_has_neither_username_nor_agent_claims(pool):
    who = verify(pool, "bot-m2m", machine_token(pool, "bot-m2m"))
    assert who.username is None and who.agent_tier is None and who.agent_id is None


def test_the_subs_are_not_the_dev_issuers_fixed_ones(pool):
    who = verify(pool, "alexa-plus-sim", sign_in(pool, "alexa-plus-sim", "diner-alice"))
    assert who.sub != USERS_BY_NAME["diner-alice"].sub  # the seed must read Cognito's subs


def test_an_id_token_is_refused_as_an_access_token(pool):
    id_token = sign_in(pool, "alexa-plus-sim", "diner-alice", key="IdToken")
    with pytest.raises(FairTableError) as exc:
        verify(pool, "alexa-plus-sim", id_token)
    assert exc.value.code is ErrorCode.UNAUTHENTICATED


def test_a_token_of_a_client_that_is_not_on_the_list_is_refused(pool):
    issuer = pool["out"]["Issuer"]
    config = VerifierConfig(issuer=issuer, audience=(pool["clients"]["bot-m2m"]["id"],), audience_claim="client_id",
                            token_use="access")
    jwks = HttpJwks(issuer + "/.well-known/jwks.json", SystemClock(), client=httpx.Client(timeout=30))
    token = sign_in(pool, "alexa-plus-sim", "diner-alice")
    with pytest.raises(FairTableError):
        TokenVerifier(config, jwks, SystemClock()).verify(token)
