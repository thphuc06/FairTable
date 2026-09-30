# tests/

| Directory | Needs | Marker |
|---|---|---|
| `unit/` | Nothing (pure functions, fake clock) | – |
| `integration/` | DynamoDB Local for most; `test_compose_smoke.py` builds and drives the full compose stack (skipped unless `-m docker`) | `ddb`, `docker` |
| `redteam/` | DynamoDB Local; RT1–RT12 as scenarios under A0, A1 and A2 (`eval/redteam.py`), plus the concurrency tests | `ddb` |
| `aws/` | Real AWS resources, opt-in | `aws` |

Every task in `docs/PLAN.md` names the tests that prove it. Tests never sleep: time is injected through a `Clock`.
