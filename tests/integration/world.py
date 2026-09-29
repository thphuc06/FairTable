"""A small world for tool tests: dev issuer + seeded table + the FairTable server, all sharing one
fake clock. ``as_("alice")`` decides whose token the next tool call carries."""

from fastapi.testclient import TestClient
from fastmcp import Client

from devauth.accounts import USERS_BY_NAME
from devauth.app import create_app as create_devauth
from devauth.issuer import IssuerSettings, load_or_create_key
from server.app import build_deps, create_server
from server.config import Settings
from server.identity import StaticJwks
from server.kernel import TrustKernel
from server.store import Store, StoreConfig
from server.store.seeding import seed_store
from web.app import WebDeps
from web.app import create_app as create_web
from web.auth import DevLogin
from web.session import SessionCodec

SUBS = {
    "alice": USERS_BY_NAME["diner-alice"].sub,
    "bob": USERS_BY_NAME["diner-bob"].sub,
    "carol": USERS_BY_NAME["diner-carol"].sub,
}
TOKEN_REQUESTS = {
    "alice": {"grant_type": "password", "client_id": "alexa-plus-sim",
              "username": "diner-alice", "password": "alice-dev-pass"},
    "bob": {"grant_type": "password", "client_id": "alexa-plus-sim",
            "username": "diner-bob", "password": "bob-dev-pass"},
    "carol": {"grant_type": "password", "client_id": "alexa-plus-sim",
              "username": "diner-carol", "password": "carol-dev-pass"},
    "shady": {"grant_type": "password", "client_id": "shady-agent",
              "username": "diner-alice", "password": "alice-dev-pass"},
    "bot": {"grant_type": "client_credentials", "client_id": "bot-m2m",
            "client_secret": "bot-m2m-dev-secret"},
}


class World:
    def __init__(
        self, client, table_name: str, endpoint: str, clock, *, per_hour: int = 20,
        real_headers: bool = False, jwks=None,
    ):
        self.clock = clock
        self.store = Store(client, table_name)
        seed_store(self.store, clock, SUBS)
        issuer = IssuerSettings()
        self.auth = TestClient(create_devauth(issuer, clock=clock, key=load_or_create_key(None)))
        self._tokens: dict[str, str] = {}
        self.current: str | None = None
        settings = Settings(
            issuer=issuer.issuer, audience=issuer.audience, rate_limit_per_hour=per_hour,
            store=StoreConfig(table_name, endpoint, "us-east-1"),
        )
        self.jwks = jwks or StaticJwks(self.auth.get("/.well-known/jwks.json").json())
        self.deps = build_deps(
            settings, clock=clock, store=self.store, jwks=self.jwks, kernel=TrustKernel.load(),
            header_provider=None if real_headers else self.headers,
        )
        self.mcp = create_server(self.deps)

    def headers(self) -> dict[str, str]:
        return {"x-ft-user-token": self.current} if self.current else {}

    def token(self, who: str) -> str:
        if who not in self._tokens:
            self._tokens[who] = self.auth.post("/token", data=TOKEN_REQUESTS[who]).json()["access_token"]
        return self._tokens[who]

    def as_(self, who: str | None) -> "World":
        self.current = self.token(who) if who else None
        return self

    def client(self) -> Client:
        return Client(self.mcp)

    def web(self) -> TestClient:
        """A browser for the consent page. Redirects are not followed so tests can see them."""
        deps = WebDeps(
            settings=self.deps.settings, store=self.store, clock=self.clock,
            login=DevLogin(self.auth, "/token", self.deps.verifier),
            sessions=SessionCodec(self.deps.settings.web_session_secret, self.clock),
            new_id=lambda: self.deps.new_id(),
        )
        return TestClient(create_web(deps), follow_redirects=False)
