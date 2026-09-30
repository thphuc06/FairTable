"""P1-18: the scripted model speaks Strands' stream protocol; the provider factory fails clearly."""

import json

import pytest

from simulator.model import HELP, ProviderError, ScriptedModel, build_model
from simulator.personas import Goal


async def events_of(model, messages):
    return [e async for e in model.stream(messages)]


async def test_a_tool_call_is_streamed_as_a_tool_use_block():
    model = ScriptedModel(Goal(kind="book", date="2026-10-05", restaurant="luna"))
    events = await events_of(model, [{"role": "user", "content": [{"text": "book"}]}])
    start = next(e for e in events if "contentBlockStart" in e)["contentBlockStart"]["start"]["toolUse"]
    delta = next(e for e in events if "contentBlockDelta" in e)["contentBlockDelta"]["delta"]["toolUse"]["input"]
    assert start["name"] == "restaurant_search" and start["toolUseId"]
    assert json.loads(delta)["party_size"] == 2
    assert next(e for e in events if "messageStop" in e)["messageStop"]["stopReason"] == "tool_use"


async def test_tool_use_ids_do_not_repeat_within_a_conversation():
    model = ScriptedModel(Goal(kind="book", date="2026-10-05", restaurant="luna"))
    first = await events_of(model, [{"role": "user", "content": [{"text": "book"}]}])
    used = [{"role": "user", "content": [{"text": "book"}]},
            {"role": "assistant", "content": [{"toolUse": {"toolUseId": "sim-call-1", "name": "restaurant_search",
                                                            "input": {}}}]},
            {"role": "user", "content": [{"toolResult": {"toolUseId": "sim-call-1", "status": "success",
                                                          "content": [{"text": '{"restaurants": []}'}]}}]}]
    second = await events_of(model, used)
    ids = [next(e for e in ev if "contentBlockStart" in e)["contentBlockStart"]["start"].get("toolUse", {}).get("toolUseId")
           for ev in (first, second)]
    assert ids[0] != ids[1]


async def test_without_a_goal_the_model_reads_the_diner_or_explains():
    model = ScriptedModel()
    events = await events_of(model, [{"role": "user", "content": [{"text": "hello"}]}])
    text = next(e for e in events if "contentBlockDelta" in e)["contentBlockDelta"]["delta"]["text"]
    assert text == HELP
    assert next(e for e in events if "messageStop" in e)["messageStop"]["stopReason"] == "end_turn"


def test_mock_is_the_default_provider():
    assert isinstance(build_model(env={}), ScriptedModel)
    assert isinstance(build_model("MOCK", env={"MODEL_PROVIDER": "bedrock"}), ScriptedModel)


def test_unknown_or_unconfigured_providers_fail_with_a_clear_message():
    with pytest.raises(ProviderError, match="Unknown MODEL_PROVIDER"):
        build_model("gpt-nine", env={})
    with pytest.raises(ProviderError, match="BEDROCK_MODEL_ID"):
        build_model("bedrock", env={})
    with pytest.raises(ProviderError, match="DEEPSEEK_API"):
        build_model("deepseek", env={})


def test_the_key_never_appears_in_errors_or_in_the_model_config():
    """With the optional package missing the error names the package; with it installed the model is
    built (no network call) and its config carries the model id, not the key."""
    try:
        model = build_model("deepseek", env={"DEEPSEEK_API": "sk-secret-value"})
    except ProviderError as e:
        assert "sk-secret-value" not in str(e)
        return
    assert "sk-secret-value" not in str(model.get_config())
    assert model.get_config()["model_id"] == "deepseek-flash"


def test_deepseek_defaults_are_the_documented_flash_model():
    from simulator import model

    assert model.DEEPSEEK_BASE_URL == "https://api.deepseek.com" and model.DEEPSEEK_MODEL == "deepseek-flash"
