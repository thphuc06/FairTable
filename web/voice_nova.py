"""The real voice session: Amazon Nova 2 Sonic through the Strands bidirectional agent (plan task P3-11, D-052).

Needs the optional ``voice`` extra (``pip install -e .[voice]``: ``strands-agents[bidi]``, Python 3.12) and AWS
credentials that may call Bedrock; nothing else imports this module. Verified against the installed
``strands-agents==1.57.1`` source and one real session on 2026-10-02 (docs/PLAN.md 3a-ter):
``BidiAgent(model=BedrockNovaSonicModel(...), tools=[...], system_prompt=...)``, ``await agent.send({"audio_delta":
{"format": "pcm", "source": {"bytes": ...}}})``, ``async for event in agent.receive()``.

The agent's tools are the seven FairTable tools, read from the MCP server (or the Gateway) with the diner's own
token; the model decides when to call them. It cannot book without the read-back and a yes: the server refuses.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from simulator.assistant import USER_TOKEN_HEADER
from web.voice_protocol import IN_RATE, OUT_RATE, to_client

log = logging.getLogger("fairtable.voice")

MODEL_ID = "amazon.nova-2-sonic-v1:0"  # the model card's ID; Bedrock runtime endpoint, in-region only
DEFAULT_VOICE = "matthew"
VOICE_PROMPT = (
    " You are speaking out loud on a voice call. Use short sentences. Say dates and times the way a person does. "
    "Never read out ids, codes or long numbers, except the booking code after a booking, one character at a time. "
    "When you list tables, name at most three times and offer to continue. "
    "If the user names a time, ask the availability tool for just that time (a window that starts and ends at that "
    "time), so that you hold the table they asked for. As soon as you know the restaurant, the day, the time and the "
    "party size, hold the table with the hold tool without asking first; then read the details back and ask whether "
    "to book it."
)
_END = object()


class NovaVoiceSession:
    def __init__(self, *, mcp_url: str, token: str, via_gateway: bool, prefix: str, system_prompt: str,
                 region: str | None = None, voice: str = DEFAULT_VOICE) -> None:
        self._mcp_url, self._token, self._via_gateway = mcp_url, token, via_gateway
        self._prefix, self._system_prompt = prefix, system_prompt + VOICE_PROMPT
        self._region, self._voice = region, voice
        self._agent: Any = None
        self._queue: asyncio.Queue = asyncio.Queue()
        self._pump: asyncio.Task | None = None
        self._seen_calls: set[str] = set()

    async def start(self) -> None:
        # imported here: the text-only install has neither the extra nor the audio libraries
        import boto3
        from strands.experimental.bidi.agent import BidiAgent
        from strands.experimental.bidi.models.bedrock import BedrockNovaSonicModel
        from strands.tools.mcp import MCPClient

        headers = ({"Authorization": f"Bearer {self._token}"} if self._via_gateway
                   else {USER_TOKEN_HEADER: self._token})
        session = boto3.Session(region_name=self._region) if self._region else boto3.Session()
        model = BedrockNovaSonicModel(
            boto_session=session, model_id=MODEL_ID, voice=self._voice,
            audio={"input": {"sample_rate": IN_RATE}, "output": {"sample_rate": OUT_RATE}},
        )
        self._agent = BidiAgent(model=model, tools=[MCPClient(url=self._mcp_url, headers=headers)],
                                system_prompt=self._system_prompt)
        await self._agent.start()
        self._pump = asyncio.create_task(self._read())

    async def _read(self) -> None:
        try:
            async for event in self._agent.receive():
                for message in to_client(event, self._prefix):
                    if message["type"] == "step" and message["phase"] == "call":
                        if message["id"] in self._seen_calls:
                            continue  # a streamed tool call arrives in pieces: show it once
                        self._seen_calls.add(message["id"])
                    await self._queue.put(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("the voice stream failed")
            await self._queue.put({"type": "error", "message": "The voice connection was lost."})
        finally:
            await self._queue.put(_END)

    async def send_audio(self, pcm: bytes) -> None:
        await self._agent.send({"audio_delta": {"format": "pcm", "source": {"bytes": pcm}}})

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            item = await self._queue.get()
            if item is _END:
                return
            yield item

    async def close(self) -> None:
        if self._pump is not None:
            self._pump.cancel()
            await asyncio.gather(self._pump, return_exceptions=True)
        if self._agent is not None:
            await self._agent.stop()
