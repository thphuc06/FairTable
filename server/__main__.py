"""Run the MCP server: ``python -m server`` (settings from the environment, see server/config.py)."""

import logging

import uvicorn

from server.app import build_deps, create_app
from server.config import Settings

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    settings = Settings.from_env()
    uvicorn.run(create_app(build_deps(settings)), host=settings.host, port=settings.port)
