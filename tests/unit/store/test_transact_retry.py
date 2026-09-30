"""P1-6: how ``Store.transact`` reacts to cancellations. A scripted fake client stands in for
DynamoDB so the retry rules can be checked exactly (the real behaviour is in the ddb tests)."""

import pytest
from botocore.exceptions import ClientError

from server.store import Store, StoreBusy, TransactionCancelled, TxOp
from server.store.repository import MAX_TX_ATTEMPTS, TX_BACKOFF_CAP_S


def cancelled(*codes: str) -> ClientError:
    reasons = [{"Code": c} for c in codes]
    return ClientError(
        {"Error": {"Code": "TransactionCanceledException", "Message": "x"}, "CancellationReasons": reasons},
        "TransactWriteItems",
    )


def error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "x"}}, "TransactWriteItems")


class ScriptedClient:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def transact_write_items(self, **_):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return {}


OPS = [TxOp("Put", item={"PK": "a", "SK": "b"}, condition="attribute_not_exists(PK)")]


def store(client):
    return Store(client, "t", sleep=lambda _s: None)


def test_success_needs_one_call():
    client = ScriptedClient(None)
    store(client).transact(OPS)
    assert client.calls == 1


def test_condition_failure_is_not_retried_and_names_the_failing_item():
    client = ScriptedClient(cancelled("None", "ConditionalCheckFailed", "None"))
    with pytest.raises(TransactionCancelled) as exc:
        store(client).transact(OPS)
    assert client.calls == 1
    assert exc.value.failed_indexes() == [1]


def test_transient_conflicts_are_retried_then_succeed():
    client = ScriptedClient(cancelled("TransactionConflict"), error("TransactionConflictException"), None)
    store(client).transact(OPS)
    assert client.calls == 3


def test_persistent_conflict_becomes_store_busy():
    client = ScriptedClient(*[cancelled("TransactionConflict")] * MAX_TX_ATTEMPTS)
    with pytest.raises(StoreBusy):
        store(client).transact(OPS)
    assert client.calls == MAX_TX_ATTEMPTS


def test_retries_wait_with_jitter_and_never_longer_than_the_cap():
    waits: list[float] = []
    client = ScriptedClient(*[cancelled("TransactionConflict")] * MAX_TX_ATTEMPTS)
    with pytest.raises(StoreBusy):
        Store(client, "t", sleep=waits.append).transact(OPS)
    assert len(waits) == MAX_TX_ATTEMPTS  # one wait after every failed attempt
    assert all(0 <= w <= TX_BACKOFF_CAP_S for w in waits)
    assert len(set(waits)) > 1  # random, not a fixed ladder


def test_a_real_failure_mixed_with_a_conflict_is_not_retried():
    client = ScriptedClient(cancelled("ConditionalCheckFailed", "TransactionConflict"))
    with pytest.raises(TransactionCancelled):
        store(client).transact(OPS)
    assert client.calls == 1


def test_unknown_errors_propagate():
    client = ScriptedClient(error("ValidationException"))
    with pytest.raises(ClientError):
        store(client).transact(OPS)


class BatchClient:
    """Records the batches it gets; ``fail_on`` makes one of them raise."""

    def __init__(self, fail_on: int | None = None):
        self.seen: list[list[str]] = []
        self.fail_on = fail_on

    def batch_write_item(self, RequestItems, **_):  # noqa: N803 (boto3 spelling)
        (requests,) = RequestItems.values()
        self.seen.append([r["PutRequest"]["Item"]["PK"]["S"] for r in requests])
        if self.fail_on is not None and len(self.seen) == self.fail_on:
            raise error("ValidationException")
        return {}


def test_batch_put_writes_every_item_once_in_batches_of_25():
    client = BatchClient()
    store(client).batch_put([{"PK": f"K{i}", "SK": "x"} for i in range(130)])
    written = [pk for batch in client.seen for pk in batch]
    assert sorted(written) == sorted(f"K{i}" for i in range(130))
    assert max(len(b) for b in client.seen) == 25 and len(client.seen) == 6


def test_batch_put_raises_the_first_error_from_any_batch():
    with pytest.raises(ClientError):
        store(BatchClient(fail_on=3)).batch_put([{"PK": f"K{i}", "SK": "x"} for i in range(130)])
