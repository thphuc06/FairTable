"""P1-1: slot_token is signed, expiring and bound to the user it was offered to."""

import base64
import json

import pytest

from server.domain.clock import FakeClock
from server.domain.errors import ErrorCode, FairTableError
from server.domain.slot_token import MAX_TOKEN_CHARS, SlotClaims, SlotTokenCodec

SECRET = b"s" * 32
CLAIMS = SlotClaims(
    restaurant_id="luna",
    date="2026-10-30",
    slot_key="1900#T2",
    party_size=4,
    slot_ver=7,
    sub="user-1",
    hot=True,
    drop_id="drop-9",
)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def codec(clock):
    return SlotTokenCodec(SECRET, clock, ttl_s=600)


def code_of(exc: pytest.ExceptionInfo) -> ErrorCode:
    return exc.value.code


def test_round_trip(codec):
    token = codec.issue(CLAIMS)
    assert codec.verify(token, sub="user-1") == CLAIMS


def test_round_trip_with_optional_fields_absent(codec):
    plain = SlotClaims("luna", "2026-10-30", "1900#T2", 2, 1, "user-1")
    assert codec.verify(codec.issue(plain), sub="user-1") == plain


def test_expired_token_is_rejected_with_its_own_code(codec, clock):
    token = codec.issue(CLAIMS)
    clock.advance(seconds=599)
    codec.verify(token, sub="user-1")  # still valid one second before expiry
    clock.advance(seconds=1)
    with pytest.raises(FairTableError) as exc:
        codec.verify(token, sub="user-1")
    assert code_of(exc) is ErrorCode.SLOT_TOKEN_EXPIRED
    assert exc.value.next_step.tool.value == "availability_check"


def test_tampered_payload_is_rejected(codec):
    token = codec.issue(CLAIMS)
    payload, mac = token.split(".")
    body = json.loads(base64.urlsafe_b64decode(payload + "=="))
    body["party"] = 2  # try to change the party size
    forged = base64.urlsafe_b64encode(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).rstrip(b"=").decode()
    with pytest.raises(FairTableError) as exc:
        codec.verify(f"{forged}.{mac}", sub="user-1")
    assert code_of(exc) is ErrorCode.INVALID_SLOT_TOKEN
    assert exc.value.reason == "bad_signature"


def test_tampered_signature_is_rejected(codec):
    token = codec.issue(CLAIMS)
    flipped = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(FairTableError) as exc:
        codec.verify(flipped, sub="user-1")
    assert code_of(exc) is ErrorCode.INVALID_SLOT_TOKEN


def test_token_signed_with_another_secret_is_rejected(clock, codec):
    other = SlotTokenCodec(b"o" * 32, clock)
    with pytest.raises(FairTableError):
        codec.verify(other.issue(CLAIMS), sub="user-1")


def test_token_is_bound_to_the_user(codec):
    token = codec.issue(CLAIMS)
    with pytest.raises(FairTableError) as exc:
        codec.verify(token, sub="someone-else")
    assert code_of(exc) is ErrorCode.INVALID_SLOT_TOKEN
    assert exc.value.reason == "wrong_user"
    # The message must not reveal that the token itself was fine.
    assert "user" not in exc.value.message.lower()


@pytest.mark.parametrize(
    "garbage",
    ["", "abc", "a.b.c", ".", "..", "é.é", "x" * (MAX_TOKEN_CHARS + 1), None, 123],
)
def test_garbage_is_rejected_without_crashing(codec, garbage):
    with pytest.raises(FairTableError) as exc:
        codec.verify(garbage, sub="user-1")
    assert code_of(exc) is ErrorCode.INVALID_SLOT_TOKEN


def test_signed_but_malformed_payload_is_rejected(codec):
    # A correctly signed payload that is not a valid slot claim set must still fail cleanly.
    payload = base64.urlsafe_b64encode(b'{"v":1}').rstrip(b"=").decode()
    token = f"{payload}.{codec._mac(payload)}"
    with pytest.raises(FairTableError) as exc:
        codec.verify(token, sub="user-1")
    assert exc.value.reason == "malformed_payload"


def test_unknown_version_is_rejected(codec):
    payload = base64.urlsafe_b64encode(b'{"v":2}').rstrip(b"=").decode()
    token = f"{payload}.{codec._mac(payload)}"
    with pytest.raises(FairTableError) as exc:
        codec.verify(token, sub="user-1")
    assert exc.value.reason == "unsupported_version"


def test_short_secret_and_bad_ttl_are_refused(clock):
    with pytest.raises(ValueError):
        SlotTokenCodec(b"short", clock)
    with pytest.raises(ValueError):
        SlotTokenCodec(SECRET, clock, ttl_s=0)


def test_token_is_deterministic_for_the_same_second(codec):
    assert codec.issue(CLAIMS) == codec.issue(CLAIMS)
