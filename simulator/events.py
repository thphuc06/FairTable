"""What happened in a conversation, in a form the personas can read: what the user said and what each
tool call returned. Built from Strands messages (``transcript``) or by hand in tests."""

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class UserSaid:
    text: str


@dataclass(frozen=True)
class Step:
    """One tool call and its answer. ``result`` is the tool's structured output (or ``{}``)."""

    tool: str
    args: dict[str, Any]
    result: dict[str, Any] = field(default_factory=dict)
    is_error: bool = False

    @property
    def error(self) -> str | None:
        return self.result.get("error") if self.is_error else None


Event = UserSaid | Step


def _payload(tool_result: dict[str, Any]) -> dict[str, Any]:
    """The JSON object a tool returned: structured content when present, else the first text block
    that parses as a JSON object."""
    structured = tool_result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    for block in tool_result.get("content", []):
        candidate = block.get("json") if "json" in block else block.get("text")
        if isinstance(candidate, dict):
            return candidate
        if isinstance(candidate, str):
            try:
                value = json.loads(candidate)
            except ValueError:
                continue
            if isinstance(value, dict):
                return value
    return {}


def transcript(messages: list[dict[str, Any]]) -> list[Event]:
    """Strands messages -> events, in order. A tool call whose result has not arrived yet is skipped."""
    calls: dict[str, tuple[str, dict[str, Any]]] = {}
    events: list[Event] = []
    for message in messages:
        for block in message.get("content", []):
            if "toolUse" in block:
                use = block["toolUse"]
                calls[use["toolUseId"]] = (use["name"], dict(use.get("input") or {}))
            elif "toolResult" in block:
                result = block["toolResult"]
                name, args = calls.get(result["toolUseId"], ("?", {}))
                events.append(Step(name, args, _payload(result), result.get("status") == "error"))
            elif "text" in block and message.get("role") == "user":
                events.append(UserSaid(block["text"]))
    return events
