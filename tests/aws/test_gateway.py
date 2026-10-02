"""P2-5 on the real account: the AgentCore Gateway in front of the Runtime.

Opt-in: ``pytest -m aws tests/aws/test_gateway.py`` after ``cdk deploy FairTableGateway`` and
``python infra/aws_ctl.py seed``. Callers talk to the Gateway with a Cognito access token as a bearer token
(no AWS credentials); the Gateway checks it, the interceptor copies it into ``x-ft-user-token`` and the Gateway
calls the Runtime with SigV4. What this settles: the token really reaches the server through both allowlists,
a header the client forged is replaced, and an unauthenticated caller never gets in.

Tools are named ``<target>___<tool>`` by the Gateway (the target is called ``ft``).
"""

import asyncio
from datetime import UTC, datetime, timedelta

import boto3
import httpx
import pytest
from botocore.exceptions import ClientError
from fastmcp import Client
from mcp.shared.exceptions import McpError
from fastmcp.client.transports import StreamableHttpTransport
from test_runtime_smoke import cognito  # noqa: F401  (a fixture: the pool, its clients and their secrets)

import test_tokens as tokens

pytestmark = pytest.mark.aws
STACK = "FairTableGateway"
PREFIX = "ft___"
TOOLS = {
    "restaurant_search", "availability_check", "reservation_hold",
    "reservation_confirm", "reservation_manage", "waitlist_watch", "waitlist_status",
}


@pytest.fixture(scope="module")
def gateway():
    try:
        stack = boto3.client("cloudformation").describe_stacks(StackName=STACK)["Stacks"][0]
    except ClientError as e:
        pytest.skip(f"{STACK} is not deployed: {e}")
    out = {o["OutputKey"]: o["OutputValue"] for o in stack["Outputs"]}
    return {"url": out["GatewayUrl"], "id": out["GatewayId"]}


def client_for(gateway, token: str | None = None, **headers) -> Client:
    all_headers = {**({"Authorization": f"Bearer {token}"} if token else {}), **headers}
    return Client(StreamableHttpTransport(gateway["url"], headers=all_headers), timeout=120)


async def call(gateway, token, tool, headers=None, **args):
    async with client_for(gateway, token, **(headers or {})) as c:
        return await c.call_tool_mcp(PREFIX + tool, args)


@pytest.mark.asyncio
async def test_the_gateway_lists_the_eight_tools_under_the_target_prefix(gateway, cognito):  # noqa: F811
    token = tokens.sign_in(cognito, "alexa-plus-sim", "diner-alice")
    async with client_for(gateway, token) as c:
        names = {t.name for t in await c.list_tools()}
    assert {PREFIX + t for t in TOOLS} <= names


@pytest.mark.asyncio
async def test_the_diner_token_reaches_the_server_through_both_allowlists(gateway, cognito):  # noqa: F811
    token = tokens.sign_in(cognito, "alexa-plus-sim", "diner-alice")
    result = await call(gateway, token, "restaurant_search")
    assert not result.isError, result.structuredContent
    assert len(result.structuredContent["restaurants"]) == 3


@pytest.mark.asyncio
async def test_a_header_forged_by_the_client_is_replaced_by_the_verified_token(gateway, cognito):  # noqa: F811
    """Alice is signed in; the client also sends Bob's token as `x-ft-user-token`. The server must see Alice.
    A slot token is bound to the user it was offered to: if the server saw Bob, Alice's slot token would be refused."""
    from datetime import UTC, datetime, timedelta

    alice = tokens.sign_in(cognito, "alexa-plus-sim", "diner-alice")
    bob = tokens.sign_in(cognito, "alexa-plus-sim", "diner-bob")
    day = (datetime.now(UTC).date() + timedelta(days=11)).isoformat()
    tag = datetime.now(UTC).strftime("%H%M%S")
    slots = (await call(gateway, alice, "availability_check", restaurant_id="luna-trattoria", date=day,
                        time_window="20:30-20:30", party_size=2)).structuredContent["slots"]
    forged = await call(gateway, alice, "reservation_hold", headers={"x-ft-user-token": bob},
                        offer_id=slots[0]["offer_id"], idempotency_key=f"forged-hold-{tag}")
    assert not forged.isError, forged.structuredContent  # the server saw Alice, not Bob
    await call(gateway, alice, "reservation_manage", action="view", reservation_id="none")  # keeps the session warm


