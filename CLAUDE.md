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
3. `docs/ARCHITECTURE.md` (English) – the as-built design; it replaced the Vietnamese design document (D-060). If code and design disagree, ask me.
4. `docs/hackathon-rules.md` – submission requirements and FAQ clarifications.
5. `docs/*.drawio` – the developer's own diagrams (XML, edited in place to match the build, D-060). Keep their style; do not regenerate them.
6. `docs/alexa-plus-addon-notes.md` – Amazon's add-on requirements as they apply here. The Vietnamese design, the research note and the raw rule texts live outside the repo in `C:\AWS_BUILD\FairTable-private-docs\` (D-060).

## Hard requirements (hackathon rules)
- MCP server on spec **2025-11-25** with **Streamable HTTP**; the repo must actually import and run it (not just mention it).
- Public repo, Apache-2.0 license, README with run instructions (working from a fresh clone) and the list of AWS services used. README lists the dev test logins.
- **The local profile is what judges run:** `docker compose up` starts everything with no AWS account (server, DynamoDB Local, chat page + owner console, dev JWT issuer in `devauth/`, simulator with `MODEL_PROVIDER=mock`). A real provider is opt-in via env.
- Rules digest: `docs/hackathon-rules.md` (dates, submission form fields, testing clause, judging). The raw rule text is not kept in the repo; do not re-fetch it, and update the digest if the rules change.
- Demo video (< 3 min) shows the server working **and the AWS-deployed path at least once** (AWS Builder). Targeting AWS Builder only; the Open Source mini challenge is out of scope.
- `docs/aws-integration.md` describes each AWS service used and how.

## Architecture decisions – do not change without asking
- **No LLM inside MCP tools.** Tools are deterministic. LLMs appear only in the simulator, the eval harness, and (later) owner rule extraction.
- **7 tools (`mandate_status` was removed, D-053):** `restaurant_search`, `availability_check`, `reservation_hold`, `reservation_confirm`, `reservation_manage`, `waitlist_watch`, `waitlist_status`.
- **Two policy enforcement points, same language (Cedar), both run in the server with `cedarpy`:**
  - PEP-1 (stateless): G1–G4, including the `has`-guard on G4. Evaluated first.
  - PEP-2 (stateful): P0 + S1–S4 in `policies/*.cedar` (see design §6.2). Map cedarpy's `policyN` reasons to the `@id` / `@on_deny` annotations via `policies_to_json_str`. Priority: deny > step_up > allow; no matching permit → POLICY_DENIED.
  - AWS profile: AgentCore Gateway Policy repeats G1–G4 as **defense in depth** (not the only place they live). Local and Gateway policy sets share one behavioural test suite.
- **Writes:** one DynamoDB `TransactWriteItems` per state change (slot, counters, hold, idempotency record, audit). DB conditions are the final guarantee under concurrency.
- **Idempotency:** key = (user sub, idempotency_key). Same params → return stored result; different params → `IDEMPOTENCY_CONFLICT`. Store only when state actually changed.
- **Never rely on DynamoDB TTL for business logic.** Always check `expires_at` on read.
- **Lazy evaluation is the base; on AWS a clock runs the same routines (D-062):**
  - expired holds are treated as released when read;
  - waitlist matching runs inside the cancel / hold-expiry code paths;
  - Fair Drop allocation is triggered by the first request after the drop time.
  - The logic is in pure functions; on AWS the Lambda `FairTableWorkers` (EventBridge Scheduler, every minute) calls `server/workers.py`. Every feature still works without it.
