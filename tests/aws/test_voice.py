"""P3-11 on the real account: a spoken booking through the voice page, microphone to Nova 2 Sonic to the Gateway.

Opt-in (``pytest -m aws tests/aws/test_voice.py``); needs the ``voice`` extra, Bedrock access to Nova 2 Sonic in
the account, and the stack of the other AWS tests. The "microphone" plays two recordings made with the Windows
speech engine (``tests/fixtures/voice/``, 16 kHz mono) into the real ``/voice/ws`` endpoint of the web app, served by
uvicorn on a free port. It checks what a machine can check: the model heard the request, called the tools in order,
held a table, **asked before booking**, and booked only after the spoken yes. How it sounds is for a person to judge.
"""

import asyncio
import json
import os
import threading
import time
import wave
from pathlib import Path

import httpx
import pytest
import uvicorn
from test_demo_flow import cancel_all, web  # noqa: F401
from test_gateway import gateway  # noqa: F401
from test_runtime_smoke import cognito  # noqa: F401

from devauth.accounts import USERS_BY_NAME
from web.app import create_app
from web.voice import VoiceService

pytest.importorskip("strands.experimental.bidi.models.bedrock")
websockets = pytest.importorskip("websockets")

pytestmark = pytest.mark.aws
DINER = os.environ.get("VOICE_DINER", "diner-alice")  # another seeded diner avoids the limit of open holds in repeat runs
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "voice"
CHUNK = 3200  # 100 ms of 16 kHz 16-bit mono


def pcm_of(name: str) -> bytes:
    with wave.open(str(FIXTURES / name)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
        return w.readframes(w.getnframes())


@pytest.fixture
def served(web):  # noqa: F811
    """The web app with the voice page switched on, on a free port."""
    import socket

    from web.voice_nova import NovaVoiceSession

    deps = web["deps"]

    def make(token: str) -> NovaVoiceSession:
        return NovaVoiceSession(mcp_url=deps.settings.mcp_url, token=token, via_gateway=True, prefix="ft___",
                                system_prompt=deps.chat.system_prompt(), region=os.environ.get("AWS_REGION") or "us-east-1")

    deps.voice = VoiceService(make)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(deps), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    yield port
    server.should_exit = True
    thread.join(timeout=10)
    deps.voice = None


class Mic:
    """A microphone that never stops: silence unless a recording is queued, 100 ms at a time. Nova 2 Sonic ends the
    session when no audio arrives for a few seconds, so a real page streams continuously as well."""

    def __init__(self, ws) -> None:
        self._ws, self._queue = ws, asyncio.Queue()
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while True:
            try:
                chunk = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                chunk = bytes(CHUNK)
            await self._ws.send(chunk)
            await asyncio.sleep(0.1)

    def say(self, pcm: bytes) -> None:
        for i in range(0, len(pcm), CHUNK):
            self._queue.put_nowait(pcm[i:i + CHUNK])

    async def stop(self) -> None:
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)


async def listen(ws, seconds: float, until=None, idle_s: float | None = None) -> list[dict]:
    """Collect the server's messages for up to ``seconds``. Stops early when ``until(messages)`` is true, or (with
    ``idle_s``) when something has been heard and nothing new came for that long: the assistant is waiting for us."""
    got: list[dict] = []
    started = last = time.monotonic()
    while time.monotonic() - started < seconds:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
        except TimeoutError:
            if until and until(got):
                break
            if idle_s and got and time.monotonic() - last > idle_s:
                break
            continue
        got.append(json.loads(raw))
        last = time.monotonic()
        if until and until(got):
            break
    return got


def steps(messages, phase="call"):
    return [m for m in messages if m["type"] == "step" and m["phase"] == phase]


def worked(messages, tool: str) -> bool:
    """A call of ``tool`` whose result came back without an error."""
    ids = {s["id"] for s in steps(messages) if s["tool"] == tool}
    return any(s["ok"] and s["id"] in ids for s in steps(messages, "result"))


