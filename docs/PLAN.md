# FairTable – Implementation Plan (draft for review)

Status: **draft v0.2 – 2026-09-29. Documentation and codebase organisation first; no implementation yet.**
Decisions behind this version are in `docs/DECISIONS.md` (D-001 … D-013). Where this plan and `DECISIONS.md` differ, `DECISIONS.md` wins.
Sources: `CLAUDE.md`, `docs/fairtable-solution-design.md` (v2, Vietnamese, until `ARCHITECTURE.md` replaces it – D-009), `docs/hackathon-rules.md`.

Local environment found on the developer PC: Windows 11, Docker 29.4.0, Java 25, Node 22, Python **3.13.9** (default) and 3.11 – no 3.12, no `uv`.

Working agreement (D-013): the developer commits; the assistant does not. Everything written (code, comments, docs) is English (D-009).

---

## 1. Understanding of the MVP

1. **Product:** FairTable is a self-hosted MCP server (spec 2025-11-25, Streamable HTTP; FastMCP 3.4.7 + mcp 1.30.0) that acts as a restaurant's front door for AI booking agents. The restaurant sets the rules, the server enforces them, and agents get structured, self-correcting errors.
2. **8 deterministic tools, no LLM inside them:** `restaurant_search`, `availability_check`, `mandate_status`, `reservation_hold`, `reservation_confirm`, `reservation_manage`, `waitlist_watch`, `waitlist_status`. Handlers stay thin. Every success returns `spoken_summary`; every failure is `isError: true` with a `next_step`.
3. **The local profile is what judges run (D-007).** `docker compose up` from a fresh clone starts, with no AWS account: the MCP server, DynamoDB Local, consent page + owner console, a **dev JWT issuer** (`devauth/`, standing in for Cognito, seeded test users), and the simulator with `MODEL_PROVIDER=mock`. A real model provider is opt-in via env. Test logins are in the README.
4. **Identity:** every write is tied to a verified user. The server verifies the token from `x-ft-user-token` with `joserfc`. The same code runs in both profiles; only issuer, JWKS URL and audience change (dev issuer locally, Cognito on AWS).
5. **Two enforcement points, both in the server, both Cedar via `cedarpy` (D-008):**
   - PEP-1: G1–G4 (stateless: claims and request shape, `has`-guard on G4);
   - PEP-2: P0 + S1–S4 (stateful: counters and mandate from DynamoDB).

   Order: PEP-1 then PEP-2. Priority: deny > step_up > allow; no matching permit is `POLICY_DENIED`. `policyN` reasons map back to `@id` / `@on_deny` via `policies_to_json_str`. On AWS, Gateway Policy repeats G1–G4 as defense in depth.
6. **Writes:** one `TransactWriteItems` per state change (slot, counters, hold, idempotency record, audit). Cedar decides; DynamoDB conditions guarantee under concurrency. Idempotency is keyed on (`sub`, `idempotency_key`): same params return the stored result, different params return `IDEMPOTENCY_CONFLICT`, and nothing is stored unless state changed.
7. **Standing mandate + step-up:** a per-user, per-venue scope record read on every call. A confirm outside the mandate returns JSON-RPC **-32042** with a consent URL. The user approves on a one-page Approve / Decline page, and the agent retries with the same `idempotency_key`.
8. **Lazy evaluation, no workers in the MVP:** expired holds are treated as released when read; waitlist matching runs inside cancel and hold-expiry paths; Fair Drop allocation runs on the first request after the drop time. All of it is pure functions so Lambdas can wrap them later.
9. **Waitlists (D-010):** DynamoDB is the source of truth for watches and drop entries. `waitlist_status` is the primary path. MCP Tasks are an optional view behind a flag (default off; `memory://` is fine locally). No Redis / ElastiCache. Everything works with Tasks disabled.
10. **Fair Drop:** commitment (SHA-256 of the seed) published first, one entry per verified user, order = HMAC-SHA256(seed, entry_id), seed revealed after the drop with a recomputable audit record.
11. **The pitch is measured:** eval harness with A0 (open store) / A1 (FairTable) / A2 (no step-up), 40 YAML tasks (HAPPY 12, NEG 8, ROB 8, ADV 12), red-team RT1–RT12, and pass@1, pass^k, C_out, violations, false-block rate. The simulator uses the mock model by default.
12. **AWS Builder (D-011):** Phase 2 deploys the same server to AgentCore Runtime behind Gateway + Policy with Cognito and DynamoDB, documented in `docs/aws-integration.md`. The demo video shows the AWS-deployed path at least once. Qualification for the Alexa+ track does not depend on it.

Explicitly **not** in the MVP: background workers, Redis, MCP Apps, Automated Reasoning, Nova Sonic, Nova Act, Web Bot Auth, ACE, Memory (decided out, D-031), KMS-signed mandates. Should/Could items need your go-ahead first.

---

## 2. Open questions and decisions

### 2a. Design inconsistencies (design and code disagree, so I ask)

| # | Issue | Recommended default |
|---|---|---|
| D1 | ✅ *Applied (D-014).* **S2 vs `waitlist_watch` loop.** S2 (agent-share cap) applies to `reservation_hold` and `waitlist_watch`, yet an S2 denial returns `next_step: waitlist_watch`, which would be denied too. | Remove `waitlist_watch` from S2's action list. A watch consumes no covers; S2 applies when a hold is created for the watcher. |
| D2 | ✅ *Applied as S3b (D-014).* **S3 covers `reservation_confirm` only**, but `reservation_manage` cancel-with-fee is specified as step-up under "S3". | Add rule **S3b** (`@on_deny("step_up")`, scoped to `reservation_manage`, fires when the cancel fee is above zero and not acknowledged). Adds a policy beyond "P0 + S1–S4". |
| D3 | ~~CLAUDE.md says lazy/no workers; design lists a hold sweeper as Must.~~ | **Resolved:** lazy in the MVP. Seed comes from a `SeedProvider` interface (`secrets.token_bytes` locally, KMS later). |
| D4 | **Counters vs lazy expiry.** Without a sweeper an expired hold keeps counting toward S1/S2. | Before every hold, run `release_expired(user, venue, slot)` as its own transaction. One pure function, reused by workers later. |
| D5 | **Local G1–G4 vs Gateway-generated schema.** The local Cedar schema is built from JWT claims; AgentCore's generated schema may differ (❓). | Keep two policy sets (`policies/` for the server, `infra/agentcore/` for Gateway) sharing one behavioural test suite (same scenarios, same outcomes). |
| D6 | **G4 and P0 both check `agent_tier`.** Overlap. | Keep both; it is intentional defense in depth. Tests cover each layer alone. |

### 2b. Needs your answer (blocking or soon)

| # | Question | Recommended default |
|---|---|---|
| Q1 | **Python 3.12** is not installed (3.13.9 default). May I use `uv` to provision 3.12? You said you will code on your PC; confirm which Python you will use there. | 3.12 via `uv`; 3.13 only if every pinned wheel exists for it. |
| Q2 | **Real model provider for eval numbers.** Bedrock is blocked (AWS Support). Mock results only validate the harness. If still blocked on **10-13**, do you want a non-AWS provider (opt-in via `MODEL_PROVIDER`)? | Decide on 10-13. Mock is the default in all profiles. Real-provider numbers, if any, are labelled as such in the report. |
| Q5 | **D1, D2, D5** (D1 and D2 change policy text). | Approve as recommended. |
| Q6 | **English-only rule for the existing Vietnamese docs (D-009).** Translate, or replace and move out? | Write `docs/ARCHITECTURE.md` in English (condensed and consolidated: v2 design + all decisions, with Mermaid), relabel both `.drawio` diagrams in English, and move the Vietnamese design and research docs **out of the repo** (a folder outside the repo or a private repo). Done in tasks P0-5, P3-6, P3-7. |

Resolved: **Q3** (identity: dev issuer, D-007), **Q4** (organizer questions, D-006).

### 2c. Smaller choices I will make unless you object

