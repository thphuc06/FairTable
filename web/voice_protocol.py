"""What the voice page and the server say to each other (plan task P3-11, decision D-052). Pure functions, no I/O.

Browser to server: binary frames of 16-bit PCM, 16 kHz, mono, little-endian (microphone), and one text frame
``{"type": "stop"}`` when the diner ends the call.

Server to browser: JSON text frames.

* ``{"type": "ready", "in_rate": 16000, "out_rate": 24000}``
* ``{"type": "audio", "pcm": "<base64 PCM16>"}``  the assistant's voice; play it in order
* ``{"type": "transcript", "role": "user" | "assistant", "text": "..."}``  a piece of what was said
* ``{"type": "barge_in"}``  the diner spoke over the assistant: drop what is queued for playback
* ``{"type": "step", "phase": "call" | "result", "id", "tool", ...}``  the tool calls behind the answer
* ``{"type": "state", "speaking": true | false}``
* ``{"type": "usage", "input": n, "output": n}``  tokens so far
* ``{"type": "error", "message": "..."}`` and ``{"type": "closed"}``

The assistant's text, never a token or an id, is what reaches the page; tool arguments are shortened.
"""

import json
from typing import Any

from simulator.events import _payload

IN_RATE = 16000
OUT_RATE = 24000
MAX_FRAME_BYTES = 64_000  # two seconds of audio; a longer frame is refused
SECRET_WORDS = ("token", "secret", "password", "authorization")
SHOWN_CHARS = 14


def short_args(args: dict[str, Any]) -> str:
    """``key=value`` pairs for the steps list; anything that looks like a secret is cut short."""
    parts = []
    for key, value in args.items():
        text = str(value)
        if any(word in key.lower() for word in SECRET_WORDS) or len(text) > 40:
            text = text[:SHOWN_CHARS] + "…"
        parts.append(f"{key}={text}")
    return ", ".join(parts)


def bare(name: str, prefix: str) -> str:
    return name[len(prefix):] if prefix and name.startswith(prefix) else name


def _result_summary(tool_result: dict[str, Any]) -> tuple[bool, str]:
    payload = _payload(tool_result)
    ok = tool_result.get("status") != "error" and not payload.get("error")
    text = payload.get("spoken_summary") or payload.get("message") or ""
    if not text:
        blocks = tool_result.get("content") or []
        text = next((b.get("text", "") for b in blocks if isinstance(b, dict) and "text" in b), "")
    return ok, str(text)[:300]


def to_client(event: Any, prefix: str = "") -> list[dict[str, Any]]:
    """One event of the Strands bidirectional agent as zero or more messages for the page."""
    if not isinstance(event, dict):
        return []
    kind = event.get("type")
    if kind == "bidi_audio_delta":
        return [{"type": "audio", "pcm": event["audio"]}]
    if kind == "bidi_transcript_delta":
        text = str(event.get("delta", ""))
        return [{"type": "transcript", "role": event.get("role", "assistant"), "text": text}] if text else []
    if kind == "bidi_transcript_stop":
        return [{"type": "transcript_end", "role": event.get("role", "assistant")}]
    if kind == "bidi_barge_in":
        return [{"type": "barge_in"}]
    if kind == "bidi_response_start":
        return [{"type": "state", "speaking": True}]
    if kind == "bidi_response_stop":
        return [{"type": "state", "speaking": False}]
    if kind == "bidi_usage":
        return [{"type": "usage", "input": event.get("inputTokens", 0), "output": event.get("outputTokens", 0)}]
    if kind == "tool_use_stream":
        use = event.get("current_tool_use") or {}
        if not use.get("name"):
            return []
        args = use.get("input")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        return [{"type": "step", "phase": "call", "id": use.get("toolUseId", ""), "tool": bare(use["name"], prefix),
                 "args": short_args(args if isinstance(args, dict) else {})}]
    message = event.get("message")
    if isinstance(message, dict):
        out = []
        for block in message.get("content") or []:
            result = block.get("toolResult") if isinstance(block, dict) else None
            if result:
                ok, summary = _result_summary(result)
                out.append({"type": "step", "phase": "result", "id": result.get("toolUseId", ""), "ok": ok,
                            "summary": summary})
        return out
    return []


def audio_frame_ok(data: bytes) -> bool:
    """A microphone frame: whole 16-bit samples, not empty, not huge."""
    return 0 < len(data) <= MAX_FRAME_BYTES and len(data) % 2 == 0


def is_stop(text: str) -> bool:
    try:
        return json.loads(text).get("type") == "stop"
    except (ValueError, AttributeError):
        return False


def origin_ok(origin: str | None, host: str | None, public_url: str) -> bool:
    """WebSocket handshakes carry cookies but are not covered by the same-origin policy: accept only a page from
    this app (the Origin names the public URL or the host the request came to). No Origin (not a browser): refused."""
    if not origin:
        return False
    allowed = {public_url.rstrip("/")}
    if host:
        allowed |= {f"http://{host}", f"https://{host}"}
    return origin.rstrip("/") in allowed
