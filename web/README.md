# web/

FastAPI pages: sign-in, the **owner console** (P1-17) and the **demo chat page** (P1-19). One sign-in covers both. There is no consent page any more: a booking is confirmed by the diner's spoken yes, typed in the chat here (docs/DECISIONS.md D-051).

Run: `python -m web` (`WEB_HOST`, `WEB_PORT` default `127.0.0.1:8080`; settings shared with the server, see `server/README.md`).

- `GET/POST /login`: signs in through the dev issuer (`devauth/`). The AWS profile would use Cognito's hosted login (scaffold only).
- `GET /owner`, `POST /owner/agent-share`: owners only (group `owners` plus a venue claim). Change the share of seats agents may book (0-100) and see the rules and recent audit; the change is audited and reaches rule S2 on the next hold.
- `GET/POST /chat`, `POST /chat/reset`: a simulated voice assistant (`simulator/`, `MODEL_PROVIDER=mock` by default) that books through the MCP server (`MCP_URL`, default `http://127.0.0.1:8000/mcp`) with the signed-in diner's own token. After a hold the assistant reads the details back and asks; the diner types yes or no. The page also shows the dev inbox (waitlist matches, Fair Drop wins). No JavaScript; the diner's token stays in server memory.
- `GET /`: signed-in diners go to `/chat`, owners to `/owner`.
- Security: HMAC-signed HttpOnly SameSite cookie, `X-Frame-Options: DENY`, strict CSP, `Cache-Control: no-store`, redirects only to `/owner` and `/chat`, every value HTML-escaped.

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

## Voice page (`/voice`, optional)
`VOICE_ENABLED=true python -m web` switches on a call page: the browser streams the microphone (16 kHz PCM) over a WebSocket (`/voice/ws`, same-origin only, signed in), the server hands it to Amazon Nova 2 Sonic through the Strands bidirectional agent and sends back the assistant's voice, the transcript and the tool calls behind it (`voice_protocol.py` lists the messages). It needs the `voice` extra and Bedrock access; the page has its own Content-Security-Policy (own scripts, microphone, same-origin socket). Run instructions with the AWS settings: the root `README.md`. Tests without a microphone or AWS: `tests/unit/web/test_voice_page.py`.
