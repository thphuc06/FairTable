"""P2-10 on the real account: the whole demo path of the AWS profile.

A person signs in to the web pages through Cognito, chats with the simulated assistant, whose requests go to the
AgentCore Gateway with a bearer token and on to the MCP server on Runtime and DynamoDB; when a booking needs the
person's approval, they approve it on the consent page (the same sign-in), tell the assistant, and it finishes.

Opt-in: ``pytest -m aws tests/aws/test_demo_flow.py`` after ``cdk deploy FairTableGateway`` and ``seed``. The web
pages run in-process here (in a browser they are ``python -m web`` with the same settings); every call to Cognito,
the Gateway, the Runtime and DynamoDB is real. Bookings made here are cancelled again.
"""

import re
import uuid
from datetime import UTC, datetime, timedelta

import boto3
import pytest
from fastapi.testclient import TestClient
from test_gateway import call, gateway  # noqa: F401  (a fixture and a helper: the Gateway URL, a tool call through it)
from test_runtime_smoke import cognito  # noqa: F401  (a fixture: the pool, its clients and their secrets)

import test_tokens as tokens
from devauth.accounts import USERS_BY_NAME
from server.config import Settings
from server.domain.clock import SystemClock
from server.identity import HttpJwks, TokenVerifier, VerifierConfig
from server.store import Store, make_client
from simulator.model import ScriptedModel
from web.app import WebDeps, create_app
from web.auth import CognitoLogin, cognito_client
from web.chat import ChatService
from web.session import SessionCodec

pytestmark = pytest.mark.aws
PREFIX = "ft___"


@pytest.fixture(scope="module")
def web(gateway, cognito):  # noqa: F811
    import httpx

    out = cognito["out"]
    client_ids = [c["id"] for c in cognito["clients"].values()]
    alexa = cognito["clients"]["alexa-plus-sim"]
    region = boto3.Session().region_name or "us-east-1"
    settings = Settings.from_env({
        "AUTH_ISSUER": out["Issuer"], "AUTH_AUDIENCE": ",".join(client_ids), "AUTH_AUDIENCE_CLAIM": "client_id",
        "AUTH_TOKEN_USE": "access", "AUTH_PROVIDER": "cognito", "COGNITO_CLIENT_ID": alexa["id"], "AWS_REGION": region,
        "MCP_URL": gateway["url"], "MCP_VIA_GATEWAY": "true", "TABLE_NAME": "fairtable",
    })
    clock = SystemClock()
    verifier = TokenVerifier(
        VerifierConfig(settings.issuer, settings.audience, settings.audience_claim, token_use=settings.token_use),
        HttpJwks(settings.jwks_url, clock, client=httpx.Client(timeout=30)), clock,
    )
    chat = ChatService(settings.mcp_url, lambda: ScriptedModel(today=datetime.now(UTC).date(), tool_prefix=PREFIX), clock,
                       via_gateway=True, tool_prefix=PREFIX)
    store = Store(make_client(settings.store), settings.store.table_name)
    deps = WebDeps(
        settings=settings, store=store, clock=clock,
        login=CognitoLogin(cognito_client(region), alexa["id"], verifier, client_secret=alexa["secret"]),
        sessions=SessionCodec(settings.web_session_secret, clock), new_id=lambda: uuid.uuid4().hex, chat=chat,
    )
    yield {"deps": deps, "store": store}
    chat.close()


def browser(web) -> TestClient:
    return TestClient(create_app(web["deps"]), follow_redirects=False)


def sign_in(client: TestClient, who: str, next_path: str = "/chat") -> None:
    user = USERS_BY_NAME[who]
    r = client.post("/login", data={"username": who, "password": user.password, "next": next_path})
    assert r.status_code == 303 and r.headers["location"] == next_path, "Cognito sign-in failed"


def csrf_of(html: str) -> str:
    return re.search(r"name='csrf' value='([^']+)'", html).group(1)


def say(client: TestClient, text: str) -> str:
    csrf = csrf_of(client.get("/chat").text)
    r = client.post("/chat", data={"message": text, "csrf": csrf})
    assert r.status_code == 303 and r.headers["location"] == "/chat"
    return client.get("/chat").text


def day(offset: int) -> str:
    return (datetime.now(UTC).date() + timedelta(days=offset)).isoformat()


def sub_of(cognito, who: str) -> str:  # noqa: F811
    import base64
    import json

    token = tokens.sign_in(cognito, "alexa-plus-sim", who)
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["sub"]


async def cancel_all(web, gateway, cognito, who: str) -> None:  # noqa: F811
    """Leave the demo table as found: cancel what the test booked (Luna's cancellation is free)."""
    token = tokens.sign_in(cognito, "alexa-plus-sim", who)
    for reservation in web["store"].reservations_of_user(sub_of(cognito, who)):
        if reservation.status == "confirmed":
            await call(gateway, token, "reservation_manage", action="cancel", reservation_id=reservation.reservation_id,
                       idempotency_key=f"demo-cancel-{reservation.reservation_id}"[:60])


@pytest.mark.asyncio
async def test_a_diner_signs_in_with_cognito_and_books_by_chatting_through_the_gateway(web, gateway, cognito):  # noqa: F811
    client = browser(web)
    try:
        sign_in(client, "diner-alice")
        html = say(client, f"Book a table at Luna Trattoria for 2 on {day(9)} at 7pm")
        assert "Assistant:" in html and "booked" in html.lower()
        assert "restaurant_search" in html and "ft___" not in html  # the steps list shows the server's own names
        assert len(web["store"].reservations_of_user(sub_of(cognito, "diner-alice"))) >= 1
    finally:
        await cancel_all(web, gateway, cognito, "diner-alice")


@pytest.mark.asyncio
async def test_a_booking_outside_the_permission_is_approved_on_the_consent_page_with_the_same_sign_in(web, gateway, cognito):  # noqa: F811
    client = browser(web)
    try:
        sign_in(client, "diner-bob")
        html = say(client, f"Book a table at Luna Trattoria for 2 on {day(10)} at 7pm")
        link = re.search(r"href='(http://localhost:8080(/consent/[A-Za-z0-9_-]+))'", html)
        assert link, "the assistant should hand over an approval link (step-up through the Gateway)"
        page = client.get(link.group(2))
        assert page.status_code == 200 and "Approve" in page.text
        decision = client.post(f"{link.group(2)}/decision", data={"decision": "approve", "csrf": csrf_of(page.text)})
        assert decision.status_code == 303
        html = say(client, "I approved it")
        assert "booked" in html.lower()
    finally:
        await cancel_all(web, gateway, cognito, "diner-bob")


def test_a_wrong_password_does_not_sign_in(web):
    client = browser(web)
    r = client.post("/login", data={"username": "diner-alice", "password": "not-the-password", "next": "/chat"})
    assert r.status_code != 303 or "location" not in r.headers or r.headers["location"] != "/chat"
    assert client.get("/chat").status_code == 303  # still signed out


def test_the_owner_console_works_with_a_cognito_owner_token(web):
    client = browser(web)
    sign_in(client, "owner-luna", next_path="/owner")
    page = client.get("/owner")
    assert page.status_code == 200 and "Luna" in page.text
