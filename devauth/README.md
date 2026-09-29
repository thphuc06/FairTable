# devauth/

Dev JWT issuer that stands in for Amazon Cognito in the local profile. **Development only**: the accounts, secrets and (optionally persisted) signing key are for local use. A compose service later (P1-23).

Run: `python -m devauth` (`DEVAUTH_HOST`, `DEVAUTH_PORT`, `DEVAUTH_ISSUER`, `DEVAUTH_AUDIENCE`, `DEVAUTH_KEY_FILE`; defaults `127.0.0.1:9000`, audience `fairtable-mcp`, ephemeral key).

| Endpoint | Purpose |
|---|---|
| `GET /.well-known/openid-configuration` | issuer metadata |
| `GET /.well-known/jwks.json` | public signing keys (`kid` set) |
| `POST /token` | `grant_type=password` (seeded diners and the owner) or `client_credentials` (machine clients); form-encoded, client secret in the form or HTTP Basic |
| `GET /healthz` | liveness |

Tokens are RS256 access tokens with `iss`, `sub`, `aud` (and `client_id`), `scope`, `iat`, `exp`, `jti`. The pre-token logic mirrors Cognito:
- **User tokens** (V2 style) get `username`, plus `agent_tier` / `agent_id` from the OAuth **client** used, and `cognito:groups` for owners.
- **Machine tokens** have no `username`; they get the agent claims only for V3-style clients (`alexa-plus-sim`). `bot-m2m` gets none (red-team RT1 and RT3).

Accounts and clients live in `accounts.py` and are listed in the top-level README. The server verifies these tokens with the same code it uses for Cognito; only issuer, JWKS URL and audience are configuration.
