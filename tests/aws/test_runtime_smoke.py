"""P2-3 on the real account: the MCP server on AgentCore Runtime, called the way the Gateway will call it.

Opt-in: ``pytest -m aws tests/aws/test_runtime_smoke.py`` after ``cdk deploy FairTableRuntime`` and
``python scripts/seed.py`` with COGNITO_USER_POOL_ID set (so that the demo data is keyed by Cognito's subs).

The caller signs each request with SigV4 (service ``bedrock-agentcore``, the runtime accepts IAM callers
only), and the diner's Cognito token travels in ``x-ft-user-token``. What this settles that nothing local can:
the header survives the runtime's allowlist, the server's Host check accepts what the platform sends, the
verifier works with Cognito's keys, the execution role is enough for DynamoDB, and stateless mode works.
"""

import urllib.parse

import boto3
import httpx
import pytest
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.exceptions import ClientError
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

import test_tokens as tokens

pytestmark = pytest.mark.aws
STACK = "FairTableRuntime"
EXPECTED_TOOLS = {
    "restaurant_search", "availability_check", "mandate_status", "reservation_hold",
    "reservation_confirm", "reservation_manage", "waitlist_watch", "waitlist_status",
}
TOKEN_HEADER = "x-ft-user-token"


class SignedRequests(httpx.Auth):
    """Signs every request with the current credentials (they refresh by themselves)."""

    requires_request_body = True

    def __init__(self, region: str) -> None:
        self._region = region
        self._session = boto3.Session()

    def auth_flow(self, request):
        credentials = self._session.get_credentials().get_frozen_credentials()
        aws = AWSRequest(method=request.method, url=str(request.url), data=request.content,
                         headers={"Content-Type": request.headers.get("content-type", "application/json")})
        SigV4Auth(credentials, "bedrock-agentcore", self._region).add_auth(aws)
        for name in ("Authorization", "X-Amz-Date", "X-Amz-Security-Token"):
            if name in aws.headers:
                request.headers[name] = aws.headers[name]
        yield request


@pytest.fixture(scope="module")
def runtime():
    try:
        stack = boto3.client("cloudformation").describe_stacks(StackName=STACK)["Stacks"][0]
    except ClientError as e:
        pytest.skip(f"{STACK} is not deployed: {e}")
    out = {o["OutputKey"]: o["OutputValue"] for o in stack["Outputs"]}
    region = boto3.Session().region_name or "us-east-1"
    encoded = urllib.parse.quote(out["RuntimeArn"], safe="")
    url = f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{encoded}/invocations?qualifier=DEFAULT"
    return {"url": url, "region": region, "arn": out["RuntimeArn"], "id": out["RuntimeId"]}


@pytest.fixture(scope="module")
def cognito():
    """Cognito pool facts, reusing the helpers of test_tokens.py."""
    stacks = boto3.client("cloudformation").describe_stacks(StackName=tokens.STACK)["Stacks"]
    out = {o["OutputKey"]: o["OutputValue"] for o in stacks[0]["Outputs"]}
    idp = boto3.client("cognito-idp")
    clients = {}
    for c in idp.list_user_pool_clients(UserPoolId=out["UserPoolId"], MaxResults=20)["UserPoolClients"]:
        d = idp.describe_user_pool_client(UserPoolId=out["UserPoolId"], ClientId=c["ClientId"])["UserPoolClient"]
        clients[d["ClientName"]] = {"id": d["ClientId"], "secret": d.get("ClientSecret")}
    return {"out": out, "clients": clients, "idp": idp}


def client_for(runtime, token: str | None = None) -> Client:
    headers = {TOKEN_HEADER: token} if token else {}
    transport = StreamableHttpTransport(runtime["url"], headers=headers, auth=SignedRequests(runtime["region"]))
    return Client(transport, timeout=120)


async def call(runtime, token, tool, **args):
    async with client_for(runtime, token) as c:
        return await c.call_tool_mcp(tool, args)


@pytest.mark.asyncio
async def test_the_runtime_lists_the_eight_tools(runtime):
    async with client_for(runtime) as c:
        names = {t.name for t in await c.list_tools()}
    assert names == EXPECTED_TOOLS


