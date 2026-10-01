"""P2-6 on the real account: the Cedar policies G1-G4 at the Gateway (defence in depth, D-049).

Opt-in: ``pytest -m aws tests/aws/test_gateway_policy.py`` after
``GATEWAY_POLICY=LOG_ONLY cdk deploy FairTableGateway`` (decisions are only logged: the tests that need a refusal
skip) and again after ``GATEWAY_POLICY=ENFORCE``. The shape of a refusal at the Gateway is not documented; these
tests accept either a JSON-RPC error or a tool result with ``isError`` and print what they saw, so the first run
settles it (record the answer in PLAN section 3a-bis).
"""

import boto3
import pytest
from botocore.exceptions import ClientError
from fastmcp.exceptions import McpError
from test_gateway import PREFIX, TOOLS, client_for, gateway  # noqa: F401  (a fixture: the gateway's url and id)
from test_runtime_smoke import cognito  # noqa: F401

import test_tokens as tokens

pytestmark = pytest.mark.aws
READS = {"restaurant_search", "availability_check", "mandate_status", "waitlist_status"}
WRITES = TOOLS - READS


@pytest.fixture(scope="module")
def mode(gateway):  # noqa: F811
    try:
        config = boto3.client("bedrock-agentcore-control").get_gateway(gatewayIdentifier=gateway["id"])
    except ClientError as e:
        pytest.skip(f"the gateway cannot be read: {e}")
    engine = config.get("policyEngineConfiguration")
    if not engine:
        pytest.skip("the gateway has no policy engine (deploy with GATEWAY_POLICY=LOG_ONLY or ENFORCE)")
    return engine["mode"]


@pytest.fixture
def enforcing(mode):
    if mode != "ENFORCE":
        pytest.skip(f"the engine is attached in {mode} mode: nothing is refused yet")


async def listed(gateway, token):  # noqa: F811
    async with client_for(gateway, token) as c:
        return {t.name.removeprefix(PREFIX) for t in await c.list_tools()}


async def refused(gateway, token, tool, **args):  # noqa: F811
    """True when the call did not reach the tool; prints how the refusal looked."""
    try:
        async with client_for(gateway, token) as c:
            result = await c.call_tool_mcp(PREFIX + tool, args)
    except McpError as e:
        print(f"{tool}: JSON-RPC error {e}")
        return True
    print(f"{tool}: isError={result.isError} {result.content}")
    return bool(result.isError)


@pytest.mark.asyncio
async def test_a_verified_agents_user_still_sees_every_tool_and_can_book(gateway, cognito, mode):  # noqa: F811
    token = tokens.sign_in(cognito, "alexa-plus-sim", "diner-alice")
    assert await listed(gateway, token) == TOOLS
    async with client_for(gateway, token) as c:
        result = await c.call_tool_mcp(PREFIX + "restaurant_search", {})
    assert not result.isError


@pytest.mark.asyncio
async def test_the_bot_sees_only_the_reads(gateway, cognito, enforcing):  # noqa: F811
    assert await listed(gateway, tokens.machine_token(cognito, "bot-m2m")) == READS


@pytest.mark.asyncio
async def test_the_unverified_agent_sees_only_the_reads(gateway, cognito, enforcing):  # noqa: F811
    assert await listed(gateway, tokens.sign_in(cognito, "shady-agent", "diner-bob")) == READS


@pytest.mark.asyncio
async def test_a_write_by_the_unverified_agent_is_refused_at_the_gateway(gateway, cognito, enforcing):  # noqa: F811
    token = tokens.sign_in(cognito, "shady-agent", "diner-bob")
    assert await refused(gateway, token, "reservation_hold", slot_token="x", idempotency_key="gw-policy-00001")


@pytest.mark.asyncio
async def test_a_party_of_eleven_is_refused_at_the_gateway(gateway, cognito, enforcing):  # noqa: F811
    token = tokens.sign_in(cognito, "alexa-plus-sim", "diner-alice")
    assert await refused(gateway, token, "availability_check", restaurant_id="luna-trattoria",
                         date="2026-12-01", party_size=11)