- **Confirmation is 100 % voice (D-051, built in P3-10; the phone step-up is gone):** a booking outside the standing permission or with a fee is confirmed by a spoken yes that the assistant relays. The server guards it: `reservation_hold` returns the terms, a read-back sentence and a signed `read_back_token`; `reservation_confirm` must carry the token and `user_confirmed`, and arrive after a minimum pause (3 s, 6 s with a fee); each booking stores `confirmation = spoken` and when the read-back was handed over. No `-32042`, no consent link, no e-mail. The server cannot hear the diner: say so wherever the guarantee is described. 
- **Tool outputs:** structured errors (`isError: true`) with `next_step`; every successful output includes a short `spoken_summary`.
- **Waitlists and MCP Tasks:** DynamoDB is the source of truth for watches and drop entries; `waitlist_status` is the primary path. MCP Tasks (FastMCP `task=True`, `pydocket`) are an **optional view** behind a flag, default off; `memory://` is only for testing/local demo. Every feature must work with Tasks disabled. **No Redis / ElastiCache.**
- **Identity:**
  - Local profile: a **dev JWT issuer** (`devauth/`) stands in for Cognito, with seeded test users and an M2M bot client (no `username`, no `agent_tier`). Tokens go in `x-ft-user-token`.
  - AWS profile: Cognito + Gateway REQUEST interceptor copies the user token to `x-ft-user-token` (the interceptor must strip any client-supplied value).
  - Both profiles: the server re-verifies the token with `joserfc`, same code; only issuer, JWKS URL and audience change.
- **Minimal scope for supporting apps:** simulator = one Strands agent + a simple chat page; owner data seeded by a Python script first; consent page retired from the booking flow (D-051); owner console = change the agent-share cap and view audit.
- **`MODEL_PROVIDER` is configurable** (`mock` default; `bedrock` and others opt-in). No LLM provider is required to run the repo.

## Pinned versions
`fastmcp==3.4.7`, `mcp==1.30.0` (do **not** upgrade to 2.x), `strands-agents==1.57.1`, `cedarpy==4.12.1`, plus `joserfc`, `mangum`, `boto3`, `pydantic`, `pytest`.

## Environment constraints
- **Amazon Bedrock is currently blocked on my first AWS account** (the second account can call it, D-043; support case pending; DeepSeek flash is the real model meanwhile, D-018/D-028). The $150 credit is real (D-030) and MFA is on (D-034). Build and test everything **locally first**:
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
server/      FastMCP server, 7 tools, Trust Kernel (cedarpy: PEP-1 + PEP-2)
policies/    *.cedar, flat: g1–g4 (PEP-1), p0 + s1–s4 (PEP-2)
devauth/     dev JWT issuer standing in for Cognito (compose service)
workers/     (later) Lambda sweeper, allocator, watch matcher
web/         FastAPI: sign-in, chat page + owner console
simulator/   Alexa+ simulator (Strands, mock model default)
eval/        task YAML, harness, pass^k reports
infra/       CDK / agentcore config (AWS profile only)
scripts/     seed data, local setup
tests/       unit/ integration/ redteam/ aws/
docs/        DECISIONS, PLAN, aws-integration, friction log, devlog/ (per-phase plan + progress + entries), rules, (design, diagrams, research until replaced)
Dockerfile, docker-compose.yml   primary run path (created in plan task P1-23)
```

## Where things stand (updated 2026-10-04, session 5)
- **Session 5 (2026-10-04):** built since session 4: the OAuth discovery document, `Authorization: Bearer` and HTTP 403 for a service token (D-065); rule S6, one confirmed table per diner, restaurant and day, with a `BOOKED#` marker (D-066); the owner console sets the cancellation terms and creates a Fair Drop (D-067); the owner console on Lambda + an HTTP API, deployed and checked on the second account (D-068, opt-in `OWNER_WEB=true`); real-model evaluation with DeepSeek, Haiku and Nova Lite (D-064; the Nova Lite loops cost about $4.2, so a real-model run needs a cap first); both diagrams mark what is a future improvement (italic grey). Whole suite 1270 passed. **AWS now:** Data, Identity, Notify, Budget and OwnerWeb are up; the AgentCore parts are down. The account is over its $5 cap ($6.89 with tax on 2026-10-04). Still to do: the frozen evaluation re-run with the final code, `-m docker`, the fresh-clone check, the Devpost description, the video (15 to 17 Oct), the `submission` tag.

