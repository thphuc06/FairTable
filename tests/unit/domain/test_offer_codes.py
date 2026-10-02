"""D-059: the offer ids. The pure parts: the alphabet, how a model's version of a code is read, the errors."""

import pytest

from server.domain.errors import ErrorCode
from server.domain.offers import ALPHABET, CODE_LENGTH, invalid, new_code, normalize, normalize_any


def test_a_new_code_is_eight_characters_from_a_safe_alphabet():
    for _ in range(200):
        code = new_code()
        assert len(code) == CODE_LENGTH == 8 and all(ch in ALPHABET for ch in code)
    assert not set("iloul") & set(ALPHABET.replace("u", "")) and "o" not in ALPHABET and "l" not in ALPHABET


def test_codes_do_not_repeat_in_a_thousand_draws():
    assert len({new_code() for _ in range(1000)}) == 1000


@pytest.mark.parametrize("written,expected", [
    ("k7m2xq4p", "k7m2xq4p"),
    ("K7M2XQ4P", "k7m2xq4p"),
    ("k7m2-xq4p", "k7m2xq4p"),
    (" k7m2 xq4p ", "k7m2xq4p"),
    ("k7m2xq4O", "k7m2xq40"),  # a capital o for the digit zero
    ("k7m2xq4l", "k7m2xq41"),  # an l for the digit one
])
def test_what_a_person_or_a_model_may_have_made_of_a_code_is_read_as_the_code(written, expected):
    assert normalize(written) == expected


@pytest.mark.parametrize("bad", [None, 7, "", "k7m2xq4", "k7m2xq4p9", "k7m2xq4u", "k7m2xq4!", "x" * 100, [], {}])
def test_anything_else_is_not_a_code(bad):
    assert normalize(bad) is None


def test_other_lengths_use_the_same_reading():
    assert normalize_any("AB12-CD34-EFG", 11) == "ab12cd34efg"
    assert normalize_any("ab12cd34ef", 11) is None


def test_the_error_is_a_refusal_with_a_next_step_and_a_reason_only_the_log_sees():
    error = invalid("wrong_user")
    assert error.code is ErrorCode.INVALID_OFFER and error.reason == "wrong_user"
    assert "offer_id" in (error.hint or "") and "wrong_user" not in error.message
    assert error.next_step.why
