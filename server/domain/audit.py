"""Audit entries: who called which tool, what was decided, and by which rule."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AuditEntry:
    venue_id: str
    timestamp: str  # ISO, becomes part of the sort key
    request_id: str
    sub: str
    agent_id: str | None
    tool: str
    decision: str  # "allow" | "deny" | "conflict" | "failed"
    rule_ids: tuple[str, ...] = ()
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def date(self) -> str:
        return self.timestamp[:10]
