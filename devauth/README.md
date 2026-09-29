# devauth/

Dev JWT issuer that stands in for Amazon Cognito in the local Docker profile. A compose service (planned, tasks P1-5 and P1-23).

Responsibilities:
- publish a JWKS and OIDC-style metadata;
- log seeded users in and issue user tokens with `sub`, `username`, `agent_tier`, `agent_id` and scope `fairtable/book`;
- issue `client_credentials` tokens for the machine clients: `alexa-plus-sim` (verified agent) and `bot-m2m` (no `username`, no `agent_tier`, used by the red-team tests);
- mirror the Cognito pre-token V2/V3 claim logic in plain Python.

The server verifies these tokens with the same code it uses for Cognito; only issuer, JWKS URL and audience are configuration.

**Development only.** Signing keys are generated at startup and are git-ignored. Seeded test credentials are listed in the top-level README.
