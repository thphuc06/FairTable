"""P0-4: DynamoDB Local spike.

Proves, against DynamoDB Local (no moto):
  1. A 5-item TransactWriteItems with one failing condition cancels everything, and
     ``CancellationReasons`` identifies the failing item by index.
  2. 20 threads racing for one slot produce exactly one success and no orphan writes.
  3. 20 threads racing for a counter with capacity 3 produce exactly three successes.

Run:  docker compose -f infra/local/docker-compose.yml up -d
      pytest -m ddb tests/integration/test_ddb_spike.py
The endpoint comes from DDB_ENDPOINT (default http://localhost:8000). Tests skip if it is unreachable.
"""

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import boto3
import pytest
from botocore.config import Config
from botocore.exceptions import ClientError, EndpointConnectionError

pytestmark = pytest.mark.ddb

ENDPOINT = os.environ.get("DDB_ENDPOINT", "http://localhost:8000")
REGION = os.environ.get("AWS_REGION", "us-east-1")  # dummy for Local; never hard-coded in server code
THREADS = 20


def make_client():
    # DynamoDB Local ignores credentials; explicit dummy values keep the test independent of ~/.aws.
    return boto3.client(
        "dynamodb",
        endpoint_url=ENDPOINT,
        region_name=REGION,
        aws_access_key_id="local",
        aws_secret_access_key="local",
        config=Config(retries={"max_attempts": 1}, connect_timeout=2, read_timeout=10),
    )


@pytest.fixture(scope="module")
def ddb():
    client = make_client()
    try:
        client.list_tables()
    except (EndpointConnectionError, ClientError, OSError) as e:  # pragma: no cover
        pytest.skip(f"DynamoDB Local not reachable at {ENDPOINT}: {e}")
    return client


@pytest.fixture
def table(ddb):
    name = f"ft-spike-{uuid.uuid4().hex[:8]}"
    ddb.create_table(
        TableName=name,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
    )
    ddb.get_waiter("table_exists").wait(TableName=name)
    yield name
    ddb.delete_table(TableName=name)


def S(v):
    return {"S": v}


def N(v):
    return {"N": str(v)}


def exists(ddb, table, pk, sk="META"):
    return "Item" in ddb.get_item(TableName=table, Key={"pk": S(pk), "sk": S(sk)}, ConsistentRead=True)


def cancellation_codes(err: ClientError) -> list[str]:
    return [r["Code"] for r in err.response["CancellationReasons"]]


# ---------------------------------------------------------------- 1. atomic cancel + failing item
def five_item_transaction(table, *, hold_id, max_holds):
    """slot (must be free) / counter (< max) / hold / idempotency record / audit."""
    return [
        {"Put": {"TableName": table, "Item": {"pk": S("SLOT#luna#19:00"), "sk": S("META"), "hold": S(hold_id)},
                 "ConditionExpression": "attribute_not_exists(pk)",
                 "ReturnValuesOnConditionCheckFailure": "ALL_OLD"}},
        {"Update": {"TableName": table, "Key": {"pk": S("COUNTER#alice#luna"), "sk": S("META")},
                    "UpdateExpression": "ADD active_holds :one",
                    "ConditionExpression": "attribute_not_exists(active_holds) OR active_holds < :max",
                    "ExpressionAttributeValues": {":one": N(1), ":max": N(max_holds)},
                    "ReturnValuesOnConditionCheckFailure": "ALL_OLD"}},
        {"Put": {"TableName": table, "Item": {"pk": S(f"HOLD#{hold_id}"), "sk": S("META")},
                 "ConditionExpression": "attribute_not_exists(pk)"}},
        {"Put": {"TableName": table, "Item": {"pk": S(f"IDEM#alice#{hold_id}"), "sk": S("META")},
                 "ConditionExpression": "attribute_not_exists(pk)"}},
        {"Put": {"TableName": table, "Item": {"pk": S(f"AUDIT#{hold_id}"), "sk": S("META")}}},
    ]


def test_five_item_transaction_succeeds_when_all_conditions_hold(ddb, table):
    ddb.transact_write_items(TransactItems=five_item_transaction(table, hold_id="h1", max_holds=2))
    for pk in ("SLOT#luna#19:00", "COUNTER#alice#luna", "HOLD#h1", "IDEM#alice#h1", "AUDIT#h1"):
        assert exists(ddb, table, pk), pk


