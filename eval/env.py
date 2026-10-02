"""One isolated environment per trial (design section 9.1: every run gets a fresh namespace).

Creates a new DynamoDB table, seeds it, and starts the dev issuer (in process), the MCP server (on a
free local port, in a thread). ``close()`` deletes the table.
Nothing here needs an AWS account: the table lives in DynamoDB Local (``DDB_ENDPOINT_URL``).
"""

import logging
import os
import socket
import threading
import time
import uuid
from typing import Self

import uvicorn
from botocore.exceptions import BotoCoreError, ClientError
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import RSAKey

from devauth.accounts import USERS_BY_NAME
from devauth.app import create_app as create_devauth
from devauth.issuer import IssuerSettings, load_or_create_key
from server.app import build_deps
from server.app import create_app as create_mcp_app
from server.config import Settings
from server.domain.clock import Clock, FakeClock
from server.identity import StaticJwks
from server.kernel import TrustKernel
from server.store import Store, StoreConfig, create_table, delete_table, make_client
from server.store.seeding import seed_store

log = logging.getLogger("fairtable.eval")
SEEDED = {"alice": "diner-alice", "bob": "diner-bob", "carol": "diner-carol"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class EvalEnv:
    def __init__(self, *, endpoint: str | None = None, region: str = "us-east-1", clock: Clock | None = None,
                 kernel: TrustKernel | None = None, rate_limit_per_hour: int = 20) -> None:
        self.endpoint = endpoint or os.environ.get("DDB_ENDPOINT_URL", "http://localhost:8000")
        self.clock = clock or FakeClock()
        self.table = f"ft-eval-{uuid.uuid4().hex[:10]}"
        self._client = make_client(StoreConfig("unused", self.endpoint, region))
        create_table(self._client, self.table)
        self.store = Store(self._client, self.table)
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        try:
            self.subs = {who: USERS_BY_NAME[name].sub for who, name in SEEDED.items()}
            seed_store(self.store, self.clock, self.subs)
            issuer = IssuerSettings()
            self.issuer = issuer
            self.key = load_or_create_key(None)
            self.auth = TestClient(create_devauth(issuer, clock=self.clock, key=self.key))
            settings = Settings(issuer=issuer.issuer, audience=issuer.audience, rate_limit_per_hour=rate_limit_per_hour,
                                store=StoreConfig(self.table, self.endpoint, region))
            self.deps = build_deps(
                settings, clock=self.clock, store=self.store,
                jwks=StaticJwks(self.auth.get("/.well-known/jwks.json").json()), kernel=kernel or TrustKernel.load(),
            )
            ids = iter(range(1, 10_000_000))
            self.deps.new_id = lambda: f"ev{next(ids):08d}"
            port = free_port()
            self._server = uvicorn.Server(uvicorn.Config(
                create_mcp_app(self.deps), host="127.0.0.1", port=port, log_level="warning"))
            self._thread = threading.Thread(target=self._server.run, daemon=True)
            self._thread.start()
            for _ in range(200):
                if self._server.started:
                    break
                time.sleep(0.05)
            if not self._server.started:
                raise RuntimeError("the MCP server did not start")
            self.mcp_url = f"http://127.0.0.1:{port}/mcp"
        except BaseException:
            self.close()
            raise

    def token(self, user: str, client_id: str = "alexa-plus-sim") -> str:
        account = USERS_BY_NAME[SEEDED[user]]
        r = self.auth.post("/token", data={"grant_type": "password", "client_id": client_id,
                                           "username": account.username, "password": account.password})
        r.raise_for_status()
        return r.json()["access_token"]

    def machine_token(self, client_id: str = "bot-m2m", secret: str = "bot-m2m-dev-secret") -> str:
        """A client-credentials token: no ``username``, and for ``bot-m2m`` no agent claims (RT1, RT3)."""
        r = self.auth.post("/token", data={"grant_type": "client_credentials", "client_id": client_id,
                                           "client_secret": secret})
        r.raise_for_status()
        return r.json()["access_token"]

    def mint(self, sub: str, *, key: RSAKey | None = None, **claims: object) -> str:
        """A token with exactly the claims given, signed with the issuer's key (or ``key``, to forge one).
        Defaults describe a verified agent acting for a signed-in diner; pass ``agent_tier=None`` to drop a claim."""
        now = int(self.clock.now().timestamp())
        body: dict[str, object] = {
            "iss": self.issuer.issuer, "sub": sub, "aud": self.issuer.audience, "client_id": "alexa-plus-sim",
            "token_use": "access", "scope": "fairtable/book", "iat": now, "exp": now + 3600,
            "username": sub, "agent_tier": "verified", "agent_id": "alexa-plus-sim",
        }
        body.update(claims)
        body = {k: v for k, v in body.items() if v is not None}
        signer = key or self.key
        return jwt.encode({"alg": "RS256", "kid": signer.kid, "typ": "JWT"}, body, signer)

    def close(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
            if self._thread is not None:
                self._thread.join(timeout=10)
            self._server = None
        try:
            delete_table(self._client, self.table)
        except (BotoCoreError, ClientError) as e:  # best effort: the table may never have been created
            log.warning("could not delete %s: %s", self.table, e)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

