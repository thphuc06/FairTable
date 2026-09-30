"""A transaction that keeps conflicting (real DynamoDB under contention) must reach the agent as a
structured, retryable refusal, never as a masked internal error."""

import pytest

from server.domain.errors import DEFAULT_NEXT_STEP, ErrorCode
from server.middleware import BusinessError, business_errors
from server.store import StoreBusy


def test_store_busy_becomes_a_temporarily_busy_business_error():
    @business_errors
    def tool():
        raise StoreBusy("transaction kept conflicting with concurrent writes")

    with pytest.raises(BusinessError) as exc:
        tool()
    error = exc.value.error
    assert error.code is ErrorCode.TEMPORARILY_BUSY
    assert error.retry_after_s == 1
    payload = error.to_payload()
    assert payload["error"] == "TEMPORARILY_BUSY"
    assert "same idempotency_key" in payload["next_step"]["why"]
    assert "conflict" not in payload["message"].lower()  # no internals in the message


def test_every_error_code_has_a_default_next_step():
    assert set(DEFAULT_NEXT_STEP) == set(ErrorCode)
