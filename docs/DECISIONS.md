# Decisions log

Short record of decisions that shape the build. Newest last. If a decision here conflicts with `fairtable-solution-design.md`, this file wins until the design is updated. Ask before overriding either.

## D-001 – Local Docker is the primary run path (2026-09-29)
- **Decision:** A locally runnable public repo plus the demo video is enough for the Alexa+ track. Hosting is not required, and judges may build and run the project themselves.
- **Meaning of "self-hosted":** our own MCP server, as opposed to Amazon's gated Alexa+ tools that participants cannot access. It is demoed through our own web front end.
- **Source:** official FAQ and rules (clarified by the developer, 2026-09-29).
- **Consequences:**
  - Local Docker (server + DynamoDB Local + web + simulator) is first-class and must work from a fresh clone.
  - AgentCore Runtime/Gateway deployment stays in Phase 2, but **only for the AWS Builder mini challenge**. If it slips, the submission still qualifies.
  - Keep all code deployment-agnostic: no account IDs, ARNs or regions in code; everything from env/config.

## D-002 – Open Source mini challenge is out of scope (2026-09-29)
- **Decision:** We target **AWS Builder only**.
- **Why:** The Open Source challenge requires a separate, additional project or contribution (the form asks for both a contribution URL and a project repo URL), and a project can win only one mini-challenge prize.
- **Consequence:** No extra repo or upstream PR work is planned.

## D-003 – Model choice is ours; MODEL_PROVIDER is configurable; mock-first (2026-09-29)
- **Decision:** Model choice is free. The provider is selected by `MODEL_PROVIDER` (`mock` by default, `bedrock` when available, others possible). Stub Bedrock early (the FAQ itself recommends this).
- **Bedrock block:** an AWS Support matter, not an organizer one. Nothing to ask the organizers.
- **Unchanged:** the 2026-10-13 decision point on where eval numbers come from. Mock-based numbers are labelled as harness validation, not model reliability.

## D-004 – Judging window and README readiness (2026-09-29)
- **Facts:** Judging runs Nov 9–20 and may include automated AI-driven review.
- **Decisions:**
  - The README must have clear setup and run instructions that work from a fresh clone (verified in P4-4 on a clean checkout, using the Docker path).
  - Do not plan on keeping AWS resources running. Spin them up for tests and the demo, then tear them down (scripted, documented).
  - The license (Apache-2.0) stays visible in the repo's About section (already done).

## D-005 – Deadline (2026-09-29)
- **Deadline:** 2026-10-23 12:00 PDT. Submission target remains 2026-10-22; 10-23 is the spare day.

## D-006 – Organizer questions withdrawn (2026-09-29)
- The questions in design §15 are no longer to be sent; the FAQ and rules answer what we needed (see D-001, D-002). Remaining unknowns are handled by design fallbacks, not by asking.

## D-007 – The local profile is what judges run (2026-09-29)
- **Decision:** A fresh clone plus `docker compose up` starts everything with **no AWS account**:
  - the MCP server (Streamable HTTP, spec 2025-11-25);
  - DynamoDB Local;
  - the consent page and owner console (`web/`);
  - a **dev JWT issuer** (`devauth/`) standing in for Cognito, with seeded test users;
  - the simulator with `MODEL_PROVIDER=mock` as the default. A real provider is opt-in via env.
- **Test login credentials are listed in the README.** They are dev-only values seeded into the local issuer, not secrets. The secret-scan test must allow them explicitly.
- **Dev issuer scope (minimum needed for the demo and RT1/RT3/RT4):**
  - publishes a JWKS and OIDC-style metadata;
  - issues user tokens (`sub`, `username`, `agent_tier`, `agent_id`, scope `fairtable/book`) after a simple login;
  - issues M2M `client_credentials` tokens for a bot client that has **no** `username` and no `agent_tier` (this is what makes RT1 and RT3 reproducible locally);
  - mirrors the Cognito pre-token V2/V3 logic in plain Python.
- **Switching to Cognito is configuration only:** issuer URL, JWKS URL, audience. The server verifier is the same code in both profiles.

## D-008 – G1–G4 also run in cedarpy (2026-09-29)
- **Decision:** The local build enforces the **full rule set** in the server with `cedarpy`: PEP-1 rules G1–G4 (including the `has`-guard on G4) **and** PEP-2 rules P0 + S1–S4.
- **AWS profile:** AgentCore Gateway Policy (G1–G4 at the Gateway) becomes **defense in depth**, not the only place these rules live.
- **Consequences:**
  - Evaluation order in the server: PEP-1 (stateless, claims and request shape) then PEP-2 (stateful).
  - Local G1–G4 use the local Cedar schema built from the verified JWT claims. The Gateway-generated schema may differ, so the two policy sets stay separate files but share one **behavioural test suite** (same scenarios, same expected outcomes).
  - The design's fallback "move G1–G4 into cedarpy" is now the default, not a fallback.
  - RT1, RT3 and RT4 become fully local tests.

## D-009 – All submission material is in English (2026-09-29)
- **Decision:** All submission materials, including code documentation, must be in English. Everything written from now on (code, comments, docs) is English.
- **Existing Vietnamese material:** `docs/fairtable-solution-design.md`, `docs/research-alexa-plus-round3-2026-09.md` and the labels inside both `.drawio` files.
- **Plan:** before the feature freeze, write `docs/ARCHITECTURE.md` in English (authoritative from then on), relabel the diagrams in English, and move the Vietnamese documents out of the repo (see `docs/PLAN.md`, tasks P0-5, P3-6, P3-7).
- Until `ARCHITECTURE.md` exists, the Vietnamese design doc remains the source of truth for design questions.

