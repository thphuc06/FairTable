# FairTable

> Bots scalp tables; restaurants ban agents. FairTable is the Alexa+ front door that lets agents book fairly, with verified identity, scoped consent, and rules owners control.

**Status:** 🚧 in progress: Amazon Developer Hackathon "Build, Ship, Shape"
**Track:** Alexa+ · **Mini challenge:** AWS Builder

**What works today:** all 8 MCP tools, both rule layers (Cedar), identity checks, DynamoDB storage, step-up approval on a consent page, standing waitlists, the verifiable Fair Drop lottery, an owner console, a chat page with a simulated assistant, an evaluation harness with an A0/A1/A2 comparison, and a 12-attack red-team suite, all runnable with `docker compose up`. **Not built yet:** the AWS deployment (AgentCore, Cognito, real DynamoDB; see [AWS](#aws-services-and-status)), the 40-task evaluation set and the English architecture document. Progress is tracked in [`docs/devlog/`](docs/devlog/).

## What it does
FairTable is a self-hosted **MCP server** (spec 2025-11-25, Streamable HTTP) that independent restaurants publish so AI agents such as Alexa+ can book tables safely:
- **Verified identity:** every booking is tied to a real, signed-in diner and a verified agent.
- **Standing mandate + step-up consent:** bookings within what the diner pre-approved confirm instantly; anything beyond is approved on their phone (JSON-RPC error `-32042` with a consent URL, or an error with a `consent_url` for clients that cannot open one).
- **Owner-controlled rules:** enforced with Cedar policies (`cedarpy`), including a cap on how many covers agents can book.
- **Standing waitlists:** no polling. Agents register once and check `waitlist_status`.
- **Fair Drop:** an auditable commit–reveal lottery for hot tables; anyone can recompute the draw.
- **Measured reliability:** pass^k evaluations against an open-storefront baseline (A0 vs A1 vs A2) plus a 12-attack red-team suite.

The 8 MCP tools are deterministic; there is no LLM inside them: `restaurant_search`, `availability_check`, `mandate_status`, `reservation_hold`, `reservation_confirm`, `reservation_manage`, `waitlist_watch`, `waitlist_status`.

## Quick start (Docker only)
The local profile is what judges run. It needs **Docker only**: no AWS account and no model account.

```bash
git clone <this repo>
cd FairTable
docker compose up --build
```

The first build takes about a minute. When it finishes everything is running and seeded (three restaurants, two weeks of slots, two standing mandates, two Fair Drops). Everything listens on `127.0.0.1` only.

| URL | What it is |
|---|---|
| http://localhost:8080 | **Start here.** Chat with the simulated assistant, the approval (consent) page and the owner console |
| http://localhost:8000/mcp | The MCP server (Streamable HTTP; identity in the `x-ft-user-token` header) |
| http://localhost:9000 | Dev token issuer standing in for Cognito (`/token`, `/.well-known/jwks.json`) |
| http://localhost:8001 | DynamoDB Local (used by the evaluation and by `pytest -m ddb`) |

Stop with `docker compose down`. Data is in memory, so every `up` starts from the same seed.

### Try it (about two minutes)
1. **Instant booking.** Open http://localhost:8080, sign in as `diner-alice` / `alice-dev-pass`, and type: `Book a table at Luna Trattoria for 2 on <a date in the next two weeks> at 7pm` (use `YYYY-MM-DD`, or "tomorrow"). Alice has a standing permission at Luna, so it is booked at once.
2. **Step-up approval.** There is no sign-out button: open a private window, go to http://localhost:8080/chat, sign in as `diner-bob` / `bob-dev-pass` and send the same request. Bob has no standing permission, so the assistant hands over an approval link. Open it, press **Approve**, go back to the chat and type `I approved it`: the booking completes. (Declining books nothing.)
   Under each assistant answer, click **N steps** to see the tool calls behind it: which tools were called with which arguments, and what the server decided (ok, refused with the rule id, or needs approval). It is the proof that the checks happen in the server, not in the assistant.
3. **Owner rules.** Sign in as `owner-luna` / `luna-dev-pass` at http://localhost:8080/owner, lower the agent share to 0 and save. The next booking an assistant tries at Luna is refused by rule S2, and the audit list shows the change.
4. **Call the tools yourself.** Get a token and use the [MCP Inspector](https://github.com/modelcontextprotocol/inspector) (transport **Streamable HTTP**, URL `http://localhost:8000/mcp`, custom header `x-ft-user-token: <token>`):

   ```bash
   curl -s -X POST http://localhost:9000/token -d grant_type=password -d client_id=alexa-plus-sim \
        -d username=diner-alice -d password=alice-dev-pass
   npx @modelcontextprotocol/inspector
   ```
5. **Waitlist and Fair Drop.** `waitlist_watch` registers a standing watch (a freed table is held for you and `waitlist_status` finds it). With `drop_id` it enters the lottery for a hot seat (Sakura Counter on Fridays, `drop-sakura-<date>`). The draw's commitment is published up front; after the draw the full record is at `fairtable://drops/<drop_id>/audit`, and `fairtable://restaurants/<id>/policies` lists each restaurant's rules in plain English.

### Test accounts
Development-only credentials for the local dev issuer (`devauth/`), seeded on purpose and public. They are not secrets and must never be used anywhere else.

| Account | Role | Password | Notes |
|---|---|---|---|
| `diner-alice` | Diner | `alice-dev-pass` | Standing mandate at Luna Trattoria: party up to 4, 17:00–22:00, 30 days ahead. |
| `diner-bob` | Diner | `bob-dev-pass` | No mandate: every confirm needs step-up. |
| `diner-carol` | Diner | `carol-dev-pass` | Mandate at Ember Grill that never auto-confirms. |
| `owner-luna` | Restaurant owner | `luna-dev-pass` | Owner console for Luna Trattoria (`/owner`). |

| OAuth client | Grant | Secret | Token carries |
|---|---|---|---|
| `alexa-plus-sim` | password (diners), client_credentials | `alexa-sim-dev-secret` (machine use only) | `agent_tier=verified`, `agent_id` |
| `shady-agent` | password | none | `agent_tier=unverified`: refused by the write rules |
| `bot-m2m` | client_credentials | `bot-m2m-dev-secret` | no `username`, no `agent_tier`: red-team attacks RT1 and RT3 |

### Using a real model (optional)
The chat assistant and the evaluation use `MODEL_PROVIDER=mock` by default: a scripted assistant, no key, no cost. To use a real model, put this in a `.env` file next to `docker-compose.yml` (never commit it) and run `docker compose up`:

```
MODEL_PROVIDER=deepseek
DEEPSEEK_API=<your key>
```

`deepseek` uses the light `deepseek-flash` model through DeepSeek's OpenAI-compatible API (defaults in `simulator/model.py`; override with `DEEPSEEK_MODEL`, `DEEPSEEK_BASE_URL`). `bedrock` needs `BEDROCK_MODEL_ID` and AWS credentials and is not used in the local profile. See `.env.example`.

## Without Docker for the apps
Docker is then only needed for DynamoDB Local. Python 3.12.

```bash
docker compose up -d dynamodb                                  # DynamoDB Local on 127.0.0.1:8001
python -m venv .venv && . .venv/bin/activate                   # Windows: .venv\Scripts\activate
pip install -e ".[dev,web,sim]"

export DDB_ENDPOINT_URL=http://localhost:8001 TABLE_NAME=fairtable   # PowerShell: $env:NAME="value"
python scripts/seed.py --reset       # create the table and load the demo data
python -m devauth                    # token issuer on 127.0.0.1:9000      (terminal 2)
python -m server                     # MCP server on 127.0.0.1:8000/mcp    (terminal 3)
python -m web                        # web pages on 127.0.0.1:8080         (terminal 4)
```

## Tests, evaluation and red team
```bash
pip install -e ".[dev,web,sim]"
pytest -q                            # unit tests; the database tests skip when DynamoDB Local is not running
docker compose up -d dynamodb && DDB_ENDPOINT_URL=http://localhost:8001 pytest -q   # everything except the Docker smoke test (about 10 minutes)
pytest -q -m docker                  # builds and starts the whole compose stack and drives it over HTTP (ports 8000, 8001, 8080, 9000 must be free)
```

```bash
DDB_ENDPOINT_URL=http://localhost:8001 python -m eval --k 2 --config A0,A1,A2   # ten starter tasks, three configurations
DDB_ENDPOINT_URL=http://localhost:8001 python -m eval.redteam                    # the twelve attacks, blocked or SUCCEEDED per configuration
```

Results with the mock assistant validate the harness and the rules, not a real model; the report says so. A0 is an open store (no policy layer), A1 is FairTable, A2 is FairTable without step-up. Details: [`eval/README.md`](eval/README.md).

## AWS services and status
**The local profile uses no AWS service** and needs no AWS account. The AWS deployment for the AWS Builder challenge is **planned, not built yet**: the same server would run on Amazon Bedrock AgentCore Runtime behind AgentCore Gateway (with Gateway Policy as defense in depth), Amazon Cognito would replace the dev issuer, and Amazon DynamoDB would replace DynamoDB Local. Code for these is written as configuration and interfaces only (nothing account-specific is hard-coded). Each service, its role and its status: [`docs/aws-integration.md`](docs/aws-integration.md).

## Documentation
- Decisions log: [`docs/DECISIONS.md`](docs/DECISIONS.md)
- Plan: [`docs/PLAN.md`](docs/PLAN.md) and the working log [`docs/devlog/`](docs/devlog/)
- AWS services and how they are used: [`docs/aws-integration.md`](docs/aws-integration.md)
- Hackathon requirements and FAQ clarifications: [`docs/hackathon-rules.md`](docs/hackathon-rules.md)
- Friction log (problems met with AWS and MCP tooling): [`docs/friction-log.md`](docs/friction-log.md)
- Architecture (English): `docs/ARCHITECTURE.md` _(planned, task P0-5)_

## Repository layout
`server/` MCP server and rule engine · `policies/` Cedar rules · `devauth/` dev token issuer · `web/` consent page, owner console, chat page · `simulator/` simulated assistant · `eval/` evaluation and red team · `scripts/` seed and health check · `tests/`. Each directory has its own `README.md`. Full plan: [`docs/PLAN.md`](docs/PLAN.md) §4.

## License
[Apache-2.0](LICENSE)
