"""P1-6: how ``Store.transact`` reacts to cancellations. A scripted fake client stands in for
DynamoDB so the retry rules can be checked exactly (the real behaviour is in the ddb tests)."""

import pytest
from botocore.exceptions import ClientError

from server.store import Store, StoreBusy, TransactionCancelled, TxOp


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
    client = ScriptedClient(*[cancelled("TransactionConflict")] * 4)
    with pytest.raises(StoreBusy):
        store(client).transact(OPS)
    assert client.calls == 4


def test_a_real_failure_mixed_with_a_conflict_is_not_retried():
    client = ScriptedClient(cancelled("ConditionalCheckFailed", "TransactionConflict"))
    with pytest.raises(TransactionCancelled):
        store(client).transact(OPS)
    assert client.calls == 1


def test_unknown_errors_propagate():
    client = ScriptedClient(error("ValidationException"))
    with pytest.raises(ClientError):
        store(client).transact(OPS)
