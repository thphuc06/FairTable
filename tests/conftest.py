"""Shared fixtures for tests that need DynamoDB Local (marker ``ddb``).

Start it with:  docker compose -f infra/local/docker-compose.yml up -d
The endpoint comes from DDB_ENDPOINT_URL (default http://localhost:8000). Tests skip when it is not
reachable; when you run ``pytest -m ddb`` on purpose, treat skips as failures.

Against the real service (empty DDB_ENDPOINT_URL) creating a table takes about 25 s, so a table per
test is slow. ``FT_TEST_SHARED_TABLE=1`` creates one table for the whole run and empties it after
every test instead (the default stays one fresh table per test).
"""

import os
import signal
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from botocore.exceptions import BotoCoreError, ClientError
from ddb_env import ENDPOINT

from server.domain.clock import FakeClock
from server.store import Store, StoreConfig, create_table, delete_table, make_client


@pytest.fixture(scope="session")
def ddb_client():
    client = make_client(StoreConfig("unused", ENDPOINT, "us-east-1"))
    try:
        client.list_tables()
    except (BotoCoreError, ClientError, OSError) as e:
        pytest.skip(f"DynamoDB Local not reachable at {ENDPOINT}: {e}")
    return client


SHARED = os.environ.get("FT_TEST_SHARED_TABLE") == "1"


def wipe_table(client, name: str) -> None:
    """Delete every item, then wait until both indexes (eventually consistent) are empty too, so the
    next test cannot see the previous one's rows through a GSI."""
    keys = []
    for page in client.get_paginator("scan").paginate(
        TableName=name, ProjectionExpression="PK, SK", ConsistentRead=True
    ):
        keys += page["Items"]
    def delete_chunk(chunk):
        requests = [{"DeleteRequest": {"Key": k}} for k in chunk]
        while requests:
            requests = client.batch_write_item(RequestItems={name: requests}).get("UnprocessedItems", {}).get(name, [])

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(delete_chunk, [keys[i : i + 25] for i in range(0, len(keys), 25)]))
    for index in ("GSI1", "GSI2"):
        deadline = time.monotonic() + 30
        while client.scan(TableName=name, IndexName=index, Limit=1)["Items"]:
            assert time.monotonic() < deadline, f"{index} still holds rows after the wipe"
            time.sleep(0.2)


@pytest.fixture(scope="session")
def shared_table(ddb_client):
    name = f"ft-test-shared-{uuid.uuid4().hex[:8]}"
    create_table(ddb_client, name)
    yield name
    delete_table(ddb_client, name)


@pytest.fixture
def table_name(ddb_client, request):
    """A fresh, empty table per test (namespacing: tests never share state). With
    FT_TEST_SHARED_TABLE=1 it is one table for the run, emptied after each test."""
    if SHARED:
        name = request.getfixturevalue("shared_table")
        yield name
        wipe_table(ddb_client, name)
        return
    name = f"ft-test-{uuid.uuid4().hex[:10]}"
    create_table(ddb_client, name)
    yield name
    delete_table(ddb_client, name)


@pytest.fixture
def store(ddb_client, table_name):
    return Store(ddb_client, table_name)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture(autouse=True)
def restore_signal_handlers():
    """uvicorn installs SIGINT/SIGTERM handlers while a server runs and restores what it found. Two
    servers overlapping in one test can restore each other's handler out of order, leaving one that
    points at a dead server; sse-starlette then thinks the process is shutting down and closes every
    later SSE stream at once (the simulator's MCP client then hangs). Put the originals back after
    every test."""
    saved = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    yield
    for number, handler in saved.items():
        signal.signal(number, handler)


def pytest_collection_modifyitems(config, items):
    """Tests marked ``docker`` build images and bind fixed ports: run them only when asked for (``-m docker``)."""
    if "docker" in (config.getoption("-m") or ""):
        return
    skip = pytest.mark.skip(reason="builds and starts the docker compose stack; run with: pytest -m docker")
    for item in items:
        if "docker" in item.keywords:
            item.add_marker(skip)
