"""Signed session cookie and CSRF tokens using only the standard library (HMAC-SHA256).

The cookie carries ``sub``, ``username`` and an expiry, signed with a server secret. It is
HttpOnly and SameSite=Lax. The CSRF token is bound to the user *and* to the approval being decided,
so a token for one approval cannot be replayed on another.
"""

import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass

from server.domain.clock import Clock, epoch_seconds

COOKIE_NAME = "ft_session"
DEFAULT_TTL_S = 3600


@dataclass(frozen=True)
class Session:
    sub: str
    username: str
    expires_at: int
    owner_of: str | None = None  # venue an owner may manage; None for diners


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class SessionCodec:
    def __init__(self, secret: str, clock: Clock, ttl_s: int = DEFAULT_TTL_S) -> None:
        if len(secret) < 16:
            raise ValueError("the session secret must be at least 16 characters")
        self._key = secret.encode()
        self._clock = clock
        self.ttl_s = ttl_s

    def _mac(self, data: str) -> str:
        return _b64e(hmac.new(self._key, data.encode("ascii"), hashlib.sha256).digest())

    def issue(self, sub: str, username: str, owner_of: str | None = None) -> str:
        body = {"sub": sub, "usr": username, "exp": epoch_seconds(self._clock) + self.ttl_s}
        if owner_of:
            body["own"] = owner_of
        payload = _b64e(json.dumps(body, separators=(",", ":")).encode())
        return f"{payload}.{self._mac(payload)}"

    def read(self, cookie: str | None) -> Session | None:
        """The session, or None for anything missing, forged, malformed or expired."""
        if not cookie or len(cookie) > 2048 or cookie.count(".") != 1 or not cookie.isascii():
            return None
        payload, mac = cookie.split(".")
        if not hmac.compare_digest(mac.encode(), self._mac(payload).encode()):
            return None
        try:
            body = json.loads(_b64d(payload))
            owner = body.get("own")
            session = Session(sub=str(body["sub"]), username=str(body["usr"]), expires_at=int(body["exp"]),
                              owner_of=str(owner) if owner else None)
        except (KeyError, ValueError, TypeError, binascii.Error):
            return None
        return session if session.expires_at > epoch_seconds(self._clock) else None

    def csrf_token(self, session: Session, subject_id: str) -> str:
        return self._mac(f"csrf|{session.sub}|{subject_id}")

    def csrf_ok(self, session: Session, subject_id: str, token: str | None) -> bool:
        return bool(token) and hmac.compare_digest(
            str(token).encode(), self.csrf_token(session, subject_id).encode()
        )
