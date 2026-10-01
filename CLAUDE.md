# FairTable – project context for Claude Code

## What this project is
- Entry for the Amazon Developer Hackathon "Build, Ship, Shape" – **Alexa+ track** (+ AWS Builder mini challenge).
- Deadline: **2026-10-23 12:00 PDT**. Solo developer. Language: **Python 3.12**.
- **Everything written (code, comments, docstrings, docs, commit messages) is in English** – submission rule. Existing Vietnamese docs are temporary (see `docs/DECISIONS.md` D-009).
- The developer runs `git add` / `git commit`. Do not commit unless asked.
- FairTable is a **self-hosted MCP server (spec 2025-11-25, Streamable HTTP)** that gives independent restaurants a trusted "front door" for AI booking agents (Alexa+ first): verified identity, owner-set rules, step-up consent, standing waitlists, and a fair lottery for hot tables.

## Source of truth (read in this order)
1. `docs/DECISIONS.md` – decisions made after the design; **wins over the design doc** where they differ.
2. `docs/PLAN.md` – phased plan, tasks, acceptance criteria, risks.
3. `docs/fairtable-solution-design.md` (v2, Vietnamese, temporary) – **authoritative design** until `docs/ARCHITECTURE.md` (English) replaces it (plan task P0-5). If code and design disagree, ask me.
4. `docs/hackathon-rules.md` – submission requirements and FAQ clarifications.
5. `docs/*.drawio` – diagrams (XML). The design doc already contains Mermaid equivalents; open these only if needed.
6. `docs/research-alexa-plus-round3-2026-09.md` – background/evidence only. Do not implement from it.

## Hard requirements (hackathon rules)
- MCP server on spec **2025-11-25** with **Streamable HTTP**; the repo must actually import and run it (not just mention it).
- Public repo, Apache-2.0 license, README with run instructions (working from a fresh clone) and the list of AWS services used. README lists the dev test logins.
- **The local profile is what judges run:** `docker compose up` starts everything with no AWS account (server, DynamoDB Local, consent page + owner console, dev JWT issuer in `devauth/`, simulator with `MODEL_PROVIDER=mock`). A real provider is opt-in via env.
- Rules digest: `docs/hackathon-rules.md` (dates, submission form fields, testing clause, judging). The raw rule text is not kept in the repo; do not re-fetch it, and update the digest if the rules change.
- Demo video (< 3 min) shows the server working **and the AWS-deployed path at least once** (AWS Builder). Targeting AWS Builder only; the Open Source mini challenge is out of scope.
- `docs/aws-integration.md` describes each AWS service used and how.

## Architecture decisions – do not change without asking
- **No LLM inside MCP tools.** Tools are deterministic. LLMs appear only in the simulator, the eval harness, and (later) owner rule extraction.
- **8 tools:** `restaurant_search`, `availability_check`, `mandate_status`, `reservation_hold`, `reservation_confirm`, `reservation_manage`, `waitlist_watch`, `waitlist_status`.
- **Two policy enforcement points, same language (Cedar), both run in the server with `cedarpy`:**
  - PEP-1 (stateless): G1–G4, including the `has`-guard on G4. Evaluated first.
  - PEP-2 (stateful): P0 + S1–S4 in `policies/*.cedar` (see design §6.2). Map cedarpy's `policyN` reasons to the `@id` / `@on_deny` annotations via `policies_to_json_str`. Priority: deny > step_up > allow; no matching permit → POLICY_DENIED.
  - AWS profile: AgentCore Gateway Policy repeats G1–G4 as **defense in depth** (not the only place they live). Local and Gateway policy sets share one behavioural test suite.
- **Writes:** one DynamoDB `TransactWriteItems` per state change (slot, counters, hold, idempotency record, audit). DB conditions are the final guarantee under concurrency.
- **Idempotency:** key = (user sub, idempotency_key). Same params → return stored result; different params → `IDEMPOTENCY_CONFLICT`. Store only when state actually changed.
- **Never rely on DynamoDB TTL for business logic.** Always check `expires_at` on read.
- **MVP uses lazy evaluation – no background workers yet:**
  - expired holds are treated as released when read;
  - waitlist matching runs inside the cancel / hold-expiry code paths;
  - Fair Drop allocation is triggered by the first request after the drop time.
  - Keep this logic in pure functions so Lambdas (sweeper, allocator, watch matcher) can reuse it later.
