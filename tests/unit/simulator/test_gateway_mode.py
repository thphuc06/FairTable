"""P2-10: the simulated assistant through the AgentCore Gateway.

Through the Gateway the token is a bearer token (the interceptor makes `x-ft-user-token` of it) and every tool
is called `<target>___<tool>`. The personas, the steps list and the graders keep working with the bare names."""

import json

import pytest

from simulator import assistant as assistant_module
from simulator.events import Step, UserSaid, transcript
from simulator.model import ScriptedModel, build_model

PREFIX = "ft___"


def messages(*tool_calls, user="book a table at Luna Trattoria for 2 on 2026-10-05 at 7pm"):
    out = [{"role": "user", "content": [{"text": user}]}]
    for i, (name, args, result) in enumerate(tool_calls):
        out.append({"role": "assistant", "content": [{"toolUse": {"toolUseId": f"t{i}", "name": name, "input": args}}]})
        out.append({"role": "user", "content": [{"toolResult": {"toolUseId": f"t{i}", "status": "success",
                                                              "content": [{"json": result}]}}]})
    return out


async def first_tool_name(model, history):
    names = []
    async for event in model.stream(history):
        start = event.get("contentBlockStart", {}).get("start", {})
        if "toolUse" in start:
            names.append(start["toolUse"]["name"])
    return names


def test_the_prefix_is_stripped_from_steps_so_personas_and_graders_see_bare_names():
    history = messages((PREFIX + "restaurant_search", {"query": "luna"}, {"restaurants": []}))
    steps = [e for e in transcript(history, PREFIX) if isinstance(e, Step)]
    assert [s.tool for s in steps] == ["restaurant_search"]


def test_without_a_prefix_nothing_changes():
    history = messages(("restaurant_search", {"query": "luna"}, {"restaurants": []}))
    assert [e.tool for e in transcript(history) if isinstance(e, Step)] == ["restaurant_search"]
    assert [e.tool for e in transcript(history, "") if isinstance(e, Step)] == ["restaurant_search"]


def test_a_name_that_does_not_carry_the_prefix_is_left_alone():
    history = messages(("restaurant_search", {}, {"restaurants": []}))
    assert [e.tool for e in transcript(history, PREFIX) if isinstance(e, Step)] == ["restaurant_search"]


def test_user_messages_still_become_events():
    assert [e.text for e in transcript(messages(), PREFIX) if isinstance(e, UserSaid)] == [
        "book a table at Luna Trattoria for 2 on 2026-10-05 at 7pm"]


@pytest.mark.asyncio
async def test_the_scripted_model_calls_prefixed_tools_and_still_reads_prefixed_history():
    model = ScriptedModel(today=__import__("datetime").date(2026, 10, 1), tool_prefix=PREFIX)
    assert await first_tool_name(model, messages()) == [PREFIX + "restaurant_search"]
    after_search = messages((PREFIX + "restaurant_search", {"query": "Luna Trattoria", "date": "2026-10-05", "party_size": 2},
                             {"restaurants": [{"restaurant_id": "luna-trattoria", "name": "Luna Trattoria"}]}))
    assert await first_tool_name(model, after_search) == [PREFIX + "availability_check"]


@pytest.mark.asyncio
async def test_without_a_prefix_the_scripted_model_is_unchanged():
    model = ScriptedModel(today=__import__("datetime").date(2026, 10, 1))
    assert await first_tool_name(model, messages()) == ["restaurant_search"]


def test_build_model_passes_the_prefix_on():
    model = build_model("mock", tool_prefix=PREFIX)
    assert model._tool_prefix == PREFIX


class FakeMCPClient:
    created: list = []

    def __init__(self, url, headers=None, **_):
        self.url, self.headers = url, headers
        FakeMCPClient.created.append(self)


@pytest.mark.parametrize("via_gateway,expected", [
    (False, {"x-ft-user-token": "tok"}),
    (True, {"Authorization": "Bearer tok"}),
])
def test_the_token_goes_where_the_route_expects_it(monkeypatch, via_gateway, expected):
    monkeypatch.setattr(assistant_module, "MCPClient", FakeMCPClient)
    FakeMCPClient.created.clear()
    assistant_module.Assistant("http://x/mcp", "tok", ScriptedModel(), via_gateway=via_gateway)
    assert FakeMCPClient.created[0].headers == expected


def test_the_default_route_is_the_server_itself():
    import inspect

    sig = inspect.signature(assistant_module.Assistant.__init__)
    assert sig.parameters["via_gateway"].default is False and sig.parameters["tool_prefix"].default == ""


def test_the_reply_steps_use_bare_names_whatever_the_route(monkeypatch):
    """The `steps` list of the chat page and the eval graders compare bare tool names."""
    history = messages((PREFIX + "availability_check", {"restaurant_id": "luna"}, {"slots": []}))
    steps = [e for e in transcript(history, PREFIX) if isinstance(e, Step)]
    assert json.dumps([s.tool for s in steps]) == '["availability_check"]'
