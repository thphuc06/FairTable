# FairTable

> Bots scalp tables; restaurants ban agents. FairTable is the Alexa+ front door that lets agents book fairly, with verified identity, scoped consent, and rules owners control.

**Status:** 🚧 in progress: Amazon Developer Hackathon "Build, Ship, Shape"
**Track:** Alexa+ · **Mini challenge:** AWS Builder

**What works today:** all 7 MCP tools, both rule layers (Cedar), identity checks, DynamoDB storage, booking confirmed by the diner's spoken yes (read-back, pause, explicit yes), standing waitlists, the verifiable Fair Drop lottery, an owner console, a chat page with a simulated assistant, a 40-task evaluation set with an A0/A1/A2 comparison, a regression gate and a 12-attack red-team suite, all runnable with `docker compose up`. The same server also runs on AWS (AgentCore Runtime and Gateway, Cognito, DynamoDB, SNS; see [AWS](#aws-services-and-status)), where an optional **voice page** books a table by talking to it (see [Voice demo](#voice-demo-optional-needs-an-aws-deployment)). **Still to do:** the English architecture document and diagrams, and the final frozen evaluation numbers. Progress is tracked in [`docs/devlog/`](docs/devlog/).

## What it does
FairTable is a self-hosted **MCP server** (spec 2025-11-25, Streamable HTTP) that independent restaurants publish so AI agents such as Alexa+ can book tables safely:
- **Verified identity:** every booking is tied to a real, signed-in diner and a verified agent.
- **Spoken confirmation, 100 % voice:** after a hold the assistant reads the details back and the diner says yes. The server checks what it can: the read-back token fits this hold, user and terms, a short pause has passed (3 s, 6 s with a fee) and the assistant states that the diner said yes. It cannot hear the diner, so these guards stop mistakes (not asking, asking too fast, confirming other terms), not a model that lies on purpose; the restaurant's own rules (caps, identity, drop seats) bound the damage.
- **Owner-controlled rules:** enforced with Cedar policies (`cedarpy`), including a cap on how many covers agents can book.
- **Standing waitlists:** no polling. Agents register once and check `waitlist_status`.
- **Fair Drop:** an auditable commit–reveal lottery for hot tables; anyone can recompute the draw.
- **Measured reliability:** pass^k evaluations against an open-storefront baseline (A0 vs A1 vs A2) plus a 12-attack red-team suite.

The 7 MCP tools are deterministic; there is no LLM inside them: `restaurant_search`, `availability_check`, `reservation_hold`, `reservation_confirm`, `reservation_manage`, `waitlist_watch`, `waitlist_status`.

## Quick start (Docker only)
The local profile is what judges run. It needs **Docker only**: no AWS account and no model account.

```bash
git clone <this repo>
cd FairTable
docker compose up --build
```

The first build takes about a minute. When it finishes everything is running and seeded (three restaurants, two weeks of slots, two Fair Drops). Everything listens on `127.0.0.1` only.

| URL | What it is |
|---|---|
| http://localhost:8080 | **Start here.** Chat with the simulated assistant and the owner console |
| http://localhost:8000/mcp | The MCP server (Streamable HTTP; identity in the `x-ft-user-token` header) |
| http://localhost:9000 | Dev token issuer standing in for Cognito (`/token`, `/.well-known/jwks.json`) |
| http://localhost:8001 | DynamoDB Local (used by the evaluation and by `pytest -m ddb`) |

Stop with `docker compose down`. Data is in memory, so every `up` starts from the same seed.

