"""Fixtures shared by the integration tests that need the server on a real port."""

import socket
import threading
import time

import pytest
import uvicorn
from ddb_env import ENDPOINT
from world import World

from server.app import create_app


@pytest.fixture
def live(ddb_client, table_name, clock):
    """The server on a real port in its own thread (the Strands MCP client blocks while connecting).
    Yields ``(world, mcp_url)``."""
    world = World(ddb_client, table_name, ENDPOINT, clock, real_headers=True)
    ids = iter(range(1, 100_000))
    world.deps.new_id = lambda: f"id{next(ids):05d}"
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(world.deps), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    yield world, f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=10)
