# AWS integration

Which AWS services FairTable uses, why, and how. This document feeds the AWS Builder product feedback and the README service list.

**Status legend:** _planned_ = designed, not built · _built_ = implemented · _verified_ = exercised against a real account.
Everything below is **planned** as of 2026-09-29.

**Principles**
- The **local Docker profile needs no AWS account** (see `docs/DECISIONS.md` D-001, D-007). The AWS profile is the same server code with different configuration.
- Nothing account-specific lives in code: account IDs, ARNs and regions come from environment or config (`AWS_PROFILE`, `AWS_REGION`, `TABLE_NAME`, …). Target region: `us-east-1`.
- AWS resources are created for tests and the demo, then torn down with a scripted, documented command (`docs/DECISIONS.md` D-004).
- The demo video shows the AWS-deployed path at least once (D-011).

## Services

| Service | Role in FairTable | How we use it | Local equivalent | Status |
|---|---|---|---|---|
| **Amazon Bedrock AgentCore Runtime** | Hosts the MCP server (Streamable HTTP) | The same container image as the local profile, deployed as an MCP server runtime | `docker compose` server container | planned |
| **Amazon Bedrock AgentCore Gateway** | Front door for agents: JWT check, request interceptor, Policy | `CUSTOM_JWT` authorizer with Cognito JWKS; MCP target pointing at the Runtime; REQUEST interceptor copies the verified user token to `x-ft-user-token` and strips any client-supplied value | Server verifies the token itself; no gateway | planned |
| **AgentCore Gateway Policy** | Defense in depth for G1–G4 (stateless rules) | Cedar policies G1–G4 at the Gateway; the same rules also run inside the server with `cedarpy` | `policies/g*.cedar` evaluated in the server | planned |
| **AgentCore Identity** | Outbound OAuth from Gateway to the Runtime target | Gateway calls the Runtime with its own OAuth credentials | – | planned |
| **Amazon Cognito** (Essentials tier) | User pool, OAuth code + PKCE, token claims | Pre-token-generation Lambda **V2** (user tokens) and **V3** (M2M tokens) add `agent_tier` and `agent_id` | `devauth/` dev JWT issuer | planned |
| **AWS Lambda** | Pre-token trigger; Gateway interceptor; optional workers later | Small Python functions; workers reuse the same pure functions as the lazy in-server paths | Same logic runs in-process | planned |
| **Amazon DynamoDB** | Single-table store: slots, holds, reservations, mandates, counters, idempotency records, audit, waitlists, drops | `TransactWriteItems` for every state change; conditions are the final concurrency guarantee. No reliance on TTL for business logic | DynamoDB Local | planned |
| **Amazon CloudWatch / AgentCore Observability** | Logs and traces for the demo and eval runs | Standard logging from the Runtime | Container logs | planned |
| **AWS Budgets** | Cost alerts at $50 / $100 / $140 | Created by the CDK app | – | planned |
| **AWS CDK (Python) / CloudFormation** | Infrastructure as code | Table, Cognito, Lambdas, Budgets; AgentCore resources via the `agentcore` CLI or CDK as supported | – | planned |
| **Amazon Bedrock (models)** | Optional real model for the simulator and eval | `MODEL_PROVIDER=bedrock`; currently **blocked on the account** (AWS Support case), so mock is the default | `MODEL_PROVIDER=mock` | blocked |

Not planned for the MVP: EventBridge Scheduler, KMS (seed comes from a local provider), API Gateway, S3, ElastiCache/Redis, AgentCore Evaluations, Memory, Nova Act, Nova Sonic. These are Should/Could items and need approval before starting.

## Per-service notes to fill in as we build

For each service, record (also feeds `docs/friction-log.md` and the Devpost product feedback):
- what we used it for;
- what worked well;
- what needs work / surprises;
- onboarding experience;
- whether we would build with it again.

## Deploy and tear down

_To be written in plan task P2-8._ Target: one documented command to deploy, one to destroy, and a check that nothing billable remains.
