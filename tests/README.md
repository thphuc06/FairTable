# tests/

| Directory | Needs | Marker |
|---|---|---|
| `unit/` | Nothing (pure functions, fake clock) | – |
| `integration/` | DynamoDB Local for most; the full compose stack for smoke tests | `ddb`, `docker` |
| `redteam/` | DynamoDB Local; one deterministic test per RT1–RT12 | `ddb` |
| `aws/` | Real AWS resources, opt-in | `aws` |

Every task in `docs/PLAN.md` names the tests that prove it. Tests never sleep: time is injected through a `Clock`.
