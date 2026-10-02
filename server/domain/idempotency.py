"""Idempotency (design section 5.3), pure.

Key = (user ``sub``, ``idempotency_key``). Same parameters -> return the stored result; different
parameters (or a different tool) -> ``IDEMPOTENCY_CONFLICT``. A record is stored only when state
really changed, in the same transaction as the change; denied or failed calls store nothing, so the
same key can be used again once the cause is fixed (for example after the diner has answered).
"""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from server.domain.errors import ErrorCode, FairTableError
from server.domain.tool_names import ToolName

KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


@dataclass(frozen=True)
class IdempotencyRecord:
    sub: str
    key: str
    tool: str
    params_hash: str
    result: dict[str, Any]
    created_at: str  # ISO timestamp


def validate_key(key: object) -> str:
    if not isinstance(key, str) or not KEY_PATTERN.match(key):
        raise FairTableError(
            ErrorCode.INVALID_INPUT,
            "The request key is not valid.",
            hint="idempotency_key must be 8-128 characters: letters, digits, '.', '_', ':' or '-'.",
        )
    return key


def params_hash(tool: ToolName, params: Mapping[str, Any]) -> str:
    """Stable hash of the tool and its parameters (key order and spacing do not matter)."""
    canonical = json.dumps(
        {"tool": tool.value, "params": params}, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def conflict() -> FairTableError:
    return FairTableError(
        ErrorCode.IDEMPOTENCY_CONFLICT,
        "That request key was already used for a different request.",
        hint="This idempotency_key was already used with different parameters.",
    )


def is_replay(record: IdempotencyRecord | None, new_hash: str) -> bool:
    """True = repeat the stored result; False = first time. Raises on a conflicting reuse."""
    if record is None:
        return False
    if record.params_hash != new_hash:
        raise conflict()
    return True