## D-010 – MCP Tasks are optional; DynamoDB is the source of truth for waitlists (2026-09-29)
- **Facts:** FastMCP's tasks extra relies on `pydocket`, which is built for Redis; the `memory://` backend is for testing only.
- **Decision:**
  - DynamoDB is the source of truth for watches and drop entries.
  - `waitlist_status` is the **primary** path for agents.
  - MCP Tasks are an **optional view** on top, behind a config flag (default off). `memory://` is acceptable for the local demo.
  - Every feature works fully with Tasks disabled.
  - **No Redis or ElastiCache** anywhere in the plan.
- **Consequence:** the design's "Tasks fallback" date (10-16) is no longer a risk to a Must feature.

## D-011 – AWS Builder: keep Phase 2; document it; show it in the video (2026-09-29)
- **Decision:** Keep Phase 2 (AgentCore Runtime, Gateway + Policy, Cognito, DynamoDB).
- Add `docs/aws-integration.md` describing each AWS service used and how.
- The demo video must show the **AWS-deployed path at least once**.
- Qualification for the Alexa+ track does not depend on it (D-001). The AWS Builder claim does.
- Minimum demonstrable AWS path if time runs short: Runtime + Cognito + DynamoDB. Cut order for the rest: Gateway Policy first, then the Gateway and interceptor.

## D-012 – Verified facts (2026-09-29, reported by the developer)
- `mcp` 1.30.0 reports `LATEST_PROTOCOL_VERSION = 2025-11-25`.
- `fastmcp` 3.4.7 requires `mcp>=1.24,<2.0`.
- No change to the pins. Spike P0-3 no longer needs to check the protocol version.

## D-013 – Working agreement (2026-09-29)
- The developer runs `git add .` and commits. The assistant does not commit.
- Current phase: documentation and codebase organisation first. Implementation is done later on the developer's PC.

## D-014 – Policy changes D1, D2, D5 applied; step-up via middleware validated (2026-09-29)
- **D1 (applied):** S2 (`policies/s2_agent_share_of_covers.cedar`) applies to `reservation_hold` only. `waitlist_watch` is removed because a watch consumes no covers, and S2's own `next_step` is `waitlist_watch`.
- **D2 (applied):** new rule **S3b** (`policies/s3b_cancel_fee_needs_ack.cedar`, `@on_deny("step_up")`, `reservation_manage`). It fires when `context.cancel_fee_cents > 0 && !context.cancel_fee_acknowledged`. `cancel_fee_cents` is a whole number in minor currency units and is `0` for view, modify and fee-free cancels. The PEP-2 set is now P0 + S1–S4 + S3b.
- **D5 (confirmed):** two policy sets (server and Gateway) share one behavioural test suite.
- **Step-up transport:** FastMCP 3.4.7 wraps exceptions raised in a tool into `ToolError`, so `UrlElicitationRequiredError` never reaches the client. The server adds an `on_call_tool` middleware that re-raises the original error, giving a JSON-RPC **-32042** error. Checked against the MCP spec 2025-11-25 (elicitation, "URL Elicitation Required Error") and FastMCP's own `ErrorHandlingMiddleware`, which uses the same pattern (inspects `__cause__`, raises `McpError` from middleware). Rules taken from the spec for the consent URL: no sensitive data in the URL, not pre-authenticated, HTTPS outside dev, and the consent page must verify that the user opening it is the user who started the request (same `sub`). Open point for P1-10: the spec says a server must not send elicitation modes the client did not declare, so check the client's `elicitation.url` capability and fall back to an `isError` result with the consent link and `next_step` if it is missing.

## D-015 – Consequences of the full rules text (2026-09-29)
Source: the official rules and event page, distilled in `docs/hackathon-rules.md`.
- **Availability until 2026-11-20:** the project must stay available free of charge to judges until the judging period ends; judges are not required to test it. Availability means the public repo plus the video (D-001, D-004 still hold: no AWS resources are kept running).
- **No changes after the deadline:** the submission cannot be altered once the submission period ends. Tag the submitted commit (`submission`) and push no functional changes until 11-20.
- **Fresh clone must keep working:** pin exact Python dependency versions (lock file) and a fixed DynamoDB Local image tag before the freeze (P1-23, P3-8). Today `joserfc`, `pydantic`, `boto3` are unpinned and the compose spike uses `amazon/dynamodb-local:latest`.
- **Friction log is a form field:** entries are pasted into the submission form; Amazon scores them in Stage 1 (bonus up to 10%). Product feedback needs five answers per tool (used for, worked well, needs work, onboarding, build again).
- **AWS credits:** requested (no reply yet, 2026-09-29). If nothing has arrived by 10-14, Phase 2 runs on the free tier with AWS Budgets alerts and only the minimum demonstrable path (Runtime + Cognito + DynamoDB, see D-011); Bedrock stays optional.
- **Help channels:** the Resources page lists live office hours and a Developer Community forum. Whether Alexa+ supports URL-mode elicitation is unanswered by the docs (D-014); asking there is the developer's call (D-006 withdrew the earlier organizer questions).
- **Simulator path:** the rules allow a simulated Alexa+ experience as an alternative to the MCP server; we do both, so the simulator's source stays in the repo and is shown in the video.
- **Open item:** MCP Apps is named as a creative Alexa+ signal. It stays a "Should", not scheduled; ask before starting.

