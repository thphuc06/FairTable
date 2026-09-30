# server/

The FairTable MCP server (FastMCP 3.4.7 on `mcp` 1.30.0, spec 2025-11-25, Streamable HTTP). Entry point: `python -m server` (settings from the environment, below).

| Package | Contents | Rule |
|---|---|---|
| `tools/` | The 8 MCP tool handlers, one module per tool | Thin: parse input, call `domain/` and `kernel/`, format output. No business logic. |
| `domain/` | Pure functions: models, errors, clock, slot tokens, mandate matching, fees, token bucket, idempotency, waitlist matching, Fair Drop | No I/O. Everything time-dependent takes a `Clock`. Reusable by future Lambda workers. |
| `kernel/` | Trust Kernel: PEP-1 (G1–G4) and PEP-2 (P0, S1–S4) via `cedarpy`, and `decide()` | Priority deny > step_up > allow; no matching permit is `POLICY_DENIED`. |
| `identity/` | Token verification with `joserfc` | Same code for the dev issuer and Cognito; only issuer, JWKS URL and audience change. |
| `store/` | DynamoDB single-table access: key builders, mappers, `TransactWriteItems` | Every state change is one transaction. Never rely on DynamoDB TTL; check `expires_at` on read. |

No LLM is called from anywhere in this package.

## Running and configuration
`python -m server` serves MCP at `http://127.0.0.1:8000/mcp`. Origin/Host validation is on, unexpected error text is masked, and expected refusals come back as structured `isError` results with a `next_step` (`server/middleware.py`).

| Variable | Default | Meaning |
|---|---|---|
| `APP_PROFILE` | `local` | `aws` refuses to start with the built-in dev slot-token secret |
| `MCP_HOST`, `MCP_PORT` | `127.0.0.1`, `8000` | bind address |
| `MCP_ALLOWED_HOSTS`, `MCP_ALLOWED_ORIGINS` | empty | extra `Host` / `Origin` values (comma-separated) for hosted or compose deployments |
| `AUTH_ISSUER`, `AUTH_AUDIENCE`, `AUTH_AUDIENCE_CLAIM`, `AUTH_JWKS_URL` | dev issuer values | token verification; `AUTH_AUDIENCE_CLAIM=client_id` for Cognito-style access tokens |
| `SLOT_TOKEN_SECRET`, `SLOT_TOKEN_TTL_S` | dev value, `900` | signing secret (at least 32 bytes) and lifetime of slot tokens |
| `RATE_LIMIT_PER_HOUR` | `20` | `availability_check` calls per user per restaurant per hour |
| `TABLE_NAME`, `DDB_ENDPOINT_URL`, `AWS_REGION` | `fairtable-dev`, none, none | DynamoDB; set the endpoint for DynamoDB Local |
| `CONSENT_BASE_URL` | `http://localhost:8080` | where consent links point (`{base}/consent/{id}`) |
| `HOLD_TTL_S` | `600` | how long a hold lasts |
| `WEB_HOST`, `WEB_PORT`, `WEB_SESSION_SECRET` | `127.0.0.1`, `8080`, dev value | the consent page (`python -m web`); the `aws` profile needs a real secret |
| `POLICY_DIR` | repo `policies/` | Cedar policy files |

Tracing: `telemetry.py` turns every tool call into an OpenTelemetry span (which tool, what each policy layer decided and by which rule, ok / refused / approval needed / error) using an allow-list of attributes, so no token or personal data can be attached (D-032). It is a no-op until an OpenTelemetry SDK is configured; on AWS the Distro for OpenTelemetry does that.

Other modules: `pipeline.py` (the write pipeline all state-changing tools use), `ratelimit.py`, `config.py`, `app.py` (assembly).

## Tools and where their logic lives
| Tool | Kind | Logic |
|---|---|---|
| `restaurant_search`, `availability_check`, `mandate_status` | read | `tools/*.py` + `domain/` |
| `reservation_hold` | write | `ops/hold.py` (slot + S1 + S2 + hold in one transaction) |
| `reservation_confirm` | write | `ops/confirm.py` (mandate or approval; step-up otherwise) |
| `reservation_manage` | write | `ops/manage.py` (`view` in the tool; `modify` reduces the party; `cancel` decides the fee before writing) |
| `waitlist_watch` | write | `ops/waitlist.py` (standing watch) and `ops/fairdrop.py` (`drop_id`: one ticket per person) |
| `waitlist_status` | read + cancel | `tools/waitlist_status.py` (watch or drop ticket; the first request after a drop time runs the draw) |

Write tools go through `pipeline.run_write`. `lifecycle.py` releases expired holds lazily, `consent.py` and `tools/stepup.py` create approvals and answer with -32042 or `consent_url`, `notify.py` is the notification seam (dev inbox), `matcher.py` offers freed tables to waiting watchers (first come, first served), `dropper.py` runs a Fair Drop draw exactly once, `resources.py` serves the public policy and audit resources, `invariants.py` checks I1, I2, I3, I5 and the counters over the whole table (tests and eval graders).
