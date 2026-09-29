"""Signed, expiring, user-bound slot tokens handed out by ``availability_check``.

Format: ``base64url(payload_json).base64url(HMAC-SHA256(secret, payload_b64))``. The token proves
that the server offered this slot to this user recently; the DynamoDB conditions still decide
whether the slot is really free (``ver`` lets the write detect a stale offer).
"""

import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass

from server.domain.clock import Clock, epoch_seconds
from server.domain.errors import ErrorCode, FairTableError

TOKEN_VERSION = 1
MIN_SECRET_BYTES = 32
MAX_TOKEN_CHARS = 2048
DEFAULT_TTL_S = 900


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


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _invalid(reason: str) -> FairTableError:
    return FairTableError(
        ErrorCode.INVALID_SLOT_TOKEN,
        "The slot_token is not valid.",
        reason=reason,
    )


class SlotTokenCodec:
    def __init__(self, secret: bytes, clock: Clock, ttl_s: int = DEFAULT_TTL_S) -> None:
        if len(secret) < MIN_SECRET_BYTES:
            raise ValueError(f"slot token secret must be at least {MIN_SECRET_BYTES} bytes")
        if ttl_s <= 0:
            raise ValueError("ttl_s must be positive")
        self._secret = secret
        self._clock = clock
        self._ttl_s = ttl_s

    def _mac(self, payload_b64: str) -> str:
        return _b64e(hmac.new(self._secret, payload_b64.encode("ascii"), hashlib.sha256).digest())

    def issue(self, claims: SlotClaims) -> str:
        now = epoch_seconds(self._clock)
        body = {
            "v": TOKEN_VERSION,
            "rid": claims.restaurant_id,
            "date": claims.date,
            "slot": claims.slot_key,
            "party": claims.party_size,
            "ver": claims.slot_ver,
            "sub": claims.sub,
            "hot": claims.hot,
            "drop": claims.drop_id,
            "iat": now,
            "exp": now + self._ttl_s,
        }
        payload = _b64e(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())
        return f"{payload}.{self._mac(payload)}"

    def verify(self, token: str, *, sub: str) -> SlotClaims:
        if not isinstance(token, str) or not token or len(token) > MAX_TOKEN_CHARS:
            raise _invalid("malformed")
        parts = token.split(".")
        if len(parts) != 2:
            raise _invalid("malformed")
        payload, mac = parts
        if not payload.isascii() or not mac.isascii():
            raise _invalid("malformed")
        if not hmac.compare_digest(mac.encode(), self._mac(payload).encode()):
            raise _invalid("bad_signature")
        try:
            body = json.loads(_b64d(payload))
            if body["v"] != TOKEN_VERSION:
                raise _invalid("unsupported_version")
            exp = int(body["exp"])
            claims = SlotClaims(
                restaurant_id=body["rid"],
                date=body["date"],
                slot_key=body["slot"],
                party_size=int(body["party"]),
                slot_ver=int(body["ver"]),
                sub=body["sub"],
                hot=bool(body["hot"]),
                drop_id=body["drop"],
            )
        except FairTableError:
            raise
        except (KeyError, ValueError, TypeError, binascii.Error):
            raise _invalid("malformed_payload") from None
        if epoch_seconds(self._clock) >= exp:
            raise FairTableError(
                ErrorCode.SLOT_TOKEN_EXPIRED,
                "The slot_token has expired.",
                reason="expired",
            )
        if not hmac.compare_digest(claims.sub.encode(), sub.encode()):
            raise _invalid("wrong_user")
        return claims