def test_one_failing_condition_cancels_all_five_and_names_the_failing_item(ddb, table):
    # Pre-fill the counter to the cap so item index 1 (the counter) fails, while item 0 (slot) would pass.
    ddb.put_item(TableName=table, Item={"pk": S("COUNTER#alice#luna"), "sk": S("META"), "active_holds": N(2)})

    with pytest.raises(ClientError) as exc:
        ddb.transact_write_items(TransactItems=five_item_transaction(table, hold_id="h2", max_holds=2))

    err = exc.value
    assert err.response["Error"]["Code"] == "TransactionCanceledException"
    codes = cancellation_codes(err)
    assert len(codes) == 5
    assert codes[1] == "ConditionalCheckFailed"
    assert [c for i, c in enumerate(codes) if i != 1] == ["None"] * 4
    # ReturnValuesOnConditionCheckFailure=ALL_OLD returns the item that blocked us (the counter).
    assert err.response["CancellationReasons"][1]["Item"]["active_holds"] == N(2)

    # Atomic: nothing from the other four items was written.
    for pk in ("SLOT#luna#19:00", "HOLD#h2", "IDEM#alice#h2", "AUDIT#h2"):
        assert not exists(ddb, table, pk), f"{pk} leaked out of a cancelled transaction"
    counter = ddb.get_item(TableName=table, Key={"pk": S("COUNTER#alice#luna"), "sk": S("META")})
    assert counter["Item"]["active_holds"] == N(2)  # unchanged


def test_failing_slot_condition_is_identified_as_index_zero(ddb, table):
    ddb.transact_write_items(TransactItems=five_item_transaction(table, hold_id="first", max_holds=2))
    with pytest.raises(ClientError) as exc:
        ddb.transact_write_items(TransactItems=five_item_transaction(table, hold_id="second", max_holds=2))
    codes = cancellation_codes(exc.value)
    assert codes[0] == "ConditionalCheckFailed"  # slot already held -> SLOT_TAKEN
    assert not exists(ddb, table, "HOLD#second")


# ---------------------------------------------------------------- 2/3. concurrency
def race(table, build_items, n=THREADS):
    """Run n transactions at once. Returns (successes, list_of_failure_code_lists, other_errors)."""
    barrier = threading.Barrier(n)

    def worker(i):
        client = make_client()  # one client per thread
        barrier.wait()
        try:
            client.transact_write_items(TransactItems=build_items(i))
            return ("ok", None)
        except ClientError as e:
            if e.response["Error"]["Code"] == "TransactionCanceledException":
                return ("cancelled", cancellation_codes(e))
            return ("error", e.response["Error"]["Code"])

    with ThreadPoolExecutor(max_workers=n) as pool:
        results = list(pool.map(worker, range(n)))
    ok = [r for r in results if r[0] == "ok"]
    cancelled = [r[1] for r in results if r[0] == "cancelled"]
    other = [r[1] for r in results if r[0] == "error"]
    return ok, cancelled, other


def test_twenty_threads_racing_for_one_slot_produce_exactly_one_winner(ddb, table):
    def items(i):
        return [
            {"Put": {"TableName": table, "Item": {"pk": S("SLOT#luna#20:00"), "sk": S("META"), "hold": S(f"h{i}")},
                     "ConditionExpression": "attribute_not_exists(pk)"}},
            {"Put": {"TableName": table, "Item": {"pk": S(f"HOLD#h{i}"), "sk": S("META")},
                     "ConditionExpression": "attribute_not_exists(pk)"}},
        ]

    ok, cancelled, other = race(table, items)
    assert other == [], f"unexpected non-cancellation errors: {other}"
    assert len(ok) == 1
    assert len(cancelled) == THREADS - 1
    # Every loser is told the slot condition (index 0) failed, or (real DynamoDB) a transaction conflict.
    for codes in cancelled:
        assert codes[0] in {"ConditionalCheckFailed", "TransactionConflict"}, codes

    # No orphans: exactly one HOLD# item exists and it matches the slot owner.
    slot = ddb.get_item(TableName=table, Key={"pk": S("SLOT#luna#20:00"), "sk": S("META")}, ConsistentRead=True)
    winner = slot["Item"]["hold"]["S"]
    holds = [i for i in range(THREADS) if exists(ddb, table, f"HOLD#h{i}")]
    assert holds == [int(winner[1:])]


def test_twenty_threads_racing_for_a_counter_with_capacity_three_produce_three_winners(ddb, table):
    cap = 3

    def items(i):
        return [
            {"Update": {"TableName": table, "Key": {"pk": S("COUNTER#venue#covers"), "sk": S("META")},
                        "UpdateExpression": "ADD booked :one",
                        "ConditionExpression": "attribute_not_exists(booked) OR booked < :max",
                        "ExpressionAttributeValues": {":one": N(1), ":max": N(cap)}}},
            {"Put": {"TableName": table, "Item": {"pk": S(f"HOLD#c{i}"), "sk": S("META")},
                     "ConditionExpression": "attribute_not_exists(pk)"}},
        ]

    ok, cancelled, other = race(table, items)
    assert other == [], other
    assert len(ok) == cap
    assert len(cancelled) == THREADS - cap
    counter = ddb.get_item(TableName=table, Key={"pk": S("COUNTER#venue#covers"), "sk": S("META")}, ConsistentRead=True)
    assert counter["Item"]["booked"] == N(cap)
    holds = [i for i in range(THREADS) if exists(ddb, table, f"HOLD#c{i}")]
    assert len(holds) == cap
