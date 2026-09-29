"""DynamoDB access. Every business state change is ONE ``TransactWriteItems`` (design section 5.4);
the conditions inside it are the final guarantee under concurrency. Never rely on DynamoDB TTL:
callers check ``expires_at`` on read.

Verified against DynamoDB Local 3.3.1 (docs/PLAN.md section 3a): ``CancellationReasons`` is
positional, one entry per item, and ``ReturnValuesOnConditionCheckFailure=ALL_OLD`` returns the
blocking item.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError

from server.domain.audit import AuditEntry
from server.domain.booking import Approval, Hold, Reservation
from server.domain.idempotency import IdempotencyRecord
from server.domain.models import Mandate, Slot, Venue
from server.store import keys
from server.store.mappers import (
    approval_to_item,
    hold_to_item,
    item_to_approval,
    item_to_hold,
    item_to_mandate,
    item_to_reservation,
    item_to_slot,
    item_to_venue,
    mandate_to_item,
    plain,
    reservation_to_item,
    slot_to_item,
    venue_to_item,
)

RETRYABLE_REASONS = frozenset({"TransactionConflict", "ThrottlingError"})
MAX_TX_ATTEMPTS = 4
BATCH_SIZE = 25


class ConditionFailed(Exception):
    """A single-item conditional write did not meet its condition."""


class StoreBusy(Exception):
    """A transaction kept conflicting with concurrent ones. Safe to retry the whole request."""


@dataclass(frozen=True)
class CancelReason:
    code: str  # "None" for a healthy item, "ConditionalCheckFailed", "TransactionConflict", ...
    item: dict[str, Any] | None = None  # the blocking item when the condition failed


class TransactionCancelled(Exception):
    """The transaction was cancelled and NOTHING was written."""

    def __init__(self, reasons: list[CancelReason]) -> None:
        super().__init__("transaction cancelled: " + ", ".join(r.code for r in reasons))
        self.reasons = reasons

    def failed_indexes(self) -> list[int]:
        return [i for i, r in enumerate(self.reasons) if r.code not in ("None", "")]


@dataclass
class TxOp:
    """One operation of a transaction, written with plain Python values."""

    kind: Literal["Put", "Update", "Delete", "ConditionCheck"]
    item: dict[str, Any] | None = None  # Put
    key: dict[str, str] | None = None  # Update / Delete / ConditionCheck
    update: str | None = None
    condition: str | None = None
    names: dict[str, str] = field(default_factory=dict)
    values: dict[str, Any] = field(default_factory=dict)


class Store:
    def __init__(
        self,
        client: Any,
        table_name: str,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._table = table_name
        self._ser = TypeSerializer()
        self._de = TypeDeserializer()
        self._sleep = sleep

    # ------------------------------------------------------------------ (de)serialisation
    def _to_av(self, item: dict[str, Any]) -> dict[str, Any]:
        return {k: self._ser.serialize(v) for k, v in item.items()}

    def _from_av(self, item: dict[str, Any]) -> dict[str, Any]:
        return plain({k: self._de.deserialize(v) for k, v in item.items()})

    def _expr(self, condition, names, values) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if condition:
            out["ConditionExpression"] = condition
        if names:
            out["ExpressionAttributeNames"] = names
        if values:
            out["ExpressionAttributeValues"] = self._to_av(values)
        return out

    # ------------------------------------------------------------------ generic access
    def get_item(self, key: keys.Key, *, consistent: bool = True) -> dict[str, Any] | None:
        response = self._client.get_item(
            TableName=self._table,
            Key=self._to_av({"PK": key.pk, "SK": key.sk}),
            ConsistentRead=consistent,
        )
        item = response.get("Item")
        return self._from_av(item) if item else None

    def put_item(
        self,
        item: dict[str, Any],
        *,
        condition: str | None = None,
        names: dict[str, str] | None = None,
        values: dict[str, Any] | None = None,
    ) -> None:
        try:
            self._client.put_item(
                TableName=self._table, Item=self._to_av(item), **self._expr(condition, names, values)
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ConditionFailed(condition) from e
            raise

    def query(
        self,
        pk: str,
        *,
        sk_prefix: str | None = None,
        sk_lte: str | None = None,
        index: str | None = None,
        consistent: bool = False,
    ) -> list[dict[str, Any]]:
        """All items with the partition value ``pk`` (paginated). ``index`` = "GSI1" / "GSI2"."""
        pk_attr = f"{index}PK" if index else "PK"
        sk_attr = f"{index}SK" if index else "SK"
        expr = "#p = :p"
        names = {"#p": pk_attr}
        values: dict[str, Any] = {":p": pk}
        if sk_prefix:
            expr += " AND begins_with(#s, :s)"
            names["#s"] = sk_attr
            values[":s"] = sk_prefix
        elif sk_lte:
            expr += " AND #s <= :s"
            names["#s"] = sk_attr
            values[":s"] = sk_lte
        params: dict[str, Any] = {
            "TableName": self._table,
            "KeyConditionExpression": expr,
            "ExpressionAttributeNames": names,
            "ExpressionAttributeValues": self._to_av(values),
        }
        if index:
            params["IndexName"] = index  # global indexes are eventually consistent
        else:
            params["ConsistentRead"] = consistent
        items: list[dict[str, Any]] = []
        while True:
            response = self._client.query(**params)
            items.extend(self._from_av(i) for i in response.get("Items", []))
            if "LastEvaluatedKey" not in response:
                return items
            params["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    def batch_put(self, items: list[dict[str, Any]]) -> None:
        """Unconditional bulk write (seeding). Not for business state changes."""
        for start in range(0, len(items), BATCH_SIZE):
            pending = {
                self._table: [
                    {"PutRequest": {"Item": self._to_av(i)}} for i in items[start : start + BATCH_SIZE]
                ]
            }
            for attempt in range(6):
                response = self._client.batch_write_item(RequestItems=pending)
                pending = response.get("UnprocessedItems") or {}
                if not pending:
                    break
                self._sleep(0.05 * (attempt + 1))
            else:
                raise StoreBusy("batch write kept returning unprocessed items")

    # ------------------------------------------------------------------ transactions
    def _tx_item(self, op: TxOp) -> dict[str, Any]:
        body: dict[str, Any] = {
            "TableName": self._table,
            **self._expr(op.condition, op.names, op.values),
        }
        if op.kind == "Put":
            body["Item"] = self._to_av(op.item or {})
        else:
            body["Key"] = self._to_av(op.key or {})
        if op.kind == "Update":
            body["UpdateExpression"] = op.update
        if op.condition:
            body["ReturnValuesOnConditionCheckFailure"] = "ALL_OLD"
        return {op.kind: body}

    def transact(self, ops: list[TxOp]) -> None:
        """Write everything or nothing. Raises ``TransactionCancelled`` when a condition fails and
        ``StoreBusy`` after repeated transaction conflicts (real DynamoDB; Local serialises)."""
        items = [self._tx_item(op) for op in ops]
        for attempt in range(MAX_TX_ATTEMPTS):
            try:
                self._client.transact_write_items(TransactItems=items)
                return
            except ClientError as e:
                code = e.response["Error"]["Code"]
                if code == "TransactionCanceledException":
                    reasons = [
                        CancelReason(
                            r.get("Code", "None"),
                            self._from_av(r["Item"]) if r.get("Item") else None,
                        )
                        for r in e.response.get("CancellationReasons", [])
                    ]
                    failing = {r.code for r in reasons if r.code not in ("None", "")}
                    if failing and failing <= RETRYABLE_REASONS:
                        self._sleep(0.02 * (attempt + 1))
                        continue
                    raise TransactionCancelled(reasons) from e
                if code in ("TransactionConflictException", "ThrottlingException"):
                    self._sleep(0.02 * (attempt + 1))
                    continue
                raise
        raise StoreBusy("transaction kept conflicting with concurrent writes")

    # ------------------------------------------------------------------ typed reads / seed writes
    def put_venue(self, venue: Venue) -> None:
        self.put_item(venue_to_item(venue))

    def get_venue(self, venue_id: str) -> Venue | None:
        item = self.get_item(keys.venue(venue_id), consistent=False)
        return item_to_venue(item) if item else None

    def list_venues(self) -> list[Venue]:
        return [item_to_venue(i) for i in self.query(keys.VENUE_DIRECTORY, index=keys.GSI1)]

    def get_slots(self, venue_id: str, date: str, *, consistent: bool = False) -> list[Slot]:
        items = self.query(keys.slot_day(venue_id, date), sk_prefix="SLOT#", consistent=consistent)
        return sorted((item_to_slot(i) for i in items), key=lambda s: (s.time, s.table_group))

    def get_slot(self, venue_id: str, date: str, time_: str, table_group: str) -> Slot | None:
        item = self.get_item(keys.slot(venue_id, date, time_, table_group))
        return item_to_slot(item) if item else None

    def put_mandate(self, mandate: Mandate) -> None:
        self.put_item(mandate_to_item(mandate))

    def get_mandate(self, sub: str, venue_id: str) -> Mandate | None:
        item = self.get_item(keys.mandate(sub, venue_id))
        return item_to_mandate(item) if item else None

    def put_slots(self, slots: list[Slot]) -> None:
        self.batch_put([slot_to_item(s) for s in slots])

    # ------------------------------------------------------------------ idempotency and audit
    def get_idempotency(self, sub: str, key: str) -> IdempotencyRecord | None:
        item = self.get_item(keys.idempotency(sub, key))
        if not item:
            return None
        return IdempotencyRecord(
            sub=item["sub"], key=item["key"], tool=item["tool"], params_hash=item["params_hash"],
            result=item["result"], created_at=item["created_at"],
        )

    @staticmethod
    def idempotency_op(record: IdempotencyRecord) -> TxOp:
        """Part of the business transaction: fails if this key was stored meanwhile."""
        k = keys.idempotency(record.sub, record.key)
        return TxOp(
            "Put",
            item={
                "PK": k.pk, "SK": k.sk, "entity": "idempotency", "sub": record.sub,
                "key": record.key, "tool": record.tool, "params_hash": record.params_hash,
                "result": record.result, "created_at": record.created_at,
            },
            condition="attribute_not_exists(PK)",
        )

    @staticmethod
    def _audit_item(entry: AuditEntry) -> dict[str, Any]:
        k = keys.audit(entry.venue_id, entry.date, entry.timestamp, entry.request_id)
        return {
            "PK": k.pk, "SK": k.sk, "entity": "audit", "venue_id": entry.venue_id,
            "sub": entry.sub, "agent_id": entry.agent_id, "tool": entry.tool,
            "decision": entry.decision, "rule_ids": list(entry.rule_ids), "detail": entry.detail,
            "at": entry.timestamp,
        }

    def audit_op(self, entry: AuditEntry) -> TxOp:
        return TxOp("Put", item=self._audit_item(entry))

    def put_audit(self, entry: AuditEntry) -> None:
        """Audit for decisions that change no state (denials, step-ups): a single best-effort put."""
        self.put_item(self._audit_item(entry))

    def list_audit(self, venue_id: str, date: str) -> list[dict[str, Any]]:
        return self.query(keys.audit_partition(venue_id, date), consistent=True)

    def scan_all(self) -> list[dict[str, Any]]:
        """Every item in the table. For tests, graders and diagnostics only (a full Scan)."""
        params: dict[str, Any] = {"TableName": self._table, "ConsistentRead": True}
        items: list[dict[str, Any]] = []
        while True:
            response = self._client.scan(**params)
            items.extend(self._from_av(i) for i in response.get("Items", []))
            if "LastEvaluatedKey" not in response:
                return items
            params["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    # ------------------------------------------------------------------ holds, reservations, approvals
    def get_hold(self, hold_id: str) -> Hold | None:
        item = self.get_item(keys.hold(hold_id))
        return item_to_hold(item) if item else None

    @staticmethod
    def hold_put_op(hold: Hold) -> TxOp:
        return TxOp("Put", item=hold_to_item(hold), condition="attribute_not_exists(PK)")

    def expired_holds_on_day(self, venue_id: str, date: str, now_iso: str) -> list[Hold]:
        """Held holds whose ``held_until`` has passed (GSI1 is sorted by expiry)."""
        items = self.query(
            keys.hold_day_partition(venue_id, date), sk_lte=f"{now_iso}#~", index=keys.GSI1
        )
        return [item_to_hold(i) for i in items]

    def holds_of_user(self, sub: str) -> list[Hold]:
        items = self.query(keys.user_partition(sub), sk_prefix="HOLD#", index=keys.GSI2)
        return [item_to_hold(i) for i in items]

    def get_reservation(self, reservation_id: str) -> Reservation | None:
        item = self.get_item(keys.reservation(reservation_id))
        return item_to_reservation(item) if item else None

    @staticmethod
    def reservation_put_op(reservation: Reservation) -> TxOp:
        return TxOp("Put", item=reservation_to_item(reservation), condition="attribute_not_exists(PK)")

    def reservations_of_user(self, sub: str) -> list[Reservation]:
        items = self.query(keys.user_partition(sub), sk_prefix="RES#", index=keys.GSI2)
        return [item_to_reservation(i) for i in items]

    def get_approval(self, subject_id: str) -> Approval | None:
        item = self.get_item(keys.approval(subject_id))
        return item_to_approval(item) if item else None

    def put_approval_if_absent(self, approval: Approval) -> bool:
        """True when created; False when an approval for this subject already exists."""
        try:
            self.put_item(approval_to_item(approval), condition="attribute_not_exists(PK)")
            return True
        except ConditionFailed:
            return False

    def replace_approval(self, approval: Approval) -> None:
        self.put_item(approval_to_item(approval))

    def put_inbox(self, sub: str, timestamp: str, message_id: str, message: dict[str, Any]) -> None:
        k = keys.inbox(sub, timestamp, message_id)
        self.put_item({"PK": k.pk, "SK": k.sk, "entity": "inbox", "sub": sub, **message})

    def list_inbox(self, sub: str) -> list[dict[str, Any]]:
        return self.query(keys.inbox_partition(sub), consistent=True)
