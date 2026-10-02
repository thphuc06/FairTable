"""Where the audit of a finished Fair Drop is published (D-062, plan task P3-15).

The audit (seed, hashed tickets, order, algorithm) is stored with the drop in DynamoDB and served as the resource
``fairtable://drops/{drop_id}/audit``. With ``AUDIT_BUCKET`` set (the AWS profile) the same JSON is also written to
S3, so that anyone who is given the object can recompute the result without calling the server. The copy is
best effort: DynamoDB stays the source of truth, a failed upload is logged and never fails the draw.
"""

import json
import logging
from typing import Any, Protocol

log = logging.getLogger("fairtable.audit_sink")
PREFIX = "drops/"


class AuditSink(Protocol):
    def publish(self, drop_id: str, audit: dict[str, Any]) -> str | None:
        """Write the audit somewhere public enough to verify it. Returns where, or None when nothing was written."""


class NullAuditSink:
    def publish(self, drop_id: str, audit: dict[str, Any]) -> str | None:
        return None


class S3AuditSink:
    """One JSON object per drop: ``s3://<bucket>/drops/<drop_id>.json`` (same bytes on every call: sorted keys)."""

    def __init__(self, client: Any, bucket: str) -> None:
        self._client, self._bucket = client, bucket

    def key_of(self, drop_id: str) -> str:
        return f"{PREFIX}{drop_id}.json"

    def publish(self, drop_id: str, audit: dict[str, Any]) -> str | None:
        key = self.key_of(drop_id)
        body = json.dumps(audit, sort_keys=True, indent=2).encode()
        try:
            self._client.put_object(Bucket=self._bucket, Key=key, Body=body, ContentType="application/json")
        except Exception:  # noqa: BLE001 - boto raises many types; the draw must not fail over a copy
            log.exception("could not write the audit of %s to s3://%s/%s", drop_id, self._bucket, key)
            return None
        return f"s3://{self._bucket}/{key}"
