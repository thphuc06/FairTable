# FairTable – project context for Claude Code

## What this project is
- Entry for the Amazon Developer Hackathon "Build, Ship, Shape" – **Alexa+ track** (+ AWS Builder mini challenge).
- Deadline: **2026-10-23 12:00 PT**. Solo developer. Language: **Python 3.12**.
- FairTable is a **self-hosted MCP server (spec 2025-11-25, Streamable HTTP)** that gives independent restaurants a trusted "front door" for AI booking agents (Alexa+ first): verified identity, owner-set rules, step-up consent, standing waitlists, and a fair lottery for hot tables.

## Source of truth (read in this order)
1. `docs/fairtable-solution-design.md` (v2) – **authoritative design**. If code and design disagree, ask me.
2. `docs/hackathon-rules.md` – submission requirements.
3. `docs/*.drawio` – diagrams (XML). The design doc already contains Mermaid equivalents; open these only if needed.
4. `docs/research-alexa-plus-round3-2026-09.md` – background/evidence only. Do not implement from it.

## Hard requirements (hackathon rules)
- MCP server on spec **2025-11-25** with **Streamable HTTP**; the repo must actually import and run it (not just mention it).
- Public repo, Apache-2.0 license, README with run instructions and the list of AWS services used.
- Demo video (< 3 min) shows the server working.

## Architecture decisions – do not change without asking
- **No LLM inside MCP tools.** Tools are deterministic. LLMs appear only in the simulator, the eval harness, and (later) owner rule extraction.
- **8 tools:** `restaurant_search`, `availability_check`, `mandate_status`, `reservation_hold`, `reservation_confirm`, `reservation_manage`, `waitlist_watch`, `waitlist_status`.
- **Two policy enforcement points, same language (Cedar):**
  - PEP-2 (build first): `cedarpy` inside the server, policies P0 + S1–S4 in `policies/*.cedar` (see design §6.2). Map cedarpy's `policyN` reasons to the `@id` / `@on_deny` annotations via `policies_to_json_str`. Priority: deny > step_up > allow; no matching permit → POLICY_DENIED.
  - PEP-1 (later): AgentCore Gateway Policy G1–G4. G4 must use a `has`-guard.
- **Writes:** one DynamoDB `TransactWriteItems` per state change (slot, counters, hold, idempotency record, audit). DB conditions are the final guarantee under concurrency.
- **Idempotency:** key = (user sub, idempotency_key). Same params → return stored result; different params → `IDEMPOTENCY_CONFLICT`. Store only when state actually changed.
- **Never rely on DynamoDB TTL for business logic.** Always check `expires_at` on read.
- **MVP uses lazy evaluation – no background workers yet:**
  - expired holds are treated as released when read;
  - waitlist matching runs inside the cancel / hold-expiry code paths;
  - Fair Drop allocation is triggered by the first request after the drop time.
  - Keep this logic in pure functions so Lambdas (sweeper, allocator, watch matcher) can reuse it later.
- **Step-up consent:** JSON-RPC error **-32042** (URLElicitationRequiredError) with a consent URL.
- **Tool outputs:** structured errors (`isError: true`) with `next_step`; every successful output includes a short `spoken_summary`.
- **Identity:**
  - MVP/local: pass a test user identity (signed test JWT or header) so every write knows the user `sub`.
  - Later: Cognito + Gateway REQUEST interceptor copies the user token to `x-ft-user-token` (the interceptor must strip any client-supplied value), and the server re-verifies it with `joserfc`.
- **Minimal scope for supporting apps:** simulator = one Strands agent + a simple chat page; owner data seeded by a Python script first; consent page = one HTML page with Approve / Decline.

## Pinned versions
`fastmcp==3.4.7`, `mcp==1.30.0` (do **not** upgrade to 2.x), `strands-agents==1.57.1`, `cedarpy==4.12.1`, plus `joserfc`, `mangum`, `boto3`, `pydantic`, `pytest`.

## Environment constraints
- **Amazon Bedrock is currently blocked on my AWS account** (support case pending). Build and test everything **locally first**:
  - DynamoDB Local (Docker) or `moto`;
  - MCP Inspector for manual testing;
  - a mock LLM for the simulator.
- **Nothing account-specific in code:** no hard-coded account IDs, ARNs, or regions. Read from env/config (`AWS_PROFILE`, `AWS_REGION`, `TABLE_NAME`, …). Target region later: `us-east-1`.
- **Never commit secrets** (`.env`, keys, tokens). The repo is public.

## Working style
- Before using any FastMCP / AgentCore / Strands / cedarpy API, **verify it against the installed package source or official docs** – do not guess signatures. Items marked ❓ in the design doc must be verified before building on them.
- Work in small steps; every step comes with pytest tests. Keep MCP tool handlers thin; business logic lives in pure, testable functions.
- Scope priority: **Must > Should > Could** (design doc §11). Ask before starting any Could item.
- Keep a friction log (`docs/friction-log.md`) of problems hit with AWS / MCP tooling – it counts for judging.

## Target repo layout
```
server/      FastMCP server, 8 tools, Trust Kernel (cedarpy)
policies/    *.cedar (P0, S1–S4)
workers/     (later) Lambda sweeper, allocator, watch matcher
web/         FastAPI: consent page + owner console
simulator/   Alexa+ simulator (Strands)
eval/        task YAML, harness, pass^k reports
infra/       CDK / agentcore config
scripts/     seed data, local setup
docs/        design, rules, diagrams, research, friction log
```
