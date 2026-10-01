# web/

FastAPI pages. The **consent page** (P1-11), the **owner console** (P1-17) and the **demo chat page** (P1-19). One sign-in covers all three.

Run: `python -m web` (`WEB_HOST`, `WEB_PORT` default `127.0.0.1:8080`; settings shared with the server, see `server/README.md`).

- `GET /consent/{id}`: shows what the assistant asked for (a booking to confirm, or a cancellation fee) and Approve / Decline. Needs a sign-in as the user who owns the request; someone else gets 403.
- `POST /consent/{id}/decision`: records the answer once (pending to approved/declined), audited; a double click changes nothing. CSRF token bound to the user and the request; expired or no-longer-active requests answer 410.
- `GET/POST /login`: signs in through the dev issuer (`devauth/`). The AWS profile would use Cognito's hosted login (scaffold only).
- `GET /owner`, `POST /owner/agent-share`: owners only (group `owners` plus a venue claim). Change the share of seats agents may book (0-100) and see the rules and recent audit; the change is audited and reaches rule S2 on the next hold.
- `GET/POST /chat`, `POST /chat/reset`: a simulated voice assistant (`simulator/`, `MODEL_PROVIDER=mock` by default) that books through the MCP server (`MCP_URL`, default `http://127.0.0.1:8000/mcp`) with the signed-in diner's own token. When approval is needed it shows the consent link (only links to our own consent page become anchors) and the dev inbox. No JavaScript; the diner's token stays in server memory.
- `GET /`: signed-in diners go to `/chat`, owners to `/owner`.
- Security: HMAC-signed HttpOnly SameSite cookie, `X-Frame-Options: DENY`, strict CSP, `Cache-Control: no-store`, redirects only to `/consent/...`, `/owner` and `/chat`, every value HTML-escaped.

`app.py` routes, `pages.py` HTML, `session.py` cookie + CSRF, `auth.py` login, `chat.py` one assistant per signed-in diner.

## Signing in through Cognito and chatting through the AgentCore Gateway (AWS profile)

```bash
AUTH_PROVIDER=cognito COGNITO_CLIENT_ID=<app client alexa-plus-sim> COGNITO_CLIENT_SECRET=<its secret> \
AUTH_ISSUER=<pool issuer> AUTH_AUDIENCE=<client ids, comma separated> AUTH_AUDIENCE_CLAIM=client_id AUTH_TOKEN_USE=access \
MCP_URL=<gateway url> MCP_VIA_GATEWAY=true TABLE_NAME=fairtable AWS_REGION=us-east-1 python -m web
```

The pages sign people in with Cognito's `InitiateAuth` (no AWS credentials needed for that) and read the real table
(needs credentials). With `MCP_VIA_GATEWAY=true` the assistant sends the bearer token to the Gateway, whose interceptor
hands it to the server in `x-ft-user-token`; tool names carry the Gateway's `ft___` prefix, which the steps list hides.
The client secret is read from the environment only. See `docs/DECISIONS.md` D-047.
