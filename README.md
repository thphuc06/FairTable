# FairTable

> Bots scalp tables; restaurants ban agents. FairTable is the Alexa+ front door that lets agents book fairly, with verified identity, scoped consent, and rules owners control.

**Status:** 🚧 in progress – Amazon Developer Hackathon "Build, Ship, Shape"
**Track:** Alexa+ · **Mini challenge:** AWS Builder

> The sections below marked _(planned)_ describe what the repository will do at submission. Built so far (Phase 1, batches A to C): the rule engine, identity checks, the dev token issuer, the storage layer with demo data, the three read tools and the booking flow (`reservation_hold`, `reservation_confirm`, `reservation_manage`) with step-up approval on a consent page. Waitlist and the verifiable Fair Drop lottery are in as well (all 8 tools). Owner console, simulator, evaluation harness and Docker packaging come next; see [`docs/PLAN.md`](docs/PLAN.md) and [`docs/devlog/`](docs/devlog/).

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

### Try what exists today (development)
No compose file for the apps yet (task P1-23). Docker is only needed for DynamoDB Local.

```bash
docker compose -f infra/local/docker-compose.yml up -d        # DynamoDB Local on 127.0.0.1:8000
python -m venv .venv && . .venv/bin/activate                  # Windows: .venv\Scripts\activate
pip install -e ".[dev,web,sim]"

export DDB_ENDPOINT_URL=http://localhost:8000 TABLE_NAME=fairtable-dev   # PowerShell: $env:NAME="value"
python scripts/seed.py --reset       # 3 restaurants, 2 weeks of slots, 2 standing mandates
python -m devauth                    # dev token issuer on http://127.0.0.1:9000   (terminal 2)
python -m server                     # MCP server on http://127.0.0.1:8000/mcp      (terminal 3)
python -m web                        # consent page on http://127.0.0.1:8080        (terminal 4)
```

Book a table end to end: as Alice (has a mandate at Luna) `reservation_hold` then `reservation_confirm` books at once; as Bob (no mandate) `reservation_confirm` answers with a `consent_url`: open it, sign in as `diner-bob`, press Approve, then repeat the same `reservation_confirm` call with the same `idempotency_key`.

Waitlist and Fair Drop: `waitlist_watch` registers a standing watch (a freed table is held for you, `waitlist_status` finds it); with `drop_id` it enters the lottery for a hot seat (Sakura Counter on Fridays). Its commitment is published up front and the full record is at `fairtable://drops/<drop_id>/audit` once the draw has run; `fairtable://restaurants/<id>/policies` lists the rules.

Get a token as Alice and call a tool with the MCP Inspector (transport **Streamable HTTP**, URL `http://127.0.0.1:8000/mcp`, custom header `x-ft-user-token: <token>`):

```bash
curl -s -X POST http://127.0.0.1:9000/token -d grant_type=password -d client_id=alexa-plus-sim \
     -d username=diner-alice -d password=alice-dev-pass
npx @modelcontextprotocol/inspector
```

### Test accounts
Development-only credentials for the local dev issuer (`devauth/`), seeded on purpose and public. They are not secrets and must never be used anywhere else.

| Account | Role | Password | Notes |
|---|---|---|---|
| `diner-alice` | Diner | `alice-dev-pass` | Standing mandate at Luna Trattoria: party up to 4, 17:00-22:00, 30 days ahead. |
| `diner-bob` | Diner | `bob-dev-pass` | No mandate: every confirm will need step-up. |
| `diner-carol` | Diner | `carol-dev-pass` | Mandate at Ember Grill that never auto-confirms; used for waitlist and Fair Drop scenarios. |
| `owner-luna` | Restaurant owner | `luna-dev-pass` | Owner console login (later task). |

| OAuth client | Grant | Secret | Token carries |
|---|---|---|---|
| `alexa-plus-sim` | password (diners), client_credentials | `alexa-sim-dev-secret` (machine use only) | `agent_tier=verified`, `agent_id` |
| `shady-agent` | password | none | `agent_tier=unverified`: refused by the write rules |
| `bot-m2m` | client_credentials | `bot-m2m-dev-secret` | no `username`, no `agent_tier`: red-team tests RT1 and RT3 |

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
