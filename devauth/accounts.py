"""Seeded dev accounts and OAuth clients. DEVELOPMENT ONLY: these values are public on purpose and
are listed in the top-level README. Never use them outside the local Docker profile.

Plain Python, no web framework, so ``scripts/seed.py`` and tests can import it too.
"""

from dataclasses import dataclass

SCOPE_BOOK = "fairtable/book"


@dataclass(frozen=True)
class DevUser:
    username: str
    sub: str
    password: str
    display_name: str
    groups: tuple[str, ...] = ()
    venue_id: str | None = None  # owners: the restaurant they manage (Cognito: custom:venue_id)


@dataclass(frozen=True)
class DevClient:
    client_id: str
    grants: frozenset[str]  # subset of {"password", "client_credentials"}
    scopes: frozenset[str]
    secret: str | None = None  # confidential clients only
    agent_tier: str | None = None
    agent_id: str | None = None
    # Mirrors Cognito's pre-token trigger versions: V2 customises user tokens only, V3 also M2M.
    add_claims_to_m2m: bool = False


USERS: tuple[DevUser, ...] = (
    DevUser("diner-alice", "dev-alice", "alice-dev-pass", "Alice"),
    DevUser("diner-bob", "dev-bob", "bob-dev-pass", "Bob"),
    DevUser("diner-carol", "dev-carol", "carol-dev-pass", "Carol"),
    DevUser("owner-luna", "dev-owner-luna", "luna-dev-pass", "Luna's owner", ("owners",), "luna-trattoria"),
)

CLIENTS: tuple[DevClient, ...] = (
    # The simulated Alexa+ agent: verified, works for signed-in users and (V3-style) as a machine.
    DevClient(
        "alexa-plus-sim",
        frozenset({"password", "client_credentials"}),
        frozenset({SCOPE_BOOK}),
        secret="alexa-sim-dev-secret",
        agent_tier="verified",
        agent_id="alexa-plus-sim",
        add_claims_to_m2m=True,
    ),
    # A third-party agent that has not been verified: used to show the G4 / P0 refusals.
    DevClient(
        "shady-agent",
        frozenset({"password"}),
        frozenset({SCOPE_BOOK}),
        agent_tier="unverified",
        agent_id="shady-agent",
    ),
    # A machine client with neither `username` nor `agent_tier` (V2-only setup): RT1 and RT3.
    DevClient(
        "bot-m2m",
        frozenset({"client_credentials"}),
        frozenset({SCOPE_BOOK}),
        secret="bot-m2m-dev-secret",
    ),
)

USERS_BY_NAME = {u.username: u for u in USERS}
CLIENTS_BY_ID = {c.client_id: c for c in CLIENTS}
