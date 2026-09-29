# FairTable

> Bots scalp tables; restaurants ban agents. FairTable is the Alexa+ front door that lets agents book fairly, with verified identity, scoped consent, and rules owners control.

**Status:** 🚧 in progress – Amazon Developer Hackathon "Build, Ship, Shape"
**Track:** Alexa+ · **Mini challenge:** AWS Builder

> The sections below marked _(planned)_ describe what the repository will do at submission. Nothing is implemented yet; see [`docs/PLAN.md`](docs/PLAN.md) for the schedule.

## What it does
FairTable is a self-hosted **MCP server** (spec 2025-11-25, Streamable HTTP) that independent restaurants publish so AI agents such as Alexa+ can book tables safely:
- **Verified identity:** every booking is tied to a real, signed-in diner.
- **Standing mandate + step-up consent:** bookings within what the diner pre-approved confirm instantly; anything beyond is approved on their phone (JSON-RPC error `-32042` with a consent URL).
- **Owner-controlled rules:** enforced with Cedar policies (`cedarpy`), including a cap on how many covers agents can book.
- **Standing waitlists:** no polling – agents register once and check `waitlist_status`.
- **Fair Drop:** an auditable commit–reveal lottery for hot tables.
- **Measured reliability:** pass^k evaluations against an open-storefront baseline (A0 vs A1 vs A2) plus a 12-case red-team suite.

The 8 MCP tools are deterministic; there is no LLM inside them: `restaurant_search`, `availability_check`, `mandate_status`, `reservation_hold`, `reservation_confirm`, `reservation_manage`, `waitlist_watch`, `waitlist_status`.

## Run locally _(planned)_
The local profile is what judges run. It needs **Docker only** – no AWS account and no model provider.

```bash
git clone <this repo>
cd FairTable
docker compose up
```

This starts: the MCP server, DynamoDB Local, the consent page and owner console, a dev JWT issuer standing in for Cognito (with seeded test users), and the simulator using the built-in mock model (`MODEL_PROVIDER=mock`). A real model provider is opt-in through environment variables (see `.env.example`).

Exact URLs and ports will be listed here once the compose file exists.

### Test accounts _(planned; final values are set by `scripts/seed.py`)_
These are development-only credentials for the local dev issuer. They are not secrets.

| Account | Role | Password | Notes |
|---|---|---|---|
| `diner-alice` | Diner | `fairtable-dev` | Has a standing mandate for the demo restaurant (party up to 4). |
| `diner-bob` | Diner | `fairtable-dev` | No mandate; every confirm needs step-up. |
| `diner-carol` | Diner | `fairtable-dev` | Used for the Fair Drop and waitlist scenarios. |
| `owner-luna` | Restaurant owner | `fairtable-dev` | Owner console login. |
| `alexa-plus-sim` | Agent client | dev client secret | Verified agent used by the simulator. |
| `bot-m2m` | Machine client | dev client secret | Unverified bot: no `username`, no `agent_tier`; used by red-team tests. |

## Run tests _(planned)_
```bash
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev,web,sim]"
pytest -q                 # unit tests, no services needed
pytest -q -m ddb          # needs DynamoDB Local
pytest -q -m docker       # needs the full compose stack
```

## AWS deployment (AWS Builder challenge) _(planned)_
The same server runs on Amazon Bedrock AgentCore Runtime behind AgentCore Gateway, with Amazon Cognito for identity and Amazon DynamoDB for state. The AWS profile is optional for running the project. Each service, what it does and how we use it: [`docs/aws-integration.md`](docs/aws-integration.md).

## Documentation
- Decisions log: [`docs/DECISIONS.md`](docs/DECISIONS.md)
- Plan: [`docs/PLAN.md`](docs/PLAN.md)
- AWS services and how they are used: [`docs/aws-integration.md`](docs/aws-integration.md)
- Hackathon requirements and FAQ clarifications: [`docs/hackathon-rules.md`](docs/hackathon-rules.md)
- Friction log: [`docs/friction-log.md`](docs/friction-log.md)
- Architecture (English): `docs/ARCHITECTURE.md` _(planned, task P0-5)_

## Repository layout
See [`docs/PLAN.md`](docs/PLAN.md) §4. Each top-level directory has its own `README.md` describing what belongs there.

## License
[Apache-2.0](LICENSE)
