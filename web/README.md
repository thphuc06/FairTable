# web/

FastAPI apps (deployable locally in Docker or on Lambda via Mangum).

- **Consent page** – one HTML page with Approve / Decline for step-up requests. Bound to the verified user, single use, expiring (plan task P1-11).
- **Owner console** – change the agent-share cap (rule S2) and view the audit log and policy text (plan task P1-17).

Both authenticate against the configured issuer (dev issuer locally, Cognito on AWS).
