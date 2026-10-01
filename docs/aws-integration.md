# AWS integration

Which AWS services FairTable uses, why, and how. This document feeds the AWS Builder product feedback and the README service list.

**Status legend:** _planned_ = designed, not built · _built_ = implemented · _verified_ = exercised against a real account.
Status as of 2026-09-30: the local profile calls no AWS service; the DynamoDB table exists on the account (P2-1), everything else is **planned**. Interfaces and configuration exist for some (a KMS seed provider and an SNS notifier are written against fake clients only, D-016).

**Principles**
- The **local Docker profile needs no AWS account** (see `docs/DECISIONS.md` D-001, D-007). The AWS profile is the same server code with different configuration.
- Nothing account-specific lives in code: account IDs, ARNs and regions come from environment or config (`AWS_PROFILE`, `AWS_REGION`, `TABLE_NAME`, …). Target region: `us-east-1`.
- AWS resources are created for tests and the demo, then torn down with a scripted, documented command (`docs/DECISIONS.md` D-004).
- The demo video shows the AWS-deployed path at least once (D-011).

## Services

| Service | Role in FairTable | How we use it | Local equivalent | Status |
|---|---|---|---|---|
| **Amazon Bedrock AgentCore Runtime** | Hosts the MCP server (Streamable HTTP) | The same server code as the local profile, as a zip (direct code deployment, no Docker) on Runtime V2; IAM (SigV4) callers only; the diner's token travels in the allowlisted header `x-ft-user-token` | `docker compose` server container | **verified** (second account; D-045) |
| **Amazon Bedrock AgentCore Gateway** | Front door for agents: JWT check, request interceptor, Policy | `CUSTOM_JWT` authorizer with Cognito JWKS; MCP target pointing at the Runtime; REQUEST interceptor copies the verified user token to `x-ft-user-token` and strips any client-supplied value | Server verifies the token itself; no gateway | planned |
| **AgentCore Gateway Policy** | Defense in depth for G1–G4 (stateless rules) | Cedar policies G1–G4 at the Gateway; the same rules also run inside the server with `cedarpy` | `policies/g*.cedar` evaluated in the server | planned |
| **AgentCore Identity** | Outbound OAuth from Gateway to the Runtime target | Gateway calls the Runtime with its own OAuth credentials | – | planned |
| **Amazon Cognito** (Essentials tier) | User pool, sign-in (`USER_PASSWORD_AUTH`, demo only), machine tokens (client credentials), token claims | One pre-token-generation trigger, version **V3_0** (user and machine tokens), adds `agent_tier`, `agent_id`, the scope `fairtable/book` and `custom:venue_id`; three app clients named like the dev issuer's | `devauth/` dev JWT issuer | built (CDK stack and tests), not deployed |
| **AWS Lambda** | Pre-token trigger; Gateway interceptor; optional workers later | Small Python functions; workers reuse the same pure functions as the lazy in-server paths. The pre-token function (`infra/cognito/pre_token`) is built and unit-tested | Same logic runs in-process | pre-token function built (not deployed); rest planned |
| **Amazon DynamoDB** | Single-table store: slots, holds, reservations, mandates, counters, idempotency records, audit, waitlists, drops | `TransactWriteItems` for every state change; conditions are the final concurrency guarantee. No reliance on TTL for business logic | DynamoDB Local | **table deployed by CDK (2026-09-30); store tests verified on the real service** |
| **AgentCore Observability** (on **Amazon CloudWatch**, OpenTelemetry) | Trace every step of a booking to troubleshoot and to show in the demo (D-031) | One-time CloudWatch *Transaction Search* (spans go to the `aws/spans` log group); Strands agent instrumented with ADOT and `strands-agents[otel]` (our simulator runs outside Runtime); Gateway and Runtime spans; session id as OpenTelemetry baggage; the server adds the policy decision of each call (tool, decision, rule ids, error code) as span attributes, never tokens or personal data | The chat page's *steps* list and the owner console's audit list | planned (required; prices to verify before enabling) |
| **AWS Budgets** | Cost alerts at $50 / $100 / $140 | Created by the CDK app; credits excluded (`IncludeCredit` defaults to true and would silence the alerts) | – | built (waiting for the alert address to deploy) |
| **AWS CDK (Python) / CloudFormation** | Infrastructure as code | Table, Cognito, Lambdas, Budgets; AgentCore resources via the `agentcore` CLI or CDK as supported | – | planned |
| **Amazon Bedrock (models)** | Optional real model for the simulator and eval | `MODEL_PROVIDER=bedrock`; currently **blocked on the account** (AWS Support case), so mock is the default | `MODEL_PROVIDER=mock` | blocked |

Not planned for the MVP: EventBridge Scheduler, KMS (seed comes from a local provider), API Gateway, S3, ElastiCache/Redis, AgentCore Evaluations, Nova Act, Nova Sonic. These are Should/Could items and need approval before starting.

**AgentCore Memory: decided out (D-031).** Short-term memory (the conversation, kept by the Strands agent) is enough for this use; durable state lives in DynamoDB.

## Per-service notes (answers for the product feedback, five per service)

**Amazon DynamoDB** (verified on the real service)
- *Used for:* the single table of the whole system: slots, holds, reservations, mandates, counters, idempotency records, audit, waitlists, drops; every state change is one `TransactWriteItems`.
- *Worked well:* conditions inside transactions gave exactly one winner in 30 of 30 rounds of 20 simultaneous writers; on-demand pricing makes an idle demo cost nothing; the table, its two indexes and the tags came up from CDK in under a minute.
- *Needs work:* `TransactionConflict` only appears on the real service (DynamoDB Local serialises transactions), and the SDKs do not retry a cancelled transaction, so the retry policy has to be written and tested against the real service (D-036). Creating and deleting a table with two indexes takes 25 to 45 s each, which makes per-test tables about a hundred times slower than on Local.
- *Onboarding:* clear; the condition-expression and reserved-word traps cost a few failed runs (friction log).
- *Build again:* yes.

