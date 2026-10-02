"""Table offers: the short ids that ``availability_check`` hands out and ``reservation_hold`` takes back (D-059).

An offer says "the server showed this slot to this user a moment ago". It used to be a 295-character signed token
that the assistant had to copy from one tool result into the next call. A speech model changed one character of it
and every hold was refused (measured on Amazon Nova 2 Sonic, docs/friction-log.md), so the claims now live in the
database and the assistant carries an id of eight characters, which the same model copied correctly in every trial.

The id is random (40 bits) and means nothing by itself: the offer item holds the restaurant, day, slot, party size,
slot version, the user it was shown to and its expiry. ``verify`` checks the user and the expiry; the DynamoDB
conditions of the hold still decide whether the slot is really free (``slot_ver`` detects a stale offer).
"""

import secrets
from dataclasses import dataclass

from server.domain.errors import ErrorCode, FairTableError

# Crockford's base32 without i, l, o and u: nothing that sounds like another symbol or looks like a digit.
ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"
CODE_LENGTH = 8
DEFAULT_TTL_S = 900
_LOOKALIKES = str.maketrans({"o": "0", "i": "1", "l": "1"})


@dataclass(frozen=True)
class SlotClaims:
    restaurant_id: str
    date: str  # ISO date, e.g. "2026-10-30"
    slot_key: str  # e.g. "1900#T2"
    party_size: int
    slot_ver: int
    sub: str  # the user the slot was offered to
    hot: bool = False
    drop_id: str | None = None


def new_code(length: int = CODE_LENGTH) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def normalize_any(raw: object, length: int) -> str | None:
    """What a person or a model may have made of a code: capitals, spaces, dashes, look-alike letters."""
    if not isinstance(raw, str) or len(raw) > 64:
        return None
    text = "".join(ch for ch in raw.lower() if ch.isalnum()).translate(_LOOKALIKES)
    return text if len(text) == length and all(ch in ALPHABET for ch in text) else None


def normalize(raw: object) -> str | None:
    return normalize_any(raw, CODE_LENGTH)


def invalid(reason: str) -> FairTableError:
    return FairTableError(
        ErrorCode.INVALID_OFFER,
        "That table offer is no longer valid.",
        hint="Use an offer_id from a fresh availability result.",
        reason=reason,
    )
