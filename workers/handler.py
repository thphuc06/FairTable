"""AWS Lambda entry point of the background workers: EventBridge Scheduler calls it every minute.

It builds the same dependencies as the MCP server (settings from the environment, DynamoDB, the SNS notifier, the
S3 audit sink) once per container and runs ``server.workers.run_once``. Nothing account-specific is read from code.
"""

import json
import logging
import os

from server.app import build_deps
from server.config import Settings
from server.tools.common import AppDeps
from server.workers import run_once

log = logging.getLogger("fairtable.workers")
logging.getLogger().setLevel(logging.INFO)
_deps: AppDeps | None = None


def deps() -> AppDeps:
    global _deps
    if _deps is None:
        _deps = build_deps(Settings.from_env(dict(os.environ)))
    return _deps


def handler(event, context):
    summary = run_once(deps())
    log.info(json.dumps({"workers": summary}))
    return summary
