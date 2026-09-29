# Phase 1 – local core (10-02 → 10-13), no AWS

Status: **in progress – batch A done 2026-09-29, waiting for review** (decisions in D-016 and D-017).

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
| P1-5 `devauth/` dev issuer | B | todo | | |
| P1-6 store layer and seed | B | todo | | |
| P1-7 read tools and token bucket | B | todo | | |
| P1-8 write pipeline and idempotency | B | todo | | |
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
