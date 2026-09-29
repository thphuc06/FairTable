# Phase 1 – local core (10-02 → 10-13), no AWS

Status: **in progress – batches A, B and C done 2026-09-29, waiting for review of C** (decisions D-016 … D-021) (decisions D-016 … D-019).

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
| P1-14 waitlist on DynamoDB | D | todo | | |
| P1-15 Fair Drop core | D | todo | | |
| P1-16 Fair Drop integration | D | todo | | |
| P1-17 owner console | E | todo | | |
| P1-18 simulator core | E | todo | | |
| P1-19 chat page and login | E | todo | | |
| P1-20 eval harness v0 | E | todo | | |
| P1-21 A0 / A1 / A2 configs | E | todo | | |
| P1-22 red-team suite | E | todo | | |
| P1-23 Docker profile | F | todo | | |
| P1-24 README and wrap-up | F | todo | | |

## Entries (newest first)

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
