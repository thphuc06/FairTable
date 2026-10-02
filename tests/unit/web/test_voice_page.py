"""P3-11: the voice page without a microphone, a model or AWS: the protocol, the socket and the page's security."""

import asyncio
import base64
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from server.domain.clock import FakeClock
from server.domain.models import Identity
from web.app import VOICE_CSP, WebDeps, create_app
from web.auth import SignedIn
from web.chat import ChatService
from web.session import SessionCodec
from web.voice import UNAVAILABLE, VoiceService
from web.voice_protocol import audio_frame_ok, is_stop, origin_ok, short_args, to_client

PUBLIC = "http://localhost:8080"


# ---------------------------------------------------------------- the protocol
def test_audio_and_transcripts_go_to_the_page_as_they_are():
    assert to_client({"type": "bidi_audio_delta", "audio": "AAAA"}) == [{"type": "audio", "pcm": "AAAA"}]
    assert to_client({"type": "bidi_transcript_delta", "role": "user", "delta": "hello"}) == [
        {"type": "transcript", "role": "user", "text": "hello"}]
    assert to_client({"type": "bidi_transcript_delta", "role": "user", "delta": ""}) == []
    assert to_client({"type": "bidi_barge_in"}) == [{"type": "barge_in"}]
    assert to_client({"type": "bidi_response_start"}) == [{"type": "state", "speaking": True}]
    assert to_client({"type": "bidi_usage", "inputTokens": 5, "outputTokens": 7, "totalTokens": 12}) == [
        {"type": "usage", "input": 5, "output": 7}]


def test_events_the_page_does_not_need_are_dropped():
    for event in ({"type": "bidi_connection_start"}, {"type": "bidi_audio_start"}, {"type": "x"}, {}, "text", None):
        assert to_client(event) == []


def test_a_tool_call_shows_its_bare_name_and_shortened_arguments():
    call = {"type": "tool_use_stream", "current_tool_use": {
        "toolUseId": "t1", "name": "ft___reservation_hold",
        "input": {"offer_id": "x" * 300, "idempotency_key": "hold-key-0001", "party_size": 2}}}
    (step,) = to_client(call, "ft___")
    assert step["tool"] == "reservation_hold" and step["phase"] == "call" and step["id"] == "t1"
    assert "x" * 30 not in step["args"] and "party_size=2" in step["args"]
    streamed = {"type": "tool_use_stream", "current_tool_use": {"toolUseId": "t1", "name": "a", "input": '{"a": 1}'}}
    assert to_client(streamed)[0]["args"] == "a=1"
    assert to_client({"type": "tool_use_stream", "current_tool_use": {"toolUseId": "t1"}}) == []  # no name yet


def test_a_tool_result_shows_whether_it_worked_and_what_it_said():
    ok = {"message": {"content": [{"toolResult": {
        "toolUseId": "t1", "status": "success", "content": [{"text": '{"spoken_summary": "Booked."}'}]}}]}}
    refused = {"message": {"content": [{"toolResult": {
        "toolUseId": "t2", "status": "error", "content": [{"text": '{"error": "X", "message": "Not allowed."}'}]}}]}}
    assert to_client(ok) == [{"type": "step", "phase": "result", "id": "t1", "ok": True, "summary": "Booked."}]
    assert to_client(refused)[0]["ok"] is False and to_client(refused)[0]["summary"] == "Not allowed."


def test_secrets_never_reach_the_page_in_full():
    assert short_args({"read_back_token": "abcdefghijklmnopqrstuvwxyz"}) == "read_back_token=abcdefghijklmn…"
    assert short_args({"authorization": "Bearer abcdefghijklmnop"}) == "authorization=Bearer abcdefg…"
    assert short_args({"party_size": 2, "date": "2026-10-12"}) == "party_size=2, date=2026-10-12"


