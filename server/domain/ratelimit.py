"""Token bucket (pure). State lives in DynamoDB; time is passed in, so tests never sleep."""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class BucketState:
    tokens: float
    updated_at: float  # epoch seconds


def consume(
    state: BucketState | None,
    now: float,
    *,
    capacity: int,
    per_hour: int,
    cost: int = 1,
) -> tuple[BucketState, bool, int]:
    """Try to take ``cost`` tokens. Returns (new state, allowed, retry_after_s).

    A missing state is a full bucket. Tokens refill continuously at ``per_hour`` / 3600 per second
    and never exceed ``capacity``. When refused, the state is refreshed but nothing is taken.
    """
    if capacity <= 0 or per_hour <= 0 or cost <= 0:
        raise ValueError("capacity, per_hour and cost must be positive")
    refill_per_s = per_hour / 3600
    if state is None:
        tokens = float(capacity)
    else:
        elapsed = max(0.0, now - state.updated_at)
        tokens = min(float(capacity), state.tokens + elapsed * refill_per_s)
    if tokens >= cost:
        return BucketState(tokens - cost, now), True, 0
    retry_after = math.ceil((cost - tokens) / refill_per_s)
    return BucketState(tokens, now), False, retry_after
