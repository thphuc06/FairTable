"""Cognito pre token generation trigger (event version V3_0) for FairTable.

Cognito's own access tokens lack what the server's rules read. This function adds it, and gives the
same claims as the local dev issuer (`devauth/`, see `tests/unit/infra/test_pre_token.py`):

* user tokens (password sign-in, refresh, managed login): `agent_tier` and `agent_id` of the app
  client, the scope `fairtable/book` (Cognito assigns only `aws.cognito.signin.user.admin` to tokens
  from `InitiateAuth`, and that scope is removed: it would let a leaked token change the user's own
  profile and password), and `custom:venue_id` for owners. `username`, `sub`, `client_id` and
  `cognito:groups` are Cognito's own and cannot be changed by a trigger.
* machine tokens (client credentials, V3_0 only): `agent_tier` and `agent_id` only for clients marked
  `claims_on_machine`; the others get nothing, so the server's G4 and P0 refuse them.

Unknown app clients get no claims and no scope, so every write is refused (fail closed). The app
client is identified by its name (`DescribeUserPoolClient`, cached per container), because the client
id is only known after deployment and the function cannot be wired to it without a cycle.

Sources: docs.aws.amazon.com/cognito/latest/developerguide/user-pool-lambda-pre-token-generation.html
(event shape, `scopesToAdd`, `accessTokenGeneration`, trigger sources, the claims a trigger cannot
change).
"""

from dataclasses import dataclass

BOOK_SCOPE = "fairtable/book"
SELF_SERVICE_SCOPE = "aws.cognito.signin.user.admin"  # lets the token holder change the user's own profile and password
MACHINE_SOURCE = "TokenGeneration_ClientCredentials"


@dataclass(frozen=True)
class ClientProfile:
    agent_tier: str | None = None
    agent_id: str | None = None
    claims_on_machine: bool = False  # V3-style: also add the claims to client-credentials tokens
    may_book: bool = True


# Keyed by app client NAME. Keep in step with devauth/accounts.py (a test compares them).
PROFILES: dict[str, ClientProfile] = {
    "alexa-plus-sim": ClientProfile("verified", "alexa-plus-sim", claims_on_machine=True),
    "shady-agent": ClientProfile("unverified", "shady-agent"),
    "bot-m2m": ClientProfile(),
}


def access_token_changes(event: dict, profile: ClientProfile | None) -> dict:
    """What to change in the access token for this event (pure; `profile` is None for an unknown client)."""
    if profile is None:
        return {}
    machine = event.get("triggerSource") == MACHINE_SOURCE
    claims: dict[str, str] = {}
    if not machine or profile.claims_on_machine:
        if profile.agent_tier:
            claims["agent_tier"] = profile.agent_tier
        if profile.agent_id:
            claims["agent_id"] = profile.agent_id
    if not machine:
        venue = (event.get("request", {}).get("userAttributes") or {}).get("custom:venue_id")
        if venue:
            claims["custom:venue_id"] = venue
    changes: dict = {}
    if claims:
        changes["claimsToAddOrOverride"] = claims
    if not machine:
        scopes = event.get("request", {}).get("scopes") or []
        if profile.may_book and BOOK_SCOPE not in scopes:
            changes["scopesToAdd"] = [BOOK_SCOPE]
        if SELF_SERVICE_SCOPE in scopes:
            changes["scopesToSuppress"] = [SELF_SERVICE_SCOPE]  # no assistant needs to call Cognito as the diner
    return changes


def build_response(event: dict, profile: ClientProfile | None) -> dict:
    changes = access_token_changes(event, profile)
    event["response"] = {"claimsAndScopeOverrideDetails": {"accessTokenGeneration": changes}} if changes else {}
    return event


_client_names: dict[tuple[str, str], str] = {}


def client_name(user_pool_id: str, client_id: str, client=None) -> str:
    key = (user_pool_id, client_id)
    if key not in _client_names:
        if client is None:
            import boto3  # available in the Lambda runtime

            client = boto3.client("cognito-idp")
        described = client.describe_user_pool_client(UserPoolId=user_pool_id, ClientId=client_id)
        _client_names[key] = described["UserPoolClient"]["ClientName"]
    return _client_names[key]


def lambda_handler(event, context=None):
    name = client_name(event["userPoolId"], event["callerContext"]["clientId"])
    return build_response(event, PROFILES.get(name))