- **Step-up consent:** JSON-RPC error **-32042** (URLElicitationRequiredError) with a consent URL.
- **Tool outputs:** structured errors (`isError: true`) with `next_step`; every successful output includes a short `spoken_summary`.
- **Waitlists and MCP Tasks:** DynamoDB is the source of truth for watches and drop entries; `waitlist_status` is the primary path. MCP Tasks (FastMCP `task=True`, `pydocket`) are an **optional view** behind a flag, default off; `memory://` is only for testing/local demo. Every feature must work with Tasks disabled. **No Redis / ElastiCache.**
- **Identity:**
  - Local profile: a **dev JWT issuer** (`devauth/`) stands in for Cognito, with seeded test users and an M2M bot client (no `username`, no `agent_tier`). Tokens go in `x-ft-user-token`.
  - AWS profile: Cognito + Gateway REQUEST interceptor copies the user token to `x-ft-user-token` (the interceptor must strip any client-supplied value).
  - Both profiles: the server re-verifies the token with `joserfc`, same code; only issuer, JWKS URL and audience change.
- **Minimal scope for supporting apps:** simulator = one Strands agent + a simple chat page; owner data seeded by a Python script first; consent page = one HTML page with Approve / Decline; owner console = change the agent-share cap and view audit.
- **`MODEL_PROVIDER` is configurable** (`mock` default; `bedrock` and others opt-in). No LLM provider is required to run the repo.

## Pinned versions
`fastmcp==3.4.7`, `mcp==1.30.0` (do **not** upgrade to 2.x), `strands-agents==1.57.1`, `cedarpy==4.12.1`, plus `joserfc`, `mangum`, `boto3`, `pydantic`, `pytest`.

## Environment constraints
- **Amazon Bedrock is currently blocked on my AWS account** (support case pending; DeepSeek flash is the real model meanwhile, D-018/D-028). The $150 credit is real (D-030) and MFA is on (D-034). Build and test everything **locally first**:
  - DynamoDB Local (Docker) – no `moto`;
  - MCP Inspector for manual testing;
  - a mock LLM for the simulator (`MODEL_PROVIDER=mock`).
- **Do not plan on keeping AWS resources running.** Spin them up for tests and the demo, then tear them down (scripted). Judging runs Nov 9–20 and may include automated AI review.
- **AWS wiring is scaffold-only until the user says "wire AWS"** (D-016): interfaces, env-driven config and skeletons yes; real AWS calls, credentials, deployed resources or AWS-dependent tests no.
- **Nothing account-specific in code:** no hard-coded account IDs, ARNs, or regions. Read from env/config (`AWS_PROFILE`, `AWS_REGION`, `TABLE_NAME`, …). Target region later: `us-east-1`.
- **After the deadline (10-23) nothing functional changes** until judging ends (11-20): tag the submitted commit `submission` (D-015). Pin dependency versions and Docker image tags before the freeze.
- **Never commit secrets** (`.env`, keys, tokens). The repo is public.

## Working style
- Before using any FastMCP / AgentCore / Strands / cedarpy API, **verify it against the installed package source or official docs** – do not guess signatures. Items marked ❓ in the design doc must be verified before building on them.
- **When unsure, look it up – never guess.** Order: installed package source first, then a web search / fetch of the official docs (modelcontextprotocol.io, gofastmcp.com, docs.aws.amazon.com/bedrock-agentcore, cedarpolicy.com, strandsagents.com, PyPI/GitHub for the pinned versions). Prefer the doc version matching the pinned package. If the sources disagree or nothing is found, say so and ask me instead of inventing an API, flag, or behaviour. Record the source you relied on in `docs/friction-log.md` or the PR notes.
- Work in small steps; every step comes with pytest tests. Keep MCP tool handlers thin; business logic lives in pure, testable functions.
- Scope priority: **Must > Should > Could** (design doc §11). Ask before starting any Could item.
- Keep a friction log (`docs/friction-log.md`) of problems hit with AWS / MCP tooling – it counts for judging.

