"""AUTH_AUDIENCE may list several Cognito app clients; AUTH_TOKEN_USE turns on the token_use check."""

from server.config import Settings
from server.identity import VerifierConfig


def test_a_list_of_clients_is_split_and_trimmed():
    s = Settings.from_env({"AUTH_AUDIENCE": " a1 , b2,c3 ", "AUTH_AUDIENCE_CLAIM": "client_id"})
    assert s.audience == ("a1", "b2", "c3")


def test_one_audience_and_the_default_stay_single_values():
    assert Settings.from_env({"AUTH_AUDIENCE": "only"}).audience == ("only",)
    assert Settings.from_env({}).audience == ("fairtable-mcp",)


def test_token_use_is_off_unless_set():
    assert Settings.from_env({}).token_use is None
    assert Settings.from_env({"AUTH_TOKEN_USE": "access"}).token_use == "access"


def test_the_verifier_config_accepts_what_settings_produce():
    s = Settings.from_env({"AUTH_AUDIENCE": "a,b", "AUTH_AUDIENCE_CLAIM": "client_id", "AUTH_TOKEN_USE": "access"})
    cfg = VerifierConfig(s.issuer, s.audience, s.audience_claim, token_use=s.token_use)
    assert cfg.allowed_audiences == ("a", "b") and cfg.token_use == "access"