- **Injectable clock** everywhere time matters (hold expiry, drop time, token bucket, mandate expiry). Tests never sleep.
- **Step-up approval record:** `APPROVAL#{hold_id}`, bound to user `sub` and the hash of the terms snapshot, single use, `expires_at` checked on read (15 min). The exact -32042 payload shape is verified from the installed MCP SDK in spike P0-3.
- **`mandate_covers_booking`** is a pure Python function; Cedar only reads booleans and counters.
- **Mandates** are seeded by `scripts/seed.py`. The consent page handles step-up approvals only. A create/revoke mandate form is a Should.
- **Hold TTL 10 min**; **token bucket** default 20 reads per user per venue per hour (configurable; RT2 fires 300).
- **Fair Drop details the design leaves open:** winners get a 10-minute HOLD; losers see status only; no auto-rollover; capacity per drop is a fixed number of seeded slots.
- **Policy files:** one `.cedar` file per rule in `policies/`, flat, with prefix by enforcement point (`g*` = PEP-1, `p*`/`s*` = PEP-2). The loader groups by prefix and maps by annotation, never by position.
- **Tasks flag:** `MCP_TASKS_ENABLED=false` by default in every profile.
- **Dev issuer location:** new top-level `devauth/` (a separate compose service). `CLAUDE.md` layout is updated to match.
- **Seeded local accounts** (dev-only, listed in the README): `diner-alice`, `diner-bob`, `diner-carol`, `owner-luna`, M2M bot client `bot-m2m`, agent client `alexa-plus-sim`. Passwords are fixed dev values, not secrets.
- **Tooling:** `ruff`; tests in `tests/` (`unit/`, `integration/`, `redteam/`, `aws/`) with markers `ddb`, `docker`, `aws`.
- "FairTable" trademark check is a reminder for you before submission; not blocking.

---

## 3. Phased plan (2026-09-29 → 2026-10-22)

Conventions
- Every task is at most half a day (½d ≈ 4 h, ¼d ≈ 2 h) and ends with `pytest` green.
- Dates assume coding starts **09-30**. If coding starts later, every date shifts and the cut list in §5 applies.
- Phase 1 needs no AWS. Each phase ends with a **gate**; if a gate slips, use the cut list instead of extending the phase.
- Spare day: **10-23** (deadline 12:00 PDT, 10-24 02:00 GMT+7). Submission target: **10-22**.
- The schedule is about 1.5 days tighter than v0.1 because of D-007 (dev issuer, owner console, full compose), D-008 (local PEP-1) and D-011 (AWS path is required for the AWS Builder claim).

### Phase 0 – Docs, spikes and bootstrap (09-29 → 10-01)

| ID | Date | Task | Acceptance criteria | Tests that prove it |
|---|---|---|---|---|
| P0-0 | 09-29 (done) | **Docs and codebase organisation:** DECISIONS, PLAN, README skeleton, `aws-integration.md` skeleton, `CLAUDE.md` alignment, repo skeleton with per-directory READMEs. | Skeleton exists and is described; no logic. | Manual review. |
| P0-1 | 09-30 | **Bootstrap env.** venv, `pip install -e .[dev]`, pinned versions. (¼d) Files already exist: `pyproject.toml`, `.env.example`, `.python-version`. | Installed versions equal the pins. | `tests/unit/test_env.py` (already written). |
| P0-2 | 09-30 | **Cedar spike.** Confirm `policies_to_json_str` and the decision API exist in cedarpy 4.12.1 (read installed source), then reproduce the 7 scenarios from design §6.2 against `policies/*.cedar`, the mapping `policyN → (rule_id, on_deny)`, and the `has`-guard behaviour from §6.1. (½d) | All 7 scenarios and the guard case behave as the design claims. | `tests/unit/test_cedar_spike.py`. |
| P0-5 | 09-30 | **`docs/ARCHITECTURE.md` in English** (D-009): consolidated v2 design plus D-001…D-013, Mermaid diagrams, D1/D2/D5 outcomes once approved. Updates `CLAUDE.md` source-of-truth order. (½d) | Every design decision needed to build is in English; Vietnamese doc no longer needed for day-to-day work. | Review checklist: every design section maps to an ARCHITECTURE section. |
| P0-3 | 10-01 | **FastMCP spike.** Verify from installed source: (a) `isError` with structured content; (b) raising -32042 with a URL elicitation payload; (c) reading `x-ft-user-token` in a tool; (d) `task=True` and its `pydocket` backend (`memory://`); (e) session handling. Protocol version is already verified (D-012). Connect with the FastMCP client and MCP Inspector. (½d) | Findings in `docs/friction-log.md`. A client receives a real -32042 with a URL. Tasks work with `memory://` or the flag stays off. | `tests/integration/test_fastmcp_spike.py` (in-process client). |
| P0-4 | 10-01 | **DynamoDB Local spike.** Compose service, single-table create script, 5-item `TransactWriteItems` with a failing condition, 20-thread race. (½d) | Cancellation reason identifies the failing item; exactly one racer wins. | `tests/integration/test_ddb_spike.py` (`-m ddb`). |

**Gate 0 (end of 10-01):** spikes pass or have a documented workaround. If -32042 cannot be raised through FastMCP, stop and report: step-up is a Must.

### Phase 1 – Local core (10-02 → 10-13), no AWS

| ID | Date | Task | Acceptance criteria | Tests that prove it |
|---|---|---|---|---|
| P1-1 | 10-02 | **Domain models, errors, clock, `slot_token`.** (½d) | All error codes exist. Success output helper enforces `spoken_summary`. Tampered or expired `slot_token` rejected. | `tests/unit/domain/`. |
| P1-2 | 10-02 | **Trust Kernel – PEP-2.** `kernel/decide.py`: policy loader, Cedar request builder, deny > step_up > allow, `Decision(kind, rule_id, hint)`. (½d) | All §6.2 scenarios (plus D1/D2 edits if approved) go through `decide()`. Every deny has a `rule_id`. | `tests/unit/kernel/` (table-driven, priority combinations, no-permit). |
| P1-3 | 10-03 | **Trust Kernel – PEP-1 (G1–G4 in cedarpy).** Local Cedar schema from JWT claims; G4 with `has`-guard. (½d) | G1 read allowed for any valid JWT; G2 write needs `username` and scope `fairtable/book`; G3 `party_size > 10` denied; G4 denies when `agent_tier` is missing or not `verified`. | `tests/unit/kernel/test_pep1.py`, including the naive-G4 vs `has`-guard case from design §6.1 (RT1, RT3 logic). |
| P1-4 | 10-03 | **Identity verifier.** `joserfc`: signature, `iss`, `aud`, `exp`, claims. No write tool runs without an `Identity`. (½d) | Valid token gives `Identity(sub, username, agent_tier, agent_id, scopes)`. | `tests/unit/identity/` (expired, wrong `aud`, bad signature, forged token = RT4 server side). |
| P1-5 | 10-04 | **`devauth/` dev JWT issuer** (FastAPI service). JWKS + metadata, simple login for seeded users, `client_credentials` for the bot, Cognito-like pre-token V2/V3 logic. (½d) | User tokens carry `agent_tier`; bot tokens carry neither `username` nor `agent_tier`. | `tests/integration/test_devauth.py` (TestClient): login, JWKS verifies with P1-4, bot token claims. |
| P1-6 | 10-04 | **Store layer and seed.** Key builders, mappers, GSIs, `scripts/seed.py` (venues, slots incl. hot and drop, users, mandates). Namespaced per eval run. (½d) | Seed populates DynamoDB Local; table and endpoint from env only. | `tests/integration/test_seed.py` (`-m ddb`), unit tests for key builders. |
| P1-7 | 10-05 | **Read tools + token bucket:** `restaurant_search`, `availability_check`, `mandate_status`. (½d) | `spoken_summary` and `next_step` everywhere. Over-limit gives `RATE_LIMITED` with `retry_after_s` and `next_step: waitlist_watch`. | `tests/unit/domain/test_ratelimit.py`; `tests/integration/test_read_tools.py` (RT2). |
| P1-8 | 10-05 | **Write pipeline core + idempotency.** `run_write()`: verify identity, PEP-1, idempotency lookup, context build, PEP-2, transact, audit. (½d) | Same key + same params replays; different params gives `IDEMPOTENCY_CONFLICT`; denied or failed calls store nothing. | `tests/integration/test_write_pipeline.py` (RT10). |
| P1-9 | 10-06 | **`reservation_hold`** with lazy expiry release (D4), 5-op transaction, cancellation-reason mapping, `within_mandate`. (½d) | Atomic write; S1, S2, S4 denials carry the right `rule_id`, `hint`, `next_step`. | `tests/integration/test_hold.py`; `tests/redteam/` RT6, RT7, RT8. |
| P1-10 | 10-06 | **`reservation_confirm` + step-up.** S3 decision, -32042 with consent URL, approval lookup, HOLD to CONFIRMED with `terms_snapshot`. (½d) | In-mandate confirms; out-of-mandate returns -32042; retry after approval confirms; expired hold gives `HOLD_EXPIRED`. | `tests/integration/test_confirm.py` (RT5). |
| P1-11 | 10-07 | **Consent page (FastAPI).** Terms from the hold, Approve / Decline, bound to verified user, single use. (½d) | Approve writes `APPROVAL#…` + audit; wrong user gets 403; decline is visible to the agent. | `tests/integration/test_consent_web.py`. |
| P1-12 | 10-07 | **`reservation_manage`** view / modify / cancel; fee computed before cancel; `FEE_APPLIES` to step-up (S3b if approved). (½d) | No silent cancel with a fee. | `tests/integration/test_manage.py`, `tests/unit/domain/test_fees.py`. |
| P1-13 | 10-08 | **Concurrency hardening** (RT6, RT9). (¼d) | Exactly one success per slot; counters never exceed caps; no orphans. | `tests/redteam/test_rt09_concurrency.py`, invariant checker I1, I2, I5. |
| P1-14 | 10-08 | **Waitlist on DynamoDB (D-010):** `waitlist_watch`, `waitlist_status` (primary path), lazy matcher in cancel and expiry paths. Tasks flag stays off. (½d) | One watch per user per day; a cancel creates a hold for the first eligible watcher; `waitlist_status` reports it with `retry_after_s` and `next_step`. | `tests/unit/domain/test_waitlist_match.py`; `tests/integration/test_waitlist.py`. |
| P1-15 | 10-09 | **Fair Drop core (pure).** `SeedProvider`, commitment, entry hashing, HMAC order, allocation, audit payload. (½d) | Order reproducible from the revealed seed; caps and capacity respected. | `tests/unit/domain/test_fairdrop.py`. |
| P1-16 | 10-09 | **Fair Drop integration.** Entries via `waitlist_watch(drop_id)`, lazy allocation on first request after drop time, S4, MCP resources for policies and audit. (½d) | Allocation happens exactly once under concurrent triggers; audit verifies. | `tests/integration/test_drop.py` (RT8, RT12). |
| P1-17 | 10-10 | **Owner console (FastAPI).** Change agent-share cap (S2), view audit and policy text. Needed for the video. (½d) | Cap change flips the next hold from allow to `POLICY_DENIED S2`. | `tests/integration/test_owner_console.py`. |
| P1-18 | 10-10 | **Simulator core.** `LLMClient` adapter chosen by `MODEL_PROVIDER` (`mock` default, `bedrock` stub, others opt-in), Strands agent wired to the server, scripted mock personas with seeded noise, tools `say / approve_consent / decline`. Verify the Strands custom-model API from installed source first. (½d) | Happy-path and step-up bookings complete with the mock. | `tests/integration/test_simulator.py`. |
| P1-19 | 10-11 | **Chat page + login.** FastAPI + one static page; logs in against the dev issuer; shows the consent link. (½d) | Seeded user logs in, chats, follows the consent link. | `tests/integration/test_chat_web.py`. |
| P1-20 | 10-11 | **Eval harness v0.** Task YAML schema, per-run namespace, runner, state and safety graders (I1–I5), pass@1, pass^k, C_out. (½d) | 10 tasks run end to end; metrics match hand-computed fixtures. | `tests/unit/eval/test_metrics.py`; `tests/integration/test_eval_run.py`. |
| P1-21 | 10-12 | **A0 / A1 / A2 configs** via config, not forks. (¼d) | A0 shows violations on ADV tasks; A1 shows none. | `tests/integration/test_ablation.py`. |
| P1-22 | 10-12 | **Local red-team suite** RT1–RT12 (all local now, D-008). (½d) | Each RT is a deterministic pytest with the expected code from design §9.5. | `tests/redteam/test_rt*.py` + summary printer. |
| P1-23 | 10-13 | **Docker profile (primary run path).** `Dockerfile`, root `docker-compose.yml`: server, DynamoDB Local, `web`, `devauth`, simulator, one-shot seed. Health checks. No AWS credentials. **Pin the DynamoDB Local image to a fixed tag (no `latest`)** so the fresh-clone path keeps working through 11-20 (D-015). (½d) | `docker compose up` on a fresh clone brings everything up, seeded, with MCP Inspector able to connect. | `tests/integration/test_compose_smoke.py` (`-m docker`). |
| P1-24 | 10-13 | **README + wrap-up.** Docker path first, plain-Python second, **test logins table**, demo script, friction log. Bedrock check (Q2 decision point). Optional Tasks view only if time is left (D-010). (½d) | A fresh clone follows the README end to end. | Commands copy-pasted on a clean clone; `pytest -q` green from a clean venv. |

