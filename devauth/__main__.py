"""Run the dev issuer: ``python -m devauth`` (host/port from DEVAUTH_HOST / DEVAUTH_PORT)."""

import os

import uvicorn

from devauth.app import create_app

if __name__ == "__main__":
    uvicorn.run(
        create_app(),
        host=os.environ.get("DEVAUTH_HOST", "127.0.0.1"),
        port=int(os.environ.get("DEVAUTH_PORT", "9000")),
    )
