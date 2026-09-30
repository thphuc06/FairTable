"""Notifier seam (docs/DECISIONS.md D-016, D-020): how a user is told that an approval is waiting.

The default is the *dev inbox*: a message stored in DynamoDB under ``INBOX#sub``, which the chat page
shows and the logs echo. It needs nothing outside the local stack. An SNS implementation (email or
SMS) is a later option for the AWS profile and would implement the same protocol.
"""

import logging
from typing import Protocol

from server.domain.clock import Clock, iso_z
from server.store import Store

log = logging.getLogger("fairtable.notify")


class Notifier(Protocol):
    def notify(self, sub: str, *, subject: str, body: str, url: str = "") -> None: ...


class DevInboxNotifier:
    def __init__(self, store: Store, clock: Clock, new_id) -> None:
        self._store = store
        self._clock = clock
        self._new_id = new_id

    def notify(self, sub: str, *, subject: str, body: str, url: str = "") -> None:
        log.info("notify %s: %s -> %s", sub, subject, url)
        try:
            self._store.put_inbox(
                sub, iso_z(self._clock.now()), self._new_id(),
                {"subject": subject, "body": body, "url": url},
            )
        except Exception:
            log.exception("could not store the inbox message for %s", sub)
