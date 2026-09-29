"""Success output helper: every successful tool output carries a short ``spoken_summary``."""

from typing import Any

MAX_SPOKEN_CHARS = 300


def success(spoken_summary: str, **fields: Any) -> dict[str, Any]:
    if not isinstance(spoken_summary, str) or not spoken_summary.strip():
        raise ValueError("spoken_summary is required and must be non-empty")
    if len(spoken_summary) > MAX_SPOKEN_CHARS:
        raise ValueError(f"spoken_summary must be at most {MAX_SPOKEN_CHARS} characters")
    return {"spoken_summary": spoken_summary.strip(), **fields}
