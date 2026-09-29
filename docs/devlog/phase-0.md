# Phase 0 – docs, spikes and bootstrap (09-29 → 10-01)

Status: **done, Gate 0 passed (2026-09-29).**

## Plan
Goal: prove that the pinned stack can do what the design needs before building on it.
Tasks (details in `docs/PLAN.md` §3, Phase 0): P0-1 environment, P0-2 Cedar spike, P0-3 FastMCP spike, P0-4 DynamoDB Local spike. P0-5 (`ARCHITECTURE.md` in English) is planned separately and is still open.
Gate 0: spikes pass or have a documented workaround; -32042 can be raised through FastMCP (Must).

## Progress
| Task | Status | Date | Note |
|---|---|---|---|
| P0-0 docs and skeleton | done | 2026-09-29 | before the coding sessions |
| P0-1 environment | done | 2026-09-29 | conda env `fairtable`, Python 3.12.14 |
| P0-2 Cedar spike | done | 2026-09-29 | + D1/D2 applied |
| P0-3 FastMCP spike | done | 2026-09-29 | -32042 needs a middleware |
| P0-4 DynamoDB Local spike | done | 2026-09-29 | |
| P0-5 ARCHITECTURE.md (English) | todo | – | open; needed before the feature freeze |

## Entries (newest first)
### 2026-09-29 · P0-3 (follow-up) · [docs] [booking-tools] · Streamable HTTP spec checked against FastMCP
- **Goal:** compare the two links from the Resources page with the design and the installed FastMCP.
- **Done:** the transport spec matches the design. One gap found and tested: FastMCP does not validate `Origin` by default (spec MUST); enabling `host_origin_protection=True` gives 403 for a hostile Origin and still accepts clients that send no Origin. The other link turned out to be the MCP Apps documentation.
- **Files:** `tests/integration/test_fastmcp_spike.py` (+3 tests), `docs/PLAN.md` §3a, `docs/friction-log.md`, `docs/hackathon-rules.md`, `docs/devlog/phase-1.md`.
- **Tests:** 51 passed, 5 skipped (DynamoDB tests; Docker was off).
- **Decisions:** none new; the bootstrap defaults are listed in `phase-1.md`.
- **Surprises / friction:** insecure default in FastMCP (friction log).
- **Follow-ups:** apply the bootstrap defaults when the server entry is created; MCP Apps stays a "Should".

### 2026-09-29 · P0-0 (follow-up) · [docs] · Full rules text distilled into the rules digest
- **Goal:** stop depending on the large raw rule text by folding what matters into the repo docs.
- **Done:** `docs/hackathon-rules.md` rewritten as a complete digest (dates, submission fields, testing clause, no-change-after-deadline, judging stages, prizes, credits). New decision D-015. PLAN tasks updated: pin image tag (P1-23), lock file (P3-8), feedback and friction-log form entry (P4-3), submission tag (P4-5), credits reminder (Phase 2).
- **Files:** `docs/hackathon-rules.md`, `docs/DECISIONS.md`, `docs/PLAN.md`, `CLAUDE.md`.
- **Tests:** not applicable (docs only).
- **Decisions:** D-015.
- **Surprises / friction:** `hackathonresource.txt` was first empty; captured afterwards. It has no Alexa+ SDK or sample code (consistent with the FAQ) and lists office hours and a forum as help channels. The rules text confirms nothing contradicts the existing docs; two gaps found (unpinned dependencies / floating image tag, and the no-change-after-deadline rule).
- **Follow-ups:** credits requested, awaiting reply; decide whether to keep the raw `.txt` files in the repo (recommended: move them out).

### 2026-09-29 · P0-2 (follow-up) · [trust-kernel] · Policy decisions D1, D2 applied; step-up transport checked
- **Goal:** apply the approved policy edits and confirm that the -32042 workaround is legitimate.
- **Done:** S2 now applies to `reservation_hold` only (D1). New rule S3b: cancelling with a fee needs step-up (D2). The middleware approach for -32042 was checked against MCP spec 2025-11-25 and FastMCP's own `ErrorHandlingMiddleware`.
- **Files:** `policies/s2_agent_share_of_covers.cedar`, `policies/s3_confirm_needs_mandate.cedar`, `policies/s3b_cancel_fee_needs_ack.cedar` (new), `policies/README.md`, `tests/unit/test_cedar_spike.py`, `docs/DECISIONS.md` (D-014), `docs/PLAN.md`.
- **Tests:** 53 passed (all suites, DynamoDB Local up).
- **Decisions:** D-014. Context fields for S3b are `cancel_fee_cents` (whole minor units) and `cancel_fee_acknowledged`.
- **Surprises / friction:** none new.
- **Follow-ups:** P1-10 must check the client's URL-elicitation capability and have a fallback (open question, see `DECISIONS.md` D-014).

### 2026-09-29 · P0-1 … P0-4 · [docs] [trust-kernel] [store] · Environment and technology spikes
- **Goal:** prove that the pinned stack can do what the design needs before building on it.
- **Done:** Python 3.12 env with all pins. Cedar reproduces the design scenarios. FastMCP returns structured errors, reads the `x-ft-user-token` header, keeps sessions, runs optional tasks (`pydocket`, `memory://`). Step-up (-32042) works only through a small middleware. DynamoDB Local cancels a 5-item transaction atomically, names the failing item, and gives exactly one winner in a 20-thread race.
- **Files:** `tests/unit/test_cedar_spike.py`, `tests/integration/test_fastmcp_spike.py`, `tests/integration/test_ddb_spike.py`, `infra/local/docker-compose.yml`, `pyproject.toml` (`tasks` extra), `docs/PLAN.md` §3a, `docs/friction-log.md`.
- **Tests:** 47 passed at the time.
- **Decisions:** middleware is the step-up transport (D-014).
- **Surprises / friction:** FastMCP swallows `UrlElicitationRequiredError`; Inspector CLI hangs on -32042; the prompt's "prepared env" did not exist on this PC. All in `friction-log.md`.
- **Follow-ups:** production middleware in P1-10.
