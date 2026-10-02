"""P1-8: idempotency rules (pure)."""

import pytest

from server.domain.errors import ErrorCode, FairTableError
from server.domain.idempotency import IdempotencyRecord, is_replay, params_hash, validate_key
from server.domain.tool_names import ToolName

HOLD = ToolName.RESERVATION_HOLD


def record(digest: str) -> IdempotencyRecord:
    return IdempotencyRecord("u1", "key-12345", "reservation_hold", digest, {"hold_id": "h1"}, "t")


@pytest.mark.parametrize("good", ["abcd1234", "3f2b9c1e-7a55-4c1d-9c3e-1234567890ab", "a.b_c:d-e12"])
def test_good_keys(good):
    assert validate_key(good) == good


@pytest.mark.parametrize("bad", ["", "short", "has space 1234", "semi;colon1", "a#b12345", "x" * 129, None, 12345678])
def test_bad_keys_are_invalid_input(bad):
    with pytest.raises(FairTableError) as exc:
        validate_key(bad)
    assert exc.value.code is ErrorCode.INVALID_INPUT


def test_hash_ignores_key_order_and_spacing_but_not_values_or_tool():
    a = params_hash(HOLD, {"offer_id": "x", "party": 2})
    assert a == params_hash(HOLD, {"party": 2, "offer_id": "x"})
    assert a != params_hash(HOLD, {"offer_id": "x", "party": 3})
    assert a != params_hash(ToolName.RESERVATION_CONFIRM, {"offer_id": "x", "party": 2})
    assert len(a) == 64


def test_first_use_is_new_same_params_replay_different_params_conflict():
    digest = params_hash(HOLD, {"a": 1})
    assert is_replay(None, digest) is False
    assert is_replay(record(digest), digest) is True
    with pytest.raises(FairTableError) as exc:
        is_replay(record(digest), params_hash(HOLD, {"a": 2}))
    assert exc.value.code is ErrorCode.IDEMPOTENCY_CONFLICT
