"""Entry point for AgentCore Runtime (direct code deployment, docs/PLAN.md section 3a).

Runtime starts this file and expects an MCP server on 0.0.0.0:8000, path /mcp, stateless Streamable HTTP,
on an ARM64 host. Everything account-specific comes from environment variables that the infrastructure code
sets on the runtime (TABLE_NAME, AWS_REGION, AUTH_ISSUER, AUTH_JWKS_URL, AUTH_AUDIENCE_CLAIM, ...).

Defaults below are only the parts the Runtime contract fixes; any variable already set wins.
"""

import logging
import os
import secrets

import uvicorn

from server.app import build_deps, create_app
from server.config import Settings

RUNTIME_CONTRACT = {
    "MCP_HOST": "0.0.0.0",
    "MCP_PORT": "8000",
    "MCP_STATELESS": "true",
    "APP_PROFILE": "aws",
}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    for name, value in RUNTIME_CONTRACT.items():
        os.environ.setdefault(name, value)
    # The server never uses the web pages' cookie secret, but the aws profile insists on a real one.
    os.environ.setdefault("WEB_SESSION_SECRET", secrets.token_urlsafe(32))
    settings = Settings.from_env()
    uvicorn.run(create_app(build_deps(settings)), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
