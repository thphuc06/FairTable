# Decisions log

Short record of decisions that shape the build. Newest last. If a decision here conflicts with `fairtable-solution-design.md`, this file wins until the design is updated. Ask before overriding either.

## D-001 – Local Docker is the primary run path (2026-09-29)
- **Decision:** A locally runnable public repo plus the demo video is enough for the Alexa+ track. Hosting is not required, and judges may build and run the project themselves.
- **Meaning of "self-hosted":** our own MCP server, as opposed to Amazon's gated Alexa+ tools that participants cannot access. It is demoed through our own web front end.
- **Source:** official FAQ and rules (clarified by the developer, 2026-09-29).
- **Consequences:**
  - Local Docker (server + DynamoDB Local + web + simulator) is first-class and must work from a fresh clone.
  - AgentCore Runtime/Gateway deployment stays in Phase 2, but **only for the AWS Builder mini challenge**. If it slips, the submission still qualifies.
  - Keep all code deployment-agnostic: no account IDs, ARNs or regions in code; everything from env/config.

## D-002 – Open Source mini challenge is out of scope (2026-09-29)
- **Decision:** We target **AWS Builder only**.
- **Why:** The Open Source challenge requires a separate, additional project or contribution (the form asks for both a contribution URL and a project repo URL), and a project can win only one mini-challenge prize.
- **Consequence:** No extra repo or upstream PR work is planned.

## D-003 – Model choice is ours; MODEL_PROVIDER is configurable; mock-first (2026-09-29)
- **Decision:** Model choice is free. The provider is selected by `MODEL_PROVIDER` (`mock` by default, `bedrock` when available, others possible). Stub Bedrock early (the FAQ itself recommends this).
- **Bedrock block:** an AWS Support matter, not an organizer one. Nothing to ask the organizers.
- **Unchanged:** the 2026-10-13 decision point on where eval numbers come from. Mock-based numbers are labelled as harness validation, not model reliability.

## D-004 – Judging window and README readiness (2026-09-29)
- **Facts:** Judging runs Nov 9–20 and may include automated AI-driven review.
- **Decisions:**
  - The README must have clear setup and run instructions that work from a fresh clone (verified in P4-4 on a clean checkout, using the Docker path).
  - Do not plan on keeping AWS resources running. Spin them up for tests and the demo, then tear them down (scripted, documented).
  - The license (Apache-2.0) stays visible in the repo's About section (already done).

## D-005 – Deadline (2026-09-29)
- **Deadline:** 2026-10-23 12:00 PDT. Submission target remains 2026-10-22; 10-23 is the spare day.

## D-006 – Organizer questions withdrawn (2026-09-29)
- The questions in design §15 are no longer to be sent; the FAQ and rules answer what we needed (see D-001, D-002). Remaining unknowns are handled by design fallbacks, not by asking.

## D-007 – The local profile is what judges run (2026-09-29)
- **Decision:** A fresh clone plus `docker compose up` starts everything with **no AWS account**:
  - the MCP server (Streamable HTTP, spec 2025-11-25);
  - DynamoDB Local;
  - the consent page and owner console (`web/`);
  - a **dev JWT issuer** (`devauth/`) standing in for Cognito, with seeded test users;
  - the simulator with `MODEL_PROVIDER=mock` as the default. A real provider is opt-in via env.
- **Test login credentials are listed in the README.** They are dev-only values seeded into the local issuer, not secrets. The secret-scan test must allow them explicitly.
- **Dev issuer scope (minimum needed for the demo and RT1/RT3/RT4):**
  - publishes a JWKS and OIDC-style metadata;
  - issues user tokens (`sub`, `username`, `agent_tier`, `agent_id`, scope `fairtable/book`) after a simple login;
  - issues M2M `client_credentials` tokens for a bot client that has **no** `username` and no `agent_tier` (this is what makes RT1 and RT3 reproducible locally);
  - mirrors the Cognito pre-token V2/V3 logic in plain Python.
- **Switching to Cognito is configuration only:** issuer URL, JWKS URL, audience. The server verifier is the same code in both profiles.

## D-008 – G1–G4 also run in cedarpy (2026-09-29)
- **Decision:** The local build enforces the **full rule set** in the server with `cedarpy`: PEP-1 rules G1–G4 (including the `has`-guard on G4) **and** PEP-2 rules P0 + S1–S4.
- **AWS profile:** AgentCore Gateway Policy (G1–G4 at the Gateway) becomes **defense in depth**, not the only place these rules live.
- **Consequences:**
  - Evaluation order in the server: PEP-1 (stateless, claims and request shape) then PEP-2 (stateful).
  - Local G1–G4 use the local Cedar schema built from the verified JWT claims. The Gateway-generated schema may differ, so the two policy sets stay separate files but share one **behavioural test suite** (same scenarios, same expected outcomes).
  - The design's fallback "move G1–G4 into cedarpy" is now the default, not a fallback.
  - RT1, RT3 and RT4 become fully local tests.

## D-009 – All submission material is in English (2026-09-29)
- **Decision:** All submission materials, including code documentation, must be in English. Everything written from now on (code, comments, docs) is English.
- **Existing Vietnamese material:** `docs/fairtable-solution-design.md`, `docs/research-alexa-plus-round3-2026-09.md` and the labels inside both `.drawio` files.
- **Plan:** before the feature freeze, write `docs/ARCHITECTURE.md` in English (authoritative from then on), relabel the diagrams in English, and move the Vietnamese documents out of the repo (see `docs/PLAN.md`, tasks P0-5, P3-6, P3-7).
- Until `ARCHITECTURE.md` exists, the Vietnamese design doc remains the source of truth for design questions.