## D-016 – Step-up ladder, notifier seam, Phase 2, and the AWS "scaffold only" rule (2026-09-29)
Confirmed by the developer before batch A.
- **Step-up ladder (P1-10):** (1) if the client declares URL-mode elicitation, return JSON-RPC **-32042** with the consent URL (middleware, D-014); (2) otherwise return a normal `isError` result whose structured content has `consent_url`, a short `spoken_summary` and `next_step`. In both cases the approval happens on our consent page with a verified login, outside the conversation. Spoken yes/no through form-mode elicitation and an MCP Apps card are **not** planned (Should; ask first).
- **Notifier seam (P1-10):** a `Notifier` interface with a "dev inbox" implementation (default; also shown in the chat page and logs). An SNS implementation is only a later option in Phase 2.
- **Phase 2 (AWS Builder path) stays in the plan** (D-011). If the $150 credits have not arrived by 10-14, run on the free tier with Budgets alerts and only the minimum path.
- **AWS work is scaffold only until the developer says otherwise:** for anything that touches an AWS service (DynamoDB on AWS, Cognito, AgentCore, Gateway, SNS, Bedrock, KMS, CDK deploys) build only the frame: interfaces, config read from env, adapters that are not called, CDK skeleton that is not deployed. Do not create resources, make AWS calls, use credentials, or add tests that need AWS. Local equivalents (DynamoDB Local, dev issuer, mock model) are real. The developer authenticates and asks for the real wiring later.

## D-017 – Implementation choices in batch A (2026-09-29)
Interpretations of the design made while building P1-1 … P1-4; each has a test.
- **PEP-1 scope:** G1 permits the four read tools for any valid token; G2 permits the four write tools only for a real user (`username`) with scope `fairtable/book`; G3 (`party_size > 10`) applies to **every** tool (`party_size` is 0 where a tool has none); G4 (`has`-guard, verified agent) applies to the **write** tools only, so reads stay open to bots as G1 says.
- **Fail closed:** any Cedar evaluation error, or a reason the loader does not know, is a deny (`policy_error`); no matching permit is a deny (`no_permit`, reported as the permit that was missing: G2 for PEP-1, P0 for PEP-2). `PolicyContext` (PEP-2 facts) has no defaults: a missing fact is a bug, not a pass.
- **Startup validation:** each policy bundle is validated against a local Cedar schema (`policies/pep1.cedarschema`, `pep2.cedarschema`) and must have `@id`; forbids need `@on_deny` (`deny` | `step_up`); any problem stops the server. Typos in attribute names are caught at load time.
- **Extra error codes** beyond the design's list: `UNAUTHENTICATED`, `INVALID_SLOT_TOKEN`, `SLOT_TOKEN_EXPIRED`, `CONSENT_DECLINED`. Every code has a default `next_step`. Internal reasons (why a token was rejected, Cedar error text) stay server-side.
- **Slot token:** HMAC-SHA256, **bound to the user's `sub`**, default lifetime 15 minutes, secret at least 32 bytes from config. Only `Identity` is a domain model so far; venue, slot and hold models arrive with the store (P1-6).
- **Verifier:** RS256 only by default; `audience_claim` is configurable (`aud`; `client_id` for Cognito-style access tokens, to be checked on real Cognito in Phase 2, scaffold-only until then). JWKS over HTTP is cached 10 minutes, a forced refresh (unknown `kid`) is throttled to once per 30 s, stale keys are served during an outage; an outage with a cold cache raises `JwksUnavailable`, which is not a token error and is masked and denied by the tools layer.

## D-018 – DeepSeek is the interim real model; Bedrock later (2026-09-29)
- **Decision:** `MODEL_PROVIDER` gains a `deepseek` value for the simulator and the eval harness while Bedrock is blocked. The key is read from the environment variable `DEEPSEEK_API` (kept in the git-ignored `.env`). `bedrock` stays a stub and is wired only when the developer says "wire AWS" (D-016); switching then is a configuration change.
- **Defaults unchanged:** `mock` is still the default in every profile, so judges and CI need no key and no money. No LLM is ever called inside an MCP tool (CLAUDE.md).
- **Budget:** the developer has about $1.80 of DeepSeek credit. The eval budget guard (P3-4) must stop well before that, count tokens per run, and report the cost. Real-model numbers are labelled with the provider and model name (D-003).
- **Before use (P1-18):** verify from the installed `strands-agents` 1.57.1 source how an OpenAI-compatible endpoint such as DeepSeek is configured (model class, base URL, model id); do not guess. If Strands has no suitable class, the provider goes behind the `LLMClient` adapter.
- **Safety:** `.env` is git-ignored and untracked (checked); the secret-scan test (P3-7) must also fail on a `DEEPSEEK_API` value in any tracked file.