def test_only_whole_16_bit_frames_of_a_sane_size_are_accepted():
    assert audio_frame_ok(b"\x00\x01" * 1600)
    assert not audio_frame_ok(b"") and not audio_frame_ok(b"\x00\x01\x02") and not audio_frame_ok(b"\x00" * 70_000)
    assert is_stop('{"type": "stop"}') and not is_stop("nonsense") and not is_stop('{"type": "audio"}')


def test_a_socket_from_another_site_is_refused():
    assert origin_ok("http://localhost:8080", "localhost:8080", PUBLIC)
    assert origin_ok("http://127.0.0.1:8080", "127.0.0.1:8080", PUBLIC)  # the host the request came to
    assert not origin_ok("http://evil.example", "localhost:8080", PUBLIC)
    assert not origin_ok(None, "localhost:8080", PUBLIC)


# ---------------------------------------------------------------- the socket and the page
class FakeSession:
    def __init__(self, token: str, script: list, fail_start: bool = False) -> None:
        self.token, self.script, self.fail_start = token, script, fail_start
        self.heard: list[bytes] = []
        self.closed = False
        self._queue: asyncio.Queue = asyncio.Queue()

    async def start(self) -> None:
        if self.fail_start:
            raise RuntimeError("no model access")
        for item in self.script:
            self._queue.put_nowait(item)

    async def send_audio(self, pcm: bytes) -> None:
        self.heard.append(pcm)

    async def events(self):
        while True:
            yield await self._queue.get()

    async def close(self) -> None:
        self.closed = True


class FakeLogin:
    def sign_in(self, username, password):
        if (username, password) != ("diner-alice", "pw"):
            return None
        return SignedIn(Identity(sub="sub-alice", username="diner-alice"), "alice-access-token", 3600)


def build(make_session):
    clock = FakeClock()
    chat = ChatService("http://unused/mcp", lambda: None, clock)
    voice = VoiceService(make_session, max_call_s=5)
    deps = WebDeps(settings=SimpleNamespace(web_public_url=PUBLIC), store=None, clock=clock, login=FakeLogin(),
                   sessions=SessionCodec("s" * 32, clock), new_id=lambda: "id", chat=chat, voice=voice)
    return TestClient(create_app(deps), follow_redirects=False, base_url="http://localhost:8080"), voice


def head(client, origin: str | None = PUBLIC) -> dict:
    """Handshake headers of a page of ours: the test client does not send its cookies on a WebSocket by itself."""
    headers = {"cookie": "ft_session=" + client.cookies["ft_session"]}
    if origin:
        headers["origin"] = origin
    return headers


def sign_in(client) -> None:
    r = client.post("/login", data={"username": "diner-alice", "password": "pw", "next": "/voice"})
    assert r.status_code == 303 and r.headers["location"] == "/voice"


def test_the_voice_page_needs_a_sign_in_and_allows_only_its_own_scripts():
    client, _ = build(lambda token: FakeSession(token, []))
    r = client.get("/voice")
    assert r.status_code == 303 and r.headers["location"] == "/login?next=/voice"
    sign_in(client)
    page = client.get("/voice")
    assert page.status_code == 200 and "Start the call" in page.text and "<script src='/voice/voice.js'" in page.text
    assert page.headers["content-security-policy"] == VOICE_CSP and "microphone=(self)" in page.headers["permissions-policy"]
    assert "unsafe-inline" not in VOICE_CSP.split("script-src")[1].split(";")[0]  # no inline script
    assert client.get("/healthz").headers["content-security-policy"].startswith("default-src 'none'; style-src")
    for name in ("voice.js", "worklet.js"):
        script = client.get(f"/voice/{name}")
        assert script.status_code == 200 and script.headers["content-type"].startswith("text/javascript")
    assert client.get("/voice/other.js").status_code == 404


def test_the_voice_page_is_off_without_a_voice_service():
    deps_off = TestClient(create_app(WebDeps(settings=SimpleNamespace(web_public_url=PUBLIC), store=None,
                                             clock=FakeClock(), login=FakeLogin(),
                                             sessions=SessionCodec("s" * 32, FakeClock()), new_id=lambda: "id")),
                          follow_redirects=False)
    assert deps_off.get("/voice").status_code == 404


