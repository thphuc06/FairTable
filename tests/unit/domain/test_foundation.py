"""P1-1: error codes, success helper, clock, identity model."""

from datetime import UTC, datetime, timedelta

import pytest

from server.domain.clock import FakeClock, SystemClock, epoch_seconds
from server.domain.errors import DEFAULT_NEXT_STEP, ErrorCode, FairTableError, NextStep
from server.domain.models import SCOPE_BOOK, Identity
from server.domain.output import MAX_SPOKEN_CHARS, success
from server.domain.tool_names import READ_TOOLS, WRITE_TOOLS, ToolName


# ---------------------------------------------------------------- tool names
def test_seven_tools_split_into_reads_and_writes():
    assert len(ToolName) == 7
    assert READ_TOOLS | WRITE_TOOLS == set(ToolName)
    assert not READ_TOOLS & WRITE_TOOLS
    assert ToolName.WAITLIST_STATUS in READ_TOOLS  # the polling path is a read
    assert ToolName.WAITLIST_WATCH in WRITE_TOOLS


# ---------------------------------------------------------------- errors
def test_every_error_code_has_a_default_next_step():
    assert set(DEFAULT_NEXT_STEP) == set(ErrorCode)


@pytest.mark.parametrize("code", list(ErrorCode))
def test_every_error_payload_has_error_message_and_next_step(code):
    payload = FairTableError(code, "boom").to_payload()
    assert payload["error"] == code.value
    assert payload["message"] == "boom"
    assert payload["next_step"]["why"]
    assert "tool" in payload["next_step"]


def test_error_payload_carries_optional_fields_only_when_set():
    bare = FairTableError(ErrorCode.SLOT_TAKEN, "gone").to_payload()
    assert set(bare) == {"error", "message", "next_step"}

    full = FairTableError(
        ErrorCode.POLICY_DENIED,
        "no",
        hint="call the venue",
        rule_id="S2_agent_share_of_covers",
        retry_after_s=60,
        next_step=NextStep("join the waitlist", ToolName.WAITLIST_WATCH),
    ).to_payload()
    assert full["hint"] == "call the venue"
    assert full["rule_id"] == "S2_agent_share_of_covers"
    assert full["retry_after_s"] == 60
    assert full["next_step"] == {"tool": "waitlist_watch", "why": "join the waitlist"}


def test_internal_reason_is_never_sent_to_the_agent():
    err = FairTableError(ErrorCode.UNAUTHENTICATED, "Invalid token.", reason="bad_signature")
    assert err.reason == "bad_signature"
    assert "bad_signature" not in str(err.to_payload())


def test_rate_limited_default_points_to_waitlist_watch():
    step = FairTableError(ErrorCode.RATE_LIMITED, "slow down", retry_after_s=60).next_step
    assert step.tool is ToolName.WAITLIST_WATCH


# ---------------------------------------------------------------- success helper
def test_success_requires_spoken_summary():
    out = success("Two tables are free at seven.", slots=[1, 2])
    assert out == {"spoken_summary": "Two tables are free at seven.", "slots": [1, 2]}


@pytest.mark.parametrize("bad", ["", "   ", None, 5])
def test_success_rejects_missing_or_blank_summary(bad):
    with pytest.raises(ValueError):
        success(bad)


def test_success_rejects_overlong_summary():
    with pytest.raises(ValueError):
        success("x" * (MAX_SPOKEN_CHARS + 1))


# ---------------------------------------------------------------- clock
def test_fake_clock_is_deterministic_and_utc():
    clock = FakeClock(datetime(2026, 10, 1, 12, 0, tzinfo=UTC))
    start = clock.now()
    clock.advance(seconds=90)
    assert clock.now() - start == timedelta(seconds=90)
    clock.advance(minutes=10)
    assert clock.now() - start == timedelta(seconds=90, minutes=10)
    assert clock.now().tzinfo is not None


def test_fake_clock_rejects_naive_datetimes():
    with pytest.raises(ValueError):
        FakeClock(datetime(2026, 10, 1, 12, 0))  # noqa: DTZ001
    with pytest.raises(ValueError):
        FakeClock().set(datetime(2026, 10, 1, 12, 0))  # noqa: DTZ001


def test_epoch_seconds_and_system_clock():
    assert epoch_seconds(FakeClock(datetime(1970, 1, 1, 0, 1, tzinfo=UTC))) == 60
    assert SystemClock().now().tzinfo is not None


# ---------------------------------------------------------------- identity
def test_identity_flags():
    user = Identity(
        sub="u1", username="alice", agent_tier="verified", scopes=frozenset({SCOPE_BOOK})
    )
    assert user.is_user and user.is_verified_agent and user.has_scope(SCOPE_BOOK)

    bot = Identity(sub="bot", scopes=frozenset({SCOPE_BOOK}))
    assert not bot.is_user and not bot.is_verified_agent

    assert not Identity(sub="x", agent_tier="unverified").is_verified_agent