## Workflow (every session)
Work is organised in **phases** (`docs/PLAN.md`) and, inside a phase, **batches** of a few tasks. The live plan and status of each phase is `docs/devlog/phase-N.md` (Plan, Progress table, Entries; see `docs/devlog/README.md`).

1. **Start of a session:** read `CLAUDE.md`, `docs/DECISIONS.md`, `docs/PLAN.md`, then the current `docs/devlog/phase-N.md`. Confirm which batch is next; if the user has not named one, propose it.
2. **Start of a batch:** mark its tasks `in progress` in the phase file's Progress table. If the plan for the batch changes (order, scope, a new task), update the Plan section and say so in the report.
3. **For each task:** verify APIs first (see Working style) → implement small pure functions and thin handlers → write pytest tests → run the **whole** suite and `ruff` → only then mark the task `done`.
4. **After each task:** add an Entry at the top of the phase file's Entries (template in the devlog README, with a feature tag) and update the Progress row. Also, where it applies:
   - a decision was made → `docs/DECISIONS.md` (new D-xxx);
   - an API or behaviour was verified → `docs/PLAN.md` §3a "Verified APIs" (exact names and versions);
   - a problem with AWS / MCP tooling → `docs/friction-log.md`;
   - a later change to a finished feature → a new `Change:` entry, never an edit of the old one.
5. **Do not guess.** If something is unclear, sources disagree, or a decision changes the architecture (see "do not change without asking"), stop that task, record it under Follow-ups, and ask.
6. **End of a batch:** stop and report: what passed, what needed a workaround, changed/new files, the gate verdict if there is one, and the questions still open. Wait for review before the next batch. Do not start the next phase without the user's go-ahead.
7. **Git:** the user runs `git add` / `git commit`. Suggest a commit message (English) at the end of a batch; never commit.
8. **Docker / external processes:** start Docker Desktop only for tests that need it (`-m ddb`, `-m docker`) and shut it down afterwards.
9. Everything written (code, comments, docs, devlog) is English. Replies to the user may be in the language the user writes in.

## Target repo layout
```
server/      FastMCP server, 8 tools, Trust Kernel (cedarpy: PEP-1 + PEP-2)
policies/    *.cedar, flat: g1–g4 (PEP-1), p0 + s1–s4 (PEP-2)
devauth/     dev JWT issuer standing in for Cognito (compose service)
workers/     (later) Lambda sweeper, allocator, watch matcher
web/         FastAPI: consent page + owner console
simulator/   Alexa+ simulator (Strands, mock model default)
eval/        task YAML, harness, pass^k reports
infra/       CDK / agentcore config (AWS profile only)
scripts/     seed data, local setup
tests/       unit/ integration/ redteam/ aws/
docs/        DECISIONS, PLAN, aws-integration, friction log, devlog/ (per-phase plan + progress + entries), rules, (design, diagrams, research until replaced)
Dockerfile, docker-compose.yml   primary run path (created in plan task P1-23)
```

