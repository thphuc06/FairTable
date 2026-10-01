"""P2-10: settings for the route through the Gateway and for sign-in through Cognito."""

import pytest

from server.config import Settings


def test_by_default_the_pages_use_the_dev_issuer_and_talk_to_the_server_directly():
    s = Settings.from_env({})
    assert s.auth_provider == "dev" and s.mcp_via_gateway is False and s.mcp_tool_prefix == ""


def test_via_the_gateway_the_tools_get_the_target_prefix_by_default():
    s = Settings.from_env({"MCP_VIA_GATEWAY": "true"})
    assert s.mcp_via_gateway is True and s.mcp_tool_prefix == "ft___"


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes"])
def test_the_flag_accepts_the_usual_spellings(value):
    assert Settings.from_env({"MCP_VIA_GATEWAY": value}).mcp_via_gateway is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "maybe"])
def test_anything_else_leaves_the_direct_route(value):
    assert Settings.from_env({"MCP_VIA_GATEWAY": value}).mcp_via_gateway is False


def test_the_prefix_can_be_overridden_and_is_only_used_via_the_gateway():
    assert Settings.from_env({"MCP_VIA_GATEWAY": "true", "MCP_TOOL_PREFIX": "tools___"}).mcp_tool_prefix == "tools___"
    assert Settings.from_env({"MCP_TOOL_PREFIX": "tools___"}).mcp_tool_prefix == ""  # direct route: never prefixed


def test_cognito_is_chosen_with_auth_provider():
    s = Settings.from_env({"AUTH_PROVIDER": "cognito", "COGNITO_CLIENT_ID": "abc", "AWS_REGION": "us-east-1"})
    assert (s.auth_provider, s.cognito_client_id, s.cognito_region) == ("cognito", "abc", "us-east-1")


def test_an_unknown_provider_is_refused_at_start():
    with pytest.raises(ValueError, match="AUTH_PROVIDER"):
        Settings.from_env({"AUTH_PROVIDER": "okta"})


def test_cognito_needs_a_client_id():
    with pytest.raises(ValueError, match="COGNITO_CLIENT_ID"):
        Settings.from_env({"AUTH_PROVIDER": "cognito"})


def test_the_client_secret_is_not_part_of_the_settings():
    """It is read from the environment where the login is built, so settings can be logged without leaking it."""
    s = Settings.from_env({"AUTH_PROVIDER": "cognito", "COGNITO_CLIENT_ID": "abc", "COGNITO_CLIENT_SECRET": "hush"})
    assert "hush" not in repr(s)