- **Phases 1 and 2 are complete** (local profile, then the AWS profile in the second account; see `docs/devlog/phase-1.md` and `phase-2.md`). **Phase 3** (`docs/devlog/phase-3.md`) is the live file: eval numbers, voice confirmation, voice demo, SNS, English docs, freeze. Verified AgentCore facts are in `docs/PLAN.md` section 3a. AWS resources exist in the second account until the developer says the footage is recorded (D-044).
- **Session 4 (2026-10-03):** the developer plans to record the video on 16 or 17 October. Built since: fuzzy `restaurant_search` (D-061), the workers Lambda + EventBridge Scheduler, the S3 audit copy and the KMS seed (D-062), versions frozen (D-063, `constraints.txt`), voice page polish; whole local suite 1162 passed (+ the 2 eval tests fixed), `-m docker` 5 passed, real-AWS tests passed, the evaluation re-run (A1: 0 violations, gate passed). **AWS was partly torn down at the developer's request:** the AgentCore parts (stacks Observability, Workers, Gateway, Runtime) were destroyed; the table, the Cognito pool, the SNS topic and the audit bucket (stacks Data, Identity, Notify) and the budget stay. To get everything back: `NOTIFY_EMAIL=<address> MCP_ALLOWED_HOSTS='*.lambda-microvm.*.on.aws' GATEWAY_POLICY=ENFORCE OBSERVABILITY=true OBSERVABILITY_RUNTIME=true python infra/aws_ctl.py up --runtime` (about 15 minutes), then `SEED_PROVIDER=kms python infra/aws_ctl.py seed` and `pytest -m aws tests/aws` before recording. Re-seed before the video so that the Fair Drop dates are in the future.
- **Session 3 (2026-10-02, voice works):** SNS is live (the developer received the test e-mail); the voice page `/voice` (Nova 2 Sonic, `VOICE_ENABLED=true`, extra `voice`) books a table by voice through the Gateway after D-059: `offer_id` (8 characters, stored in DynamoDB) replaces the long `slot_token`, the read-back code is 11 characters, a reused idempotency key no longer replays a dead hold. Real-AWS tests: all of `tests/aws` pass (37), voice booking 4 of 4; local suite 1106 passed (+ the CDK synthesis file alone 49 passed; do not run it while a `cdk deploy` uses the same folders). Not done yet: the developer's own listening test, the `-m docker` smoke run, a final whole-suite run, the frozen eval numbers (P3-8), English `ARCHITECTURE.md`, diagrams, Vietnamese docs out, version pins.
- **Session 3 (2026-10-02, AWS wired):** the seven-tool server (voice confirmation, HTTP 401) runs on the second account (1905): Runtime redeployed, Gateway re-synced and read policy updated, data re-seeded, `pytest -m aws tests/aws` 35 passed, 1 skipped; a real model (DeepSeek) booked through the Gateway. Not deployed: SNS (needs the address in `NOTIFY_EMAIL` and "wire SNS"), Bedrock voice (P3-11, the developer chose the browser page with a microphone, form B). Deploy with `MCP_ALLOWED_HOSTS='*.lambda-microvm.*.on.aws' GATEWAY_POLICY=ENFORCE OBSERVABILITY=true OBSERVABILITY_RUNTIME=true` so that the other stacks keep what they have. Nothing is cleaned up until the developer says the footage is recorded.
- **Session 3 (2026-10-02, newest):** P3-2 and P3-3 done (D-057): `python -m eval --merge ...`, `python -m eval.gate`, `python -m eval.charts`, whole suite 1089 passed, 41 skipped; committed run `eval/reports/mock-k4-2026-10-02.*` (mock, k = 4: A1 clean, A0 28 violations, A2 28). P3-12 local part done: `SnsNotifier` behind `NOTIFY_TOPIC_ARN`, CDK stack `FairTableNotify` (needs `NOTIFY_EMAIL` at deploy), not deployed. The developer will record the video only after every feature, voice included, is built and wired once on AWS; AWS stays up until then (D-044 cleanup waits for their word). Next: P3-11 research (Nova 2 Sonic), then the single wire (Runtime 7 tools, SNS, Bedrock).
- **Session 3 (2026-10-02, latest):** P3-9 done (D-056): spoken parts free of codes and names, five options at most, HTTP 401 for a tool call without a valid token (`server/http_auth.py`), plain argument errors; whole suite 1056 passed, 40 skipped; the notes list what was left alone (duplicate bookings, `modify` of day or time, `Authorization: Bearer`, well-known document). Next: one DeepSeek check of the voice flow, then P3-2/P3-3.
- **Session 3 (2026-10-02, later):** P3-10 is built locally: confirmation is a spoken yes guarded by a signed read-back token, a pause and an explicit yes (rules S5a-c); no mandate, no approval page, no `-32042`, seven tools, stateless by default (D-051, D-053, D-054, D-055; whole suite 1034 passed, 40 skipped). Still to do for it: the AWS redeploy (plan step 8, needs the developer's go) and the `-m docker` smoke run. Next: P3-9, P3-2 (report with k > 1), the voice demo (P3-11), SNS (P3-12), docs and freeze.
- **Session 3 (2026-10-02, earlier):** Phase 2 is closed (P2-9 observability done: Transaction Search plus Gateway, Policy and Runtime spans, D-050; last full suite 1060 passed, 40 skipped). Phase 3 started (`docs/devlog/phase-3.md`): the 40-task set and its generator exist (`eval/generate.py`, `python -m eval.generate --check`; all 40 pass under A1 with the mock model; the ten starter tasks moved to `tests/fixtures/eval_starter/` because tests pin their numbers). Decisions D-051 (100 % voice confirmation, Alexa+ client facts) and D-052 (voice demo with a speech model) change the plan: P3-10 builds the voice confirmation before the numbers are measured, P3-11 the voice demo, P3-9 checks the Alexa+ add-on requirements. AWS stays up in the second account until the developer says the footage is recorded (D-044).
- **Phase 2 status (2026-10-01):** D-035 confirmed. `docs/devlog/phase-2.md` is the live file. Done: P2-1 (DynamoDB, budget), P2-2 (Cognito + V3_0 trigger), P2-3 (Runtime V2, zip), P2-4 (verifier), P2-5 (Gateway `fairtable-gw` + REQUEST interceptor, tools are named `ft___<tool>`; 25/25 real-AWS tests), P2-8 (`python infra/aws_ctl.py status|up|seed|down`). The first AWS account is blocked for Bedrock and Runtime (zero quotas, support case open, D-041/D-042); **the AWS profile runs in the second account** (profile `fairtable2-admin`, IAM user with MFA, budget $5, D-043/D-044/D-045). Credentials: `aws login` sessions cannot be read by boto3 here (no `awscrt`): use `scripts/aws_credential_process.py` with `FAIRTABLE_SOURCE_PROFILE=<profile>`; `down --yes` needs `--account <last4>`. Real-AWS tests: `pytest -m aws tests/aws`. P2-10 (Cognito sign-in for the web pages, the assistant through the Gateway; `AUTH_PROVIDER=cognito`, `MCP_VIA_GATEWAY=true`, see web/README.md) is done too. P2-7 is done: `-32042` does NOT survive the Gateway (D-048), so AWS stays stateless and the step-up is the plain `CONSENT_REQUIRED` result with the link. P2-6 is done too (2026-10-02, D-049): Gateway Policy G1-G4 deployed on the second account, engine `fairtable_engine` attached in `ENFORCE` (set `GATEWAY_POLICY=LOG_ONLY|ENFORCE`; the first deploy needs `GATEWAY_POLICY_STAGE=permits`, `aws_ctl.py up` does both). P2-9 is done too; what comes next is in the Session 3 line above. Clean up per D-044 only when the developer says the footage is recorded.

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