**Gate 1 (end of 10-13):** all Phase 1 tests green; `docker compose up` works from a clean clone; hold to step-up to confirm, waitlist match and Fair Drop demo locally; RT1–RT12 blocked under A1.

### Phase 2 – AWS Builder path (10-14 → 10-17)
Resources are created for tests and the demo and torn down afterwards (D-004). **Credits: the $150 credit is confirmed (D-030), so the free-tier fallback of D-015 is not needed; credits do not cap spending, so Budgets alerts and the cost-before-creating rule (D-016) stay.** Nothing account-specific in code. Full plan of what each service does: `docs/aws-integration.md`.

| ID | Date | Task | Acceptance criteria | Tests that prove it |
|---|---|---|---|---|
| P2-1 | 10-14 | **CDK: DynamoDB + GSIs + AWS Budgets ($50/$100/$140).** `AWS_PROFILE`, `AWS_REGION` from env (target `us-east-1`). (½d) | `cdk synth` clean; the Phase 1 integration suite passes against real DynamoDB by changing env only. | CDK snapshot; `-m aws` re-run. |
| P2-2 | 10-14 | **Cognito (Essentials) + pre-token V2/V3 + PKCE client.** (½d) | Same claims as the dev issuer, including M2M via V3. | Lambda unit tests; `tests/aws/test_tokens.py`. |
| P2-3 | 10-15 | **Server on AgentCore Runtime** (reuses the Dockerfile). (½d) | Reachable over Streamable HTTP with a Cognito JWT; verifier is config-only different. | `tests/aws/test_runtime_smoke.py`. |
| P2-4 | 10-15 | **Verifier with Cognito JWKS** (fetch + cache). (¼d) | Same verifier tests pass with a Cognito-shaped JWKS. | Extend `tests/unit/identity/`. |
| P2-5 | 10-16 | **Gateway:** `CUSTOM_JWT`, MCP target with outbound OAuth, REQUEST interceptor (strip client `x-ft-user-token`, copy from verified `Authorization`, `passRequestHeaders`). (½d) | Through the Gateway the server sees a valid `x-ft-user-token`; a forged header is removed. | Interceptor unit tests; `tests/aws/test_gateway_identity.py`. |
| P2-6 | 10-16 | **Gateway Policy G1–G4 (defense in depth).** Dump the generated Cedar schema first (❓). (½d) | Schema documented in the friction log; G2 and G4 deny as in the local suite. | `tests/aws/test_pep1.py` sharing scenarios with the local suite (D5). |
| P2-7 | 10-17 | **Decision point + -32042 through Gateway.** If the Gateway rewrites the error or Policy blocks, keep what works and document the rest. (½d) | Decision written down; step-up works through the Gateway or the direct Runtime route is used. | `tests/aws/test_stepup_through_gateway.py`. |
| P2-9 | 10-17 | **AgentCore Observability (D-031, required). Server part built 2026-09-30 (D-032); the AWS part remains.** Verify prices first. Enable CloudWatch Transaction Search; instrument the Strands agent (ADOT, `strands-agents[otel]`, session id baggage); enable Gateway and Runtime spans; add policy-decision attributes to the server's spans (this part can be built and tested earlier with an in-memory exporter); capture one booking trace for the video. (½d) | One booking produces one trace showing agent, Gateway and server steps, with the rule ids; no token or personal data in any span. | Unit test with an in-memory span exporter (server attributes, no secrets); manual check in CloudWatch. |
| P2-8 | 10-17 | **Teardown scripts + `docs/aws-integration.md` filled in.** One documented command to deploy and one to destroy. (½d) | After teardown nothing billable remains; each AWS service in the doc has role, usage, what worked, what needs work. | Teardown dry-run lists resources by tag; listing after teardown recorded in the friction log. |

**Gate 2 (10-17):** at minimum Runtime + Cognito + DynamoDB run and can be demoed. If Phase 2 slips, cut in the order in D-011 (Gateway Policy, then Gateway + interceptor). The local Docker profile is unaffected.

### Phase 3 – Quality, English docs and freeze (10-18 → 10-20)

