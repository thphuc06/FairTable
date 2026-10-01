"""P2-2: the Cognito pre token trigger gives the claims the dev issuer gives (same rules, same names)."""

import importlib.util
from pathlib import Path

import pytest

from devauth.accounts import CLIENTS, CLIENTS_BY_ID, SCOPE_BOOK

HANDLER = Path(__file__).resolve().parents[3] / "infra" / "cognito" / "pre_token" / "handler.py"
spec = importlib.util.spec_from_file_location("pre_token_handler", HANDLER)
handler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handler)

USER_SOURCES = [
    "TokenGeneration_Authentication",
    "TokenGeneration_HostedAuth",
    "TokenGeneration_NewPasswordChallenge",
    "TokenGeneration_RefreshTokens",
    "TokenGeneration_AuthenticateDevice",
]


def event(source, scopes=("aws.cognito.signin.user.admin",), attributes=None):
    return {
        "version": "3",
        "triggerSource": source,
        "userPoolId": "pool",
        "callerContext": {"clientId": "cid"},
        "request": {"userAttributes": attributes or {}, "scopes": list(scopes)},
        "response": {},
    }


def access(result):
    return result["response"].get("claimsAndScopeOverrideDetails", {}).get("accessTokenGeneration", {})


def test_the_lambda_bundle_uses_only_the_standard_library_and_boto3():
    text = HANDLER.read_text()
    assert "import boto3" in text and "import requests" not in text
    assert handler.BOOK_SCOPE == SCOPE_BOOK


def test_the_profiles_equal_the_dev_issuers_clients():
    assert set(handler.PROFILES) == set(CLIENTS_BY_ID)
    for c in CLIENTS:
        p = handler.PROFILES[c.client_id]
        assert (p.agent_tier, p.agent_id, p.claims_on_machine) == (c.agent_tier, c.agent_id, c.add_claims_to_m2m)
        assert p.may_book == (SCOPE_BOOK in c.scopes)


@pytest.mark.parametrize("source", USER_SOURCES)
def test_a_verified_agents_user_token_gets_agent_claims_and_the_booking_scope(source):
    changes = access(handler.build_response(event(source), handler.PROFILES["alexa-plus-sim"]))
    assert changes["claimsToAddOrOverride"] == {"agent_tier": "verified", "agent_id": "alexa-plus-sim"}
    assert changes["scopesToAdd"] == [SCOPE_BOOK]


def test_the_cognito_self_service_scope_is_removed_from_user_tokens_only():
    user = access(handler.build_response(event("TokenGeneration_Authentication"), handler.PROFILES["alexa-plus-sim"]))
    assert user["scopesToSuppress"] == ["aws.cognito.signin.user.admin"]
    without = access(handler.build_response(event("TokenGeneration_Authentication", scopes=(SCOPE_BOOK,)),
                                            handler.PROFILES["alexa-plus-sim"]))
    assert "scopesToSuppress" not in without  # nothing to remove
    machine = event("TokenGeneration_ClientCredentials", scopes=("aws.cognito.signin.user.admin",))
    assert "scopesToSuppress" not in access(handler.build_response(machine, handler.PROFILES["alexa-plus-sim"]))


def test_an_unverified_agent_is_labelled_unverified():
    changes = access(handler.build_response(event("TokenGeneration_Authentication"), handler.PROFILES["shady-agent"]))
    assert changes["claimsToAddOrOverride"]["agent_tier"] == "unverified"


def test_owners_get_their_venue_in_the_access_token():
    attrs = {"custom:venue_id": "luna-trattoria", "email": "x@example.com"}
    changes = access(handler.build_response(event("TokenGeneration_Authentication", attributes=attrs),
                                            handler.PROFILES["alexa-plus-sim"]))
    assert changes["claimsToAddOrOverride"]["custom:venue_id"] == "luna-trattoria"
    assert "email" not in changes["claimsToAddOrOverride"]  # only what the server reads


def test_the_scope_is_not_added_twice():
    ev = event("TokenGeneration_Authentication", scopes=("openid", SCOPE_BOOK))
    assert "scopesToAdd" not in access(handler.build_response(ev, handler.PROFILES["alexa-plus-sim"]))


def test_a_machine_token_of_a_v3_client_gets_the_agent_claims_but_no_venue_and_no_scope_change():
    ev = event("TokenGeneration_ClientCredentials", scopes=(SCOPE_BOOK,), attributes={"custom:venue_id": "x"})
    changes = access(handler.build_response(ev, handler.PROFILES["alexa-plus-sim"]))
    assert changes == {"claimsToAddOrOverride": {"agent_tier": "verified", "agent_id": "alexa-plus-sim"}}


def test_a_machine_token_of_the_bot_client_gets_nothing_so_g4_and_p0_refuse_it():
    ev = event("TokenGeneration_ClientCredentials", scopes=(SCOPE_BOOK,))
    assert handler.build_response(ev, handler.PROFILES["bot-m2m"])["response"] == {}


def test_an_unknown_client_gets_no_claims_and_no_scope():
    assert handler.build_response(event("TokenGeneration_Authentication"), None)["response"] == {}


def test_only_access_token_generation_is_touched():
    result = handler.build_response(event("TokenGeneration_Authentication"), handler.PROFILES["alexa-plus-sim"])
    assert set(result["response"]["claimsAndScopeOverrideDetails"]) == {"accessTokenGeneration"}


class FakeCognito:
    def __init__(self):
        self.calls = 0

    def describe_user_pool_client(self, UserPoolId, ClientId):  # noqa: N803 (boto3 spelling)
        self.calls += 1
        return {"UserPoolClient": {"ClientName": "alexa-plus-sim"}}


def test_the_client_name_is_looked_up_once_per_client():
    handler._client_names.clear()
    fake = FakeCognito()
    assert handler.client_name("pool", "cid", fake) == "alexa-plus-sim"
    assert handler.client_name("pool", "cid", fake) == "alexa-plus-sim"
    assert fake.calls == 1
    handler._client_names.clear()
