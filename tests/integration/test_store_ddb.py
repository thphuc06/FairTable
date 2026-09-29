"""P1-6: the store and the seed script against DynamoDB Local."""

import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from ddb_env import ENDPOINT

from devauth.accounts import USERS_BY_NAME
from server.store import (
    Store,
    StoreConfig,
    TransactionCancelled,
    TxOp,
    delete_table,
    ensure_table,
    keys,
    make_client,
    table_exists,
)
from server.store.seed_data import DAYS, TIMES
from server.store.seeding import seed_store

pytestmark = pytest.mark.ddb

SUBS = {
    "alice": USERS_BY_NAME["diner-alice"].sub,
    "bob": USERS_BY_NAME["diner-bob"].sub,
    "carol": USERS_BY_NAME["diner-carol"].sub,
}
REPO = Path(__file__).resolve().parents[2]


def test_ensure_table_is_idempotent(ddb_client, table_name):
    assert table_exists(ddb_client, table_name)
    assert ensure_table(ddb_client, table_name) is False  # already there


def test_seeded_data_can_be_read_back(store, clock):
    data = seed_store(store, clock, SUBS)

    venues = store.list_venues()
    assert [v.name for v in venues] == ["Ember Grill", "Luna Trattoria", "Sakura Counter"]
    assert store.get_venue("luna-trattoria").agent_cover_cap == 24
    assert store.get_venue("nowhere") is None

    today = clock.now().date().isoformat()
    slots = store.get_slots("luna-trattoria", today)
    assert len(slots) == len(TIMES) * 3
    assert [(s.time, s.table_group) for s in slots] == sorted((s.time, s.table_group) for s in slots)
    assert store.get_slot("luna-trattoria", today, "19:00", "T4").seats == 4
    assert store.get_slot("luna-trattoria", today, "03:00", "T4") is None

    assert store.get_mandate(SUBS["alice"], "luna-trattoria").party_size_max == 4
    assert store.get_mandate(SUBS["bob"], "luna-trattoria") is None
    assert len(data.slots) == DAYS * len(TIMES) * 6


def test_slots_of_other_days_and_venues_do_not_leak(store, clock):
    seed_store(store, clock, SUBS)
    other_day = "2000-01-01"
    assert store.get_slots("luna-trattoria", other_day) == []
    today = clock.now().date().isoformat()
    assert {s.venue_id for s in store.get_slots("ember-grill", today)} == {"ember-grill"}


def test_transaction_cancels_atomically_and_names_the_failing_item(store):
    store.put_item({"PK": "CNT#x", "SK": "N", "n": 2})
    ops = [
        TxOp("Put", item={"PK": "SLOT#a", "SK": "META"}, condition="attribute_not_exists(PK)"),
        TxOp("Update", key={"PK": "CNT#x", "SK": "N"}, update="ADD n :one",
             condition="n < :max", values={":one": 1, ":max": 2}),
        TxOp("Put", item={"PK": "HOLD#a", "SK": "META"}),
    ]
    with pytest.raises(TransactionCancelled) as exc:
        store.transact(ops)
    assert exc.value.failed_indexes() == [1]
    assert exc.value.reasons[1].item["n"] == 2  # the blocking item comes back
    assert store.get_item(keys.Key("SLOT#a", "META")) is None
    assert store.get_item(keys.Key("HOLD#a", "META")) is None
    assert store.get_item(keys.Key("CNT#x", "N"))["n"] == 2


def test_twenty_racing_transactions_for_one_slot_have_exactly_one_winner(ddb_client, table_name):
    barrier = threading.Barrier(20)

    def attempt(i: int) -> bool:
        local = Store(ddb_client, table_name)
        barrier.wait()
        try:
            local.transact([
                TxOp("Put", item={"PK": "SLOT#s", "SK": "META", "owner": f"u{i}"},
                     condition="attribute_not_exists(PK)"),
                TxOp("Put", item={"PK": f"HOLD#{i}", "SK": "META"}),
            ])
            return True
        except TransactionCancelled:
            return False

    with ThreadPoolExecutor(max_workers=20) as pool:
        wins = list(pool.map(attempt, range(20)))
    assert wins.count(True) == 1
    store = Store(ddb_client, table_name)
    owner = store.get_item(keys.Key("SLOT#s", "META"))["owner"]
    holds = [i for i in range(20) if store.get_item(keys.Key(f"HOLD#{i}", "META"))]
    assert holds == [int(owner[1:])]  # no orphan holds


def test_batch_put_handles_more_than_one_batch(store):
    items = [{"PK": f"BULK#{i}", "SK": "META", "n": i} for i in range(60)]
    store.batch_put(items)
    assert store.get_item(keys.Key("BULK#59", "META"))["n"] == 59
    assert len(store.query("BULK#0")) == 1


def test_seed_script_creates_and_fills_a_table(ddb_client):
    name = "ft-seedscript-" + os.urandom(4).hex()
    env = {**os.environ, "TABLE_NAME": name, "DDB_ENDPOINT_URL": ENDPOINT, "AWS_REGION": "us-east-1"}
    try:
        out = subprocess.run(
            [sys.executable, "scripts/seed.py"], cwd=REPO, env=env, capture_output=True, text=True,
            timeout=60, check=True,
        ).stdout
        assert f"created table {name}" in out and "3 venues" in out
        store = Store(make_client(StoreConfig(name, ENDPOINT, "us-east-1")), name)
        assert len(store.list_venues()) == 3
        again = subprocess.run(
            [sys.executable, "scripts/seed.py"], cwd=REPO, env=env, capture_output=True, text=True,
            timeout=60, check=True,
        ).stdout
        assert f"reused table {name}" in again  # running twice is safe
    finally:
        delete_table(ddb_client, name)
