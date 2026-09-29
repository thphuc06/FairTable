"""Standing-mandate checks (pure). Cedar only sees the boolean ``mandate_covers_booking``; the
reasoning lives here so it is testable and can be explained to the agent (``mandate_status``)."""

from dataclasses import dataclass
from datetime import date, datetime

from server.domain.models import MANDATE_ACTIVE, Mandate


@dataclass(frozen=True)
class MandateCheck:
    covered: bool
    reasons: tuple[str, ...] = ()  # why the booking is outside the mandate (plain English)


def _parse(moment: str) -> datetime:
    return datetime.fromisoformat(moment)


def is_active(mandate: Mandate | None, now: datetime) -> bool:
    """Active means: status active AND not past ``expires_at`` (checked on every read)."""
    return (
        mandate is not None
        and mandate.status == MANDATE_ACTIVE
        and now < _parse(mandate.expires_at)
    )


def check_mandate(
    mandate: Mandate | None,
    *,
    now: datetime,
    agent_id: str | None,
    party_size: int,
    day: date,
    time: str,
    cancel_fee_cents: int,
) -> MandateCheck:
    """Would confirming this booking need the user's approval? Empty ``reasons`` = covered."""
    if mandate is None:
        return MandateCheck(False, ("there is no standing permission for this restaurant",))
    if not is_active(mandate, now):
        return MandateCheck(False, ("the standing permission is revoked or expired",))
    reasons: list[str] = []
    if mandate.agent_ids and agent_id not in mandate.agent_ids:
        reasons.append("this agent is not on the permission")
    if "confirm" not in mandate.actions or not mandate.allow_auto_confirm:
        reasons.append("the permission does not allow confirming without asking")
    if party_size > mandate.party_size_max:
        reasons.append(f"the party is larger than {mandate.party_size_max}")
    days_ahead = (day - now.date()).days
    if days_ahead < 0 or days_ahead > mandate.days_ahead_max:
        reasons.append(f"the date is more than {mandate.days_ahead_max} days ahead")
    if not mandate.window_start <= time <= mandate.window_end:
        reasons.append(f"the time is outside {mandate.window_start}-{mandate.window_end}")
    if cancel_fee_cents > mandate.max_cancel_fee_cents:
        reasons.append("the cancellation fee is above what was allowed")
    return MandateCheck(not reasons, tuple(reasons))


def mandate_covers_booking(mandate: Mandate | None, **kwargs) -> bool:
    return check_mandate(mandate, **kwargs).covered
