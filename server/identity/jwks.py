"""JWKS providers. The verifier only sees the ``JwksProvider`` interface, so the dev issuer, a test
key set and Cognito differ by configuration (URL), not by code (docs/DECISIONS.md D-007)."""

import threading
from typing import Any, Protocol

import httpx
from joserfc.jwk import KeySet

from server.domain.clock import Clock


class JwksUnavailable(Exception):
    """The key set cannot be fetched and nothing usable is cached. Callers must fail closed."""


class JwksProvider(Protocol):
    def key_set(self, *, refresh: bool = False) -> KeySet:
        """Current keys. ``refresh=True`` asks for a re-fetch (for example an unknown ``kid``)."""
        ...


class StaticJwks:
    """A fixed key set: tests, and issuers whose keys are provisioned with the deployment."""

    def __init__(self, keys: KeySet | dict[str, Any]) -> None:
        self._keys = keys if isinstance(keys, KeySet) else KeySet.import_key_set(keys)

    def key_set(self, *, refresh: bool = False) -> KeySet:
        return self._keys


class HttpJwks:
    """Fetches ``{"keys": [...]}`` from a URL, caches it, and survives a temporary outage."""

    def __init__(
        self,
        url: str,
        clock: Clock,
        *,
        ttl_s: int = 600,
        min_refresh_s: int = 30,
        timeout_s: float = 3.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._url = url
        self._clock = clock
        self._ttl_s = ttl_s
        self._min_refresh_s = min_refresh_s
        self._client = client or httpx.Client(timeout=timeout_s)
        self._lock = threading.Lock()
        self._cached: KeySet | None = None
        self._fetched_at = 0.0

    def _age(self) -> float:
        return self._clock.now().timestamp() - self._fetched_at

    def key_set(self, *, refresh: bool = False) -> KeySet:
        with self._lock:
            if self._cached is not None:
                fresh = self._age() < self._ttl_s
                throttled = refresh and self._age() < self._min_refresh_s
                if (fresh and not refresh) or throttled:
                    return self._cached
            try:
                response = self._client.get(self._url)
                response.raise_for_status()
                fetched = KeySet.import_key_set(response.json())
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
                if self._cached is not None:  # stale-if-error: keep serving the last good keys
                    return self._cached
                raise JwksUnavailable(f"cannot fetch JWKS from {self._url}: {e}") from e
            self._cached = fetched
            self._fetched_at = self._clock.now().timestamp()
            return fetched
