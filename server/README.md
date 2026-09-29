# server/

The FairTable MCP server (FastMCP 3.4.7 on `mcp` 1.30.0, spec 2025-11-25, Streamable HTTP). Entry point: `python -m server` (planned).

| Package | Contents | Rule |
|---|---|---|
| `tools/` | The 8 MCP tool handlers, one module per tool | Thin: parse input, call `domain/` and `kernel/`, format output. No business logic. |
| `domain/` | Pure functions: models, errors, clock, slot tokens, mandate matching, fees, token bucket, idempotency, waitlist matching, Fair Drop | No I/O. Everything time-dependent takes a `Clock`. Reusable by future Lambda workers. |
| `kernel/` | Trust Kernel: PEP-1 (G1–G4) and PEP-2 (P0, S1–S4) via `cedarpy`, and `decide()` | Priority deny > step_up > allow; no matching permit is `POLICY_DENIED`. |
| `identity/` | Token verification with `joserfc` | Same code for the dev issuer and Cognito; only issuer, JWKS URL and audience change. |
| `store/` | DynamoDB single-table access: key builders, mappers, `TransactWriteItems` | Every state change is one transaction. Never rely on DynamoDB TTL; check `expires_at` on read. |

No LLM is called from anywhere in this package.
