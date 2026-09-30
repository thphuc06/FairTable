# Phase 1 – local core (10-02 → 10-13), no AWS

Status: **in progress – batches A–D done and committed; batch E done 2026-09-30, waiting for review** (decisions D-016 … D-027)

## Plan
Goal: everything a judge runs with `docker compose up`: the trust checks, the 8 tools, identity, storage, waitlist and Fair Drop, the supporting web pages, the simulator and the eval harness. Task list, acceptance criteria and tests: `docs/PLAN.md` §3, Phase 1.

Work is done in **batches**. A batch ends with a report and a review before the next one starts.

| Batch | Tasks | In plain words |
|---|---|---|
| A – foundation | P1-1, P1-2, P1-3, P1-4 | error codes, signed slot token, the two rule-checking layers, JWT identity check |
| B – data and reads | P1-5, P1-6, P1-7, P1-8 | dev token issuer, storage layer and seed data, read-only tools, duplicate-request protection |
| C – booking flow | P1-9, P1-10, P1-11, P1-12, P1-13 | hold, confirm with step-up, consent page, manage/cancel, concurrency checks |
| D – waitlist and drops | P1-14, P1-15, P1-16 | standing waitlists and the fair lottery for hot tables |
| E – apps and proof | P1-17 … P1-22 | owner console, simulator, chat page, eval harness, A0/A1/A2, red-team suite |
| F – packaging | P1-23, P1-24 | Docker profile, README |

Server bootstrap defaults (from the Phase 0 review, `PLAN.md` §3a): `host_origin_protection=True` with configured `allowed_hosts`, `mask_error_details=True`, local bind on `127.0.0.1`, the -32042 middleware. Do this when the FastMCP app entry is created (P1-7 at the latest).

Batch C plan (design in `DECISIONS.md` D-020):
1. **P1-9** `reservation_hold`: domain records and mappers, lazy release of expired holds, the hold operation (slot, S1, S2, hold in one transaction), tool.
2. **P1-10** `reservation_confirm` + step-up: approvals, mandate check, confirm operation, `tools/stepup.py` (-32042 or `consent_url`), dev inbox notifier.
3. **P1-11** consent page in `web/`: login, terms, Approve/Decline, same-user check, single use.
4. **P1-12** `reservation_manage`: view, reduce party size, cancel with fee and step-up.
5. **P1-13** concurrency hardening: races on slot, S1, S2, confirm; invariant checker.
Each task ends with the whole suite and `ruff` green and a devlog entry.

Batch D plan (design in `DECISIONS.md` D-023):
1. **P1-14** standing watches: watch records, `waitlist_watch`, `waitlist_status`, the lazy matcher hooked into cancel and hold-expiry, dev-inbox notice.
2. **P1-15** Fair Drop core (pure): `SeedProvider`, commitment, entry ids, HMAC order, allocation walk, audit build and `verify_audit`.
3. **P1-16** Fair Drop integration: drop records and seed data, entries with the one-ticket rule (I4, RT12), lazy exactly-once allocation, MCP resources for the audit and the policies.
Each task ends with the whole suite and `ruff` green and a devlog entry.

Batch E plan (research in `PLAN.md` §3a "Strands", design in `DECISIONS.md` D-026; order is by dependency):
1. **P1-17** owner console in `web/`: `/owner` (owners group + `custom:venue_id` claim), agent-share form with CSRF, rules text, recent audit; the change is audited and reaches rule S2 at once.
2. **P1-18** simulator core: `LLMClient`/model factory by `MODEL_PROVIDER` (`mock` default; `bedrock` and `deepseek` opt-in, lazy imports), a scripted Strands `Model` driven by deterministic personas with seeded noise, Strands `Agent` + `MCPClient` to the server, user-side tools `say` / `approve_consent` / `decline`.
3. **P1-19** chat page and login on the same web app (one sign-in for chat and consent), dev inbox shown.
4. **P1-20** eval harness v0: task YAML schema, per-run table namespace, runner, state and safety graders (reuse `check_invariants`), pass@1, pass^k, C_out.
5. **P1-21** A0 / A1 / A2 as configuration of the same server (A0 = no trust checks, A2 = no step-up).
6. **P1-22** red-team suite RT1–RT12 as deterministic tests with a summary printer.
Each task ends with the whole suite and `ruff` green and a devlog entry. Anything that would need a new dependency (`openai` for DeepSeek) is left as a lazy import and reported, not installed.

P1-20 design (eval harness v0):
- `eval/tasks.py` task YAML (id, category HAPPY|NEG|ROB|ADV, user, agent client, goal, noise, how the diner answers a consent link, expected end state) and loader that rejects unknown keys.
- `eval/env.py` one isolated environment per trial: a fresh DynamoDB table (the per-run namespace), seed data, the dev issuer, the MCP server on a free port, the consent page; torn down after.
- `eval/runner.py` runs the conversation with the simulator (assistant + simulated diner), then grades. `eval/graders.py`: state grader (expected reservations, holds, refusals) and safety grader (invariants I1-I5, counters, S1 and S2 limits). `eval/metrics.py`: pass@1, pass^k, C_out, violation, block and false-block rates, latency. `eval/report.py`, `python -m eval`.
- 10 hand-written starter tasks; the 40-task generator is P3-1. Only configuration A1 exists until P1-21. Reports label the model provider; mock numbers are harness validation.

Open design points to settle inside the batch that owns them:
- P1-10: step-up ladder when the client cannot open a URL (see `DECISIONS.md` D-014).

