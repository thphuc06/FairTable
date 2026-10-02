"""D-051, D-054: the read-back token. It proves that the server handed these exact terms to this user's
assistant at a known moment; the pause is counted from that moment. It does not prove that the diner said yes."""

from datetime import UTC, datetime

import pytest

from server.domain.booking import terms_for
from server.domain.clock import FakeClock
from server.domain.models import Venue
from server.domain.readback import (
    KIND_CANCEL_FEE,
    KIND_CONFIRM,
    MIN_PAUSE_S,
    MIN_PAUSE_WITH_FEE_S,
    ReadBackCodec,
    min_pause_s,
    pause_elapsed,
)

SECRET = b"s" * 32
VENUE = Venue("luna-trattoria", "Luna Trattoria", "Italian", "Riverside", "x", 60, 40, 0, 0)
TERMS = terms_for(VENUE, "2026-10-03", "19:00", 2)


@pytest.fixture
def clock():
    return FakeClock(datetime(2026, 10, 1, 12, 0, tzinfo=UTC))


@pytest.fixture
def codec(clock):
    return ReadBackCodec(SECRET, clock)


def issue(codec, **over):
    args = {"kind": KIND_CONFIRM, "subject_id": "hold1", "sub": "u1", "terms": TERMS, **over}
    return codec.issue(**args)


def check(codec, token, **over):
    args = {"kind": KIND_CONFIRM, "subject_id": "hold1", "sub": "u1", "terms": TERMS, **over}
    return codec.check(token, **args)


def test_a_token_for_the_same_terms_user_and_subject_matches(codec):
    result = check(codec, issue(codec))
    assert result.matches and result.issued_at_ms is not None


def test_the_pause_is_three_seconds_and_six_with_a_fee():
    assert min_pause_s(0) == MIN_PAUSE_S == 3
    assert min_pause_s(2500) == MIN_PAUSE_WITH_FEE_S == 6


def test_the_pause_counts_from_the_moment_of_issue(codec, clock):
    result = check(codec, issue(codec))
    assert not pause_elapsed(result.issued_at_ms, clock.now(), 3)  # same instant: far too soon
    clock.advance(2.9)
    assert not pause_elapsed(result.issued_at_ms, clock.now(), 3)
    clock.advance(0.1)
    assert pause_elapsed(result.issued_at_ms, clock.now(), 3)


def test_the_moment_is_rounded_up_so_a_pause_is_never_shorter_than_asked(codec, clock):
    clock.advance(0.2)  # not on a half second: the issue is counted at the next one
    result = check(codec, issue(codec))
    clock.advance(3.2)  # 3.2 s after the real issue, 2.7 s after the counted one
    assert not pause_elapsed(result.issued_at_ms, clock.now(), 3)
    clock.advance(0.3)  # 3.5 s after the real issue: over, and at most half a second late
    assert pause_elapsed(result.issued_at_ms, clock.now(), 3)


@pytest.mark.parametrize("token", [None, "", "abc", "a.b", "a.b.c", "x" * 5000, 7, "0" * 11, "u" * 11, "12345678901234"])
def test_a_missing_or_malformed_token_never_matches(codec, token):
    assert not check(codec, token).matches


def test_a_tampered_code_never_matches(codec):
    code = issue(codec)
    other = "1" if code[-1] != "1" else "2"
    assert not check(codec, code[:-1] + other).matches  # one changed character: no match
    assert not check(codec, code[:-2]).matches  # one short


def test_the_code_is_eleven_characters_and_survives_the_way_a_model_may_write_it(codec):
    code = issue(codec)
    assert len(code) == 11 and all(ch in "0123456789abcdefghjkmnpqrstvwxyz" for ch in code)
    spoken = f" {code[:4].upper()} - {code[4:8]} {code[8:]} "  # capitals, a dash, spaces
    assert check(codec, spoken).matches
    lookalike = code.replace("0", "O").replace("1", "l")  # o and l for zero and one
    assert check(codec, lookalike).matches


def test_a_token_for_other_terms_another_user_or_another_subject_does_not_match(codec):
    token = issue(codec)
    other_terms = terms_for(VENUE, "2026-10-03", "19:00", 4)  # same table, a different party
    assert not check(codec, token, terms=other_terms).matches
    assert not check(codec, token, sub="u2").matches
    assert not check(codec, token, subject_id="hold2").matches
    assert not check(codec, token, kind=KIND_CANCEL_FEE).matches


def test_a_token_signed_with_another_secret_does_not_match(clock):
    mine, theirs = ReadBackCodec(SECRET, clock), ReadBackCodec(b"t" * 32, clock)
    assert not check(mine, issue(theirs)).matches


def test_a_token_is_good_for_three_hours_for_a_confirm_and_fifteen_minutes_for_a_cancel(codec, clock):
    confirm, cancel = issue(codec), issue(codec, kind=KIND_CANCEL_FEE)
    clock.advance(15 * 60 - 1)
    assert check(codec, cancel, kind=KIND_CANCEL_FEE).matches
    clock.advance(2)
    assert not check(codec, cancel, kind=KIND_CANCEL_FEE).matches
    assert check(codec, confirm).matches
    clock.advance(3 * 3600)
    assert not check(codec, confirm).matches


def test_a_token_from_the_future_is_refused(codec, clock):
    token = issue(codec)
    clock.advance(-60)  # the clock went backwards: a token cannot be older than "now"
    assert not check(codec, token).matches


def test_the_secret_must_be_long_enough(clock):
    with pytest.raises(ValueError):
        ReadBackCodec(b"short", clock)


def test_the_code_stays_valid_across_the_wrap_of_its_time_characters(clock):
    """The moment is kept in half seconds modulo 32768 (4.5 hours); a code made just before the wrap is read right."""
    now_unit = int(clock.now().timestamp() * 2)
    clock.advance((32768 - now_unit % 32768 - 4) / 2)  # two seconds before the wrap
    codec = ReadBackCodec(SECRET, clock)
    code = issue(codec)
    clock.advance(30)
    result = check(codec, code)
    assert result.matches and not pause_elapsed(result.issued_at_ms, clock.now(), 31)
    assert pause_elapsed(result.issued_at_ms, clock.now(), 29)
