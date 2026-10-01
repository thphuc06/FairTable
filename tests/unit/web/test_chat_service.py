"""The chat service answers one message at a time per diner; a second Send while one is being answered
(a double click, or pressing again because a real model is slow) is dropped instead of queued."""

import asyncio
from types import SimpleNamespace
from typing import ClassVar

import pytest

from server.domain.clock import FakeClock
from web import chat


class SlowAssistant:
    """Stands in for simulator.Assistant: answers after a short delay and counts the questions it got."""

    asked: ClassVar[list[str]] = []
    built: ClassVar[list[dict]] = []

    def __init__(self, url, token, model, system_prompt, via_gateway=False, tool_prefix=""):
        self.system_prompt = system_prompt
        SlowAssistant.built.append({"url": url, "token": token, "via_gateway": via_gateway, "tool_prefix": tool_prefix})

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    async def say(self, text):
        SlowAssistant.asked.append(text)
        await asyncio.sleep(0.2)
        return SimpleNamespace(text=f"answer to {text}", steps=[])


@pytest.fixture
def service(monkeypatch):
    SlowAssistant.asked = []
    SlowAssistant.built = []
    monkeypatch.setattr(chat, "Assistant", SlowAssistant)
    s = chat.ChatService("http://unused/mcp", lambda: None, FakeClock())
    s.remember("alice", "token", 3600)
    return s


async def test_a_double_press_of_send_is_answered_once(service):
    await asyncio.gather(service.send("alice", "hi"), service.send("alice", "hi"))
    turns = [(t.who, t.text) for t in service.transcript("alice")]
    assert turns == [("you", "hi"), ("assistant", "answer to hi")]
    assert SlowAssistant.asked == ["hi"]


async def test_a_message_sent_after_the_answer_is_a_new_message(service):
    await service.send("alice", "hi")
    await service.send("alice", "hi")
    assert SlowAssistant.asked == ["hi", "hi"]
    assert [t.who for t in service.transcript("alice")] == ["you", "assistant", "you", "assistant"]


async def test_two_diners_are_answered_at_the_same_time(service):
    service.remember("bob", "token", 3600)
    await asyncio.gather(service.send("alice", "one"), service.send("bob", "two"))
    assert sorted(SlowAssistant.asked) == ["one", "two"]


async def test_the_prompt_carries_the_date(service):
    assert "Today is" in service.system_prompt()


async def test_the_route_through_the_gateway_reaches_the_assistant(monkeypatch):
    SlowAssistant.asked, SlowAssistant.built = [], []
    monkeypatch.setattr(chat, "Assistant", SlowAssistant)
    gateway = chat.ChatService("https://gw.example/mcp", lambda: None, FakeClock(), via_gateway=True, tool_prefix="ft___")
    gateway.remember("alice", "tok", 3600)
    await gateway.send("alice", "hi")
    assert SlowAssistant.built == [{"url": "https://gw.example/mcp", "token": "tok", "via_gateway": True, "tool_prefix": "ft___"}]


async def test_the_default_route_is_direct(service):
    await service.send("alice", "hi")
    assert SlowAssistant.built[0]["via_gateway"] is False and SlowAssistant.built[0]["tool_prefix"] == ""
