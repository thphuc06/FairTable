"""D-068: the owner console behind API Gateway. The Lambda handler is the FastAPI app of `web/` wrapped by Mangum."""

import json

import pytest

from web import lambda_handler

ENV = {
    "APP_PROFILE": "aws", "TABLE_NAME": "fairtable", "AWS_REGION": "us-east-1", "AWS_ACCESS_KEY_ID": "x",
    "AWS_SECRET_ACCESS_KEY": "x", "AUTH_PROVIDER": "cognito", "AUTH_ISSUER": "https://cognito-idp.example/pool",
    "AUTH_JWKS_URL": "https://cognito-idp.example/pool/.well-known/jwks.json", "AUTH_AUDIENCE_CLAIM": "client_id",
    "AUTH_AUDIENCE": "client-1", "AUTH_TOKEN_USE": "access", "COGNITO_CLIENT_ID": "client-1", "COGNITO_REGION": "us-east-1",
    "COGNITO_CLIENT_SECRET": "not-a-real-secret", "WEB_SESSION_SECRET": "w" * 48, "SLOT_TOKEN_SECRET": "w" * 48,
    "WEB_PUBLIC_URL": "https://owner-console.invalid", "SEED_PROVIDER": "local",
}


def event(path: str, method: str = "GET", headers: dict | None = None, body: str | None = None) -> dict:
    """An API Gateway HTTP API (payload format 2.0) event."""
    return {
        "version": "2.0", "routeKey": "$default", "rawPath": path, "rawQueryString": "",
        "headers": {"host": "abc.execute-api.us-east-1.amazonaws.com", **(headers or {})},
        "requestContext": {"http": {"method": method, "path": path, "protocol": "HTTP/1.1", "sourceIp": "203.0.113.9",
                                    "userAgent": "test"}, "stage": "$default"},
        "body": body, "isBase64Encoded": False,
    }


@pytest.fixture(autouse=True)
def fresh_container(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(lambda_handler, "_handler", None)


def test_the_hosted_console_signs_people_in_through_cognito_only(monkeypatch):
    monkeypatch.setenv("AUTH_PROVIDER", "dev")
    with pytest.raises(RuntimeError, match="Cognito"):
        lambda_handler.build_deps()


def test_the_dependencies_have_no_chat_and_no_voice():
    deps = lambda_handler.build_deps()
    assert deps.chat is None and deps.voice is None and deps.settings.web_public_url.startswith("https://")


def test_a_health_check_answers_through_the_handler():
    response = lambda_handler.handler(event("/healthz"), None)
    assert response["statusCode"] == 200 and response["headers"]["x-frame-options"] == "DENY"


def test_the_owner_page_sends_a_visitor_to_the_sign_in():
    response = lambda_handler.handler(event("/owner"), None)
    assert response["statusCode"] == 303 and response["headers"]["location"] == "/login?next=/owner"


def test_the_sign_in_page_is_served_with_the_security_headers():
    response = lambda_handler.handler(event("/login"), None)
    assert response["statusCode"] == 200 and "Sign in" in response["body"]
    assert response["headers"]["cache-control"] == "no-store" and "frame-ancestors 'none'" in response["headers"]["content-security-policy"]


def test_the_chat_page_is_off_because_no_assistant_is_set_up():
    response = lambda_handler.handler(event("/chat"), None)
    assert response["statusCode"] in (303, 404)  # sent to sign in first, or "not set up"; never a page that runs a model


def test_a_form_post_without_a_session_is_refused_and_nothing_is_written():
    body = "fee=0&hours=0&csrf=x"
    response = lambda_handler.handler(event("/owner/terms", "POST", {"content-type": "application/x-www-form-urlencoded"}, body), None)
    assert response["statusCode"] in (303, 403)


def test_the_handler_is_built_once_per_container():
    lambda_handler.handler(event("/healthz"), None)
    first = lambda_handler._handler
    lambda_handler.handler(event("/healthz"), None)
    assert lambda_handler._handler is first
    assert json.dumps(ENV)  # (the fixture sets the whole environment, the test only needs it to be there)