@pytest.mark.asyncio
async def test_a_diner_token_in_the_header_reaches_the_server_and_dynamodb(runtime, cognito):
    token = tokens.sign_in(cognito, "alexa-plus-sim", "diner-alice")
    result = await call(runtime, token, "restaurant_search")
    assert not result.isError, result.structuredContent
    assert len(result.structuredContent["restaurants"]) == 3  # the seeded demo restaurants


@pytest.mark.asyncio
async def test_a_call_without_the_header_is_unauthenticated(runtime):
    result = await call(runtime, None, "restaurant_search")
    assert result.isError and result.structuredContent["error"] == "UNAUTHENTICATED"


@pytest.mark.asyncio
async def test_a_token_that_is_not_ours_is_unauthenticated(runtime):
    result = await call(runtime, "not.a.jwt", "restaurant_search")
    assert result.isError and result.structuredContent["error"] == "UNAUTHENTICATED"


@pytest.mark.asyncio
async def test_an_id_token_is_unauthenticated(runtime, cognito):
    id_token = tokens.sign_in(cognito, "alexa-plus-sim", "diner-alice", key="IdToken")
    result = await call(runtime, id_token, "restaurant_search")
    assert result.isError and result.structuredContent["error"] == "UNAUTHENTICATED"


async def a_real_slot_token(runtime, token):
    """Reads are open to any valid token (G1), so even a bot can get a real slot token; the write is what is refused."""
    from datetime import UTC, datetime, timedelta

    day = (datetime.now(UTC).date() + timedelta(days=5)).isoformat()
    result = await call(runtime, token, "availability_check", restaurant_id="luna-trattoria", date=day,
                        time_window="19:00-19:00", party_size=2)
    assert not result.isError, result.structuredContent
    return result.structuredContent["slots"][0]["slot_token"]


@pytest.mark.asyncio
async def test_a_machine_token_without_agent_claims_cannot_write(runtime, cognito):
    token = tokens.machine_token(cognito, "bot-m2m")
    slot = await a_real_slot_token(runtime, token)  # allowed: a read
    result = await call(runtime, token, "reservation_hold", slot_token=slot, idempotency_key="smoke-bot-00001")
    assert result.isError and result.structuredContent["error"] == "POLICY_DENIED"


@pytest.mark.asyncio
async def test_the_unverified_agent_cannot_write(runtime, cognito):
    token = tokens.sign_in(cognito, "shady-agent", "diner-bob")
    slot = await a_real_slot_token(runtime, token)
    result = await call(runtime, token, "reservation_hold", slot_token=slot, idempotency_key="smoke-shady-0001")
    assert result.isError and result.structuredContent["error"] == "POLICY_DENIED"


@pytest.mark.asyncio
async def test_a_booking_inside_alices_permission_runs_end_to_end_and_is_cancelled(runtime, cognito):
    """Hold, confirm and cancel through the runtime: DynamoDB transactions with the execution role."""
    from datetime import UTC, datetime, timedelta

    token = tokens.sign_in(cognito, "alexa-plus-sim", "diner-alice")
    day = (datetime.now(UTC).date() + timedelta(days=3)).isoformat()
    tag = datetime.now(UTC).strftime("%H%M%S")
    slots = (await call(runtime, token, "availability_check", restaurant_id="luna-trattoria", date=day,
                        time_window="20:00-20:00", party_size=2)).structuredContent["slots"]
    assert slots
    held = await call(runtime, token, "reservation_hold", slot_token=slots[0]["slot_token"],
                      idempotency_key=f"smoke-hold-{tag}")
    assert not held.isError, held.structuredContent
    confirmed = await call(runtime, token, "reservation_confirm", hold_id=held.structuredContent["hold_id"],
                           idempotency_key=f"smoke-conf-{tag}")
    assert not confirmed.isError, confirmed.structuredContent  # Luna is inside Alice's seeded permission
    reservation_id = confirmed.structuredContent["reservation_id"]
    cancelled = await call(runtime, token, "reservation_manage", action="cancel", reservation_id=reservation_id,
                           idempotency_key=f"smoke-cancel-{tag}")
    assert not cancelled.isError, cancelled.structuredContent