### Try it (about two minutes)
1. **Book by saying yes.** Open http://localhost:8080, sign in as `diner-alice` / `alice-dev-pass`, and type: `Book a table at Luna Trattoria for 2 on <a date in the next two weeks> at 7pm` (use `YYYY-MM-DD`, or "tomorrow"). The assistant holds a table and reads the details back; nothing is booked yet. Wait a few seconds, then type `Yes, please`: the table is booked. Typing `No, thanks` books nothing and the hold ends by itself.
2. **See what the server decided.** Under each assistant answer, click **N steps** to see the tool calls behind it: which tools were called with which arguments, and what the server decided (ok, refused with the rule id, or waiting for the diner's yes). It is the proof that the checks happen in the server, not in the assistant. Restaurants with a cancellation fee (Ember Grill, Sakura Counter) read the fee back and ask for a slightly longer pause.
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
| `diner-alice` | Diner | `alice-dev-pass` | An ordinary diner. |
| `diner-bob` | Diner | `bob-dev-pass` | An ordinary diner. |
| `diner-carol` | Diner | `carol-dev-pass` | An ordinary diner. |
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
DDB_ENDPOINT_URL=http://localhost:8001 python -m eval --k 2 --config A0,A1,A2   # the 40 tasks, three configurations
DDB_ENDPOINT_URL=http://localhost:8001 python -m eval.redteam                    # the twelve attacks, blocked or SUCCEEDED per configuration
```

Results with the mock assistant validate the harness and the rules, not a real model; the report says so. A0 is an open store (no policy layer), A1 is FairTable, A2 is FairTable without the voice guards (whatever the assistant sends counts as the diner's yes). Details: [`eval/README.md`](eval/README.md).

## AWS services and status
**The local profile (`docker compose up`) uses no AWS service** and needs no AWS account. Judges are not asked to run anything on AWS, and nothing here depends on AWS resources still running.

The same code also runs on AWS (built and tested on a real account; each service, its role and what was measured is in [`docs/aws-integration.md`](docs/aws-integration.md)):

| Service | Role |
|---|---|
| Amazon Bedrock AgentCore **Runtime** | runs the MCP server (direct code deployment, stateless) |
| Amazon Bedrock AgentCore **Gateway** and **Policy** | the front door for the agent (bearer token in, tool catalog) and Cedar rules G1 to G4 as defence in depth |
| Amazon Bedrock AgentCore **Observability** (CloudWatch) | traces of the Gateway, the policy decisions and the Runtime |
| Amazon **Cognito** | sign-in for diners and the machine clients |
| Amazon **DynamoDB** | the single table (on demand) |
| Amazon **SNS** | one topic for waitlist and Fair Drop notices |
| Amazon **Bedrock** (Nova 2 Sonic) | the voice page |
| AWS Budgets, Secrets Manager, Lambda (Cognito trigger and Gateway interceptor), CDK | cost alerts, the token secret, glue, deployment |

Deploy and tear down (needs your own AWS account; the scripts name the account they act on and never use a root user):

```bash
python infra/aws_ctl.py up --runtime      # build the package and deploy the stacks (about 8 minutes)
python infra/aws_ctl.py seed              # load the demo data
python infra/aws_ctl.py status            # what exists and what can cost money
python infra/aws_ctl.py down --yes --account <last four digits of the account id>
pytest -m aws tests/aws                   # the real-AWS tests (opt-in, a few cents)
```

Set `NOTIFY_EMAIL` to subscribe an address to the notice topic when deploying (AWS sends a confirmation link; the address is never stored in the repository). Nothing account-specific is hard-coded: account, region and names come from the environment.

## Voice demo (optional, needs an AWS deployment)
Not part of `docker compose up`: it needs the AWS deployment above and Bedrock access to **Amazon Nova 2 Sonic** (`amazon.nova-2-sonic-v1:0`, us-east-1 or three other regions). The web app serves a page `/voice` with a microphone button; your voice goes to Nova 2 Sonic, which calls the same seven tools through the AgentCore Gateway with the diner's own token, so every rule of the server applies. The assistant holds a table, reads the details back, and books only after you say yes.

1. Sign in to AWS on your machine (the profile that owns the deployment) and install the optional extra: `pip install -e ".[web,sim,voice]"` (Python 3.12).
2. Read the settings from the deployed stacks and start the web app. Bash:

   ```bash
   export AWS_REGION=us-east-1                 # and your profile, for example AWS_PROFILE=<profile>
   OUT() { aws cloudformation describe-stacks --stack-name "$1" --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text; }
   POOL=$(OUT FairTableIdentity UserPoolId)
   export AUTH_PROVIDER=cognito AUTH_TOKEN_USE=access AUTH_AUDIENCE_CLAIM=client_id
   export AUTH_ISSUER=$(OUT FairTableIdentity Issuer)
   export COGNITO_CLIENT_ID=$(OUT FairTableIdentity ClientIdAlexaPlusSim)
   export COGNITO_CLIENT_SECRET=$(aws cognito-idp describe-user-pool-client --user-pool-id "$POOL" --client-id "$COGNITO_CLIENT_ID" --query UserPoolClient.ClientSecret --output text)
   export AUTH_AUDIENCE=$(aws cognito-idp list-user-pool-clients --user-pool-id "$POOL" --query "UserPoolClients[].ClientId" --output text | tr '\t' ',')
   export MCP_URL=$(OUT FairTableGateway GatewayUrl) MCP_VIA_GATEWAY=true TABLE_NAME=fairtable VOICE_ENABLED=true
   python -m web
   ```

   PowerShell:

   ```powershell
   $env:AWS_REGION = "us-east-1"               # and your profile: $env:AWS_PROFILE = "<profile>"
   function Out($stack, $key) { aws cloudformation describe-stacks --stack-name $stack --query "Stacks[0].Outputs[?OutputKey=='$key'].OutputValue" --output text }
   $pool = Out FairTableIdentity UserPoolId
   $env:AUTH_PROVIDER = "cognito"; $env:AUTH_TOKEN_USE = "access"; $env:AUTH_AUDIENCE_CLAIM = "client_id"
   $env:AUTH_ISSUER = Out FairTableIdentity Issuer
   $env:COGNITO_CLIENT_ID = Out FairTableIdentity ClientIdAlexaPlusSim
   $env:COGNITO_CLIENT_SECRET = aws cognito-idp describe-user-pool-client --user-pool-id $pool --client-id $env:COGNITO_CLIENT_ID --query UserPoolClient.ClientSecret --output text
   $env:AUTH_AUDIENCE = (aws cognito-idp list-user-pool-clients --user-pool-id $pool --query "UserPoolClients[].ClientId" --output text) -replace "\s+", ","
   $env:MCP_URL = Out FairTableGateway GatewayUrl; $env:MCP_VIA_GATEWAY = "true"; $env:TABLE_NAME = "fairtable"; $env:VOICE_ENABLED = "true"
   python -m web
   ```

3. Open http://localhost:8080/voice, sign in as `diner-alice` / `alice-dev-pass` (the Cognito users have the same names and passwords as the local ones), press **Start the call**, allow the microphone, and say: *"Book a table at Luna Trattoria for two people tomorrow at seven in the evening."* Use headphones, or the speaker's sound goes back into the microphone. When the assistant asks "Shall I book it?", say *"Yes, please."* The page shows what you said, what it said, and each tool call behind it. Stop with **End the call**; a call lasts at most seven minutes.
4. Cost: a whole booking conversation used about 3,300 tokens in and 1,400 out (speech tokens cost $3 and $12 per million in us-east-1 on 2026-09-30), under two cents. `VOICE_REGION` and `VOICE_NAME` change the region and the voice. If the call stops at the start, check that your account can use Nova 2 Sonic in that region.

The same flow is tested end to end without a person: `pytest -m aws tests/aws/test_voice.py` plays two recorded sentences into the page's endpoint and checks that the assistant asks before booking and books after the yes.

## Documentation
- Decisions log: [`docs/DECISIONS.md`](docs/DECISIONS.md)
- Plan: [`docs/PLAN.md`](docs/PLAN.md) and the working log [`docs/devlog/`](docs/devlog/)
- AWS services and how they are used: [`docs/aws-integration.md`](docs/aws-integration.md)
- Hackathon requirements and FAQ clarifications: [`docs/hackathon-rules.md`](docs/hackathon-rules.md)
- Friction log (problems met with AWS and MCP tooling): [`docs/friction-log.md`](docs/friction-log.md)
- How the server compares with Amazon's Alexa+ add-on requirements, and the deliberate differences: [`docs/alexa-plus-addon-notes.md`](docs/alexa-plus-addon-notes.md)
- Evaluation reports and the chart: [`eval/reports/`](eval/reports/)
- Architecture (English): `docs/ARCHITECTURE.md` _(planned, task P0-5)_

## Repository layout
`server/` MCP server and rule engine · `policies/` Cedar rules · `devauth/` dev token issuer · `web/` sign-in, owner console, chat page · `simulator/` simulated assistant · `eval/` evaluation and red team · `scripts/` seed and health check · `tests/`. Each directory has its own `README.md`. Full plan: [`docs/PLAN.md`](docs/PLAN.md) §4.

## License
[Apache-2.0](LICENSE)
