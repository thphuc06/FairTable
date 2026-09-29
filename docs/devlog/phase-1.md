# Phase 1 – local core (10-02 → 10-13), no AWS

Status: **in progress – batches A and B done 2026-09-29, B reviewed, waiting for the go-ahead for batch C** (decisions D-016 … D-019).

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
| P1-9 `reservation_hold` | C | todo | | |
| P1-10 `reservation_confirm` and step-up | C | todo | | |
| P1-11 consent page | C | todo | | |
| P1-12 `reservation_manage` | C | todo | | |
| P1-13 concurrency hardening | C | todo | | |
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
