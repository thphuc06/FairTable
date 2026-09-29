"""DynamoDB Local endpoint for integration tests (kept out of conftest so imports are unambiguous)."""

import os

ENDPOINT = os.environ.get("DDB_ENDPOINT_URL", "http://localhost:8000")