## D-010 – MCP Tasks are optional; DynamoDB is the source of truth for waitlists (2026-09-29)
- **Facts:** FastMCP's tasks extra relies on `pydocket`, which is built for Redis; the `memory://` backend is for testing only.
- **Decision:**
  - DynamoDB is the source of truth for watches and drop entries.
  - `waitlist_status` is the **primary** path for agents.
  - MCP Tasks are an **optional view** on top, behind a config flag (default off). `memory://` is acceptable for the local demo.
  - Every feature works fully with Tasks disabled.
  - **No Redis or ElastiCache** anywhere in the plan.
- **Consequence:** the design's "Tasks fallback" date (10-16) is no longer a risk to a Must feature.

## D-011 – AWS Builder: keep Phase 2; document it; show it in the video (2026-09-29)
- **Decision:** Keep Phase 2 (AgentCore Runtime, Gateway + Policy, Cognito, DynamoDB).
- Add `docs/aws-integration.md` describing each AWS service used and how.
- The demo video must show the **AWS-deployed path at least once**.
- Qualification for the Alexa+ track does not depend on it (D-001). The AWS Builder claim does.
- Minimum demonstrable AWS path if time runs short: Runtime + Cognito + DynamoDB. Cut order for the rest: Gateway Policy first, then the Gateway and interceptor.

## D-012 – Verified facts (2026-09-29, reported by the developer)
- `mcp` 1.30.0 reports `LATEST_PROTOCOL_VERSION = 2025-11-25`.
- `fastmcp` 3.4.7 requires `mcp>=1.24,<2.0`.
- No change to the pins. Spike P0-3 no longer needs to check the protocol version.

## D-013 – Working agreement (2026-09-29)
- The developer runs `git add .` and commits. The assistant does not commit.
- Current phase: documentation and codebase organisation first. Implementation is done later on the developer's PC.

## D-014 – Policy changes D1, D2, D5 applied; step-up via middleware validated (2026-09-29)
- **D1 (applied):** S2 (`policies/s2_agent_share_of_covers.cedar`) applies to `reservation_hold` only. `waitlist_watch` is removed because a watch consumes no covers, and S2's own `next_step` is `waitlist_watch`.
- **D2 (applied):** new rule **S3b** (`policies/s3b_cancel_fee_needs_ack.cedar`, `@on_deny("step_up")`, `reservation_manage`). It fires when `context.cancel_fee_cents > 0 && !context.cancel_fee_acknowledged`. `cancel_fee_cents` is a whole number in minor currency units and is `0` for view, modify and fee-free cancels. The PEP-2 set is now P0 + S1–S4 + S3b.
- **D5 (confirmed):** two policy sets (server and Gateway) share one behavioural test suite.
- **Step-up transport:** FastMCP 3.4.7 wraps exceptions raised in a tool into `ToolError`, so `UrlElicitationRequiredError` never reaches the client. The server adds an `on_call_tool` middleware that re-raises the original error, giving a JSON-RPC **-32042** error. Checked against the MCP spec 2025-11-25 (elicitation, "URL Elicitation Required Error") and FastMCP's own `ErrorHandlingMiddleware`, which uses the same pattern (inspects `__cause__`, raises `McpError` from middleware). Rules taken from the spec for the consent URL: no sensitive data in the URL, not pre-authenticated, HTTPS outside dev, and the consent page must verify that the user opening it is the user who started the request (same `sub`). Open point for P1-10: the spec says a server must not send elicitation modes the client did not declare, so check the client's `elicitation.url` capability and fall back to an `isError` result with the consent link and `next_step` if it is missing.

## D-015 – Consequences of the full rules text (2026-09-29)
Source: the official rules and event page, distilled in `docs/hackathon-rules.md`.
- **Availability until 2026-11-20:** the project must stay available free of charge to judges until the judging period ends; judges are not required to test it. Availability means the public repo plus the video (D-001, D-004 still hold: no AWS resources are kept running).
- **No changes after the deadline:** the submission cannot be altered once the submission period ends. Tag the submitted commit (`submission`) and push no functional changes until 11-20.
- **Fresh clone must keep working:** pin exact Python dependency versions (lock file) and a fixed DynamoDB Local image tag before the freeze (P1-23, P3-8). Today `joserfc`, `pydantic`, `boto3` are unpinned and the compose spike uses `amazon/dynamodb-local:latest`.
- **Friction log is a form field:** entries are pasted into the submission form; Amazon scores them in Stage 1 (bonus up to 10%). Product feedback needs five answers per tool (used for, worked well, needs work, onboarding, build again).
- **AWS credits:** requested (no reply yet, 2026-09-29). If nothing has arrived by 10-14, Phase 2 runs on the free tier with AWS Budgets alerts and only the minimum demonstrable path (Runtime + Cognito + DynamoDB, see D-011); Bedrock stays optional.
- **Help channels:** the Resources page lists live office hours and a Developer Community forum. Whether Alexa+ supports URL-mode elicitation is unanswered by the docs (D-014); asking there is the developer's call (D-006 withdrew the earlier organizer questions).
- **Simulator path:** the rules allow a simulated Alexa+ experience as an alternative to the MCP server; we do both, so the simulator's source stays in the repo and is shown in the video.
- **Open item:** MCP Apps is named as a creative Alexa+ signal. It stays a "Should", not scheduled; ask before starting.