def test_a_call_carries_the_microphone_in_and_the_assistant_out_and_ends_cleanly():
    made = []

    def make(token):
        session = FakeSession(token, [
            {"type": "audio", "pcm": base64.b64encode(b"\x00\x00").decode()},
            {"type": "transcript", "role": "assistant", "text": "Hello"},
        ])
        made.append(session)
        return session

    client, voice = build(make)
    sign_in(client)
    with client.websocket_connect("/voice/ws", headers=head(client)) as ws:
        ready = ws.receive_json()
        assert ready == {"type": "ready", "in_rate": 16000, "out_rate": 24000}
        assert ws.receive_json()["type"] == "audio" and ws.receive_json()["text"] == "Hello"
        ws.send_bytes(b"\x01\x02" * 100)
        ws.send_bytes(b"\x01")  # not a whole sample: ignored, not fatal
        ws.send_text('{"type": "stop"}')
        assert ws.receive_json() == {"type": "closed"}
    session = made[0]
    assert session.token == "alice-access-token"  # the diner's own token, taken from the web process, never the page
    assert session.heard == [b"\x01\x02" * 100] and session.closed
    assert not voice.is_open("sub-alice")


def test_a_socket_without_a_sign_in_or_from_another_site_is_closed_before_anything_starts():
    made = []
    client, _ = build(lambda token: made.append(token) or FakeSession(token, []))
    with pytest.raises(Exception):  # noqa: B017  (starlette raises WebSocketDisconnect)
        with client.websocket_connect("/voice/ws", headers={"origin": PUBLIC}):  # no cookie
            pass
    sign_in(client)
    with pytest.raises(Exception):  # noqa: B017
        with client.websocket_connect("/voice/ws", headers=head(client, "http://evil.example")):
            pass
    with pytest.raises(Exception):  # noqa: B017
        with client.websocket_connect("/voice/ws", headers=head(client, None)):  # no Origin: not a page of ours
            pass
    assert made == []


def test_a_failing_session_tells_the_page_and_frees_the_account():
    client, voice = build(lambda token: FakeSession(token, [], fail_start=True))
    sign_in(client)
    with client.websocket_connect("/voice/ws", headers=head(client)) as ws:
        assert ws.receive_json() == {"type": "error", "message": UNAVAILABLE}
        assert ws.receive_json() == {"type": "closed"}
    assert not voice.is_open("sub-alice")


def test_a_second_call_for_the_same_account_is_refused_while_the_first_is_open():
    client, voice = build(lambda token: FakeSession(token, []))
    sign_in(client)
    with client.websocket_connect("/voice/ws", headers=head(client)) as first:
        assert first.receive_json()["type"] == "ready"
        assert voice.is_open("sub-alice")
        with client.websocket_connect("/voice/ws", headers=head(client)) as second:
            assert second.receive_json()["type"] == "error"
        first.send_text('{"type": "stop"}')
        assert first.receive_json() == {"type": "closed"}
    assert not voice.is_open("sub-alice")


def test_the_voice_page_has_lights_for_who_is_talking_and_its_script_drives_them():
    client, _ = build(lambda token: FakeSession(token, []))
    sign_in(client)
    page = client.get("/voice").text
    script = client.get("/voice/voice.js").text
    for element in ("ind-you", "ind-bot", "level"):
        assert f"id='{element}'" in page and f"$('{element}')" in script


def test_the_tool_calls_sit_under_each_answer_not_in_one_list_at_the_end():
    client, _ = build(lambda token: FakeSession(token, []))
    sign_in(client)
    page = client.get("/voice").text
    script = client.get("/voice/voice.js").text
    assert "id='steps'" not in page and ".stepsbox" in page
    assert "turnBox" in script and "insertBefore(div, turnBox)" in script
