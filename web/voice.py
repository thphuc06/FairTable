"""Server side of the voice page (plan task P3-11, decision D-052): one WebSocket per call.

The page sends the microphone as PCM frames; the server hands them to a *voice session* (Amazon Nova 2 Sonic through
the Strands bidirectional agent, see ``web/voice_nova.py``) and sends back what the session produces: the assistant's
voice, the transcript and the tool calls behind it. The session talks to the MCP server with the diner's own access
token, exactly like the text chat, so every rule of the server applies unchanged.

``VoiceSession`` is the seam: tests use a fake one; nothing here needs AWS, a microphone or the ``voice`` extra.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any, Protocol

from fastapi import WebSocket, WebSocketDisconnect

from web.voice_protocol import IN_RATE, OUT_RATE, audio_frame_ok, is_stop

log = logging.getLogger("fairtable.voice")

MAX_CALL_S = 420  # Nova 2 Sonic ends a connection after 8 minutes; the call ends first, on our terms
BUSY = "A call is already open for this account."
UNAVAILABLE = "The voice assistant is not available right now. Use the text chat instead."


class VoiceSession(Protocol):
    async def start(self) -> None: ...

    async def send_audio(self, pcm: bytes) -> None: ...

    def events(self) -> AsyncIterator[dict[str, Any]]: ...

    async def close(self) -> None: ...


class VoiceService:
    def __init__(self, make_session: Callable[[str], VoiceSession], *, max_call_s: float = MAX_CALL_S) -> None:
        self._make_session = make_session
        self._max_call_s = max_call_s
        self._open: set[str] = set()

    def is_open(self, sub: str) -> bool:
        return sub in self._open

    async def serve(self, ws: WebSocket, *, sub: str, token: str) -> None:
        """Run one call until the diner stops, the page goes away, the session ends or the time is up."""
        await ws.accept()
        if sub in self._open:
            await self._say(ws, {"type": "error", "message": BUSY})
            await ws.close()
            return
        self._open.add(sub)
        session: VoiceSession | None = None
        try:
            session = self._make_session(token)
            await session.start()
            await ws.send_json({"type": "ready", "in_rate": IN_RATE, "out_rate": OUT_RATE})
            inbound = asyncio.create_task(self._inbound(ws, session))
            outbound = asyncio.create_task(self._outbound(ws, session))
            _, pending = await asyncio.wait({inbound, outbound}, timeout=self._max_call_s,
                                            return_when=asyncio.FIRST_COMPLETED)
            for task in (inbound, outbound):
                task.cancel()
            await asyncio.gather(inbound, outbound, return_exceptions=True)
        except Exception:
            log.exception("the voice call failed")
            await self._say(ws, {"type": "error", "message": UNAVAILABLE})
        finally:
            self._open.discard(sub)
            if session is not None:
                try:
                    await session.close()
                except Exception:
                    log.exception("could not close the voice session")
            await self._say(ws, {"type": "closed"})
            try:
                await ws.close()
            except RuntimeError:
                pass  # already closed

    @staticmethod
    async def _say(ws: WebSocket, message: dict[str, Any]) -> None:
        try:
            await ws.send_json(message)
        except (RuntimeError, WebSocketDisconnect):
            pass  # the page is gone

    @staticmethod
    async def _inbound(ws: WebSocket, session: VoiceSession) -> None:
        while True:
            frame = await ws.receive()
            if frame["type"] == "websocket.disconnect":
                return
            if frame.get("bytes") is not None:
                if audio_frame_ok(frame["bytes"]):
                    await session.send_audio(frame["bytes"])
            elif frame.get("text") is not None and is_stop(frame["text"]):
                return

    @staticmethod
    async def _outbound(ws: WebSocket, session: VoiceSession) -> None:
        async for message in session.events():
            await ws.send_json(message)
