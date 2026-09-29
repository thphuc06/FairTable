"""Per (user, restaurant) read limiter: the pure token bucket plus its DynamoDB state.

Concurrency: optimistic update with a version condition. If the same user keeps colliding with
themselves the request is refused (fail closed) rather than allowed for free.
"""

from decimal import Decimal

from server.domain.clock import Clock
from server.domain.errors import ErrorCode, FairTableError
from server.domain.ratelimit import BucketState, consume
from server.store import ConditionFailed, Store, keys

MAX_ATTEMPTS = 3


class RateLimiter:
    def __init__(self, store: Store, clock: Clock, *, per_hour: int = 20, capacity: int | None = None):
        self._store = store
        self._clock = clock
        self._per_hour = per_hour
        self._capacity = capacity or per_hour

    def check(self, sub: str, venue_id: str) -> None:
        """Take one token or raise ``RATE_LIMITED`` (with ``retry_after_s``)."""
        key = keys.rate_bucket(sub, venue_id)
        now = self._clock.now().timestamp()
        for _ in range(MAX_ATTEMPTS):
            item = self._store.get_item(key)
            state = BucketState(float(item["tokens"]), float(item["updated_at"])) if item else None
            new_state, allowed, retry_after = consume(
                state, now, capacity=self._capacity, per_hour=self._per_hour
            )
            version = int(item["ver"]) if item else 0
            row = {  # DynamoDB numbers must be Decimal, not float
                "PK": key.pk, "SK": key.sk, "ver": version + 1,
                "tokens": Decimal(str(round(new_state.tokens, 6))),
                "updated_at": Decimal(str(round(new_state.updated_at, 3))),
            }
            try:
                if item is None:
                    self._store.put_item(row, condition="attribute_not_exists(PK)")
                else:
                    self._store.put_item(row, condition="ver = :v", values={":v": version})
            except ConditionFailed:
                continue  # somebody else updated the bucket first: read again
            if allowed:
                return
            raise self._refused(retry_after)
        raise self._refused(1)

    @staticmethod
    def _refused(retry_after_s: int) -> FairTableError:
        return FairTableError(
            ErrorCode.RATE_LIMITED,
            "Too many availability checks for this restaurant.",
            retry_after_s=max(1, retry_after_s),
        )