## D-019 – Implementation choices in batch B (2026-09-29)
- **Dev issuer:** agent claims come from the OAuth **client**, not the user (as in the design's pre-token trigger). Clients: `alexa-plus-sim` (verified; password grant for diners, and V3-style machine tokens with the claims), `shady-agent` (unverified), `bot-m2m` (no claims). Owners carry `cognito:groups=["owners"]`. Passwords and secrets are public dev values listed in the README.
- **Storage:** one table with two overloaded indexes (`GSI1`: venue directory now, hold-expiry later; `GSI2`: a user's holds and reservations later). Ids that enter keys reject `#` and control characters. `Slot.held_until` is checked on read (lazy expiry, D4). Times in slots are wall-clock times compared with the server clock's date and time. **Decided by the developer: keep it simple, use the server's time zone (UTC by default, from the injected clock); no per-venue time zone.**
- **Rate limit:** only `availability_check`, per (user, restaurant), a token bucket of 20 per hour (configurable), optimistic update; on repeated self-contention the request is refused (fail closed).
- **`mandate_status` without a mandate** returns a normal answer (`mandate_state: none`, "every booking will need approval") instead of the design table's `NOT_FOUND` + `consent_url`. `NOT_FOUND` is kept for an unknown restaurant. Reason: a missing mandate is a normal state, and the create-mandate page is only a "Should". **Confirmed: the developer left this to my judgement and it stands.**
- **Write pipeline (`server/pipeline.py`):** PEP-1 → idempotency lookup → facts → PEP-2 → one transaction (tool writes + idempotency record + audit). Idempotency key is 8-128 characters `[A-Za-z0-9._:-]`; the stored-result replay carries `idempotent_replay: true`; the hash covers the tool name, so one key cannot be reused across tools. Denials, step-ups and failures store no key (the same key can be retried after the cause is fixed) but are audited with a separate best-effort write. A duplicate delivery that lands between lookup and write is detected by the idempotency condition inside the transaction.
- **Error boundary:** tools raise `FairTableError`; `@business_errors` turns it into a `BusinessError` (a `ToolError` at INFO level, so FastMCP logs no traceback for routine refusals) and `ErrorMappingMiddleware` returns the structured `isError` result. Real bugs stay masked and loud.
- **Server defaults:** Origin/Host protection on, `mask_error_details=True`, bind `127.0.0.1` unless configured; the profile `aws` refuses the built-in dev slot-token secret.

## D-020 – Design of the booking flow, batch C (2026-09-29)
Settled before coding P1-9 … P1-13 (research: mcp 1.30 / FastMCP 3.4.7 source, MCP spec 2025-11-25).
- **Records.** *Hold* (`HOLD#id`): user, agent, venue, date, slot, party, status `held|confirmed|released|expired`, `held_until` (10 min, `HOLD_TTL_S`), terms snapshot; while `held` it is listed in GSI1 (`HOLDS#venue#date`, sorted by expiry) and GSI2 (`USER#sub`). *Reservation* (`RES#id`): confirmed booking with code, terms snapshot, status `confirmed|cancelled`. *Approval* (`APPROVAL#subject_id`): what the user must approve (`confirm` a hold, or `cancel_fee` on a reservation), the user's `sub`, a hash of the terms, status `pending|approved|declined|used`, valid 15 minutes, single use. The subject id is a random 128-bit id, so the consent URL is `{CONSENT_BASE_URL}/consent/{subject_id}`; it grants nothing by itself, the page requires a login as the same `sub`.
- **Counters.** S1 counts a user's *held* holds per restaurant (max 2, equal to the Cedar rule; a test keeps the two in sync). S2 counts agent covers per restaurant and day (holds + reservations). Confirm lowers S1 only; cancel lowers S2; expiry lowers both.
- **Lazy expiry (D4).** Before a hold or confirm, expired holds of the restaurant/day (GSI1) and of the user (GSI2) are released, one small transaction each (hold to `expired`, both counters down). The slot itself is treated as open once `held_until` has passed (read side and write condition), and is restored best-effort. No worker.
- **Step-up (D-016).** A `STEP_UP` decision becomes: (1) if the client declared `elicitation.url`, JSON-RPC -32042 with the consent URL; (2) otherwise an `isError` result with `consent_url` and code `CONSENT_REQUIRED` (confirm) or `FEE_APPLIES` (cancel). Both create the approval once (a repeat call reuses it) and put a message in the *dev inbox* (a `Notifier` seam; item `INBOX#sub` in DynamoDB, shown by the chat page later; SNS is a later option). The SDK's `check_client_capability` only tests that `elicitation` exists, so the tool reads `client_params.capabilities.elicitation.url` itself; no session (stateless) means rung 2.
- **Approvals.** The agent retries with the same `idempotency_key`; an approved, unexpired, unused approval for the same terms hash makes the Cedar fact `mandate_covers_booking` / `cancel_fee_acknowledged` true and is consumed in the same transaction. A declined approval gives `CONSENT_DECLINED`.
- **Cancel fee.** A flat venue fee applies when the booking starts within `free_cancel_hours` (server time zone). The design's diagram says "per person"; flat is the MVP simplification.
- **`reservation_manage`.** `view` changes nothing and skips the pipeline (PEP-1 and ownership only). `cancel` runs the pipeline (S3b applies). `modify` is limited to **reducing** the party size (never adds covers or cost); an increase is refused with a hint to cancel and rebook. Cancel frees the slot and is where waitlist matching hooks in later (P1-14).
- **Consent page (`web/`).** Cookie session signed with HMAC (no extra dependencies), login through the dev issuer, CSRF token on the decision form, `X-Frame-Options: DENY`, strict CSP, `Cache-Control: no-store`.
- **Invariants.** `server/invariants.py` checks I1 (no booking outside mandate without an approval), I2 (no double-booked slot), I3 (a fee is only charged with an approved approval), I5 (no write without identity) plus counter consistency; used by the concurrency tests now and by the eval graders later. I4 (one ticket per drop) arrives with Fair Drop.

## D-021 – What batch C changed relative to the plan (2026-09-29)
- **Seed data:** Luna Trattoria now has free cancellation (fee 0). With a $10 fee Alice's mandate (max fee 0, as in the design's example) could never cover a booking there. Ember Grill ($25, 48 h) and Sakura Counter ($50, 72 h) keep fees, so rule S3b is easy to demonstrate.
- **Timestamps:** all stored timestamps use `iso_z()` (`YYYY-MM-DDTHH:MM:SSZ`, fixed width) because expiry checks and sort keys compare them as text.
- **New error code `CONSENT_REQUIRED`** (the fallback when the client cannot open URLs, for confirm); `FEE_APPLIES` is the fallback for a cancel with a fee. `FairTableError` gained `details` (for example alternatives after `SLOT_TAKEN`).
- **Pipeline addition:** operations may implement `approval_request()`; `StepUpRequired` carries the operation so the tool layer can create the approval and answer.
- **`reservation_manage`:** `view` skips the pipeline; `modify` only reduces the party size (D-020).
- **Web:** `python -m web` serves the consent page on port 8080 (`WEB_HOST`, `WEB_PORT`, `WEB_SESSION_SECRET`; the `aws` profile refuses the built-in dev secret).

## D-022 – The hold is lengthened once for a step-up approval (2026-09-29)
- **Problem found in review:** a hold lasts 10 minutes but a phone approval is valid for 15, and an approval is only useful while the hold is alive. A user who took 11 minutes lost the table although they did everything right, and the consent page said "no longer active".
- **Decision (developer chose option A):** when a *confirm* needs approval, the hold is lengthened **once**, to the end of the approval window (15 minutes from the first ask), together with the slot, in one guarded transaction (`lifecycle.extend_hold`). Holds that do not need approval stay at 10 minutes. The lock is bounded: the step-up can only start while the hold is alive (at most 10 minutes after it was taken) and adds at most 15, so a table is never locked longer than about 25 minutes, and only when the user was actually asked. It cannot be extended twice, after expiry, or after the slot was taken over.
- **Messages:** the -32042 prompt and the `consent_url` hint now say how many minutes the user has.
- **Not chosen:** one longer TTL for every hold (locks tables needlessly), a longer TTL only for holds known to be outside the mandate (less exact), and re-taking the table automatically after approval (surprising).
- **Login on the consent page (explained to the developer):** the link is in the assistant's hands, so approving must need something the assistant does not have: a sign-in through the dev issuer (Cognito hosted login on AWS, scaffold). Task P1-19 will serve the chat page and the consent page from the same web app so one sign-in covers both; the session length (now 1 hour) is still open.

## D-023 – Design of waitlists and Fair Drop, batch D (2026-09-29)
No internet research was needed: SHA-256, HMAC-SHA256 and commit-reveal are standard-library operations; MCP Tasks stay off (D-010); KMS is scaffold only (D-016). Design read from `fairtable-solution-design.md` sections 7.2, 7.3 and the plan tasks P1-14 to P1-16.
- **Standing watch (`waitlist_watch`).** A *watch* records who wants a table (restaurant, date, time window, party size) plus a snapshot of the caller's verified identity (`sub`, `username`, `agent_tier`, `agent_id`, scopes). **One active watch per person per restaurant per day** (`ALREADY_ENTERED` otherwise; the watch ends on match, cancel or expiry and then a new one is allowed). If a fitting table is free right now the tool says so and creates nothing. A watch consumes no covers (D1); it needs a verified agent (P0) like every write.
- **Matching is lazy.** When a table is freed (a cancel, or an expired hold released by the lazy sweep) the freed slot is offered to waiting watchers in arrival order (FIFO by creation time). The matcher takes the first watcher whose window and party fit and creates a normal 10-minute hold for them through the same write pipeline with the stored identity snapshot, so S1, S2 and P0 still apply (a denied watcher is skipped). The hold and the watch's change to `matched` are one transaction, so two matchers cannot both win. The watcher is told in the dev inbox and finds the hold with `waitlist_status`; confirming is the normal `reservation_confirm`. Drop-controlled slots are never matched by a standing watch.
- **`waitlist_status`** (read tool) takes a `watch_id` (a watch or a drop entry) and `action` status | cancel. It answers `waiting` with `retry_after_s` and a next step, `matched` with the hold and its expiry, `expired`, `cancelled`; for drop entries `entered`, `won`, `lost`, `skipped`. Cancel is a single conditional update by the owner (no idempotency key needed, repeating it is harmless).
- **Fair Drop.** A *drop* covers one or more drop-controlled slots (`drop_id` on the slot) and has `opens_at`, `drop_at`, capacity = number of its slots, and a **commitment** = SHA-256 of a secret 32-byte seed, published from the start (in the entry answer, `waitlist_status` and the audit resource). The seed comes from a `SeedProvider` (`secrets.token_bytes` locally; a KMS `GenerateRandom` implementation exists as scaffold only and is not called). Entries: `waitlist_watch(drop_id=...)`, **one per verified person per drop** (a conditional write on `ENTRY#hash`, RT12), only while `opens_at <= now < drop_at` (`DROP_CLOSED` after). The entry id is `drop_id~SHA-256(drop_id|sub)` so the public audit never shows a `sub`.
- **Allocation (lazy, exactly once).** The first request after `drop_at` (a `waitlist_watch` on the drop, a `waitlist_status`, or a read of the audit resource) claims the drop with a conditional status change `open -> allocating` (a stale claim older than 60 s can be taken over), orders the entries by **HMAC-SHA256(seed, entry_id)** ascending, and walks down the list giving each entry a hold on the next free drop slot that seats the party, through the pipeline with the winner's stored identity. This is the one sanctioned route around rule S4 (the win is the authorisation), so the operation passes `slot_is_drop_controlled = false`; S1 and S2 still apply and an entry that cannot take a hold is `skipped` with the rule id and the walk continues. Idempotency keys `drop-<id>-<entry hash>` make a resumed run safe. Winners confirm through the normal flow (mandate or step-up). Finally the drop becomes `allocated`, the seed is revealed and the audit is stored.
- **Audit** (`fairtable://drops/{drop_id}/audit`, public): before allocation the commitment and the rules; afterwards the seed, every entry id in entry order, the HMAC order, the winners and skipped entries. `verify_audit()` recomputes commitment, order and winners from the published data alone, so anyone can check the draw.
- **Resources** `fairtable://restaurants/{id}/policies` (rules in plain English plus the restaurant's caps) and the audit above need no sign-in: they hold no personal data.
- **Invariants.** I4 (one ticket per person per drop) joins `server/invariants.py`; counters and slots stay consistent through watch matches and allocation.

## D-024 – What batch D changed or found (2026-09-29)
- **Race fixed in the write pipeline (found by the concurrency tests).** A duplicate delivery could pass the first idempotency lookup, the original could then commit, and the copy would fail its own checks for a reason the original had just created ("slot taken", "hold no longer active") instead of returning the stored result. Every failure after the first lookup (facts, rule refusal, step-up, plan, transaction) now looks the key up once more and returns the stored result (or `IDEMPOTENCY_CONFLICT` if the parameters differ). It appeared about once in five runs of the 20-simultaneous-confirms test; eight consecutive runs are clean and three deterministic tests cover the window.
- **Watches and tickets:** one shared `watch_id` argument; a Fair Drop ticket id is `drop_id~SHA-256(drop_id|sub)`. Withdrawing a ticket before the draw deletes it (re-entering gives the same id, so nothing can be gained). `waitlist_status` is annotated as not read-only because it can cancel; its access rule is still G1.
- **Draw time in the seed data:** entries open at seed time, the draw is 24 hours before the seats and never sooner than 10 minutes after seeding, so a fresh demo can always enter first.
- **Public resources need no sign-in** (`fairtable://restaurants/{id}/policies`, `fairtable://drops/{id}/audit`); reading the audit after the draw time runs the draw, like any other first request.
- **`KmsSeedProvider` exists as scaffold only** (D-016): it is tested against a fake client and never called against AWS.

## D-025 – AWS account status, read-only check (2026-09-29)
Checked with the developer's own credentials, read-only, nothing created. No account id or ARN is recorded here.
- **Access:** an IAM user with `AdministratorAccess`, signed in with `aws login` (short-term credentials, no access keys). Root has MFA and no keys; the IAM user has no MFA yet (recommended).
- **Empty and ready:** DynamoDB, Cognito, AgentCore (runtimes, gateways), KMS, SNS, Lambda, S3 and ECR all respond and hold nothing. CDK is not bootstrapped. Only budget: "My Zero-Spend Budget" ($1). The account plan is PAID with 0 free-plan credits; the hackathon's $150 credit could not be confirmed through the API (check the Billing console, Credits page, including expiry and which services it covers).
- **Bedrock models are not usable yet** (see the friction log): every invocation is refused, first-time-use form for Anthropic not submitted, zero cross-region quotas. AgentCore, DynamoDB, Cognito and KMS do not depend on it, so the AWS Builder path (Phase 2) is not blocked; only real-model runs on Bedrock are.
- **Rule D-016 still holds:** nothing is wired to AWS until the developer says so, per part.


## D-026 – Owner console and batch E choices (2026-09-30)
- **Owner identity:** an owner is a signed-in user whose token has the group `owners` **and** a venue claim (`custom:venue_id`, the same name a Cognito custom attribute would have). Both are read by the verifier into optional `Identity` fields and are used by the web app only; no MCP tool or policy reads them. The venue is never taken from the URL or the form, only from the session, so an owner cannot touch another restaurant.
- **Owner console scope (as in CLAUDE.md):** change the agent share (0-100 %) and view the rules and recent audit. Nothing else. The change and its audit entry are one transaction; rule S2 reads the venue on every hold, so the effect is immediate.
- **Session:** the signed cookie carries the owned venue too, so one sign-in serves the consent page, the owner console and (P1-19) the chat page.

## D-027 – What A0 and A2 mean in the evaluation (2026-09-30)
Design section 9.3 gives the ablation in one line each; this fixes what they do in the code (`eval/configs.py`, `server/kernel/variants.py`).
- **A0 (open store)** replaces PEP-1 and PEP-2 with allow-all. It removes the *policy* layer only. The database's atomic guards stay on in every configuration (one live claim per table; the counters behind S1 and S2 are DynamoDB conditions). So A0 does not show S1 or S2 violations, and the report says so. **Recommendation kept, open for the developer:** a stricter A0 that also lifts the S1/S2 conditions would need a switch inside the write operations; I did not add one because a switch that turns safety off inside the server is a risk in a public repo, and the comparison already shows the layer that matters (identity, party size, drop seats, approvals).
- **A2 (no step-up)** is the real rules with every `step_up` decision treated as `allow`: the assistant's own "yes" is enough, nothing goes to the diner. All denials still apply.
- **Never selectable in the server.** Only the evaluation builds these kernels; `python -m server` always loads the real policies, and a test scans `server/` for any other reference.
- **A trial passes only if the end state is right and the safety grader finds nothing.** So a booking made outside the diner's permission without their approval fails a HAPPY task under A0 and A2 (invariant I1), while the same booking with approval passes under A1. Happy-path expectations therefore state outcomes (reservations, holds), not mechanisms (error codes).

## D-028 – DeepSeek defaults verified (2026-09-30)
Source: DeepSeek API docs (api-docs.deepseek.com: home, pricing, create-chat-completion), read 2026-09-30; the pages were summarised by a small model and agree with each other.
- Base URL `https://api.deepseek.com` (OpenAI-compatible, `POST /chat/completions`). Light model: **`deepseek-flash`** (the older `deepseek-v4-flash` still works); the other model is `deepseek-v4-pro`. Flash supports tool calls and streaming; about $0.15 per million input tokens (cache miss) and $0.6 per million output, doubled in peak hours (01-04 and 06-10 UTC, Monday to Friday).
- These are now the defaults of `MODEL_PROVIDER=deepseek`; only `DEEPSEEK_API` is required (D-018 stays: the key lives in the git-ignored `.env`). Not yet exercised against the live API; that needs the `openai` package installed and the developer's go-ahead.

## D-029 – The Docker profile (2026-09-30)
Built for plan task P1-23; nothing here touches AWS.
- **One image, four services.** A single `Dockerfile` (base `python:3.12.14-slim`, pinned by tag and digest) runs the server, the dev issuer, the web pages and the seed script. The source stays in `/app` as an editable install because the Cedar policies are found relative to the code. The container user is not root; app containers drop all capabilities and cannot gain privileges.
- **Ports.** Everything is published on `127.0.0.1` only. MCP 8000, web 8080, issuer 9000, and DynamoDB Local on **8001** (not 8000) so the MCP server can keep the documented 8000. The Phase 0 file `infra/local/docker-compose.yml` still uses 8000 for the `-m ddb` tests; use one or the other, or point the tests at 8001.
- **DynamoDB Local** is pinned (`3.3.1`, same digest as the `latest` the spikes used), in memory, so every `up` starts from the same seed; the seed script waits for the database (`--wait`) instead of relying on a health check the image cannot run.
- **Names inside vs outside.** Tokens name `http://localhost:9000` as issuer (a label; browsers never open it), the server fetches keys from `http://devauth:9000/...`, and the web container signs diners in at `AUTH_TOKEN_URL` (new setting, default issuer + `/token`). The MCP server allows Host names `localhost`, `127.0.0.1` and `server` (a request with another Host answers 421).
- **Model.** `MODEL_PROVIDER` defaults to `mock`; `DEEPSEEK_*` are passed through only when set. No AWS variable is passed to any container (an empty `AWS_PROFILE` breaks boto3; `.env.example` now leaves it commented out).
- **Checked.** `tests/integration/test_compose_smoke.py` (`pytest -m docker`) drives the running stack over real HTTP: tools, refusal of a missing token and a foreign Host, the chat booking with approval on the consent page, the owner console. Run once on the working tree and once on a copy holding only tracked and unignored files, without any `.env`.
- **Not done here (by design).** Exact dependency versions and the image lock file are P3-8 (D-015); `joserfc`, `pydantic`, `boto3` and `httpx` are still unpinned.

## D-030 – Credits confirmed; small UX fix found by hand-testing (2026-09-30)
- **Credits:** the developer confirmed the **$150 hackathon credit is real** (seen in the Billing console; the IAM user used for the read-only check cannot see it, D-025). The Phase 2 plan therefore does not need the free-tier fallback of D-015; the $5 budget alarm, the Budgets alerts in P2-1 and the "tell the cost before creating anything" rule (D-016) still apply. Credits do not cap spending.
- **Landing page:** the signed-out home page had no way in. It now links to the chat and the owner console.

## D-031 – AgentCore Observability is in; AgentCore Memory is out; the chat shows the agent's steps (2026-09-30)
Decided by the developer. Sources for the facts below: AWS documentation "Get started with AgentCore Observability" and "MCP protocol contract", read 2026-09-30.
- **AgentCore Memory: not used.** The assistant needs short-term memory only (the conversation), which the Strands agent already keeps for the length of a session; the lasting truth (mandates, bookings, holds, watches, tickets, approvals) lives in DynamoDB. This closes the "Could" item in the design (section 8, row 15, and the scope list). Known limit, kept: a chat session is lost on a restart, a new sign-in or "Start over".
- **AgentCore Observability: required part of the AWS path.** It is built on Amazon CloudWatch and OpenTelemetry. Facts from the docs: (1) a one-time, per-account setup, *CloudWatch Transaction Search*, sends spans to the CloudWatch Logs group `aws/spans` (about ten minutes before they can be searched; indexing 1 % of traces is free); (2) agents hosted on AgentCore Runtime are instrumented automatically; (3) an agent that runs elsewhere, like our simulator, needs the AWS Distro for OpenTelemetry (`aws-opentelemetry-distro`) and Strands' `strands-agents[otel]`, plus OpenTelemetry environment variables; (4) Gateway spans are enabled per Gateway; (5) a session id passed as OpenTelemetry baggage correlates the traces of one conversation. **Not verified yet:** prices (CloudWatch ingestion, X-Ray indexing above 1 %), whether an MCP server container on Runtime needs extra instrumentation, and the exact Gateway setting. Read the pricing page and tell the developer the cost before enabling anything (D-016).
- **What we trace:** the assistant's steps (model calls and tool calls, from Strands' own spans), the Gateway, the Runtime, and, added by us in the server, the decision of each tool call as span attributes (tool, decision, rule ids, error code, idempotent replay) and never a token or personal data. This is for troubleshooting and for one trace shown in the demo. It is **not on the cut list** of D-011 (which stays: Gateway Policy first, then Gateway and interceptor).
- **Local equivalent (built now):** the chat page shows, under each assistant answer, the tool calls behind it: name, key arguments (long tokens shortened), the server's outcome (ok, refused with the rule id, or needs approval), the suggested next step and anything the assistant said between calls. It shows what the model *did*, not its hidden reasoning (the Chat Completions path drops reasoning content, and raw reasoning is not something to put in front of a diner). The owner console's audit list remains the server's own record.

## D-032 – How the server emits traces (2026-09-30)
Built for the server part of plan task P2-9; nothing here touches AWS. Verified on the installed packages (`opentelemetry-api`/`-sdk` 1.45.0, `fastmcp` 3.4.7, `mcp` 1.30.0), see `docs/PLAN.md` section 3a.
- **One span per tool call**, `fairtable.tool <name>`, opened by `TelemetryMiddleware` (server/telemetry.py). It is added first, so it is outermost and sees the final result after `ErrorMappingMiddleware` has turned refusals into `isError` results. It never changes what the caller receives.
- **Attributes are an allow-list** (`ALLOWED` in `server/telemetry.py`): tool, caller kind (`user` / `machine`) and agent tier, restaurant id, party size, each policy layer's decision and rule ids (`pep1.*`, `pep2.*`), outcome (`ok` / `refused` / `step_up` / `error`), error code, rule id, idempotent replay, and the exception class name on a bug. A name off the list raises, so a mistake shows in tests. Never present: token, slot token, user id, username, idempotency key, hold or approval id, approval link, free text, exception messages. A test runs a whole booking with a step-up and scans every span for these.
- **Outcome vs status.** A refusal or an approval request is an ordinary result, so its span is *not* marked as an error; only a bug (an unexpected exception) sets status `ERROR`, with the class name and no message.
- **Why a context variable.** FastMCP opens its own inner span; with only our provider configured that inner span does not record, so "the current span" inside the tool is useless. `annotate` writes to the tool span kept in a context variable, which reaches the tool's worker thread.
- **Joining the caller's trace.** A Strands agent puts its trace context in the request's `_meta`. FastMCP hands it to the server on `fastmcp_context.request_context.meta` (not on the call's params, which arrive with `meta=None`); the span is parented on it, so agent, Gateway and server steps form one trace.
- **No SDK, no cost.** Without an OpenTelemetry SDK the API is a no-op. The server never configures a provider or exporter: on AWS the AWS Distro for OpenTelemetry (or Runtime's instrumentation) does (P2-9, later). Tests inject an in-memory provider with `use_tracer_provider`.

## D-033 – A standing permission can be granted on the approval page (2026-09-30)
A "Should" item (the design's "create a mandate" form), built with the developer's approval and the limits they agreed.
- **What an approval is (unchanged).** One approval covers one hold, for one user, for exactly its terms, for 15 minutes, once. It never turns into a permission by itself.
- **What is new.** When a *booking confirmation* is approved, the page can offer a tick box: "Let my assistant book at <restaurant> without asking me again, for the next <7 | 30 | 90> days", with the fixed limits printed under it. Approving with the box ticked stores a mandate in the **same transaction** as the approval and its audit entry, so a double click cannot create two, and Decline never grants anything.
- **The diner chooses two things:** the restaurant (the one being booked) and the number of days (7, 30 or 90; default 30; anything else is refused). **Fixed and always shown:** up to 4 people each time, any time of day, no cancellation fee above the restaurant's current fee (shown as "no cancellation fee" or "up to $X may apply"), only for the assistant that asked, and revocable at any time. If the restaurant raises its fee later, a new booking exceeds what was allowed and asks again.
- **Never wider than shown.** The sentence and the stored numbers come from one module (`server/domain/grant.py`); the form supplies only the number of days, everything else (restaurant, assistant, fee, party) is read on the server. A test compares what the page says with what is stored.
- **Never replaces or narrows.** The box is not offered when the diner already has a live permission at that restaurant; if one appears between showing the page and pressing Approve, the answer is recorded and the existing permission is kept. It is not offered on a cancellation-fee approval.
- **Permissions page** (`/permissions`, linked from the chat and the approval page): lists the live permissions in one line each (also the seeded ones) with a **Revoke** button (CSRF token; the record is addressed from the signed-in user, never from the form; the version goes up and `revoked_at` is stored; audited as `permissions` / `revoked`).
- **Invariant I1** now judges a booking by the permission that was live when it was made (`revoked_at`), so revoking does not make old bookings look unauthorised; a booking made after the revocation without approval is still flagged (both tested).
- **Why these limits.** A permission bounds the damage of a confused or misused assistant. Restaurant, duration, money (fee) and size are the four things that matter; the time of day does not, since the restaurant's own hours already limit it. Not built: creating a permission without a booking, editing one, per-assistant management.

## D-034 – MFA is on for the IAM user (2026-09-30)
The developer enabled MFA on the IAM user (recommended in D-025). Nothing else about the account changed: sign-in stays `aws login` (short-term credentials, no access keys), the $5 alarm `fairtable-5usd` stays, and the $150 credit is real (D-030). The Phase 2 recommendations (CDK Python with the CloudFormation AgentCore resources, Runtime as a zip, Gateway to Runtime with SigV4, Runtime V2 in us-east-1, the web pages local with Cognito USER_PASSWORD_AUTH for the demo) still wait for the developer's confirmation; once given they become D-035.