## Progress
| Task | Batch | Status | Date | Note |
|---|---|---|---|---|
| P1-1 domain models, errors, clock, slot_token | A | done | 2026-09-29 | errors, clock, slot token, success helper, Identity |
| P1-2 Trust Kernel PEP-2 | A | done | 2026-09-29 | engine, 6 rules, priority, fail-closed |
| P1-3 Trust Kernel PEP-1 (G1–G4) | A | done | 2026-09-29 | G1–G4 + shared scenarios |
| P1-4 identity verifier | A | done | 2026-09-29 | joserfc verifier + JWKS provider |
| P1-5 `devauth/` dev issuer | B | done | 2026-09-29 | FastAPI issuer, JWKS, password + client_credentials |
| P1-6 store layer and seed | B | done | 2026-09-29 | single table, 2 GSIs, seed script, transact wrapper |
| P1-7 read tools and token bucket | B | done | 2026-09-29 | 3 read tools, RT2, secure server defaults |
| P1-8 write pipeline and idempotency | B | done | 2026-09-29 | run_write, replay/conflict, audit |
| P1-9 `reservation_hold` | C | done | 2026-09-29 | hold op, lazy release, S1/S2/S4 in DB conditions |
| P1-10 `reservation_confirm` and step-up | C | done | 2026-09-29 | confirm op, approvals, -32042 / consent_url, dev inbox |
| P1-11 consent page | C | done | 2026-09-29 | web/: login, terms, Approve/Decline, CSRF, same-user |
| P1-12 `reservation_manage` | C | done | 2026-09-29 | view, reduce party, cancel with fee step-up |
| P1-13 concurrency hardening | C | done | 2026-09-29 | RT6/RT7/RT9 under load, invariant checker |
| P1-14 waitlist on DynamoDB | D | done | 2026-09-29 | standing watches, lazy matcher on cancel and expiry, status/cancel |
| P1-15 Fair Drop core | D | done | 2026-09-29 | commitment, tickets, HMAC order, verifiable audit |
| P1-16 Fair Drop integration | D | done | 2026-09-29 | entries, exactly-once lazy draw, audit and policy resources, I4 |
| P1-17 owner console | E | done | 2026-09-30 | /owner: share cap, rules, audit; cap change reaches S2 |
| P1-18 simulator core | E | done | 2026-09-30 | scripted Strands model, personas, assistant, simulated diner |
| P1-19 chat page and login | E | done | 2026-09-30 | /chat, one sign-in for chat, consent and owner console |
| P1-20 eval harness v0 | E | done | 2026-09-30 | 10 starter tasks x k=2 all pass on A1; metrics checked by hand |
| P1-21 A0 / A1 / A2 configs | E | done | 2026-09-30 | kernels selected by config; A1 clean, A0 and A2 show violations |
| P1-22 red-team suite | E | done | 2026-09-30 | RT1-RT12 as scenarios: A1 12/12, A0 8/12, A2 11/12 |
| P1-23 Docker profile | F | todo | | |
| P1-24 README and wrap-up | F | todo | | |

## Entries (newest first)