| ID | Date | Task | Acceptance criteria | Tests that prove it |
|---|---|---|---|---|
| P3-1 | 10-18 | **40-task set** (HAPPY 12, NEG 8, ROB 8, ADV 12) via generator. (½d) | 40 valid tasks; generator deterministic. | `tests/unit/eval/test_tasks.py`. |
| P3-2 | 10-18 | **Full runs + report + regression gate.** (½d) | Report has the design §9.5 table with measured values only. | `tests/unit/eval/test_gate.py`. |
| P3-3 | 10-19 | **Charts** for pass^k and violations (use the `dataviz` skill). (¼d) | One readable chart per report. | Render smoke test. |
| P3-4 | 10-19 | **Real-provider runs** only if Q2 decided yes. Budget guard. (¼d) | Cost tracked; stops at the $100 mark. | `tests/unit/eval/test_budget_guard.py`. |
| P3-6 | 10-19 | **Relabel both `.drawio` diagrams in English.** (½d) | No Vietnamese text left in any diagram. | Grep for Vietnamese diacritics finds nothing. |
| P3-7 | 10-20 | **Move Vietnamese docs out of the repo**, update README and `CLAUDE.md` links, final secret scan (allowing the documented dev credentials). (¼d) | `git grep` finds no Vietnamese text, keys, ARNs or account IDs. | `tests/unit/test_language_and_secrets.py`. |
| P3-8 | 10-20 | **Feature freeze.** Final frozen eval run. **Pin exact dependency versions (lock file) and image tags** (D-015). (¼d) | Numbers frozen in `eval/reports/`. | Full suite green. |

### Phase 4 – Submission (10-20 → 10-22, spare 10-23)

| ID | Date | Task | Acceptance criteria |
|---|---|---|---|
| P4-1 | 10-20 (pm) | **Record footage:** local Docker demo **and the AWS-deployed path at least once** (D-011), per the video script in the design §12. (½d) | Both paths captured before AWS teardown. |
| P4-2 | 10-21 | **Video edit** (< 3 min, English, best material first). (½d) | Shows the server working; no third-party logos or music. |
| P4-3 | 10-21 | **Devpost text, product feedback for every tool/SDK (five answers each, see `docs/hackathon-rules.md`), friction log final and pasted into the submission form** (it is a form field worth up to 10%). (½d) | Complete, in English, AWS services described. |
| P4-4 | 10-22 | **Fresh-clone verification, judging-ready** (D-004): Docker path with no AWS credentials, then plain-Python path. README readable by an automated AI reviewer. Apache-2.0 visible in About. (¼d) | Every README command works as written. |
| P4-5 | 10-22 | **Submit, tag the submitted commit (`submission`), then tear down AWS.** No functional pushes until judging ends 11-20 (D-015). Track Alexa+, mini challenge **AWS Builder only**. (¼d) | Devpost confirmation; nothing left running. |
| — | 10-23 | Spare day; deadline 12:00 PDT. | Only if something broke. |

---

## 3a. Verified APIs (Phase 0 spikes, 2026-09-29)

Environment: Python 3.12.14 (conda env `fairtable`), `fastmcp==3.4.7` (+ `fastmcp-slim` 3.4.7), `mcp==1.30.0`, `cedarpy==4.12.1`, `strands-agents==1.57.1`, `joserfc==1.7.5`, optional `pydocket==0.25.2`, DynamoDB Local 3.3.1 (`amazon/dynamodb-local:latest`), boto3 1.43.104. Source of every item: the installed package plus the spike test named in brackets.

**cedarpy** [`tests/unit/test_cedar_spike.py`]
- `cedarpy.is_authorized(request, policies, entities, schema=None, verbose=False) -> AuthzResult`. `request` is a dict with `principal`, `action`, `resource` (Cedar strings like `'Diner::"alice"'` or `{"type","id"}` dicts) and `context` (dict).
- `entities`: list of `{"uid": {"type","id"}, "attrs": {...}, "parents": []}`, a JSON string, or `cedarpy.Entities.from_json_str(...)`. `policies`: a string or `cedarpy.PolicySet.from_str(...)` (pre-parsed handle).
- `AuthzResult`: `.decision` (`cedarpy.Decision.Allow|Deny|NoDecision`), `.allowed`, `.diagnostics.reasons` (`["policy0", ...]`), `.diagnostics.errors`, `.diagnostics.id_annotations_by_reason` (`{"policy0": "<@id>"}`).
- `cedarpy.policies_to_json_str(text)` returns JSON with `staticPolicies["policyN"]["annotations"]` (`id`, `on_deny`). `policyN` is the index of the policy in the concatenated text, so build the table from the exact text you evaluate.
- Reproduced: all 7 scenarios of design §6.2 (plus D1/D2 from D-014: S2 no longer covers `waitlist_watch`; new S3b for cancel with a fee), priority deny > step_up > allow, no-permit -> deny, and G4 naive (Allow + error) vs `has`-guard (Deny). Incomplete contexts make a forbid error out and be skipped, so contexts must always be complete.

- Policy validation (batch A, `tests/unit/kernel/`): `cedarpy.validate_policies(policies_text, schema_text)` returns a result with `.validation_passed` and `.errors` (each has `policy_id` and `error`); it accepts the human-readable Cedar schema (`entity Diner;`, `entity Venue = { agent_cover_cap: Long };`, `type Ctx = {...};`, `action a, b appliesTo { principal: ..., resource: ..., context: Ctx };`, optional attributes `name?: String`). A misspelt context attribute in a policy is reported. `cedarpy.PolicySet.from_str(text)` gives the pre-parsed handle used for evaluation.

**joserfc 1.7.5** [`tests/unit/identity/`]
- `joserfc.jwt.decode(token, key_set, algorithms=["RS256"])` returns `Token(.header, .claims)`; the key is chosen by `kid` from a `joserfc.jwk.KeySet` (`KeySet.import_key_set({"keys": [...]})`, `KeySet([...]).as_dict(private=False)`). Algorithms outside the list (`HS256`, `none`) raise `UnsupportedAlgorithmError`; an unknown `kid` raises `InvalidKeyIdError`; a bad signature raises `BadSignatureError`; garbage raises `DecodeError`.
- Claims: `jwt.JWTClaimsRegistry(now=callable, leeway=seconds, iss={"essential": True, "value": ...}, aud={...}, exp={"essential": True}).validate(claims)` raises `ExpiredTokenError`, `InvalidClaimError`, `MissingClaimError` (all `JoseError`, with a `.description` naming the claim). `validate` only checks claims that are present, so every required claim must be marked `essential`.

**boto3 / DynamoDB** [`tests/integration/test_store_ddb.py`, `test_write_pipeline.py`]
- `boto3.dynamodb.types.TypeSerializer().serialize(value)` / `TypeDeserializer().deserialize(av)` convert Python values to and from DynamoDB attribute values for the low-level client; **floats are rejected** (use `Decimal(str(x))`), numbers come back as `Decimal`. `transact_write_items` items may carry `ReturnValuesOnConditionCheckFailure="ALL_OLD"`; the cancellation error is `TransactionCanceledException` with positional `CancellationReasons` (`Code` `None` / `ConditionalCheckFailed` / `TransactionConflict`). With DynamoDB Local, when several conditions fail, every failing item is reported.

**DynamoDB expressions** [`tests/integration/test_reservation_*.py`]
- `sub` is a reserved word: use `ExpressionAttributeNames` (`#sub`) in every condition or update that names it (also `status`, and check others against the reserved-word list). Condition expressions have **no arithmetic**, so "counter + x <= cap" is written `n <= :cap_minus_x`, with `attribute_not_exists(n)` allowed only when even 0 fits. `SET a.b = :v` updates a nested map attribute; `REMOVE` and `SET` can share one update expression; `ADD n :neg` creates a missing counter.

**MCP client capabilities** [`tests/integration/test_reservation_confirm.py`]
- In a tool: `fastmcp.server.dependencies.get_context().session.client_params.capabilities.elicitation` (an `mcp.types.ElicitationCapability` with `form` / `url`, each `None` when not declared). `ServerSession.check_client_capability(...)` only tests that `elicitation` exists, so it cannot tell URL mode from form mode; read `.url` directly. The `mcp` client declares both `form` and `url` only when given an elicitation callback (`fastmcp.Client(..., elicitation_handler=...)`), otherwise none. No initialize params (stateless) means `client_params is None`.