@pytest.mark.asyncio
async def test_without_a_token_the_gateway_refuses(gateway):
    async with httpx.AsyncClient(timeout=60) as http:
        r = await http.post(gateway["url"], json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                            headers={"Accept": "application/json, text/event-stream"})
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_a_forged_header_alone_does_not_get_in(gateway, cognito):  # noqa: F811
    bob = tokens.sign_in(cognito, "alexa-plus-sim", "diner-bob")
    async with httpx.AsyncClient(timeout=60) as http:
        r = await http.post(gateway["url"], json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                            headers={"Accept": "application/json, text/event-stream", "x-ft-user-token": bob})
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_an_id_token_is_refused_by_the_gateway(gateway, cognito):  # noqa: F811
    id_token = tokens.sign_in(cognito, "alexa-plus-sim", "diner-alice", key="IdToken")
    async with httpx.AsyncClient(timeout=60) as http:
        r = await http.post(gateway["url"], json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                            headers={"Accept": "application/json, text/event-stream",
                                     "Authorization": f"Bearer {id_token}"})
    assert r.status_code in (401, 403)


async def refused_write(gateway, token, slot, key):
    """A write the caller may not make is refused at the Gateway when its policy engine enforces G2 and G4
    (a JSON-RPC error naming the policy, D-049) and by the server's own PEP-1 when it does not (POLICY_DENIED)."""
    try:
        result = await call(gateway, token, "reservation_hold", offer_id=slot, idempotency_key=key)
    except McpError as e:
        assert "Tool Execution Denied" in str(e) and "policy" in str(e).lower()
        return True
    return bool(result.isError and result.structuredContent["error"] == "POLICY_DENIED")


async def a_offer_id(gateway, token):
    day = (datetime.now(UTC).date() + timedelta(days=6)).isoformat()
    result = await call(gateway, token, "availability_check", restaurant_id="luna-trattoria", date=day,
                        time_window="19:00-19:00", party_size=2)
    assert not result.isError, result.structuredContent
    return result.structuredContent["slots"][0]["offer_id"]


@pytest.mark.asyncio
async def test_the_bot_client_can_read_but_not_write(gateway, cognito):  # noqa: F811
    token = tokens.machine_token(cognito, "bot-m2m")
    slot = await a_offer_id(gateway, token)
    assert await refused_write(gateway, token, slot, "gw-bot-0000001")


@pytest.mark.asyncio
async def test_the_unverified_agent_cannot_write(gateway, cognito):  # noqa: F811
    token = tokens.sign_in(cognito, "shady-agent", "diner-bob")
    slot = await a_offer_id(gateway, token)
    assert await refused_write(gateway, token, slot, "gw-shady-000001")


@pytest.mark.asyncio
async def test_a_booking_confirmed_after_the_read_back_runs_through_the_gateway(gateway, cognito):  # noqa: F811
    token = tokens.sign_in(cognito, "alexa-plus-sim", "diner-alice")
    tag = datetime.now(UTC).strftime("%H%M%S")
    day = (datetime.now(UTC).date() + timedelta(days=4)).isoformat()
    slots = (await call(gateway, token, "availability_check", restaurant_id="luna-trattoria", date=day,
                        time_window="20:30-20:30", party_size=2)).structuredContent["slots"]
    held = await call(gateway, token, "reservation_hold", offer_id=slots[0]["offer_id"],
                      idempotency_key=f"gw-hold-{tag}")
    assert not held.isError, held.structuredContent
    assert held.structuredContent["read_back"] and held.structuredContent["read_back_token"]
    await asyncio.sleep(4)  # the diner listens and says yes; longer than the 3 s pause (real time on AWS)
    confirmed = await call(gateway, token, "reservation_confirm", hold_id=held.structuredContent["hold_id"],
                           idempotency_key=f"gw-conf-{tag}", read_back_token=held.structuredContent["read_back_token"],
                           user_confirmed=True)
    assert not confirmed.isError, confirmed.structuredContent
    cancelled = await call(gateway, token, "reservation_manage", action="cancel",
                           reservation_id=confirmed.structuredContent["reservation_id"],
                           idempotency_key=f"gw-cancel-{tag}")
    assert not cancelled.isError, cancelled.structuredContent
