"""Shared fixtures for tests that need DynamoDB Local (marker ``ddb``).

Start it with:  docker compose -f infra/local/docker-compose.yml up -d
The endpoint comes from DDB_ENDPOINT_URL (default http://localhost:8000). Tests skip when it is not
reachable; when you run ``pytest -m ddb`` on purpose, treat skips as failures.
"""

import uuid

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


@pytest.fixture
def table_name(ddb_client):
    """A fresh, empty table per test (namespacing: tests never share state)."""
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