**AgentCore facts for Phase 2** [read 2026-09-30 from the AWS documentation and from github.com/awslabs/agentcore-samples (`01-features/02-host-your-agent/01-runtime/02-hosting-tools/01-mcp-server-basics`, `01-features/07-centralize-and-govern-your-ai-infrastructure/01-gateway` and `.../02-policy`, `02-use-cases/01-conversational-agents/healthcare-appointment-agent/policy`); nothing here has been run against the developer's account]
- *Runtime, MCP server contract* (docs "MCP protocol contract"): Streamable HTTP, **stateless** (`stateless_http=True`; the platform adds an `Mcp-Session-Id` that must not be rejected), host `0.0.0.0`, port **8000**, `POST /mcp`, **ARM64**. Runtime is created with `protocolConfiguration={"serverProtocol": "MCP"}`; a `DEFAULT` endpoint is created with it. An MCP server is a plain FastMCP server, not `BedrockAgentCoreApp`. A JSON-RPC error still comes back as HTTP 200. Runtime accepts no model call from an MCP server, so no `bedrock:InvokeModel` is needed.
- *Runtime, code or container*: **direct code deployment** (zip in S3, `runtime: PYTHON_3_12`, `entryPoint: ["file.py"]`) needs no Docker and no ECR; limit **250 MB zipped / 750 MB unzipped**. Checked here: every one of our 76 server dependencies (resolved on Linux for fastmcp 3.4.7, mcp 1.30.0, cedarpy 4.12.1, joserfc, pydantic, boto3, httpx, uvicorn) has a `manylinux aarch64` wheel for CPython 3.12, **37 MB zipped in total** (`pip download --no-deps --platform manylinux2014_aarch64 --python-version 3.12 --only-binary=:all:`).
- *Runtime V2* (`platformVersion="V2"`, set explicitly, read back with `get_agent_runtime`): environment snapshot for consistent fast starts; needs boto3 >= 1.43.95 (we have 1.43.104+); regions us-east-1, us-east-2, us-west-2, eu-west-1, ap-northeast-1; code captured at start is frozen in the snapshot (resolve AWS credentials per request; do not use `random` for anything unique per session; our server keeps a boto3 client created at start, to be checked).
- *Runtime, headers*: only allowlisted request headers reach the container: `requestHeaderConfiguration={"requestHeaderAllowlist": [...]}` (up to 20 names; `x-amz-*` and `x-amzn-*` are refused except `X-Amzn-Bedrock-AgentCore-Runtime-Custom-*`; `Authorization` only with a custom JWT authorizer). **`x-ft-user-token` must be on this list or it is dropped.** Idle sessions are billed until the idle timeout (default 900 s): the biggest cost lever.
- *Runtime, execution role* must allow CloudWatch Logs (`/aws/bedrock-agentcore/runtimes/*`), X-Ray (`PutTraceSegments`, `PutTelemetryRecords`, `GetSamplingRules`, `GetSamplingTargets`) and `cloudwatch:PutMetricData` (namespace `bedrock-agentcore`), else it serves traffic but emits no traces; plus our own DynamoDB permissions.
- *Gateway*: tools are named `{targetName}___{tool}` (three underscores), also prompts; resources keep their URI. Gateway names allow hyphens, not underscores. MCP versions supported: 2026-07-28, 2025-11-25, 2025-06-18, 2025-03-26. **Outbound authorization to an MCP server target can be IAM SigV4 with the gateway's service role, and AgentCore Runtime supports it** (no OAuth credential provider needed); other options: OAuth (client credentials, auth code, token exchange), API key, none. Sessions (`sessionConfiguration`) cut re-initialisation on Runtime targets. Elicitation, including URL-mode, needs streaming and sessions on the gateway (the sample: `05-elicitation`); whether a plain -32042 error passes through is **unverified**.
- *Gateway, headers*: per target `metadataConfiguration.allowedRequestHeaders` (max 10; names `[A-Za-z0-9_-]`; values up to 4 KB, printable ASCII). A REQUEST interceptor can return headers; `Authorization` from an interceptor is forwarded (it cannot be allowlisted), every other header it returns must be allowlisted, and the interceptor's value wins over the client's. Interceptor input `event["mcp"]["gatewayRequest"]`, output `{"interceptorOutputVersion": "1.0", "mcp": {"transformedGatewayRequest": {"headers": {...}, "body": ...}}}`. From the sample (empirical, not in the docs): the interceptor runs **before** the policy engine, Cedar still sees the *inbound* token's claims, and a value injected as `Authorization` must be a parseable JWT. Our design does not depend on this order: the interceptor sets `x-ft-user-token`, never `Authorization`.
- *Policy (Cedar at the Gateway)*: `create_policy_engine(name=..., type="CEDAR")`, attached with `update_gateway(policyEngineConfiguration={"arn": ..., "mode": "ENFORCE" | "MONITOR"})` (ENFORCE is default-deny, MONITOR only logs; the sample advises starting in MONITOR). Policy shape: `permit(principal, action == AgentCore::Action::"<Target>___<tool>", resource == AgentCore::Gateway::"<gateway arn>") when { principal.hasTag("claim") && principal.getTag("claim") == "x" && context.input has arg && context.input.arg <= 10 };` JWT claims are **principal tags** (use `hasTag` before `getTag`), a `scope` claim is a space-separated string (`like "*x*"`), array claims arrive as JSON strings, and `context.input.<name>` is `params.arguments.<name>`. **Documentation ("Authorization flow", "Cedar policy") confirms the types: principal `AgentCore::OAuthUser` (id = the JWT `sub`, every claim is a tag), action `AgentCore::Action`, resource `AgentCore::Gateway` (capital G; one sample README writes `gateway` and is wrong). Still dump the real schema in P2-6 before writing G1-G4.** These differ from our local G1-G4 (entity attributes, `principal has agent_tier`), so the two sets stay separate files sharing one behavioural suite (D5). "Guardrails in policies" attaches Bedrock Guardrails classifiers to free-text arguments (`context.input.<field>`); our tools have almost no free text, so it is not planned.
- *Cognito for the Gateway*: access tokens carry **no `aud` claim**, so the Gateway authorizer must not set `allowedAudience` (use `allowedClients`), and our verifier uses `audience_claim="client_id"` (D-017). The pre-token-generation trigger **V3_0** (adds claims to machine tokens as well) needs the **Essentials** or Plus tier.
- *Prices* (aws.amazon.com/bedrock/agentcore/pricing and /cognito/pricing, read 2026-09-30): Runtime V1 $0.0895/vCPU-h and $0.00945/GB-h, V2 $0.1276/vCPU-h and $0.0169/GB-h (per second, CPU only while working, memory peak, 128 MB minimum); Gateway $0.005 per 1,000 invocations, search $0.025 per 1,000, tool indexing $0.02 per 100 tools per month; **Policy $0.000025 per authorisation request** (plus $0.13 per 1,000 tokens only for natural-language policy generation, which we do not use); Identity free with Runtime or Gateway; Observability billed as CloudWatch (X-Ray indexing 1 % free); Memory not used. Cognito: Essentials $0.015 per MAU with **10,000 MAU free**, machine tokens **$0.00225 per token request** (no free tier). New AWS customers: up to $200 credits (the developer has $150, D-030).

**AgentCore facts, second pass against the primary documentation, and a local proof** [2026-09-30]
- *Primary documentation read in full for each point*: direct code deployment ("Direct code deployment for Python": zip mounted at `/var/task` first in `sys.path`, arm64 wheels, no `__pycache__`, modes 644/755, 250 MB / 750 MB, `lifecycleConfiguration={"idleRuntimeSessionTimeout": s, "maxLifetime": s}`, `StopRuntimeSession`, teardown by `delete_agent_runtime` and deleting the S3 object); Runtime MCP contract (`0.0.0.0:8000/mcp`, stateless recommended, platform adds `Mcp-Session-Id`); Runtime `requestHeaderAllowlist` ("Pass custom headers"); Gateway header propagation ("Header propagation with Gateway"); Gateway outbound authorization table: an **MCP server target supports the gateway service role (SigV4)**, configured with `credentialProviderConfigurations` = `iamCredentialProvider {service: "bedrock-agentcore", region?}` ("Set up outbound authorization"); Gateway target for an MCP server (`SynchronizeGatewayTargets`, DEFAULT vs DYNAMIC listing, MCP versions incl. 2025-11-25); Cedar entity types ("Authorization flow"); Cognito pre-token trigger versions (V2_0 for user tokens, V3_0 adds machine tokens, plan Essentials) and `USER_PASSWORD_AUTH` in `InitiateAuth`.
- *CloudFormation (and so CDK L1) covers everything we need* ("Bedrock AgentCore" template reference): `AWS::BedrockAgentCore::Runtime` (properties `AgentRuntimeArtifact`, `EnvironmentVariables`, `LifecycleConfiguration`, `NetworkConfiguration`, `PlatformVersion`, `ProtocolConfiguration`, `RequestHeaderConfiguration`, `RoleArn`, `AuthorizerConfiguration`, `Tags`), `RuntimeEndpoint`, `Gateway` (`AuthorizerConfiguration`, `InterceptorConfigurations`, `PolicyEngineConfiguration`, `ProtocolConfiguration`, `RoleArn`, `Tags`), `GatewayTarget` (with `MetadataConfiguration.AllowedRequestHeaders`), `PolicyEngine`, `Policy`, `WorkloadIdentity`, `OAuth2CredentialProvider`, `ResourcePolicy`.
- *Prices double-checked* on the raw pricing page (`curl` of aws.amazon.com/bedrock/agentcore/pricing, not a summary): Runtime $0.0895 / $0.00945 (V1) and $0.1276 / $0.0169 (V2) per vCPU-hour / GB-hour; Gateway $0.005 per 1,000 InvokeTool calls, search $0.025 per 1,000; Policy $0.000025 per authorisation request; $0.13 per 1,000 tokens (natural-language generation).
- *Local proof that the zip route works* (`infra/runtime/`): `build_zip.py` builds `dist/fairtable-runtime.zip` (**5,743 files, 38.5 MB zipped, 93.7 MB unpacked**, deterministic, modes 644/755, no bytecode). Unpacked to `/var/task` in a `python:3.12.14-slim` container with `--platform linux/arm64` (`aarch64`), `python runtime_entry.py` started an MCP server on `0.0.0.0:8000/mcp` (stateless; `cedarpy` native code loaded from the zip), and from the host: `tools/list` with a platform-style `Mcp-Session-Id` (8 tools), `restaurant_search` (3 restaurants), a full hold, confirm (inside Alice's permission) and cancel against DynamoDB Local (JWT verified with the dev issuer's keys), a refusal without a token (`UNAUTHENTICATED`) and the party-of-12 refusal (`G3_party_size_max_10`). This proves the package, the entry point, the arm64 wheels and the stateless mode; it does not prove AgentCore itself (networking, the header allowlists, V2 snapshots), which needs the account.
- *Not verified, to settle on the account*: that `x-ft-user-token` survives the Gateway target allowlist and the Runtime allowlist end to end; whether the Runtime's Host header passes our Host check (`MCP_ALLOWED_HOSTS`, probably `*` because IAM is the boundary); whether a plain `-32042` error passes through the Gateway; the exact IAM action the gateway role needs to invoke the Runtime (the page says `bedrock-agentcore:InvokeGateway`, which looks like a documentation slip for `InvokeAgentRuntime`); credentials cached by the boto3 client created at start-up under V2 snapshots; USER_PASSWORD_AUTH is the plain-password flow (use it only for the demo).

**OpenTelemetry in the server** [`tests/unit/test_telemetry.py`, `tests/integration/test_telemetry_spans.py`, 2026-09-30]
- `opentelemetry-api` / `-sdk` 1.45.0 come with `strands-agents`; `opentelemetry.sdk.trace.export.in_memory_span_exporter.InMemorySpanExporter` collects spans in tests; `trace.get_tracer(name, tracer_provider=...)` takes an explicit provider.
- A FastMCP `Middleware.on_call_tool(context, call_next)` sees `context.message` (`mcp.types.CallToolRequestParams`: `name`, `arguments`, and `meta`, which is `None` even when the client sent `_meta`). The client's `_meta` (with `traceparent`) is on `context.fastmcp_context.request_context.meta`. `Client.call_tool_mcp(name, args, meta={...})` sends it.
- FastMCP starts its own span inside the tool call; when only a custom provider is set, that inner span is a `NonRecordingSpan`, so `trace.get_current_span()` in the tool cannot be annotated. Keep your own span in a `ContextVar`; anyio's thread pool copies context variables to the worker thread.
- Strands' `MCPClient` injects the active trace context into `_meta` of outgoing tool calls (`strands.tools.mcp.mcp_instrumentation.inject_trace_context`).

**FastMCP resources** [`tests/integration/test_fair_drop.py`]
- `@mcp.resource("scheme://{param}/path", mime_type="...")` on a function returning `str` registers a resource template (`Client.list_resource_templates()` shows `uriTemplate`); `Client.read_resource(uri)` returns a list whose items have `.text`. Raising `fastmcp.exceptions.ResourceError("message")` reaches the client as `mcp.shared.exceptions.McpError` with that message (it is not masked).

**FastMCP / mcp** [`tests/integration/test_fastmcp_spike.py`]
- Error logging: an exception that is a `fastmcp.exceptions.FastMCPError` (for example `ToolError(msg, log_level=logging.INFO)`) is logged at that level without a traceback and re-raised as is; any other exception is logged at ERROR with a full traceback and wrapped in `ToolError`. Middleware `on_call_tool` may return a `ToolResult(is_error=True, structured_content=...)` to answer instead of raising.
- (a) Structured error: `from fastmcp.tools import ToolResult`; `ToolResult(content="...", structured_content={...}, is_error=True)` gives `isError: true` plus `structuredContent`. Client side: `Client.call_tool_mcp(name, args)` returns the raw `CallToolResult`; `Client.call_tool(...)` raises `ToolError` on `isError`.
- (b) Step-up: `from mcp.shared.exceptions import UrlElicitationRequiredError`; `from mcp.types import ElicitRequestURLParams` (`mode="url"`, `message`, `url`, `elicitationId`). **FastMCP 3.4.7 swallows it into `isError` unless a middleware re-raises it** (`Middleware.on_call_tool`: catch `fastmcp.exceptions.ToolError`, `raise e.__cause__` if it is a `UrlElicitationRequiredError`). With the middleware the client gets `McpError` with `error.code == -32042 == mcp.types.URL_ELICITATION_REQUIRED` and `error.data["elicitations"][0]["url"]`; works in-process and over Streamable HTTP. Validated against the MCP spec 2025-11-25 and FastMCP's `ErrorHandlingMiddleware` pattern (D-014). Production copy: task P1-10.
- (c) Header: `from fastmcp.server.dependencies import get_http_headers`; `get_http_headers().get("x-ft-user-token")`. Names are lower-cased; `authorization` is stripped by default (pass `include={"authorization"}` to keep it); returns `{}` with no HTTP request (in-process client). Verified over real HTTP, per request, with a missing header giving `None`.
- (d) Tasks: `@mcp.tool(task=True)` requires `pydocket` (optional extra `tasks`); default backend `memory://` (`FASTMCP_DOCKET_URL`) works, no Redis. Client: `await client.call_tool(name, args, task=True)` returns a `ToolTask` (`.returned_immediately`, `.status()`, `.result()`). Flag stays off by default (D-010).
- (e) Sessions: `Context.session_id` (tool parameter `ctx: Context`) is stable within one client session and differs across sessions over Streamable HTTP. Identity is read from the header on every request, never cached on the session.
- Serving: `FastMCP.http_app()` (Starlette app, default path `/mcp`, setting `streamable_http_path`) or `FastMCP.run(transport="http", host=..., port=...)`. Client: `Client(StreamableHttpTransport(url, headers={...}))`. `FastMCP(mask_error_details=True)` hides unexpected exception text but not structured errors or -32042.
- Transport security (spec 2025-11-25, Streamable HTTP; `tests/integration/test_fastmcp_spike.py`): the spec says servers MUST validate `Origin` (403 if present and invalid), SHOULD bind to localhost when local, and MUST answer an unsupported `MCP-Protocol-Version` with 400. **FastMCP 3.4.7 defaults to `host_origin_protection=False`** (no Origin check). Enable it with `http_app(host_origin_protection=True, allowed_hosts=[...], allowed_origins=[...])` (also `FASTMCP_HTTP_HOST_ORIGIN_PROTECTION`); tested: hostile Origin gives 403, a request with no Origin still works, a bad `Host` is refused, a bad protocol-version header gives 400. Hosted profiles must list their real hostname in `allowed_hosts`. Docker: publish ports on `127.0.0.1` for local runs.
- Sessions in the spec are optional (`MCP-Session-Id`, 404 when expired); the spec also says elicitation state MUST NOT be tied to a session id alone, which matches our per-request identity. A -32042 error is a normal response to `tools/call`, so step-up does not need a server-initiated stream; form-mode elicitation (server request to the client) would.
- MCP Inspector: `npx @modelcontextprotocol/inspector`, transport **Streamable HTTP**, URL `http://localhost:<port>/mcp`, add a custom header `x-ft-user-token: <jwt>`. CLI check that worked: `npx @modelcontextprotocol/inspector --cli http://127.0.0.1:<port>/mcp --transport http --method tools/call --tool-name <tool> --header "x-ft-user-token: <jwt>"`. The CLI does not return for a -32042 tool (see friction log); the UI was not verified headless.

**Strands 1.57.1** [read from the installed source, 2026-09-30; used from P1-18]
- A custom model subclasses `strands.models.Model` and implements `update_config`, `get_config`, `structured_output` and `stream(messages, tool_specs, system_prompt, *, tool_choice, ...)`, an async generator of Bedrock-style stream events (`messageStart`, `contentBlockStart`/`Delta`/`Stop`, `messageStop`, `metadata`; event types in `strands/types/streaming.py`).
- MCP tools: `strands.tools.mcp.MCPClient(url=..., headers={...}, elicitation_callback=...)` builds a Streamable HTTP transport itself; the client is passed in `Agent(tools=[client])`.
- **Live check, DeepSeek (2026-09-30):** `OpenAIModel(client_args={"api_key": ..., "base_url": "https://api.deepseek.com"}, model_id="deepseek-flash")` (needs the `openai` package, 2.54.0 installed) drives the whole booking over MCP: search, availability, mandate, hold, confirm; 6 tool calls, about 30k tokens, 11 s, final state correct, no safety violation (`simulator/model.py`, `MODEL_PROVIDER=deepseek`). Endpoint, model id and prices: `docs/DECISIONS.md` D-028.
- Providers in the package: `BedrockModel`, `OpenAIModel` (needs the optional `openai` package, `client_args={"base_url", "api_key"}`), plus others loaded lazily from `strands.models`.

**DynamoDB Local** [`tests/integration/test_ddb_spike.py`, `-m ddb`]
- `infra/local/docker-compose.yml` starts `amazon/dynamodb-local` on `127.0.0.1:8000` (`-inMemory -sharedDb`). Endpoint via `DDB_ENDPOINT_URL` (default `http://localhost:8000`); tests skip if unreachable.
- `transact_write_items` with 5 items and one failing condition raises `ClientError` code `TransactionCanceledException`; `err.response["CancellationReasons"]` has one entry per item (positional; `Code` is `None` or `ConditionalCheckFailed`); `ReturnValuesOnConditionCheckFailure="ALL_OLD"` returns the blocking item under `Item`. Nothing else is written.
- 20 threads racing for one slot: exactly 1 success, 19 `ConditionalCheckFailed` at the slot item, no orphan holds. Counter with capacity 3: exactly 3 successes. Real DynamoDB may also return `TransactionConflict`; treat it as retryable.

---

### 3a-bis. Verified on the real account (Phase 2, 2026-09-30)
- **CDK:** CLI `aws-cdk@2.1143.0` (npm, `infra/cdk/package.json`, run with `npx cdk`) with `aws-cdk-lib==2.271.0` and `constructs==10.8.1` (PyPI) synthesises and deploys; CLI and library versions are independent. `cdk bootstrap aws://<account>/us-east-1 --tags project=fairtable` created the `CDKToolkit` stack (default execution policy `AdministratorAccess`, qualifier `hnb659fds`). `cdk diff` before deploy showed exactly one table and one budget.
- **`aws_dynamodb.Table` (2.271.0):** `point_in_time_recovery` is deprecated, use `point_in_time_recovery_specification=PointInTimeRecoverySpecification(point_in_time_recovery_enabled=...)`; `TableEncryption.DEFAULT` = AWS-owned key (no `SSESpecification` in the template, `DescribeTable` has no `SSEDescription`, the table is still encrypted at rest); `add_global_secondary_index(index_name, partition_key, sort_key, projection_type)`.
- **`AWS::Budgets::Budget`:** `CostTypes.IncludeCredit` defaults to true (CloudFormation reference, "AWS::Budgets::Budget CostTypes"); absolute-value notification thresholds are supported (`ThresholdType: ABSOLUTE_VALUE`). Prices (AWS Price List API, `AWSBudgets`): cost budgets $0.00; action-enabled budgets free for 62 budget-days, then $0.10 per budget-day; reports $0.01 each. DynamoDB us-east-1 on-demand: $0.625 per million write units, $0.125 per million read units, storage free for 25 GB then $0.25 per GB-month (`AmazonDynamoDB` price list).
- **Real DynamoDB behaviour:** `TransactWriteItems` does return `TransactionConflict` under contention (see D-036); the store's conditions still gave exactly one winner in 30 of 30 rounds of 20 simultaneous writers. Creating and deleting the table with two GSIs takes about 50 s.
- **boto3 and `aws login`:** needs `awscrt`; blocked by Windows App Control here; use `aws configure export-credentials --format env` (friction log).
- **Cognito trigger (docs read 2026-09-30, "Pre token generation Lambda trigger"):** `LambdaConfig.PreTokenGenerationConfig {LambdaArn, LambdaVersion: V3_0}`; response `claimsAndScopeOverrideDetails.accessTokenGeneration {claimsToAddOrOverride, claimsToSuppress, scopesToAdd, scopesToSuppress}`; trigger sources `TokenGeneration_Authentication | HostedAuth | NewPasswordChallenge | ClientCredentials | AuthenticateDevice | RefreshTokens`; the client id is `event.callerContext.clientId`; `clientMetadata` is **not** passed for `InitiateAuth`. A trigger **cannot** add or change `sub`, `username`, `client_id`, `cognito:username`; it can change `scope` and `cognito:groups`; scope values may not contain spaces. V2_0 and V3_0 need the Essentials or Plus plan; machine tokens get changes only with V3_0. Password sign-in tokens carry only the scope `aws.cognito.signin.user.admin`. The token endpoint (`/oauth2/token`, on the pool's domain) needs an app client with a secret, `client_credentials` in `AllowedOAuthFlows` and the scope enabled; it rejects a request with a scope the client may not use (`invalid_grant`). A domain-less M2M option exists (`ALLOW_CLIENT_TOKEN_AUTH` as the client's only flow); not used.
- **Cognito prices (AWS Price List API, `AmazonCognito`, us-east-1, published 2026-09-25):** Essentials $0.015 per MAU with the first 10,000 MAU free; machine token requests $0.00225 each (first tier, no free allowance); app clients for client credentials $0; Lite $0.0055, Plus $0.02; the per-RPS items are paid rate-limit increases, not automatic. No SKU for a prefix domain.
- **Cognito on the real account (deployed 2026-09-30, `us-east-1`):** access tokens, decoded and checked by the server's own verifier (`tests/aws/test_tokens.py`, 6 of 6): *diner via `alexa-plus-sim`* `{username, scope: "fairtable/book", agent_tier: verified, agent_id: alexa-plus-sim, token_use: access, client_id, sub}`; *owner* the same plus `cognito:groups: ["owners"]` and `custom:venue_id: luna-trattoria`; *machine, `alexa-plus-sim`* `{scope, agent_tier, agent_id, version: 2}` and **no `username`**; *machine, `bot-m2m`* `{scope}` only. No token has an `aud` claim (the verifier uses `client_id`). Issuer `https://cognito-idp.us-east-1.amazonaws.com/<pool id>`, keys at `<issuer>/.well-known/jwks.json`, lifetime 3600 s. The trigger removes `aws.cognito.signin.user.admin` with `scopesToSuppress` (without it, a leaked token could change the user's password). Sign-in with `InitiateAuth` `USER_PASSWORD_AUTH` on a client with a secret needs `SECRET_HASH` = base64(HMAC-SHA256(secret, username + client id)). The token endpoint is `https://<domain prefix>.auth.us-east-1.amazoncognito.com/oauth2/token` (basic auth with the client id and secret, `grant_type=client_credentials`, `scope=fairtable/book`). Stack deployment took 75 s; a function update 23 s.
- **AgentCore Runtime in CloudFormation (docs read 2026-09-30):** `AWS::BedrockAgentCore::Runtime` needs `AgentRuntimeArtifact`, `AgentRuntimeName` (pattern `[a-zA-Z][a-zA-Z0-9_]{0,47}`: no hyphen), `RoleArn`; optional `ProtocolConfiguration` (a string: `MCP | HTTP | A2A | AGUI`), `NetworkConfiguration.NetworkMode` (`PUBLIC | VPC`), `LifecycleConfiguration {IdleRuntimeSessionTimeout, MaxLifetime}` (60 to 1,209,600 s each), `RequestHeaderConfiguration.RequestHeaderAllowlist` (1 to 20 names), `PlatformVersion` (a string; **missing from the L1 class of aws-cdk-lib 2.271.0**, so `add_property_override`), `EnvironmentVariables`, `AuthorizerConfiguration`. Code artifact: `CodeConfiguration {Code: {S3: {Bucket, Prefix (the object key), VersionId?}}, EntryPoint (1 or 2 strings), Runtime: PYTHON_3_10 ... PYTHON_3_14 | NODE_22}`. `Ref` returns the runtime ARN; `GetAtt` has `AgentRuntimeArn`, `AgentRuntimeId`, `AgentRuntimeVersion`, `Status`, `FailureReason`. The S3 zip is read with the role that calls create/update (here CloudFormation's), not the execution role. Execution role trust: `bedrock-agentcore.amazonaws.com` with `aws:SourceAccount` and `aws:SourceArn` like `arn:aws:bedrock-agentcore:<region>:<account>:*`. Invoke URL: `https://bedrock-agentcore.<region>.amazonaws.com/runtimes/<URL-encoded ARN>/invocations?qualifier=DEFAULT`; with IAM callers the request is signed with SigV4 for service `bedrock-agentcore`; the platform adds `Mcp-Session-Id` when missing; an `Accept` header, if sent, must be `application/json` and/or `text/event-stream`.
- **Other facts used:** FastMCP's `allowed_hosts` accepts `*` and glob patterns and always adds its default loopback names; Secrets Manager dynamic references are allowed in ordinary resource properties (not in custom resources); a secret scheduled for deletion is not charged; Secrets Manager $0.40 per secret and month, $0.05 per 10,000 API requests (Price List API, `AWSSecretsManager`, us-east-1).
- **AgentCore Runtime on the real service (deployed 2026-10-01, second account, `us-east-1`):** `get_agent_runtime` reads back `status READY`, `platformVersion V2`, `protocolConfiguration MCP`, `networkMode PUBLIC`, `requestHeaderAllowlist ["x-ft-user-token"]`, `idleRuntimeSessionTimeout 120`, `maxLifetime 900`; each environment-variable change makes a new runtime version and the `DEFAULT` endpoint moves to it (`liveVersion 2, 3, ...`; about 4.4 minutes per `cdk deploy`). **The Host header the platform forwards to the container is `<uuid>.lambda-microvm.<region>.on.aws`** (one name per microVM), so `MCP_ALLOWED_HOSTS=*.lambda-microvm.*.on.aws`; with the server's default names it answers 421, and the platform's health checks come from `127.0.0.1` (`POST /mcp` 200) and pass. The caller side: SigV4 (service `bedrock-agentcore`) on `https://bedrock-agentcore.<region>.amazonaws.com/runtimes/<URL-encoded ARN>/invocations?qualifier=DEFAULT` with the FastMCP client (`StreamableHttpTransport(url, headers=..., auth=httpx.Auth)`) works; the client's closing `DELETE` gets a 404 (stateless; harmless). The log group `/aws/bedrock-agentcore/runtimes/<runtime id>-DEFAULT` is created at runtime creation (not by CloudFormation). A first Runtime creation in an old, normal account needed no service-linked-role workaround. Tests: `tests/aws/test_runtime_smoke.py` (8 of 8) and `tests/aws/test_tokens.py` (8 of 8).
- **aws-cdk-lib 2.271.0 Cognito:** `UserPool(feature_plan=FeaturePlan.ESSENTIALS, ...)`, `add_trigger(UserPoolOperation.PRE_TOKEN_GENERATION_CONFIG, fn, lambda_version=LambdaVersion.V3_0)`, `add_resource_server`, `OAuthScope.resource_server`, `add_client(disable_o_auth=..., o_auth=OAuthSettings(flows=OAuthFlows(client_credentials=True)))`, `add_domain(cognito_domain=CognitoDomainOptions(domain_prefix=...))`. CDK omits `ExplicitAuthFlows` when no flow is enabled (Cognito then applies its own defaults), so `bot-m2m` sets it with a property override.

## 4. Repo skeleton (created in P0-0)

```
CLAUDE.md  README.md  LICENSE  pyproject.toml  .python-version  .env.example  .gitignore
docs/
  DECISIONS.md  PLAN.md  aws-integration.md  friction-log.md  hackathon-rules.md
  (Vietnamese design/research/diagrams until P3-6/P3-7; ARCHITECTURE.md arrives in P0-5)
server/                 FastMCP app entry (python -m server)
  tools/                thin handlers, one module per tool (8)
  domain/               pure functions: models, errors, clock, slot_token, mandate, fees,
                        ratelimit, idempotency, waitlist, fairdrop
  kernel/               Trust Kernel: PEP-1 (G1–G4) + PEP-2 (P0, S1–S4), decide()
  identity/             joserfc verifier (dev issuer and Cognito use the same code)
  store/                DynamoDB access: keys, mappers, transactions
policies/               Cedar files, flat: p0_*, s1_*..s4_* (PEP-2, present); g1_*..g4_* (PEP-1, P1-3)
devauth/                dev JWT issuer standing in for Cognito (compose service)
web/                    FastAPI: consent page + owner console
simulator/              Strands agent, LLM adapter (mock default), chat page
eval/                   tasks/, harness, graders, reports/
workers/                (later) Lambda wrappers for the pure functions
infra/                  CDK app + AgentCore config (Phase 2); infra/local/ for Phase 0 spikes
scripts/                seed.py and local setup helpers
tests/                  unit/  integration/  redteam/  aws/
Dockerfile, docker-compose.yml   (created in P1-23; the primary run path)
```

---

## 5. Risks, verification order and cut list

### 5a. Unverified items, in verification order

| Order | Item | Why it is risky | How I verify | When |
|---|---|---|---|---|
| 1 | **Raising -32042 from a FastMCP 3.4.7 tool** (payload shape, not swallowed into `isError`) | Step-up is a Must. Not marked ❓ in the design but not yet proven. | Read installed FastMCP/mcp source, then spike P0-3 with the in-process client and MCP Inspector. | 10-01 |
| 2 | **cedarpy 4.12.1 claims** (`policies_to_json_str`, annotations kept, `has`-guard behaviour, Windows wheel for the chosen Python) | The whole Trust Kernel depends on it. | Spike P0-2 turns the design's scenarios into pytest. | 09-30 |
| 3 | **Header access in a FastMCP tool** (`x-ft-user-token`) and session behaviour | Identity depends on it. | P0-3. | 10-01 |
| 4 | **`task=True` with `pydocket` on `memory://`** (D-010) | Optional view only; must not affect Must features. | P0-3 (d); flag stays off if it does not work. | 10-01 |
| 5 | **DynamoDB Local `TransactWriteItems`** cancellation reasons and race behaviour | Needed to map cancellations to `SLOT_TAKEN` vs `POLICY_DENIED`. | P0-4. | 10-01 |
| 6 | **Strands custom/mock model API** | The simulator has no Bedrock. | Read installed `strands-agents` source, spike in P1-18. | 10-10 |
| 7 | ❓ **AgentCore Policy Cedar schema for an MCP target** | Only needed for the Gateway defense-in-depth copy (D5). | Create the Gateway, dump the schema (P2-6). | 10-16 |
| 8 | **-32042 and interceptor behaviour through Gateway** | Gateway is a proxy and might rewrite errors or drop headers. | P2-5, P2-7. | 10-16 / 10-17 |
| 9 | ❓ Model pricing | Only matters if a real provider is used. | P1-24 / P3-4. | 10-13 |
| 10 | ❓ Nova Act access | Could item, not planned. | – | – |

### 5b. Other risks

| Risk | Impact | Mitigation |
|---|---|---|
| **Schedule is tight** (D-007/008/011 added work) | Slips into Phase 3 | Cut list below; each gate is a decision point. |
| **Bedrock stays blocked** | No real-model numbers; weaker AWS Builder story | `MODEL_PROVIDER` adapter from day one; Q2 decision on 10-13; mock numbers labelled as harness validation. |
| **Dev issuer diverges from Cognito** | Local passes, AWS fails | Same verifier code; claim-shape tests run against both issuers' token fixtures (P2-4). |
| **Two Cedar policy sets drift** (D5) | Local and Gateway behave differently | Shared behavioural test suite. |
| **Judges cannot run it** | Lost points | Docker-first, README verified from a fresh clone (P4-4), no AWS needed. |
| **Vietnamese text left in the repo** | Breaks the language rule | P3-6, P3-7, and a language scan test. |
| **Lazy evaluation subtly wrong** (D4) | False denies, flaky evals | Invariant checker (I1–I5) after every integration test; one release function for all paths. |
| **Windows tooling** (Docker Desktop, wheels, paths) | Lost time | Found in P0-1 / P0-4; Java 25 is present as a DynamoDB Local fallback. |
| **AWS cost near the $150 credit** | Budget exhausted | Budgets alerts, teardown after each window, local-first evals. |
| **Public repo secrets** | Security | `.env.example` only; dev credentials clearly labelled; scan test allows only those. |
| **Version drift** | Breakage | Versions pinned; no mcp 2.x or FastMCP 4.x. |

**Cut list, in this order, if behind:**
1. Optional Tasks view (already optional).
2. Gateway Policy (P2-6), then Gateway + interceptor (P2-5); keep Runtime + Cognito + DynamoDB for the AWS demo.
3. Owner console beyond the S2 cap and audit view.
4. Eval set from 40 tasks down to a smaller stratified subset (state the number in the report).
5. A2 runs reduced to NEG tasks only.

Should items (Sim B, MCP Apps, Automated Reasoning, mandate form) are not scheduled; I ask before starting any.

---

## 6. What I need from you
1. Answers to **Q1, Q2, Q5, Q6** (defaults in §2b).
2. A yes/no on **D1, D2, D5** (they change policy text or structure).
3. Confirm coding starts **09-30**; otherwise the dates shift.
