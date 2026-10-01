"""P2-5: the Gateway REQUEST interceptor. It copies the caller's verified bearer token into `x-ft-user-token`
and makes sure that nothing the client put in that header can reach the server."""

import importlib.util
import json
import logging
from pathlib import Path

import pytest

HANDLER = Path(__file__).resolve().parents[3] / "infra" / "gateway" / "interceptor" / "handler.py"
spec = importlib.util.spec_from_file_location("gateway_interceptor_handler", HANDLER)
handler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handler)

TOKEN = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1In0.c2lnbmF0dXJl"
BODY = {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "ft___restaurant_search", "arguments": {}}}


def event(headers, body=BODY):
    request = {"path": "/mcp", "httpMethod": "POST", "body": body}
    if headers is not None:
        request["headers"] = headers
    return {"interceptorInputVersion": "1.0", "mcp": {"rawGatewayRequest": {"body": json.dumps(body)}, "gatewayRequest": request}}


def forwarded(result):
    return result["mcp"]["transformedGatewayRequest"]


def test_the_bearer_token_becomes_x_ft_user_token_and_the_body_is_unchanged():
    result = handler.lambda_handler(event({"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}))
    assert result["interceptorOutputVersion"] == "1.0"
    assert forwarded(result)["headers"] == {"x-ft-user-token": TOKEN}
    assert forwarded(result)["body"] == BODY
    assert "transformedGatewayResponse" not in result["mcp"]


def test_no_header_but_ours_is_forwarded_and_authorization_is_never_sent_on():
    """`Authorization` from an interceptor would be forwarded to the target and clash with the gateway's own SigV4."""
    result = handler.lambda_handler(event({"Authorization": f"Bearer {TOKEN}", "User-Agent": "x", "Mcp-Session-Id": "s"}))
    assert set(forwarded(result)["headers"]) == {"x-ft-user-token"}


@pytest.mark.parametrize("name", ["x-ft-user-token", "X-FT-User-Token", "X-Ft-User-Token"])
def test_a_forged_header_is_replaced_by_the_verified_token(name):
    result = handler.lambda_handler(event({"Authorization": f"Bearer {TOKEN}", name: "forged-token-of-another-user"}))
    assert forwarded(result)["headers"] == {"x-ft-user-token": TOKEN}
    assert "forged" not in json.dumps(result)


@pytest.mark.parametrize("auth", ["authorization", "AUTHORIZATION", "Authorization"])
def test_the_authorization_header_name_is_case_insensitive(auth):
    result = handler.lambda_handler(event({auth: f"Bearer {TOKEN}"}))
    assert forwarded(result)["headers"]["x-ft-user-token"] == TOKEN


@pytest.mark.parametrize("scheme", ["Bearer", "bearer", "BEARER"])
def test_the_bearer_scheme_is_case_insensitive(scheme):
    result = handler.lambda_handler(event({"Authorization": f"{scheme}   {TOKEN}"}))
    assert forwarded(result)["headers"]["x-ft-user-token"] == TOKEN


@pytest.mark.parametrize("headers", [
    None,  # headers not passed to the interceptor at all
    {},
    {"Accept": "application/json"},
    {"Authorization": ""},
    {"Authorization": "Bearer"},
    {"Authorization": "Bearer "},
    {"Authorization": "Basic dXNlcjpwYXNz"},
    {"Authorization": TOKEN},  # no scheme
    {"Authorization": "Bearer " + "a" * 9000},  # longer than the server accepts
    {"x-ft-user-token": TOKEN},  # a client-supplied header alone is never enough
])
def test_without_a_usable_bearer_token_the_gateway_answers_401_and_nothing_goes_to_the_server(headers):
    result = handler.lambda_handler(event(headers))
    response = result["mcp"]["transformedGatewayResponse"]
    assert response["statusCode"] == 401
    assert response["body"]["jsonrpc"] == "2.0" and response["body"]["id"] == 7
    assert response["body"]["error"]["code"] == -32001
    assert "transformedGatewayRequest" not in result["mcp"]  # fail closed: the request is not forwarded


def test_a_401_does_not_echo_the_header_or_token():
    result = handler.lambda_handler(event({"Authorization": "Basic c2VjcmV0", "x-ft-user-token": "forged"}))
    text = json.dumps(result)
    assert "c2VjcmV0" not in text and "forged" not in text


def test_the_error_keeps_a_missing_request_id_missing():
    result = handler.lambda_handler(event({}, body={"jsonrpc": "2.0", "method": "notifications/initialized"}))
    assert result["mcp"]["transformedGatewayResponse"]["body"]["id"] is None


def test_the_token_is_never_written_to_the_log(caplog):
    with caplog.at_level(logging.DEBUG):
        handler.lambda_handler(event({"Authorization": f"Bearer {TOKEN}"}))
        handler.lambda_handler(event({"Authorization": "Bearer " + TOKEN + "x", "x-ft-user-token": "forged-1"}))
        handler.lambda_handler(event({"Authorization": "Basic c2VjcmV0"}))
    text = " ".join(caplog.messages)
    assert TOKEN not in text and "forged-1" not in text and "c2VjcmV0" not in text


def test_the_function_uses_only_the_standard_library():
    source = HANDLER.read_text()
    assert "import boto3" not in source and "import requests" not in source