## Where things stand (updated 2026-09-30, end of session 2)
- **Phase 1 is complete** (batches A-F plus the additions in the devlog: owner console, chat page with the tool-call steps, standing permission on the approval page D-033, OpenTelemetry spans D-032, Docker profile D-029, eval harness, A0/A1/A2 and red team). Last full suite: see `docs/devlog/phase-1.md` (about 800 tests; 5 Docker smoke tests only run with `-m docker`). **Phase 2 (AWS) has not started; no AWS resource exists.** Its plan and the verified AgentCore facts are in `docs/PLAN.md` (Phase 2 table and section 3a, "AgentCore facts" and "second pass"). Create `docs/devlog/phase-2.md` when it starts.
- The developer's confirmation is still needed for the Phase 2 choices listed in the last devlog entry (then record them as D-035).
- **Phase 2 status (2026-10-01):** D-035 confirmed. `docs/devlog/phase-2.md` is the live file. Done: P2-1 (DynamoDB, budget), P2-2 (Cognito + V3_0 trigger), P2-3 (Runtime V2, zip), P2-4 (verifier), P2-5 (Gateway `fairtable-gw` + REQUEST interceptor, tools are named `ft___<tool>`; 25/25 real-AWS tests), P2-8 (`python infra/aws_ctl.py status|up|seed|down`). The first AWS account is blocked for Bedrock and Runtime (zero quotas, support case open, D-041/D-042); **the AWS profile runs in the second account** (profile `fairtable2-admin`, IAM user with MFA, budget $5, D-043/D-044/D-045). Credentials: `aws login` sessions cannot be read by boto3 here (no `awscrt`): use `scripts/aws_credential_process.py` with `FAIRTABLE_SOURCE_PROFILE=<profile>`; `down --yes` needs `--account <last4>`. Real-AWS tests: `pytest -m aws tests/aws`. P2-10 (Cognito sign-in for the web pages, the assistant through the Gateway; `AUTH_PROVIDER=cognito`, `MCP_VIA_GATEWAY=true`, see web/README.md) is done too. P2-7 is done: `-32042` does NOT survive the Gateway (D-048), so AWS stays stateless and the step-up is the plain `CONSENT_REQUIRED` result with the link. P2-6 is done too (2026-10-02, D-049): Gateway Policy G1-G4 deployed on the second account, engine `fairtable_engine` attached in `ENFORCE` (set `GATEWAY_POLICY=LOG_ONLY|ENFORCE`; the first deploy needs `GATEWAY_POLICY_STAGE=permits`, `aws_ctl.py up` does both). Next: P2-9 (observability), clean up per D-044, then Phase 3.

## Commands that work here (Windows, Git Bash, conda env `fairtable`)
- Local stack: `docker compose up -d --build --wait` (web 8080, MCP 8000, issuer 9000, DynamoDB Local **8001**); stop with `docker compose down`. `.env` (git-ignored) selects the model: `MODEL_PROVIDER=mock|deepseek`; never print it, and do not export the whole file (an empty `AWS_PROFILE=` breaks boto3): load only `DEEPSEEK_*`.
- Tests: `DDB_ENDPOINT_URL=http://localhost:8001 python -m pytest -q` (whole suite, about 12 minutes, run it in the background and wait for it); unit tests need nothing; `-m docker` builds and drives the compose stack.
- Evaluation: `python -m eval --k 2 --config A0,A1,A2`, `python -m eval.redteam`. Runtime package: `python infra/runtime/build_zip.py`.

## Session tool quirks (cost hours once; do not repeat)
- **Shell:** long heredocs with quotes can fail to parse, and backslash escapes are unescaped once by the tool layer (a `\1` became a control character, `\r\n` became real newlines). For files, use the Write tool (or a script written with Write and then run); build strings with backslashes using `chr(92)` in a shell command. In Git Bash `curl -d "next=/chat"` is rewritten to a Windows path: `export MSYS_NO_PATHCONV=1`. `conda run python -c` drops multi-line code.
- **Waiting:** never `sleep` in a command; use a background command plus a Monitor with an `until` loop. A hung test run is usually the SSE/signal-handler problem (`tests/conftest.py` restores handlers).
- **Do not run Docker tests against the developer's running stack** without saying so: `pytest -m docker` starts and then stops the `fairtable` compose project.
- **Order of trust:** installed package source, then the AWS documentation tools (`mcp__aws-docs__*`), then the official pricing page fetched raw with curl. A summary from a web fetch is one source, not proof.

## Also expected from every session (added by the developer)
- Answer questions in plain Vietnamese, short, with a recommendation; say what is verified and what is not; show real numbers.
- After every change: whole suite, `ruff`, a devlog entry, and the decision/verified-API/friction-log records; suggest an English commit message with the attribution lines; never commit.
- For any AWS service: verify with the documentation, look at the price on the official page, say the cost before creating anything, tag `project=fairtable`, script the teardown, and wait for "wire X". Prefer the cheapest option that still shows the service (idle timeouts, MONITOR before ENFORCE, no natural-language policy generation).
- AWS rule (2026-10-01, D-044): deploy to test, and once the tests are stable remove what bills by time or use with `python infra/aws_ctl.py down --yes --account <last4>`; run `status` afterwards and report what is left. The new account has a small budget (about $5). Two accounts exist: always say which one a command runs in, and never use a root user.
