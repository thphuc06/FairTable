# web/

FastAPI pages. Today: the **consent page** (task P1-11); the owner console follows (P1-17).

Run: `python -m web` (`WEB_HOST`, `WEB_PORT` default `127.0.0.1:8080`; settings shared with the server, see `server/README.md`).

- `GET /consent/{id}`: shows what the assistant asked for (a booking to confirm, or a cancellation fee) and Approve / Decline. Needs a sign-in as the user who owns the request; someone else gets 403.
- `POST /consent/{id}/decision`: records the answer once (pending to approved/declined), audited; a double click changes nothing. CSRF token bound to the user and the request; expired or no-longer-active requests answer 410.
- `GET/POST /login`: signs in through the dev issuer (`devauth/`). The AWS profile would use Cognito's hosted login (scaffold only).
- Security: HMAC-signed HttpOnly SameSite cookie, `X-Frame-Options: DENY`, strict CSP, `Cache-Control: no-store`, redirects only to `/consent/...`, every value HTML-escaped.

`app.py` routes, `pages.py` HTML, `session.py` cookie + CSRF, `auth.py` login.
