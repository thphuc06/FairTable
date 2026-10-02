"""Read-back tokens: the server's side of a spoken confirmation (docs/DECISIONS.md D-051, D-054).

A booking (or a cancellation with a fee) is confirmed by the diner's spoken yes, which the assistant relays.
The server cannot hear the diner. What it can do is make the relay honest about the basics:

* the terms the diner is asked about are exactly the terms that get booked (the token binds them);
* the token was handed out for *this* user and *this* hold or reservation (nobody else's will do);
* a pause has passed since the token was handed over, so the assistant cannot have asked and got an
  answer in the same breath.

None of this proves that the diner said yes: a model that lies on purpose can wait and send the token.
These checks stop mistakes, not lies. The code is eleven characters long because a speech model could not copy a long
signed token (D-059).
"""

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from server.domain.booking import terms_hash
from server.domain.clock import Clock
from server.domain.offers import ALPHABET, normalize_any

KIND_CONFIRM = "confirm"
KIND_CANCEL_FEE = "cancel_fee"

MIN_PAUSE_S = 3  # the diner needs a moment to hear the terms and answer
MIN_PAUSE_WITH_FEE_S = 6  # longer when money is involved
MAX_AGE_S = {KIND_CONFIRM: 3 * 3600, KIND_CANCEL_FEE: 15 * 60}  # a stale read-back is not a read-back
MIN_SECRET_BYTES = 32
TOKEN_VERSION = 2
UNIT_MS = 500  # the moment of issue is kept in half seconds, rounded up (a pause is never counted short)
TIME_CHARS = 3  # that count modulo 32**3 = 32768 half seconds (4.5 hours), longer than the longest age
MAC_CHARS = 8  # 40 bits of HMAC
CODE_CHARS = TIME_CHARS + MAC_CHARS
SKEW_S = 5  # clocks of two instances may differ a little


def min_pause_s(fee_cents: int) -> int:
    return MIN_PAUSE_WITH_FEE_S if fee_cents > 0 else MIN_PAUSE_S


def pause_elapsed(issued_at_ms: int | None, now: datetime, min_pause: int) -> bool:
    return issued_at_ms is not None and now.timestamp() * 1000 - issued_at_ms >= min_pause * 1000


@dataclass(frozen=True)
class ReadBackCheck:
    matches: bool  # the token is ours, fresh, and for these terms, this user and this subject
    issued_at_ms: int | None = None


NO_MATCH = ReadBackCheck(False)


def _encode(value: int, chars: int) -> str:
    out = []
    for _ in range(chars):
        out.append(ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(out))


def _decode(text: str) -> int:
    value = 0
    for ch in text:
        value = (value << 5) | ALPHABET.index(ch)
    return value


class ReadBackCodec:
    """Eleven characters: the moment of issue in half seconds (3) and 40 bits of an HMAC over the kind, the subject,
    the user, the terms and that moment (8). A speech model copies eleven characters correctly; it did not copy 200
    (D-059). The moment is recovered from the three characters (it is the latest one, not in the future, with those
    low bits), so the pause and the age are measured without storing anything. It is rounded up to the next half
    second, so a pause can be at most half a second longer than asked, never shorter."""

    def __init__(self, secret: bytes, clock: Clock) -> None:
        if len(secret) < MIN_SECRET_BYTES:
            raise ValueError(f"read-back secret must be at least {MIN_SECRET_BYTES} bytes")
        self._secret = secret
        self._clock = clock

    def _now_ms(self) -> int:
        return int(self._clock.now().timestamp() * 1000)

    def _mac(self, kind: str, subject_id: str, sub: str, terms: dict[str, Any], unit: int) -> str:
        message = f"{TOKEN_VERSION}|{kind}|{subject_id}|{sub}|{terms_hash(terms)}|{unit}".encode()
        digest = hmac.new(self._secret, message, hashlib.sha256).digest()[: MAC_CHARS * 5 // 8]
        return _encode(int.from_bytes(digest, "big"), MAC_CHARS)

    def issue(self, *, kind: str, subject_id: str, sub: str, terms: dict[str, Any]) -> str:
        unit = -(-self._now_ms() // UNIT_MS)  # rounded up
        return _encode(unit % 32**TIME_CHARS, TIME_CHARS) + self._mac(kind, subject_id, sub, terms, unit)

    def check(self, token: object, *, kind: str, subject_id: str, sub: str, terms: dict[str, Any]) -> ReadBackCheck:
        """Never raises: a code that does not fit simply does not match."""
        code = normalize_any(token, CODE_CHARS)
        if code is None:
            return NO_MATCH
        now_ms = self._now_ms()
        now_unit = now_ms // UNIT_MS
        modulus = 32**TIME_CHARS
        low = _decode(code[:TIME_CHARS])
        latest = now_unit - ((now_unit - low) % modulus)  # the latest moment with these low bits
        for unit in (latest, latest + modulus):
            age_s = (now_ms - unit * UNIT_MS) / 1000
            if age_s < -SKEW_S or age_s > MAX_AGE_S[kind]:
                continue
            if hmac.compare_digest(code[TIME_CHARS:], self._mac(kind, subject_id, sub, terms, unit)):
                return ReadBackCheck(True, unit * UNIT_MS)
        return NO_MATCH
