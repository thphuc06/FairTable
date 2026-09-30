# Phase 2 – AWS Builder path (10-14 → 10-17, started early 2026-09-30)

Status: **started 2026-09-30; P2-1 done (table `fairtable`, budget `fairtable-150usd`, CDK bootstrap exist on the account)** (decisions D-016, D-030, D-031, D-034, D-035)

## Plan
Goal: run the same server on AWS (DynamoDB, Cognito, AgentCore Runtime, Gateway, Policy, Observability) so the demo shows the AWS path once, then tear everything down. Task list and acceptance criteria: `docs/PLAN.md` §3, Phase 2. Choices: D-035.

Rules for this phase: wire only the part the developer names ("wire X"); before creating anything state what it is, its cost from the official pricing page and how it is removed, then wait for a yes; CDK, tag `project=fairtable`, least privilege, scripted teardown run after every test or demo; read-only checks first.

| Batch | Tasks | In plain words |
|---|---|---|
| A – first contact | P2-1, P2-2, P2-3 | DynamoDB + Cognito + Runtime; on the way, settle the "not verifiable without the account" list (D-035) |
| B – Gateway | P2-4, P2-5, P2-6, P2-7 | verifier on Cognito, Gateway identity, Gateway Policy, `-32042` through the Gateway |
| C – observability and teardown | P2-9, P2-8 | traces on AWS, deploy/destroy scripts, `aws-integration.md` |

Read-only account check at the start, 2026-09-30 (us-east-1): budgets `My Zero-Spend Budget` ($1) and `fairtable-5usd` ($5) exist; no DynamoDB table; no CloudFormation stack. P2-1 must not recreate the $5 alarm; the planned $50/$100/$140 alerts are additional and need the developer's yes.

## Progress
| Task | Batch | Status | Date | Note |
|---|---|---|---|---|
| P2-1 CDK: DynamoDB + Budgets | A | done | 2026-09-30 | table and budget deployed; 44/44 store tests pass on the real table; TEMPORARILY_BUSY found and fixed |
| P2-2 Cognito + pre-token | A | todo | | |
| P2-3 Server on Runtime | A | todo | | local package already proven on arm64 |
| P2-4 Verifier with Cognito JWKS | B | todo | | |
| P2-5 Gateway + interceptor | B | todo | | |
| P2-6 Gateway Policy G1-G4 | B | todo | | |
| P2-7 -32042 through the Gateway | B | todo | | |
| P2-9 Observability (AWS part) | C | todo | | server part done (D-032) |
| P2-8 Teardown + aws-integration.md | C | todo | | |

## Entries (newest first)

### 2026-09-30 · P2-1 · [aws] [store] · CDK app, real DynamoDB table and budget; conflict handling fixed
- **Goal:** run the store on the real service and find what DynamoDB Local hides.
- **Done:** `infra/cdk/` (Python CDK, pinned; two stacks); `cdk bootstrap` (tag `project=fairtable`); deployed `FairTableData` (table `fairtable`, on-demand, GSI1/GSI2, AWS-owned key, destroyed with the stack) and `FairTableBudget` (`fairtable-150usd`, alerts at $50/$100/$140 of actual spend, credits excluded, email from `BUDGET_EMAIL`). The store tests were re-run against the real service by changing the environment only. A race of 20 writers exposed `StoreBusy` (16 of 600 requests) that nothing handled: `Store.transact` now makes 8 attempts with full-jitter backoff and the tools answer `TEMPORARILY_BUSY` (0 of 600 afterwards). `batch_put` is parallel (seed 35 s to 9.5 s). Test helpers: `FT_TEST_SHARED_TABLE=1` (one table per run), `scripts/aws_credential_process.py` (credentials without `awscrt`).
- **Files:** `infra/cdk/*`, `server/{store/repository.py,domain/errors.py,middleware.py}`, `tests/{conftest.py,integration/test_store_ddb.py,unit/store/test_transact_retry.py,unit/test_busy_error.py,unit/infra/test_cdk_table.py}`, `scripts/aws_credential_process.py`, `docs/{DECISIONS,PLAN,friction-log,aws-integration}.md`.
- **Tests:** whole local suite 840 passed, 5 skipped (Docker smoke, by design), 14:35; `ruff` clean. On the real table (shared-table mode): 44 of 44 tests of `test_store_ddb`, `test_write_pipeline`, `test_reservation_hold` pass (the seed-script test after raising its timeout); `test_ddb_spike.py` is Local-only and not run on AWS. Race script: 30 rounds x 20 writers, exactly one winner every round. New: CDK parity tests (table keys and indexes equal `server/store/table.py`, tags, removal policy, budget thresholds and credit handling, no account id in the app), retry/jitter and `batch_put` unit tests, `TEMPORARILY_BUSY` mapping.
- **Decisions:** D-036 (conflicts, error code, CDK layout, budget, credentials), D-037 (test mode, network finding).
- **Surprises / friction:** `aws login` credentials need `awscrt`, blocked by Windows App Control; `IncludeCredit` default in Budgets; `TransactionConflict` only on the real service; every SDK call takes about 1 s from this PC (friction log). Budget email confirmation is sent by AWS to the subscriber; not verifiable through the API here.
- **Follow-ups:** decide how the local web pages reach DynamoDB at about 1 s per call (D-037) before P2-3; P2-2 (Cognito) and P2-3 (Runtime) must also settle the "not verifiable without the account" list (D-035); the `CDKToolkit` stack stays until the end of the phase, remove it in P2-8.

### 2026-09-30 · Phase 2 start · [aws] [docs] · D-035 recorded, read-only account check
- **Goal:** open Phase 2 with the developer's choices on record and a known starting state.
- **Done:** D-035 written; this file created; read-only check of budgets, DynamoDB tables and CloudFormation stacks; fixed a ruff E731 in `tests/unit/simulator/test_model.py` (left over from Phase 1).
- **Files:** `docs/DECISIONS.md`, `docs/devlog/phase-2.md`, `tests/unit/simulator/test_model.py`.
- **Tests:** whole suite 829 passed, 5 skipped (Docker smoke, by design) in 12:34; ruff clean.
- **Decisions:** D-035.
- **Surprises / friction:** the first suite run failed at import (`No module named boto3`) because it was started outside the `fairtable` conda env; use `conda run -n fairtable`.
- **Follow-ups:** P2-1 started after the suite showed 829 passed; first resource waits for "wire X".