### 2026-09-30 · P1-18 · [simulator] · Change: DeepSeek flash verified live
- **Goal:** replace the unverified DeepSeek placeholders with documented values and prove one real conversation works.
- **Done:** defaults `https://api.deepseek.com` and `deepseek-flash` (from DeepSeek's API docs, D-028); only `DEEPSEEK_API` is required. `.env` gained `DEEPSEEK_MODEL` and `DEEPSEEK_BASE_URL` (no secrets; the key was already there and was never printed). `openai` 2.54.0 installed and declared in the `sim` extra (`pip check` clean, no pin changed). `Reply.tokens` reports the model's tokens per turn. Live run of task `happy-luna-alice-in-mandate` on the real model: search, availability, mandate, hold, confirm; final state 1 reservation, 0 violations; **29,840 tokens (at most about $0.04), 11 s.** The model's first confirm returned `IDEMPOTENCY_CONFLICT` (a real model mis-handled the key once; the server refused correctly and the model recovered). Not investigated further.
- **Files:** `simulator/{model,assistant}.py`, `tests/unit/simulator/test_model.py`, `.env.example`, `pyproject.toml`, `docs/{DECISIONS,PLAN,friction-log}.md`.
- **Tests:** unit tests updated (37 in `tests/unit/simulator`); the live call is a manual run, not a test (it needs the key and costs money). Whole suite result: see the batch report.
- **Decisions:** D-028.
- **Surprises / friction:** the Strands "reasoningContent" warning and the empty `AWS_PROFILE` problem (both in the friction log).
- **Follow-ups:** P3-4 (real-provider eval runs with a budget guard: about $0.03 per booking conversation at this size, so the $1.80 balance allows roughly 50 conversations, less at peak hours); P1-23 must not pass empty AWS variables to containers.

### 2026-09-30 · P1-22 · [eval] [redteam] · Red-team suite RT1-RT12
- **Goal:** the design's twelve attacks as deterministic scenarios, with the "blocked x/12" row for A0, A1 and A2.
- **Done:** `eval/redteam.py`: each attack runs against a real server in its own fresh environment and is judged from the database or the answers (blocked = the harmful effect did not happen), with the rule or error that stopped it. Uses real HTTP clients, a machine token (RT1), tokens minted with the issuer's key but missing a claim (RT3, RT9's twenty racers) and a token signed by another key (RT4). `python -m eval.redteam [--config A0,A1,A2]` prints the table and exits 1 if A1 misses an attack. **Result: A1 12/12, A0 8/12 (RT1, RT3, RT5, RT8 succeed), A2 11/12 (RT5 succeeds).**
- **Files:** `eval/redteam.py`, `eval/env.py` (`mint`, `machine_token`), `tests/redteam/test_redteam_suite.py` (18), `eval/README.md`.
- **Tests:** every attack blocked under A1 by the expected layer; exactly the policy-dependent attacks succeed under A0 and A2; RT2, RT4, RT6, RT7, RT9 to RT12 are blocked in every configuration (token verification, rate limiter, database conditions); the table and the exit code. Whole suite green, `ruff` clean.
- **Decisions:** none new. Two observations differ from the design table and are recorded as they are: RT1 is stopped by G4 (a machine token lacks both `username` and `agent_tier`; the engine reports the forbid), so either G2 or G4 counts; RT5 is reported as rule S3 (the answer's code is `CONSENT_REQUIRED`). RT2 polls 25 times against the 20-an-hour limit instead of 300 (same limiter, faster). RT11: no tool has a free-text field that is stored or acted on (there is no `special_requests`), so the injection text can only be a search term or an invalid value and nothing may change.
- **Surprises / friction:** none.
- **Follow-ups:** RT4 through the Gateway interceptor (strip a client-supplied header) is a Phase 2 check (P2-5), scaffold only until "wire AWS".

### 2026-09-30 · P1-21 · [eval] [trust-kernel] · A0 / A1 / A2 as configuration
- **Goal:** show, with the same server code, what the trust layer and the step-up each contribute.
- **Done:** `server/kernel/variants.py` (`OpenPep1/2` allow everything; `NoStepUpPep2` turns approval-needed into allow), `TrustKernel.open_store()` and `.without_step_up()`, `eval/configs.py` (name to kernel), the runner, the CLI (`--config A0,A1,A2`) and a comparison table in the design's layout. Result on the ten starter tasks (mock model, k = 1): **A1** all pass, 0 violations; **A0** 6 violations, 0/2 refusals and 0/2 attacks handled; **A2** 4 violations (exactly the bookings that needed the diner's approval, invariant I1), attacks still 2/2 blocked, the "diner declines" task fails because the booking happens anyway.
- **Files:** `server/kernel/{variants,__init__}.py`, `eval/{configs,runner,report,__main__}.py`, two HAPPY tasks now state outcomes only, `tests/unit/kernel/test_variants.py` (9), `tests/integration/test_ablation.py` (9).
- **Tests:** the claims above as assertions; A1 costs no legitimate booking (pass^k not lower than A0, false-block rate 0); a scan proves nothing under `server/` (outside the kernel package) can select a weakened kernel.
- **Decisions:** D-027 (what A0 and A2 mean; A0 keeps the database's guards so it shows no S1/S2 violations; open for the developer whether to build a stricter A0).
- **Surprises / friction:** none.
- **Follow-ups:** none blocking.

### 2026-09-30 · P1-20 · [eval] · Eval harness v0
- **Goal:** measure whether the trust layer holds, with numbers that can be recomputed by hand.
- **Done:** `eval/`: strict task YAML (`tasks.py`, unknown keys and bad values are errors), one isolated environment per trial (`env.py`: fresh DynamoDB table, seed, dev issuer, MCP server on a free port, consent page; the table is deleted afterwards), the runner (`runner.py`: the simulator's assistant and diner, up to three approval rounds), graders (`graders.py`: expected end state and refusals; safety = invariants I1-I5, counters, S1 and S2 limits read from the database), metrics (`metrics.py`: pass@1, pass^k, C_out, nearest-rank percentiles), report (`report.py`, banner says a mock run validates the harness only; nothing measured shows as "n/a", never 0) and `python -m eval`. A trial where the harness itself fails is a crash: reported, excluded, exit code 1, never a pass or a block. Ten starter tasks: HAPPY 4, NEG 2, ROB 2, ADV 2.
- **Files:** `eval/*.py`, `eval/tasks/*.yaml`, `eval/README.md`, `pyproject.toml` (packages `simulator*`, `eval*`; extra `eval = ["pyyaml"]`), `tests/unit/eval/` (38), `tests/integration/test_eval_run.py` (5).
- **Tests:** metrics against hand-worked values (for four trials of 4/4, 2/4, 0/4: pass@1 0.5, pass^2 7/18, pass^3 1/3, C_out 2/3); task validation; state grader; report; end to end: all 10 tasks x 2 trials pass with no violations and no table left behind; the run is reproducible; a wrong expectation fails with a reason; a harness failure is a crash; the safety grader reports a hand-made double booking as I2 (so a system that allowed one would not pass). Whole suite 671 passed, `ruff` clean.
- **Decisions:** none new. `pyyaml` is declared as an extra (it was already installed through strands-agents); no version pins changed.
- **Surprises / friction:** none. First real run: 10/10 on A1 at about 0.35 s per conversation.
- **Follow-ups:** cost per booking needs token counts (real models only, P3-4); the 40-task generator is P3-1; A0 and A2 are P1-21.

### 2026-09-30 · P1-19 · [web] [simulator] · Chat page and shared sign-in
- **Goal:** the demo a judge can click: sign in, talk to the assistant, follow the approval link, come back.
- **Done:** `/chat` (transcript, message box, "Start over", the dev inbox as Notifications). Each signed-in diner gets their own `simulator.Assistant` connected to the MCP server with their own token (`web/chat.py`; tokens stay in the web process's memory, never in the cookie or page). The same cookie serves the consent page and the owner console, so one sign-in covers all; `/` sends diners to `/chat` and owners to `/owner`. No JavaScript (works under the strict CSP); CSRF token bound to the user on both forms; only links to our own consent page become anchors; messages cut at 500 characters. `Login` now returns `SignedIn` (identity, access token, lifetime). New setting `MCP_URL`. `python -m web` builds the chat with `MODEL_PROVIDER` (mock by default).
- **Files:** `web/{chat,app,auth,pages,__main__}.py`, `web/README.md`, `server/config.py`, `tests/integration/{test_chat_web,conftest,world,test_simulator}.py` (the `live` server fixture moved to a shared conftest).
- **Tests:** 12 new: sign-in required, landing redirects, booking by chat, the full step-up loop in one browser session (assistant hands over the link, diner approves, assistant completes), escaping, link whitelisting, CSRF (also across users), start over, separate conversations, length cut, chat off, owner page closed to diners. Whole suite 628 passed, `ruff` clean.
- **Decisions:** none new; the session length (1 hour) stays as is and the chat asks for a new sign-in when the token expires.
- **Surprises / friction:** none.
- **Follow-ups:** the Docker profile (P1-23) must set `MCP_URL` to the server's service name and run `python -m web`. The AWS profile would use Cognito's hosted login (scaffold only).

### 2026-09-30 · P1-18 · [simulator] · Simulator core
- **Goal:** a simulated Alexa+ assistant that uses the real server exactly as a real agent would, with no model account.
- **Done:** `simulator/`: `events` (Strands messages to `UserSaid`/`Step`), `personas.decide()` (pure: book, watch, cancel; follows each tool's `next_step`; asks for approval and waits; seeded noise such as a retried hold), `request.parse_request` (a diner's sentence to a goal, for the chat page), `model.ScriptedModel` (a Strands `Model` driven by a persona) and `build_model()` (`MODEL_PROVIDER`: `mock` default; `bedrock` and `deepseek` built lazily, with clear errors when unconfigured), `assistant.Assistant` (Strands `Agent` + `MCPClient` to the server with the diner's token in `x-ft-user-token`, exactly the 8 tools), `user.SimulatedUser` (signs in and approves or declines on the consent page; the assistant cannot). Personas were also fixed twice during testing (a watch never followed up; restaurant matching now scores words and asks on a tie).
- **Files:** `simulator/*.py`, `simulator/README.md`, `tests/unit/simulator/`, `tests/integration/test_simulator.py`, `tests/conftest.py` (signal fixture).
- **Tests:** 36 unit + 7 integration (real HTTP, real Strands agent): booking inside the mandate in one turn; outside it, link then approval then booked; declined approval books nothing; retried hold gives one hold; a chat sentence is enough; another diner cannot approve; exactly 8 tools. Whole suite 616 passed, `ruff` clean.
- **Decisions:** the deepseek provider has **no default base URL or model id** (they are not verified yet, D-018); it needs `DEEPSEEK_API`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL` and the optional `openai` package, which I did not install. The bedrock provider needs `BEDROCK_MODEL_ID`. Neither was called.
- **Surprises / friction:** the full suite hung once the simulator joined it (sse-starlette read a stale SIGTERM handler left by an earlier two-server test as "server shutting down"); fixed with an autouse fixture. Details in `friction-log.md`.
- **Follow-ups:** the real-model providers are untested until a key or Bedrock access exists (P3-4).

### 2026-09-30 · P1-17 · [web] · Owner console
- **Goal:** the restaurant owner can lower the share of seats agents may book and sees what happened, so the S2 demo moment is real.
- **Done:** `/owner` (sign-in as an owner; the owners group and a `custom:venue_id` claim from the dev issuer are both required), the agent-share form (whole number 0-100, CSRF token bound to the user and the venue), the plain-English rules the server enforces, and the last three days of audit (newest first, 40 rows). A change is one transaction: venue update plus an audit entry (`owner_console`, old and new value). Owners can only see their own restaurant; diners get 403; the next hold after a change reads the new cap (S2).
- **Files:** `web/{app,pages,session}.py`, `server/domain/models.py` (`Identity.groups`, `venue_id`, `owned_venue`), `server/identity/verifier.py`, `devauth/{accounts,issuer}.py`, `tests/integration/test_owner_console.py`, one assertion in `test_devauth.py`.
- **Tests:** 15 new; whole suite 573 passed, `ruff` clean. Includes the demo flow: a hold succeeds, the owner sets the share to 0, the same request is refused with `S2_agent_share_of_covers`.
- **Decisions:** D-026.
- **Surprises / friction:** none. `Identity` gained two optional fields; nothing in the trust kernel reads them.
- **Follow-ups:** the AWS profile maps `cognito:groups` and a Cognito custom attribute the same way (scaffold only, D-016).

### 2026-09-29 · environment · [aws] · The new AWS account, read-only check
- **Goal:** find out what the developer's new AWS account can do before any AWS wiring.
- **Done:** signed in with `aws login` (IAM user with admin, no access keys); read-only checks of identity, IAM, Bedrock models, availability, quotas and invocation, and the services the project will use. Findings in D-025 and the friction log.
- **Files:** `docs/DECISIONS.md` (D-025), `docs/friction-log.md`.
- **Tests:** not applicable (no code changed). Two Bedrock `converse` attempts were refused (nothing billed); Cost Explorer was queried three times (small per-request charge, to be confirmed).
- **Decisions:** D-025.
- **Surprises / friction:** Bedrock refuses all invocations with an unspecific error while quotas read 0 (friction log).
- **Follow-ups:** the developer decides about the Anthropic first-time-use form, a quota-increase request, MFA for the IAM user, payment method and credit check; then "wire AWS" part by part (DynamoDB first).

### 2026-09-29 · P1-8 · [store] · Change: a duplicate that loses a race is answered from the stored result
- **Goal:** close a race the batch D concurrency tests exposed (about one run in five).
- **Done:** every failure after the first idempotency lookup now looks the key up once more; if the original has committed meanwhile, the copy gets the stored result (or `IDEMPOTENCY_CONFLICT` if its parameters differ) instead of a misleading "slot taken" or "hold no longer active".
- **Files:** `server/pipeline.py` (`_late_replay`), `tests/integration/test_write_pipeline.py` (3 deterministic tests for the window).
- **Tests:** 558 passed; the red-team file was run eight times in a row without a failure.
- **Decisions:** D-024.
- **Surprises / friction:** the bug only shows with real concurrency, which is why those tests exist.
- **Follow-ups:** none.

### 2026-09-29 · P1-16 · [fairdrop] · Fair Drop integration
- **Goal:** a lottery hot-table seekers can trust: committed in advance, one ticket per person, checkable afterwards.
- **Done:** drops are created with the seed data (secret seed, public commitment); `waitlist_watch(drop_id)` issues one ticket per verified person (RT12, invariant I4) while the drop is open; the first request after the drop time (a ticket status, an entry attempt, an audit read) claims the drop with a conditional status change, walks the entries in HMAC order giving each a hold on the next free seat that fits, skips people the rules refuse (S1, S2, P0) with the rule named, marks the rest lost, reveals the seed and stores the audit; a claim older than 60 s is taken over, so a crashed run is finished. Winners confirm through the normal flow. Public resources: the drop audit and each restaurant's rules in plain English. `verify_audit` recomputes the draw from the published data; the invariant checker now enforces I4 and audit validity.
- **Files:** `server/ops/fairdrop.py`, `server/dropper.py`, `server/resources.py`, `server/tools/{waitlist_watch,waitlist_status}.py`, store additions (tickets, drops), `server/store/{seed_data,seeding}.py`, `server/invariants.py`, `tests/integration/test_fair_drop.py`, `tests/redteam/test_rt09_concurrency.py` (RT12), `tests/integration/test_invariants.py`.
- **Tests:** 21 Fair Drop + 2 RT12/entry-storm + 2 invariant checks. Includes: draw order equals the published order, two places / five tickets / a party that fits no seat, 16 simultaneous first requests run the draw exactly once, an interrupted draw is finished, a running draw is not stolen, late entries refused.
- **Decisions:** D-023, D-024.
- **Surprises / friction:** none in the design; the real HTTP run shows all 8 tools and both resource templates.
- **Follow-ups:** the owner console (P1-17) can set a drop's times; the simulator (P1-18) needs a drop scenario for the video.

### 2026-09-29 · P1-15 · [fairdrop] · Fair Drop core (pure)
- **Goal:** the trust mechanism as plain, testable functions.
- **Done:** `SeedProvider` (local randomness; KMS as scaffold), `commitment`, ticket ids that hide the person, `order_entries` by HMAC-SHA256, `build_audit`, `pending_audit`, `verify_audit` (detects a wrong seed, wrong order, wrong draw keys, impossible winners, someone passed over, missing reasons).
- **Files:** `server/domain/fairdrop.py`, `tests/unit/domain/test_fairdrop_core.py`.
- **Tests:** 20, including a fairness sanity check (each of four tickets wins first about a quarter of the time over 400 seeds).
- **Decisions:** D-023.
- **Surprises / friction:** none.
- **Follow-ups:** none.

### 2026-09-29 · P1-14 · [waitlist] · Standing watches
- **Goal:** register once, be given a table when one opens; no polling loop.
- **Done:** `waitlist_watch` (one active watch per person, restaurant and day; declines to register when a table is free now), `waitlist_status` (status with `retry_after_s`, matched hold, cancel), and the lazy matcher: a freed table (a cancel, or an expired hold released by the lazy sweep, including the confirm path) goes to the first fitting watcher in arrival order through the normal write pipeline with their stored identity, so P0, S1 and S2 still apply and a refused watcher is skipped; the watch and the hold change together in one transaction; the watcher gets a dev-inbox notice; a failing matcher never breaks the cancel that triggered it.
- **Files:** `server/domain/waitlist.py`, `server/ops/waitlist.py`, `server/matcher.py`, `server/tools/{waitlist_watch,waitlist_status}.py`, hooks in `ops/hold.py`, `ops/confirm.py`, `lifecycle.py`, `tools/reservation_manage.py`, store additions, `tests/integration/test_waitlist.py`, `tests/unit/domain/test_waitlist_match.py`.
- **Tests:** 29 + 7.
- **Decisions:** D-023.
- **Surprises / friction:** none.
- **Follow-ups:** MCP Tasks remain an optional view, off by default (D-010); not started.

### 2026-09-29 · P1-10 · [booking-tools] · Change: the hold is lengthened once when approval is needed
- **Goal:** a user who needs a few minutes on their phone must not lose the table (found in the batch C review: hold 10 minutes vs approval 15).
- **Done:** `lifecycle.extend_hold` lengthens the hold and its slot together, once, to the approval's expiry when a confirm asks for step-up; the messages say how many minutes the user has. Nothing else changes: in-mandate bookings keep the 10-minute hold, expired or taken-over holds cannot be extended, and the lock is bounded (D-022).
- **Files:** `server/lifecycle.py`, `server/tools/stepup.py`, `server/domain/booking.py` (`Hold.extended`), `server/store/mappers.py`, tests in `test_reservation_confirm.py` (6 new) and `test_consent_web.py` (the old "page dies at minute 11" test now expects the page to work, plus an end-to-end slow-user case).
- **Tests:** 474 passed, `ruff` clean; the invariant checker still passes after an extension.
- **Decisions:** D-022.
- **Surprises / friction:** `extended` is a DynamoDB reserved word (friction log).
- **Follow-ups:** P1-19 shares the sign-in between the chat page and the consent page; session length still open.

### 2026-09-29 · P1-13 · [store] [booking-tools] · Concurrency hardening and the invariant checker
- **Goal:** prove the database conditions, not the happy path, are what keep the rules true under load.
- **Done:** `server/invariants.py` scans the table for I1 (unapproved booking outside the mandate), I2 (double-booked table), I3 (fee without approval), I5 (write without identity), counter consistency and slot/owner agreement. Real-thread tests: 20 simultaneous holds on one slot give exactly one winner (RT9); one user racing over 20 slots ends with exactly two holds (RT6); the Ember agent-share cap gives exactly five holds of two (RT7); 20 deliveries of one confirm make one booking; 10 different keys confirming one hold make one booking; 10 cancels free the table once and the counter never goes negative; confirm works one second before expiry and fails at the exact expiry moment; a seeded storm of 120 mixed operations ends with every invariant intact.
- **Files:** `server/invariants.py`, `Store.scan_all`, `tests/redteam/test_rt09_concurrency.py`, `tests/integration/test_invariants.py`, `tests/conftest.py` (moved up so red-team tests share the DynamoDB fixtures).
- **Tests:** 8 concurrency + 7 checker tests; the concurrency file was run three times in a row without a flake.
- **Decisions:** D-020, D-021.
- **Surprises / friction:** none in the code under test; the checker tests show it detects each kind of damage (otherwise the concurrency tests would prove nothing).
- **Follow-ups:** I4 (one Fair Drop ticket per person) joins the checker in P1-16; the eval graders (P1-20) reuse `check_invariants`.

### 2026-09-29 · P1-12 · [booking-tools] · `reservation_manage`
- **Goal:** view, shrink or cancel a booking, never cancelling silently when a fee applies.
- **Done:** `view` (what cancelling costs right now, no state change), `modify` (only reduces the party; adds no cost), `cancel` (fee computed before writing; S3b step-up when a fee applies; approval bound to that exact fee; slot and covers freed in one transaction). Fee step-up answers -32042 or `FEE_APPLIES` with `consent_url`; a declined fee gives `CONSENT_DECLINED`.
- **Files:** `server/ops/manage.py`, `server/tools/reservation_manage.py`, `server/tools/common.py` (`check_pep1`), `tests/integration/{test_reservation_manage,flows}.py`, two cancel-fee cases in `test_consent_web.py`.
- **Tests:** 19 + 2.
- **Decisions:** D-020 (flat fee, modify limited to reducing), D-021.
- **Surprises / friction:** none. Freed slots are where waitlist matching hooks in (marked in `CancelOperation.plan`, task P1-14).
- **Follow-ups:** P1-14 hooks the waitlist after a cancel; the fee is flat (the design's diagram says per person).

### 2026-09-29 · P1-11 · [web] · Consent page
- **Goal:** the out-of-conversation approval: only the right user, only once, only for the exact terms.
- **Done:** `python -m web`: login through the dev issuer, HMAC session cookie, terms page with Approve / Decline, CSRF bound to user and request, single-use decision audited in one transaction, 403 for another account, 410 when the request or the booking behind it is over, 404 for unknown ids, safe redirects only, no framing, strict CSP, all output escaped. End to end: the assistant asks, the user approves on the page, the same confirm call then succeeds and consumes the approval.
- **Files:** `web/{app,pages,session,auth,__main__}.py`, `web/README.md`, `tests/integration/test_consent_web.py`, `tests/integration/world.py` (`World.web()`).
- **Tests:** 22.
- **Decisions:** D-020 (URL names the approval, login proves the person).
- **Surprises / friction:** no `itsdangerous`/`jinja2` installed, so cookies and HTML use the standard library.
- **Follow-ups:** P1-17 (owner console) reuses the session code; the AWS profile swaps `web/auth.py` for Cognito hosted login (scaffold only, D-016); the chat page (P1-19) shows the dev inbox.

### 2026-09-29 · P1-10 · [booking-tools] · `reservation_confirm` and step-up
- **Goal:** book at once inside the mandate; otherwise make the user approve, outside the chat.
- **Done:** confirm operation (hold, slot, S1 and reservation in one transaction), mandate check, approval lookup (approved, same user, same terms hash, unexpired, unused, consumed in the same transaction), step-up ladder: -32042 for clients that declared `elicitation.url`, otherwise `CONSENT_REQUIRED` with `consent_url`; approvals are created once per request; the dev inbox notifier records the message.
- **Files:** `server/ops/confirm.py`, `server/consent.py`, `server/notify.py`, `server/tools/{reservation_confirm,stepup}.py`, `server/domain/booking.py`, `tests/integration/test_reservation_confirm.py`.
- **Tests:** 15 including both ladder rungs and every way an approval can be worthless (other user, other terms, expired, declined).
- **Decisions:** D-020, D-021.
- **Surprises / friction:** the SDK's capability helper cannot tell URL mode from form mode (friction log); `sub` is a DynamoDB reserved word.
- **Follow-ups:** none blocking.

### 2026-09-29 · P1-9 · [booking-tools] · `reservation_hold`
- **Goal:** take a table for ten minutes without ever double-booking or exceeding a cap.
- **Done:** hold operation with slot, S1 and S2 conditions in one transaction; lazy release of expired holds (restaurant/day and user), so stale holds never block S1/S2 and expired slots read as open; drop-controlled seats refused (S4); `SLOT_TAKEN` returns alternative times; `within_mandate` and the reasons it is false are reported so the agent can warn the user before confirm; slot tokens for the same slot and party count as the same request for idempotency.
- **Files:** `server/ops/{hold,common}.py`, `server/lifecycle.py`, `server/tools/reservation_hold.py`, domain `booking.py`, store mappers/queries/keys, `tests/integration/test_reservation_hold.py`.
- **Tests:** 21, including the keep-in-sync test between the Cedar S1 limit and the code constant.
- **Decisions:** D-020, D-021 (Luna now has free cancellation).
- **Surprises / friction:** none.
- **Follow-ups:** none.

### 2026-09-29 · P1-8 · [store] [booking-tools] · Write pipeline and idempotency
- **Goal:** one ordered path for every state-changing tool, so the rules and the guarantees cannot be skipped.
- **Done:** `run_write()`: PEP-1 → idempotency lookup → facts → PEP-2 → one transaction (tool writes + idempotency record + audit). Same key + same parameters returns the stored result (`idempotent_replay: true`); different parameters or another tool gives `IDEMPOTENCY_CONFLICT`; denials, step-ups and failures store no key and are audited. A duplicate that lands between lookup and write is caught by the transaction's own condition. `StepUpRequired` carries the decision to the tool layer (P1-10).
- **Files:** `server/pipeline.py`, `server/domain/{idempotency,audit}.py`, store additions (`get_idempotency`, `idempotency_op`, `audit_op`, `put_audit`, `list_audit`), `tests/unit/domain/test_idempotency_logic.py`, `tests/integration/test_write_pipeline.py`.
- **Tests:** 18 integration + 4 unit. Includes 20 duplicate deliveries of one request (exactly one hold, 19 replays), 20 users racing for one slot (one winner, losers' counters rolled back, no orphan holds), and two deterministic interleavings.
- **Decisions:** D-019 (key format, replay flag, audit on denial).
- **Surprises / friction:** DynamoDB Local reports every failing condition, so both the slot and the idempotency item show up when a duplicate loses.
- **Follow-ups:** the real operations (`reservation_hold` …) implement `WriteOperation` in batch C; the test double `FakeHold` shows the shape.

### 2026-09-29 · P1-7 · [booking-tools] [docs] · Read tools, rate limit, server assembly
- **Goal:** the server runs for the first time and answers read questions safely.
- **Done:** `restaurant_search`, `availability_check` (signed, user-bound `slot_token`s; hot and Fair-Drop slots flagged; expired holds treated as open), `mandate_status`; token bucket per (user, restaurant) for `availability_check` (RT2: the 21st call in an hour is `RATE_LIMITED` with `retry_after_s` and a waitlist next step); `python -m server` with Origin/Host protection, masked errors and structured refusals; `mandate_covers_booking` logic ready for confirm.
- **Files:** `server/{app,config,middleware,ratelimit,pipeline}.py`, `server/tools/{common,present,restaurant_search,availability_check,mandate_status}.py`, `server/domain/{mandate,ratelimit,availability}.py`, tests in `tests/unit/domain/` and `tests/integration/{test_read_tools,test_server_http,world}.py`.
- **Tests:** about 90 new, including forged/expired/missing tokens over real HTTP (RT4 server side), a bearer header alone is not an identity, a key-server outage is refused without leaking why, and a bug stays masked and loud in the logs.
- **Decisions:** D-019 (`mandate_status` without mandate is a normal answer; error boundary; defaults).
- **Surprises / friction:** FastMCP logs a full traceback for every raised business error (friction log); fixed by a `FastMCPError` subclass at INFO level. Spoken times repeated when two table sizes shared a time; deduplicated.
- **Follow-ups:** both open questions were closed by the developer (D-019: `mandate_status` answer stands; the server's time zone is used, no per-venue zone). The consent link for creating a mandate is not offered until that page exists.

### 2026-09-29 · P1-6 · [store] · Storage layer and seed data
- **Goal:** a tested way to read and write DynamoDB, and demo data that makes every rule easy to trigger.
- **Done:** key builders that reject ids which could collide, mappers, `Store` (get/put/query/batch/transact with retry on transient conflicts, `TransactionCancelled` naming the failing items, `StoreBusy`), table creation with two overloaded indexes, deterministic seed (3 restaurants, 14 days, a hot Saturday table at Ember Grill, a Friday Fair-Drop seat at Sakura Counter, mandates for Alice and Carol), `scripts/seed.py` (idempotent, `--reset`).
- **Files:** `server/store/*`, `scripts/seed.py`, `tests/unit/store/`, `tests/integration/{conftest,ddb_env,test_store_ddb}.py`.
- **Tests:** 29 (pure key/mapper/seed checks, retry rules with a scripted client, DynamoDB Local reads, atomic cancel, 20-way race, the seed script run twice).
- **Decisions:** D-019 (overloaded indexes, lazy `held_until`, UTC wall-clock times).
- **Surprises / friction:** boto3's serializer rejects floats (friction log).
- **Follow-ups:** AWS path uses the same code with the default credential chain; scaffold only until "wire AWS" (D-016).

### 2026-09-29 · P1-5 · [identity] · Dev token issuer (`devauth/`)
- **Goal:** local stand-in for Cognito so the whole identity chain can run offline.
- **Done:** FastAPI service with OIDC-style metadata, JWKS, and `/token` for the password grant (diners, owner) and client credentials (machines); agent claims follow the client (verified / unverified / none), reproducing RT1 and RT3; owner group claim; optional persisted signing key; `python -m devauth`.
- **Files:** `devauth/{accounts,issuer,app,__main__}.py`, `devauth/README.md`, `tests/integration/test_devauth.py`.
- **Tests:** 23; tokens verify with the server's own verifier and drive the PEP-1 decisions end to end.
- **Decisions:** D-019 (clients, claims).
- **Surprises / friction:** none.
- **Follow-ups:** P1-11 (consent page login) and P1-19 (chat page) call `/token` with the password grant.

### 2026-09-29 · P1-4 · [identity] · Token verifier and JWKS provider
- **Goal:** no write tool can run without a verified caller.
- **Done:** `TokenVerifier` (joserfc, RS256 only, `iss` / `aud` / `exp` / `nbf` / `sub`, configurable audience claim) turns a valid JWT into an `Identity`; every failure is `UNAUTHENTICATED` with a server-side reason. `HttpJwks` caches keys, throttles refreshes and survives an outage; `StaticJwks` for tests. `verify_headers()` reads `x-ft-user-token`.
- **Files:** `server/identity/{jwks,verifier,__init__}.py`, `tests/unit/identity/` (conftest, `token_env.py`, `test_verifier.py`, `test_jwks.py`), `pyproject.toml` (`httpx`).
- **Tests:** 55 new: forged, tampered, wrong-key, `alg: none`, HS256-with-public-key, expired, wrong audience/issuer, garbage, key rotation, refresh throttling, outage.
- **Decisions:** D-017 (verifier and JWKS choices).
- **Surprises / friction:** joserfc validates only claims that are present, so required claims must be `essential`. Cognito access tokens use `client_id`, not `aud` (handled by `audience_claim`; unverified on real Cognito, scaffold-only per D-016).
- **Follow-ups:** the FastMCP tool layer (P1-7) reads the header and masks `JwksUnavailable`; the dev issuer (P1-5) must publish `kid`s and the claims the verifier expects.

### 2026-09-29 · P1-3 · [trust-kernel] · PEP-1 (G1–G4)
- **Goal:** stateless checks on claims and request shape, before any state is read.
- **Done:** `policies/g1…g4*.cedar` + `pep1.cedarschema`; `Pep1.decide()`. 15 behavioural scenarios in `tests/unit/kernel/pep1_scenarios.py` (shared with the future Gateway suite, D5), including the naive-G4 vs `has`-guard regression.
- **Files:** `policies/g*.cedar`, `policies/pep1.cedarschema`, `server/kernel/pep1.py`, `tests/unit/kernel/{pep1_scenarios,test_pep1}.py`.
- **Tests:** 15 scenarios plus guard and input checks.
- **Decisions:** D-017 (G3 on every tool, G4 on writes only).
- **Surprises / friction:** none; optional token claims are omitted from the Cedar entity when absent so `principal has <claim>` is honest.
- **Follow-ups:** the Gateway-side copy of G1–G4 (P2-6) must pass the same scenarios; scaffold only until "wire AWS".

### 2026-09-29 · P1-2 · [trust-kernel] · PEP-2 engine and rules
- **Goal:** a single `decide()` path with deny > step_up > allow that never fails open.
- **Done:** `PolicyBundle` (load, validate against schema, evaluate), `Pep2.decide()` with a required-field `PolicyContext`, `deny_to_error()` turning a denial into a structured error with `hint`, `rule_id` and `next_step`. D1 and D2 are covered (S2 no longer blocks `waitlist_watch`; S3b step-up on cancel with a fee).
- **Files:** `server/kernel/{engine,pep2,guidance,__init__}.py`, `policies/pep2.cedarschema`, `tests/unit/kernel/{test_pep2,test_policy_loading,test_guidance}.py`.
- **Tests:** 17 rule cases, priority, fail-closed on evaluation error, 11 loader checks, guidance mapping.
- **Decisions:** D-017 (fail closed, schema validation at startup, extra error codes).
- **Surprises / friction:** `validate_policies` catches misspelt attributes, so the schema files pay for themselves.
- **Follow-ups:** the write pipeline (P1-8) builds `PolicyContext` from store facts; a STEP_UP decision becomes the -32042 / `consent_url` flow in P1-10 (D-016).

### 2026-09-29 · P1-1 · [docs] [trust-kernel] · Foundation: errors, clock, slot token, output helper
- **Goal:** the shared vocabulary every later task uses.
- **Done:** `ToolName` (8 tools, read/write sets), `ErrorCode` (15) with default `next_step` and `FairTableError.to_payload()`, `success()` enforcing a short `spoken_summary`, `Clock` / `SystemClock` / `FakeClock`, `Identity`, and `SlotTokenCodec` (signed, expiring, user-bound).
- **Files:** `server/domain/{tool_names,errors,output,clock,models,slot_token}.py`, `tests/unit/domain/{test_foundation,test_slot_token}.py`.
- **Tests:** 50 new (every code has a next step; tampering, expiry, wrong user, garbage tokens).
- **Decisions:** D-017 (slot token bound to `sub`, 15-minute lifetime).
- **Surprises / friction:** none.
- **Follow-ups:** venue, slot and hold models are added with the store (P1-6) instead of speculatively now.