def asked(messages) -> bool:
    """The hold worked and the assistant has finished speaking since: it has put its question to the diner."""
    ids = {s["id"] for s in steps(messages) if s["tool"] == "reservation_hold"}
    at = [i for i, m in enumerate(messages)
          if m["type"] == "step" and m["phase"] == "result" and m["ok"] and m["id"] in ids]
    return bool(at) and any(m["type"] == "state" and not m["speaking"] for m in messages[at[0]:])


def booked(messages) -> bool:
    return worked(messages, "reservation_confirm")


def said(messages, role):
    return "".join(m["text"] for m in messages if m["type"] == "transcript" and m["role"] == role).lower()


@pytest.mark.asyncio
async def test_a_spoken_booking_asks_first_and_books_only_after_the_yes(served, web, gateway, cognito):  # noqa: F811
    port = served
    base = f"http://127.0.0.1:{port}"
    async with httpx.AsyncClient(base_url=base, follow_redirects=False, timeout=60) as http:
        r = await http.post("/login", data={"username": DINER, "password": USERS_BY_NAME[DINER].password, "next": "/voice"})
        assert r.status_code == 303, "Cognito sign-in failed"
        cookie = f"ft_session={http.cookies['ft_session']}"
        page = await http.get("/voice", headers={"cookie": cookie})
        assert page.status_code == 200 and "Start the call" in page.text

    all_messages: list[dict] = []
    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}/voice/ws",
                                      additional_headers={"cookie": cookie, "origin": base}, max_size=None) as ws:
            ready = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
            assert ready["type"] == "ready", ready

            # turn 1: the diner asks for a table; the assistant must hold one and ask, not book
            mic = Mic(ws)
            mic.say(pcm_of("book-luna-tomorrow-seven.wav"))
            first = await listen(ws, 90, asked, idle_s=12)
            all_messages += first
            print("TURN1 steps:", [(s["tool"], s["args"][:60]) for s in steps(first)])
            print("TURN1 results:", [(s["ok"], s["summary"][:90]) for s in steps(first, "result")])
            print("TURN1 user said:", said(first, "user")[:160])
            print("TURN1 assistant said:", said(first, "assistant")[:300])
            assert said(first, "user"), "the model heard nothing"
            assert any(m["type"] == "audio" for m in first), "no voice came back"
            calls = [s["tool"] for s in steps(first)]
            assert "reservation_confirm" not in calls, "it booked before the diner said yes"

            # the diner says yes. If the model had not held a table yet, this yes lets it hold one and read it
            # back: it must ask again, and only a second yes may book.
            yes_count = 0
            while not worked(all_messages, "reservation_confirm") and yes_count < 3:
                await asyncio.sleep(4)
                read_back = asked(all_messages)  # a held table has been read back to the diner
                mic.say(pcm_of("yes-please.wav"))
                yes_count += 1
                more = await listen(ws, 90, booked if read_back else asked, idle_s=12)
                all_messages += more
                print(f"YES {yes_count} steps:", [(s["tool"], s["args"][:40]) for s in steps(more)])
                print(f"YES {yes_count} results:", [(s["ok"], s["summary"][:70]) for s in steps(more, "result")])
                print(f"YES {yes_count} assistant said:", said(more, "assistant")[:300])
                assert read_back or "reservation_confirm" not in [s["tool"] for s in steps(more)], (
                    "it booked on a yes that came before it had read a held table back")
            assert worked(all_messages, "reservation_hold") and worked(all_messages, "reservation_confirm"), (
                "no booking came out of the call")
            usage = [m for m in all_messages if m["type"] == "usage"]
            print("USAGE (last):", usage[-1] if usage else None)
            await mic.stop()
            await ws.send(json.dumps({"type": "stop"}))
    finally:
        await cancel_all(web, gateway, cognito, DINER)
