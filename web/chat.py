"""Server side of the chat page: one simulated assistant per signed-in diner.

The assistant is the same ``simulator.Assistant`` the eval harness uses, connected to the MCP server
with the diner's own access token. Tokens live only in this process's memory (never in the cookie or
the page); after a restart or an expired token the diner signs in again.

Everything here is for the local demo: with ``MODEL_PROVIDER=mock`` (the default) the "assistant"
follows a script, and no model account is needed.
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from strands.models import Model

from server.domain.clock import Clock, epoch_seconds
from simulator.assistant import SYSTEM_PROMPT, Assistant
from simulator.events import Step

log = logging.getLogger("fairtable.chat")

MAX_MESSAGE_CHARS = 500
MAX_TURNS = 60
UNREACHABLE = "I cannot reach the booking service right now. Please try again in a moment."
SIGNED_OUT = "Your sign-in has expired. Please sign in again."


@dataclass(frozen=True)
class Turn:
    who: str  # "you" | "assistant"
    text: str
    steps: tuple[Step, ...] = ()  # the tool calls behind an assistant answer, in order


@dataclass
class _Conversation:
    token: str
    expires_at: int
    turns: list[Turn] = field(default_factory=list)
    assistant: Assistant | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class ChatService:
    def __init__(self, mcp_url: str, make_model: Callable[[], Model], clock: Clock, *,
                 via_gateway: bool = False, tool_prefix: str = "") -> None:
        self._via_gateway = via_gateway
        self._tool_prefix = tool_prefix
        self._mcp_url = mcp_url
        self._make_model = make_model
        self._clock = clock
        self._conversations: dict[str, _Conversation] = {}

    def system_prompt(self) -> str:
        """The assistant's instructions plus today's date: a model cannot resolve "tomorrow" without it."""
        now = self._clock.now()
        return f"{SYSTEM_PROMPT} Today is {now:%A, %Y-%m-%d} (UTC). Dates you give to tools are YYYY-MM-DD."

    def remember(self, sub: str, token: str, expires_in_s: int) -> None:
        """Called at sign-in: a fresh token means a fresh conversation."""
        self._close(sub)
        self._conversations[sub] = _Conversation(token, epoch_seconds(self._clock) + expires_in_s)

    def is_signed_in(self, sub: str) -> bool:
        c = self._conversations.get(sub)
        return c is not None and c.expires_at > epoch_seconds(self._clock)

    def transcript(self, sub: str) -> list[Turn]:
        c = self._conversations.get(sub)
        return list(c.turns) if c else []

    def reset(self, sub: str) -> None:
        c = self._conversations.get(sub)
        if c is not None:
            self._close_assistant(c)
            c.turns.clear()

    def _close_assistant(self, c: _Conversation) -> None:
        if c.assistant is not None:
            try:
                c.assistant.__exit__(None, None, None)
            except Exception:
                log.exception("could not close the assistant")
            c.assistant = None

    def _close(self, sub: str) -> None:
        old = self._conversations.pop(sub, None)
        if old is not None:
            self._close_assistant(old)

    def close(self) -> None:
        for sub in list(self._conversations):
            self._close(sub)

    async def send(self, sub: str, text: str) -> None:
        """Add the diner's message and the assistant's answer to their transcript."""
        c = self._conversations.get(sub)
        text = text.strip()[:MAX_MESSAGE_CHARS]
        if c is None or not text:
            return
        if c.lock.locked():
            return  # the previous message is still being answered: a second press of Send is dropped, not queued
        async with c.lock:
            c.turns.append(Turn("you", text))
            if c.expires_at <= epoch_seconds(self._clock):
                c.turns.append(Turn("assistant", SIGNED_OUT))
                return
            try:
                if c.assistant is None:
                    assistant = Assistant(self._mcp_url, c.token, self._make_model(), self.system_prompt(),
                                          via_gateway=self._via_gateway, tool_prefix=self._tool_prefix)
                    await asyncio.to_thread(assistant.__enter__)  # blocks while it connects
                    c.assistant = assistant
                reply = await c.assistant.say(text)
                c.turns.append(Turn("assistant", reply.text or "Sorry, I have no answer for that.", tuple(reply.steps)))
            except Exception:
                log.exception("the assistant failed")
                self._close_assistant(c)
                c.turns.append(Turn("assistant", UNREACHABLE))
            del c.turns[:-MAX_TURNS]
