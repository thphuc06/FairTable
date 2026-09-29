# Phase 1 – local core (10-02 → 10-13), no AWS

Status: **not started.** Waiting for the go-ahead after the Phase 0 review.

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
| P1-1 domain models, errors, clock, slot_token | A | todo | | |
| P1-2 Trust Kernel PEP-2 | A | todo | | |
| P1-3 Trust Kernel PEP-1 (G1–G4) | A | todo | | |
| P1-4 identity verifier | A | todo | | |
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
_None yet._
