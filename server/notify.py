"""Notifier seam (docs/DECISIONS.md D-016, D-020): how a user is told that something happened while they were not in a conversation
(a waitlist match, a Fair Drop win).

The default is the *dev inbox*: a message stored in DynamoDB under ``INBOX#sub``, which the chat page
shows and the logs echo. It needs nothing outside the local stack. When ``NOTIFY_TOPIC_ARN`` is set (the AWS
profile), ``SnsNotifier`` also publishes the notice to that one SNS topic (D-054, task P3-12): the developer
subscribes their own e-mail address to it. There is no per-user address; a production service would need one
(SES or similar) and a user contact, which is stated as a limit.
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


class SnsNotifier:
    """Publish the notice to one SNS topic. ``client`` is a boto3 SNS client (a fake one in tests).

    Verified against botocore 1.43.104 (docs/PLAN.md section 3a): ``Publish(TopicArn, Message, Subject)``; ``Message``
    is required; ``Subject`` is shown by e-mail subscriptions, must be UTF-8 without line breaks or control
    characters and shorter than 100 characters. A notice holds no code, id or link (D-054), so ``url`` is not sent.
    Never raises: a notification must not break the request that triggered it.
    """

    MAX_SUBJECT = 99

    def __init__(self, client, topic_arn: str) -> None:
        if not topic_arn:
            raise ValueError("SnsNotifier needs a topic ARN")
        self._client = client
        self._topic_arn = topic_arn

    def notify(self, sub: str, *, subject: str, body: str, url: str = "") -> None:
        one_line = " ".join(subject.split())  # no line breaks or control characters
        try:
            self._client.publish(
                TopicArn=self._topic_arn, Subject=f"FairTable: {one_line}"[: self.MAX_SUBJECT], Message=body,
            )
        except Exception:
            log.exception("could not publish the notice %r to SNS", subject)


class FanoutNotifier:
    """Tell every notifier; one failing never stops the others."""

    def __init__(self, *notifiers: Notifier) -> None:
        self._notifiers = notifiers

    def notify(self, sub: str, *, subject: str, body: str, url: str = "") -> None:
        for notifier in self._notifiers:
            try:
                notifier.notify(sub, subject=subject, body=body, url=url)
            except Exception:
                log.exception("notifier %s failed", type(notifier).__name__)