**Amazon Cognito** (Essentials; verified on the real service)
- *Used for:* sign-in (`USER_PASSWORD_AUTH`, demo only), machine tokens (client credentials), and the claims the server's rules read, added by one pre token generation trigger (V3_0).
- *Worked well:* the claims a trigger can add matched what the design needed; real tokens passed the server's verifier with only configuration changes; Essentials with 10,000 free monthly users costs nothing for a demo.
- *Needs work:* password sign-in tokens carry only `aws.cognito.signin.user.admin` (a trigger has to add the scope and should remove that one); a function cannot be wired to an app client id without a dependency cycle; CDK leaves `ExplicitAuthFlows` out for a machine client and Cognito then turns on its defaults.
- *Onboarding:* the trigger page is thorough; the table of claims a trigger cannot change is the most useful part.
- *Build again:* yes.

**AWS Lambda** (the pre token trigger)
- *Used for:* one 128 MB arm64 Python function called by Cognito before each token is signed.
- *Worked well:* pure function plus a cached client-name lookup; free at this volume.
- *Needs work:* nothing specific.
- *Onboarding / build again:* straightforward / yes.

**AWS Budgets** (verified)
- *Used for:* one monthly budget with actual-spend alerts (credits excluded): $150 with alerts at $50, $100 and $140 on the first account; $5 with alerts at $1, $3 and $4.5 on the second.
- *Worked well:* free for cost budgets without actions; created from CDK.
- *Needs work:* `IncludeCredit` defaults to true, which silences the alerts while a credit lasts.
- *Build again:* yes.

**AWS CDK (Python) and CloudFormation** (verified)
- *Used for:* all infrastructure; a scripted `up` and `down`.
- *Worked well:* `cdk diff` before every deploy; stacks deployed in 1 to 2 minutes; rollback of a failed Runtime creation left nothing behind.
- *Needs work:* the L1 class of the Runtime lacked `PlatformVersion`; a Node stack trace on every command on Windows (harmless); `aws login` credentials need `awscrt`, which may be blocked on locked-down PCs.
- *Build again:* yes.

**Amazon Bedrock AgentCore Runtime** (verified, second account)
- *Used for:* hosting the MCP server (FastMCP, stateless Streamable HTTP) from a zip, Runtime V2, IAM callers only, the diner's token in the allowlisted header `x-ft-user-token`.
- *Worked well:* direct code deployment (38.5 MB zip with arm64 wheels, no Docker, no ECR); the execution role from the documentation was enough; header allowlist, V2 and stateless mode behaved as documented; a full booking with DynamoDB transactions ran from the zip.
- *Needs work:* the Host header the proxy forwards (`<uuid>.lambda-microvm.<region>.on.aws`) is not documented and an MCP server with Host validation fails every call with a 421 whose cause the log does not show; every environment change takes about 4.4 minutes; the L1 CDK class lacks `PlatformVersion`; on a new account the Runtime quotas can be 0 with an error that names no quota (D-041).
- *Onboarding:* the MCP contract page is short and clear; the CloudFormation reference is the most useful page for CDK.
- *Build again:* yes.

**Amazon Bedrock AgentCore Gateway / Policy / Observability:** to be written when they exist.

## Deploy and tear down

One tool, `infra/aws_ctl.py` (details in `infra/cdk/README.md`; credentials: anything boto3 and the CDK CLI accept, region from `AWS_REGION`, target `us-east-1`):

```bash
python infra/aws_ctl.py status                 # what exists, and what can cost money
python infra/aws_ctl.py up [--runtime]         # deploy the stacks, create the demo users
python infra/aws_ctl.py seed                   # write the demo data (keyed by Cognito's subs)
python infra/aws_ctl.py down                   # dry run: the plan
python infra/aws_ctl.py down --yes             # destroy the stacks and what they leave behind
python infra/aws_ctl.py down --yes --include-budget --include-bootstrap    # at the very end
```

- `down` touches only resources whose names belong to the project (`FairTable*` stacks, the table, the `fairtable-users` pool, `FairTable*` functions, `fairtable_mcp*` runtimes and log groups, test tables `ft-test-*`). The developer's own budget `fairtable-5usd` and everything else on the account is never listed, let alone deleted.
- It destroys the stacks dependents first (Runtime, Identity, Data), then removes what no stack owns (test tables and the log group the Runtime service creates for itself), and ends with a listing: it exits 1 if anything that costs money is still there. The budget stack and the CDK bootstrap stack stay unless `--include-budget` / `--include-bootstrap` are given.
- Measured on 2026-09-30 (real account): `down --yes` of the data and identity stacks 2 min 8 s, ending with "nothing that costs money is left"; `up` 3 min 14 s (table 58 s, Cognito 75 s, users created); the real-token tests then passed 8 of 8 on the new pool (a new pool id and new subs). The bootstrap teardown (empty the versioned asset bucket, delete the stack) is covered by unit tests with fake clients and has **not** been run on the real account yet.
- Tag check: every stack tags its resources `project=fairtable`.

## Teardown checklist for the end of the project
1. `python infra/aws_ctl.py down --yes --include-budget --include-bootstrap` (after the demo footage is recorded, P4-1, and after the submission, P4-5).
2. `python infra/aws_ctl.py status` prints "Nothing that costs money is left."
3. Record the listing in `docs/friction-log.md` (P2-8 acceptance).
