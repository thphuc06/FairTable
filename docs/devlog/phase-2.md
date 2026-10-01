# Phase 2 – AWS Builder path (10-14 → 10-17, started early 2026-09-30)

Status: **P2-1 to P2-5, P2-7, P2-8, P2-10 done; the AWS profile runs in the developer's second account (D-045); next P2-6 Policy, P2-9 observability** (decisions D-016, D-030, D-031, D-034, D-035)

## Plan
Goal: run the same server on AWS (DynamoDB, Cognito, AgentCore Runtime, Gateway, Policy, Observability) so the demo shows the AWS path once, then tear everything down. Task list and acceptance criteria: `docs/PLAN.md` §3, Phase 2. Choices: D-035.

Rules for this phase: wire only the part the developer names ("wire X"); before creating anything state what it is, its cost from the official pricing page and how it is removed, then wait for a yes; CDK, tag `project=fairtable`, least privilege, scripted teardown run after every test or demo; read-only checks first.

| Batch | Tasks | In plain words |
|---|---|---|
| A – first contact | P2-1, P2-2, P2-3 | DynamoDB + Cognito + Runtime; on the way, settle the "not verifiable without the account" list (D-035) |
| B – Gateway | P2-4, P2-5, P2-6, P2-7 | verifier on Cognito, Gateway identity, Gateway Policy, `-32042` through the Gateway |
| C – observability and teardown | P2-9, P2-8 | traces on AWS, deploy/destroy scripts, `aws-integration.md` |

Read-only account check at the start, 2026-09-30 (us-east-1): budgets `My Zero-Spend Budget` ($1) and `fairtable-5usd` ($5) exist; no DynamoDB table; no CloudFormation stack. P2-1 must not recreate the $5 alarm; the planned $50/$100/$140 alerts are additional and need the developer's yes.

## Progress
| Task | Batch | Status | Date | Note |
|---|---|---|---|---|
| P2-1 CDK: DynamoDB + Budgets | A | done | 2026-09-30 | table and budget deployed; 44/44 store tests pass on the real table; TEMPORARILY_BUSY found and fixed |
| P2-2 Cognito + pre-token | A | done | 2026-09-30 | deployed; 6/6 real-token tests pass; self-service scope removed (D-039) |
| P2-3 Server on Runtime | A | done | 2026-10-01 | runs on Runtime V2 in the second account; 16 of 16 real-AWS tests pass (the first account stays blocked, D-041) |
| P2-4 Verifier with Cognito JWKS | B | done | 2026-09-30 | several client ids, token_use; real Cognito tokens pass with configuration only |
| P2-5 Gateway + interceptor | B | todo | | |
| P2-6 Gateway Policy G1-G4 | B | todo | | |
| P2-7 -32042 through the Gateway | B | done | 2026-10-01 | measured: lost through the Gateway; plain result with the link works; D-048 |
| P2-9 Observability (AWS part) | C | todo | | server part done (D-032) |
| P2-8 Teardown + aws-integration.md | C | in progress | 2026-09-30 | started while P2-3 waits for the quota |

## Entries (newest first)

### 2026-10-01 · P2-7 · [aws] [gateway] [stepup] · `-32042` through the Gateway measured; real model through the Gateway tried
- **Goal:** answer the P2-7 question and try a real model through the Gateway.
- **Done:** (1) probes with a URL-capable client: stateless Runtime gives the plain `CONSENT_REQUIRED` result with the link, through the Gateway and directly; with a stateful Runtime and a sessions-enabled Gateway (then with streaming too) the Runtime returns the real `-32042` but the Gateway turns it into a plain error and the link is lost (D-048, friction log). The experiment was reverted (Runtime env change 267 s, Gateway 36 s); 17 of 17 Gateway and Runtime tests pass again. (2) DeepSeek through the Gateway: `tests/aws/test_real_model.py` (skipped without `DEEPSEEK_API`; only `DEEPSEEK_*` lines are read from `.env`, nothing printed): booked every time in 5 runs; an instruction about unique `idempotency_key`s was added to the assistant's prompt. (3) CDK switches `RUNTIME_STATELESS`, `GATEWAY_SESSIONS`, `GATEWAY_STREAMING` (off by default) with template tests.
- **Files:** `infra/cdk/{app.py,stacks/runtime_stack.py,stacks/gateway_stack.py}`, `simulator/assistant.py`, `tests/aws/test_real_model.py`, `tests/unit/infra/test_cdk_table.py`, docs.
- **Tests:** CDK template tests 35 passed; real AWS: Gateway and Runtime 17 of 17 after the revert, real model 1 of 1 (five runs); unit tests see the batch report.
- **Decisions:** D-048.
- **Surprises / friction:** the Gateway drops the elicitation URL (friction log).
- **Follow-ups:** P2-6 (Policy G1-G4), P2-9 (observability), then clean up per D-044; the whole local suite still has to be run once more after the prompt sentence and the CDK switches.

### 2026-10-01 · P2-10 · [aws] [web] [simulator] · Cognito sign-in for the web pages and the assistant through the Gateway
- **Goal:** make the AWS demo path complete: a person signs in with Cognito, chats, and the assistant reaches the server through the Gateway.
- **Done:** `CognitoLogin` and `cognito_client` (unsigned), settings for the provider and the gateway route, the tool-name prefix handled in `transcript`, `ScriptedModel`, `build_model`, `Assistant` (bearer token via the Gateway, bare names in steps) and `ChatService`; `python -m web` picks the login and the route from the environment. Tests written first (red), then the code: 38 new unit tests (login against a fake Cognito, prefix, settings). Real account: `tests/aws/test_demo_flow.py` 4 of 4 on the first run (Cognito sign-in, chat booking through the Gateway, step-up with the consent page, owner console); the test cleans up after itself.
- **Files:** `web/{auth,chat,__main__}.py`, `simulator/{assistant,events,model}.py`, `server/config.py`, `tests/unit/{web/test_cognito_login,simulator/test_gateway_mode,test_gateway_settings}.py`, `tests/aws/test_demo_flow.py`, docs.
- **Tests:** unit 40 new (login against a fake Cognito, prefix, settings, chat route), real AWS 4 new (29 in all); whole local suite 1008 passed, 34 skipped (5 Docker, 29 AWS), 15:49; `ruff` clean. The first full run found 3 failures: a fake assistant in `tests/unit/web/test_chat_service.py` had the old signature; fixed in the test double.
- **Decisions:** D-047.
- **Surprises / friction:** none; it worked first time.
- **Follow-ups:** P2-7 (`-32042` through the Gateway), P2-6 (Policy), P2-9 (observability); a real model (DeepSeek) through the Gateway has not been tried (the mock was used); the web pages still run on the developer's PC against the real table (about a second per call, D-038).

### 2026-10-01 · P2-5 · [aws] [gateway] · Change: the Gateway is deployed and verified (second account); 25 of 25 real-AWS tests pass
- **Goal:** put the Gateway in front of the Runtime and prove the token travels and a forged header does not.
- **Done:** `cdk diff` (7 resources), deploy. First try failed: the Runtime stack had not exported the runtime id yet (`--exclusively`); CloudFormation rolled back, nothing was left; `cdk deploy FairTableGateway` without `--exclusively` updated the Runtime stack (28 s, only new exports) and created the Gateway (56 s). Gateway and target `READY`, tools synchronised. `tests/aws/test_gateway.py` 9 of 9 on the first run, all real-AWS tests 25 of 25. The interceptor's CloudWatch log (49 invocations) contains no token.
- **Files:** `docs/{PLAN,friction-log,aws-integration}.md`, this file.
- **Tests:** real service 25 of 25 (8 tokens, 8 Runtime, 9 Gateway); whole local suite 960 passed, 30 skipped (5 Docker, 25 AWS), 14:36; `ruff` clean.
- **Decisions:** D-046 stands as built.
- **Surprises / friction:** the export order of cross-stack references (friction log).
- **Follow-ups:** P2-10 (Cognito sign-in for the web pages and the simulator through the Gateway, including the `ft___` prefix), P2-7 (does `-32042` pass through), P2-6 (Policy), P2-9 (observability); clean up per D-044 when the batch is stable.

### 2026-10-01 · P2-5 (built, not deployed) · [aws] [gateway] · Gateway stack, interceptor and tests; waiting for "wire Gateway"
- **Goal:** put the AgentCore Gateway in front of the Runtime, with the token handed to the server in `x-ft-user-token`.
- **Done:** read the Gateway, target, interceptor, header-propagation, inbound and outbound authorization and permissions documentation and the IAM service reference (facts in `PLAN.md` 3a-bis, friction log row); interceptor `infra/gateway/interceptor/handler.py` (25 unit tests: token copied, forged header replaced, 401 and nothing forwarded without a bearer token, never logs a token, one header name in three places); `FairTableGateway` stack (Gateway, target `ft`, role, interceptor Lambda) with 9 template tests; `aws_ctl.py` knows the gateway (destroy order, inventory, `up --runtime`); real-AWS tests written (`tests/aws/test_gateway.py`, 9, skipped until deployed).
- **Files:** `infra/gateway/interceptor/handler.py`, `infra/cdk/{app.py,stacks/gateway_stack.py}`, `infra/aws_ctl.py`, `tests/unit/infra/{test_gateway_interceptor,test_cdk_table,test_aws_ctl}.py`, `tests/aws/test_gateway.py`, docs.
- **Tests:** infra unit tests pass; whole suite at the end of the batch.
- **Decisions:** D-046.
- **Surprises / friction:** the documentation never names the IAM action that lets the gateway call a Runtime (friction log).
- **Follow-ups:** the developer's "wire Gateway" (cost stated first); then `tests/aws/test_gateway.py` and the check of header and token passing through the Gateway; P2-10 handles the `ft___` prefix in the simulator.

### 2026-10-01 · P2-3 · [aws] [runtime] · Change: the MCP server runs on AgentCore Runtime (second account); 16 of 16 real-AWS tests pass
- **Goal:** put the server on Runtime in the account that can, and settle what could not be known without it.
- **Done:** bootstrap, then `up --runtime` in the second account (Data, Identity, Runtime, Budget $5, four demo users; 7 min 24 s), seed (588 slots, 2 mandates, 2 drops), smoke tests. First run 8 failures (421). Cause found with a new log line for refused Hosts: the platform forwards `<uuid>.lambda-microvm.us-east-1.on.aws`; fixed with `MCP_ALLOWED_HOSTS=*.lambda-microvm.*.on.aws`. Two test mistakes fixed (a write needs a real slot token before the rules can refuse it). Result: tokens 8 of 8, Runtime smoke 8 of 8, including a hold, confirm and cancel from the zip against DynamoDB.
- **Files:** `server/app.py` (`LogRefusedHost`, `printable_host`), `tests/integration/test_server_stateless.py` (+3), `tests/aws/test_runtime_smoke.py`, docs.
- **Tests:** on the real service 16 of 16; whole local suite 927 passed, 21 skipped (5 Docker, 16 AWS), 17:42; `ruff` clean.
- **Decisions:** D-045.
- **Surprises / friction:** the undocumented Host and the 4.4-minute update loop (friction log).
- **Follow-ups:** P2-5 Gateway (target = this Runtime, SigV4), P2-6 Policy, P2-7 `-32042` through the Gateway, P2-9 observability; clean up per D-044 when the tests of the phase are stable; the first account's stacks stay as a fallback for now.

### 2026-10-01 · P2-1 · [aws] [budget] · Change: the budget limit and alert levels are configurable (small budget for the new account)
- **Goal:** let the second account have a $5 budget, and write down the "deploy, test, clean" rule.
- **Done:** `BUDGET_LIMIT_USD` and `BUDGET_ALERTS` (validated: alerts rise and stay below the limit); the budget is named `fairtable-cap-<limit>usd` and `aws_ctl.py` recognises that prefix only. Rule and the facts behind it: D-044 (only the secret bills by time; everything else bills by use). One line added to `CLAUDE.md`.
- **Files:** `infra/cdk/{app.py,stacks/budget_stack.py}`, `infra/aws_ctl.py`, `tests/unit/infra/{test_cdk_table,test_aws_ctl}.py`, docs, `CLAUDE.md`.
- **Tests:** infra unit tests 91 passed (new: a $5 budget with alerts 1, 3, 4.5; five invalid alert sets refused); `ruff` clean; whole suite at the end of the batch.
- **Decisions:** D-044.
- **Surprises / friction:** none.
- **Follow-ups:** the first account's budget stack still has the old name `fairtable-150usd` until it is redeployed (a free replacement); budget email for the second account.

### 2026-10-01 · P2-3 · [aws] [accounts] · Change: a second account is checked read-only, and aws_ctl learns to tell accounts apart
- **Goal:** find out whether the developer's second account can host the Runtime, and make a mix-up of accounts impossible.
- **Done:** read-only checks of the second account (profile `fairtable2`, root user): old account, AgentCore quotas non-zero, Bedrock AUTHORIZED, one 12-token Nova Micro call works, nothing deployed there. `aws_ctl.py` prints the account (last four digits, root/user/role) at the start of every command and `down --yes` requires `--account <last4>`; with a wrong or missing value it refuses and touches nothing. `status` ran on the second account ("none"); the first account's login session had expired.
- **Files:** `infra/aws_ctl.py`, `tests/unit/infra/test_aws_ctl.py`, `docs/{DECISIONS,friction-log}.md`.
- **Tests:** 30 unit tests in `test_aws_ctl.py` (5 new); `ruff` clean; the whole suite is run at the end of the batch.
- **Decisions:** D-043.
- **Surprises / friction:** see the friction log.
- **Follow-ups:** an IAM admin user (with MFA) in the second account; the budget address there; then bootstrap and `up --runtime` there, after the developer says "wire" and the cost is stated (D-016). The first account stays as the fallback.

### 2026-09-30 · P2-3 · [aws] [research] · What others report about zero Bedrock and AgentCore quotas, and what our account looks like
- **Goal:** find out whether other people hit the same blocks and how they got out.
- **Done:** web search (re:Post, GitHub, AWS pages) and a read-only look at the account. **Account (read-only):** created 2026-05-20 (about four months ago), state ACTIVE, plan type PAID, not a member of an AWS Organization, no Premium Support subscription (the Support API answers `SubscriptionRequiredException`, so only Basic-plan cases are available: account and billing, and quota increases), no AgentCore service-linked role yet; the IAM user cannot see the remaining credit (it reports 0). **Community:** the pattern is common (see the friction log row of the same date). Advice found: a support case "Account and billing" asking for account verification (free), or a quota-increase case for "Amazon Bedrock AgentCore - Agent Runtimes" with region and numbers; adding a payment method alone does not help; waits from a couple of days to 15 days. One re:Post answer says most normal quota requests are approved within hours, but that applies to quotas above their default; ours sits below it. The service-linked-role rate-limit cause is a different error text and does not match.
- **Files:** `docs/friction-log.md`, this file.
- **Tests:** none.
- **Decisions:** none (D-041 and D-042 stand).
- **Sources:** repost.aws threads "Unable to create AgentCore Runtimes due to ServiceQuotaExceededException even though none exist", "Unable to host an agent using Amazon Bedrock AgentCore Runtime", "Bedrock error: ValidationException Operation Not Allowed", "New AWS account has 0 Amazon Bedrock quotas in all regions", "All Bedrock model quotas stuck at 0 tokens/day", "15 days unresolved: All Bedrock quotas stuck at 0 TPM/RPM - 7 support cases", "Free Plan - Bedrock has zero quotas"; github.com/aws-samples/sample-autonomous-cloud-coding-agents/issues/875 (service-linked role); awsfundamentals.com/limits/bedrock-agentcore (defaults); aws.amazon.com/about-aws/whats-new/2026/07/amazon-bedrock-agentcore-increases-default-runtime-quota-limits; the hackathon community forum (community.amazondeveloper.com).
- **Follow-ups:** the developer files the support case (account verification plus the AgentCore quotas); optionally asks in the hackathon community forum; 2026-10-04 stays the date for deciding a fallback.

### 2026-09-30 · P2-8 (tool done; notes for the Runtime, Gateway and Policy still to write) · [aws] [docs] · One tool to deploy, inspect and remove
- **Goal:** one documented command to deploy and one to destroy, with a check that nothing billable remains.
- **Done:** `infra/aws_ctl.py` (`status`, `up`, `seed`, `down`): inventory limited to names owned by the project; dry run by default; stacks destroyed dependents first; strays (test tables, the Runtime's own log group) removed; ends with a listing and exit 1 if anything that costs money is left; the budget and the bootstrap stack are kept unless asked. Run for real on the account: dry run, then `down --yes` (2 min 8 s, nothing left), then `up` (3 min 14 s, four users) and the real-token tests 8 of 8 on the new pool. `docs/aws-integration.md`: per-service notes (five answers each) for DynamoDB, Cognito, Lambda, Budgets, CDK; the deploy/teardown section and the end-of-project checklist; READMEs updated.
- **Files:** `infra/aws_ctl.py`, `tests/unit/infra/test_aws_ctl.py` (25), `docs/{aws-integration,friction-log}.md`, `infra/README.md`, `infra/cdk/README.md`.
- **Tests:** whole suite 913 passed, 21 skipped (5 Docker, 16 AWS), 15:35; `ruff` clean. 25 new unit tests with fake AWS clients; the real run above.
- **Decisions:** none new (D-004, D-016).
- **Surprises / friction:** see the friction log (listing after teardown).
- **Follow-ups:** the bootstrap-stack teardown is only unit-tested; notes for Runtime, Gateway, Policy and Observability when they exist; `seed` has not been run on the real table yet (waiting for the Runtime).

### 2026-09-30 · P2-3 · [aws] [blocked] · Change: the quota request through Service Quotas is refused; a support case is needed
- **Goal:** file the increase requests for the four Runtime quotas that are 0.
- **Done:** tried `RequestServiceQuotaIncrease` for the four quotas with small values; every call was refused by the API because the desired value must exceed the default. Nothing was submitted. Decision D-042: use the support case, with a fixed date for the fallback decision (2026-10-04). Next work that does not need the Runtime: P2-8 (teardown and documentation).
- **Files:** `docs/{DECISIONS,friction-log}.md`, this file.
- **Tests:** none (an API call on the account that changed nothing).
- **Decisions:** D-042.
- **Surprises / friction:** see the friction log.
- **Follow-ups:** the developer files the support text; P2-3 stays `blocked`.

### 2026-09-30 · P2-3 · [aws] [blocked] · Runtime creation refused: the account's AgentCore quotas are 0
- **Goal:** deploy the MCP server on AgentCore Runtime and run the smoke tests.
- **Done:** `cdk diff` (4 new resources, only export outputs on the data and identity stacks), `cdk deploy FairTableRuntime`: the secret, role and policy were created, the zip was published, then the runtime was refused (`maxAgents limit exceeded`, 402). CloudFormation rolled back and the stack was deleted; the account holds no Runtime leftovers (checked: no stack, no secret, no role, no runtime). Read-only check of Service Quotas found the cause: four Runtime quotas are applied at 0 (default 1000, 10, 1000, 5000), all adjustable, no request pending.
- **Files:** `docs/{DECISIONS,friction-log}.md`, this file.
- **Tests:** none run against the runtime (it does not exist); the smoke tests stay skipped.
- **Decisions:** D-041.
- **Surprises / friction:** see the friction log; same root cause as the zero Bedrock quotas.
- **Follow-ups:** the developer decides whether I file the Service Quotas increase requests (Total Agents per Account, Endpoints per Agent, Versions per Agent, Active Session Workloads per Account) and whether to add this to the open support case. P2-3 stays `blocked` until a quota is granted; P2-5 to P2-7 depend on it.

### 2026-09-30 · P2-3 (built, not deployed) and P2-4 · [aws] [identity] · Runtime stack, smoke test, verifier for several app clients
- **Goal:** get everything for the Runtime ready and proven as far as the local machine allows, and finish the verifier work that the Runtime depends on.
- **Done:** P2-4: `VerifierConfig.audience` takes several values and `token_use` (`access`) is checked when configured; `AUTH_AUDIENCE` (comma separated) and `AUTH_TOKEN_USE` in `Settings`; real Cognito tokens of all three clients pass, an ID token and an unlisted client are refused (`tests/aws/test_tokens.py`, 8 of 8). P2-3: read the AgentCore Runtime documentation (CloudFormation reference, execution role and trust policy, MCP invocation, S3 permission rules); `FairTableRuntime` stack (runtime `fairtable_mcp`, V2, MCP, public network, header allowlist `x-ft-user-token`, idle 120 s, least-privilege execution role, generated slot-token secret); `dist/fairtable-runtime.zip` rebuilt (38.5 MB); `tests/aws/test_runtime_smoke.py` (8 tests: tools, diner read, missing/foreign/ID token, bot and unverified agent refused, hold-confirm-cancel inside Alice's permission) calling the runtime with SigV4 and the token in the header.
- **Files:** `server/{config.py,app.py,identity/verifier.py}`, `web/__main__.py`, `infra/cdk/{app.py,cdk.json,stacks/runtime_stack.py,stacks/identity_stack.py}`, `tests/{unit/identity/*,unit/infra/test_cdk_table.py,aws/test_tokens.py,aws/test_runtime_smoke.py}`, docs.
- **Tests:** whole suite 888 passed, 21 skipped (5 Docker, 16 AWS), 15:13; `ruff` clean. New: verifier (several clients, token_use, settings: 7), CDK template tests for the runtime stack (8 more, 19 in the file); real Cognito 8 of 8. The 8 runtime smoke tests are skipped until the runtime exists.
- **Decisions:** D-040.
- **Surprises / friction:** the L1 runtime class lacks `PlatformVersion`; cross-stack flag warning; log group left behind by the service (friction log).
- **Follow-ups:** deploy on "wire Runtime", seed the table with Cognito's subs (`python scripts/seed.py` with `COGNITO_USER_POOL_ID`, writes about 600 demo items into `fairtable`), run the smoke test; settle the items of D-035's list that this batch can reach (header allowlist, Host check, execution role, boto3 credentials under V2, stateless mode) and record the results in `PLAN.md` 3a-bis.

### 2026-09-30 · P2-2 · [aws] [identity] · Change: Cognito deployed and verified on the real account
- **Goal:** prove that real Cognito tokens carry the dev issuer's claims and pass the server's verifier.
- **Done:** `cdk deploy FairTableIdentity` (11 resources, 75 s); `scripts/cognito_users.py` created the four demo users; `pytest -m aws tests/aws/test_tokens.py` passed 6 of 6 on the first run. Decoding the real tokens showed the diner's tokens still carried Cognito's self-service scope `aws.cognito.signin.user.admin`; the trigger now suppresses it (D-039), redeployed in 23 s, 6 of 6 again and the scope is gone. The real claim shapes are in `PLAN.md` 3a-bis.
- **Files:** `infra/cognito/pre_token/handler.py`, `tests/unit/infra/test_pre_token.py` (+1), `tests/aws/test_tokens.py`, docs.
- **Tests:** real pool: 6 of 6 (sign-in through `alexa-plus-sim` and `shady-agent`, owner with group and venue, machine tokens of `alexa-plus-sim` and `bot-m2m`, Cognito's subs differ from the dev issuer's). Whole local suite re-run after the change, see the next entry or the batch report.
- **Decisions:** D-039.
- **Surprises / friction:** none new; it worked first time (the design choices are in the friction log).
- **Follow-ups:** P2-3 (Runtime) and P2-4 (verifier accepts several client ids, checks `token_use`); `scripts/seed.py` against the real table with `COGNITO_USER_POOL_ID` is not run yet (needs the user's go-ahead to write demo data into `fairtable`).

### 2026-09-30 · P2-2 (built, not deployed) · [aws] [identity] · Cognito stack, pre-token trigger and demo users
- **Goal:** give the AWS profile the same identities and claims as the dev issuer, so the server's verifier and rules work unchanged.
- **Done:** read the Cognito documentation (trigger versions and events, claims a trigger cannot change, token endpoint, prices); `FairTableIdentity` CDK stack (Essentials pool, no self sign-up, `owners` group, `custom:venue_id`, resource server `fairtable/book`, domain, three app clients named like the dev issuer's, V3_0 trigger); the trigger function `infra/cognito/pre_token/handler.py` (pure logic plus a cached client-name lookup); `scripts/cognito_users.py` (demo users, idempotent) and Cognito-aware subs in `scripts/seed.py`; opt-in `tests/aws/test_tokens.py` (sign-in and machine tokens checked through the real verifier); `aws` tests are skipped unless `-m aws`.
- **Files:** `infra/cdk/{app.py,stacks/identity_stack.py}`, `infra/cognito/pre_token/handler.py`, `scripts/{cognito_users,seed}.py`, `tests/{conftest.py,aws/test_tokens.py,unit/infra/test_pre_token.py,unit/infra/test_cognito_users.py,unit/infra/test_cdk_table.py}`, docs.
- **Tests:** whole suite 871 passed, 11 skipped (5 Docker, 6 AWS), 15:18; `ruff` clean. New: trigger (15: every trigger source, claims equal the dev issuer's clients, unknown client gets nothing, machine rules), users script (10, fake client), CDK template checks (6 more: plan, V3_0, no self sign-up, clients equal the dev issuer's, machine client has no user flow, scope name, least-privilege policy, group).
- **Decisions:** D-038 (web latency accepted; Cognito layout, client-by-name, PKCE dropped, subs, verifier gap for P2-4).
- **Surprises / friction:** a pool-function-client dependency cycle; CDK leaves `ExplicitAuthFlows` out (Cognito defaults would enable SRP and custom auth on the machine client); see the friction log.
- **Follow-ups:** deploy on "wire Cognito", run `scripts/cognito_users.py` and `pytest -m aws tests/aws/test_tokens.py` and record the real claims in `PLAN.md` 3a-bis; P2-4: verifier must accept several client ids and check `token_use`.

### 2026-09-30 · P2-1 · [aws] [store] · CDK app, real DynamoDB table and budget; conflict handling fixed
- **Goal:** run the store on the real service and find what DynamoDB Local hides.
- **Done:** `infra/cdk/` (Python CDK, pinned; two stacks); `cdk bootstrap` (tag `project=fairtable`); deployed `FairTableData` (table `fairtable`, on-demand, GSI1/GSI2, AWS-owned key, destroyed with the stack) and `FairTableBudget` (`fairtable-150usd`, alerts at $50/$100/$140 of actual spend, credits excluded, email from `BUDGET_EMAIL`). The store tests were re-run against the real service by changing the environment only. A race of 20 writers exposed `StoreBusy` (16 of 600 requests) that nothing handled: `Store.transact` now makes 8 attempts with full-jitter backoff and the tools answer `TEMPORARILY_BUSY` (0 of 600 afterwards). `batch_put` is parallel (seed 35 s to 9.5 s). Test helpers: `FT_TEST_SHARED_TABLE=1` (one table per run), `scripts/aws_credential_process.py` (credentials without `awscrt`).
- **Files:** `infra/cdk/*`, `server/{store/repository.py,domain/errors.py,middleware.py}`, `tests/{conftest.py,integration/test_store_ddb.py,unit/store/test_transact_retry.py,unit/test_busy_error.py,unit/infra/test_cdk_table.py}`, `scripts/aws_credential_process.py`, `docs/{DECISIONS,PLAN,friction-log,aws-integration}.md`.
- **Tests:** whole local suite 840 passed, 5 skipped (Docker smoke, by design), 14:35; `ruff` clean. On the real table (shared-table mode): 44 of 44 tests of `test_store_ddb`, `test_write_pipeline`, `test_reservation_hold` pass (the seed-script test after raising its timeout); `test_ddb_spike.py` is Local-only and not run on AWS. Race script: 30 rounds x 20 writers, exactly one winner every round. New: CDK parity tests (table keys and indexes equal `server/store/table.py`, tags, removal policy, budget thresholds and credit handling, no account id in the app), retry/jitter and `batch_put` unit tests, `TEMPORARILY_BUSY` mapping.
- **Decisions:** D-036 (conflicts, error code, CDK layout, budget, credentials), D-037 (test mode, network finding).
- **Surprises / friction:** `aws login` credentials need `awscrt`, blocked by Windows App Control; `IncludeCredit` default in Budgets; `TransactionConflict` only on the real service; every SDK call takes about 1 s from this PC (friction log). Budget email confirmation is sent by AWS to the subscriber; not verifiable through the API here.
- **Follow-ups:** decide how the local web pages reach DynamoDB at about 1 s per call (D-037) before P2-3; P2-2 (Cognito) and P2-3 (Runtime) must also settle the "not verifiable without the account" list (D-035); the `CDKToolkit` stack stays until the end of the phase, remove it in P2-8.

### 2026-09-30 · Phase 2 start · [aws] [docs] · D-035 recorded, read-only account check
- **Goal:** open Phase 2 with the developer's choices on record and a known starting state.
- **Done:** D-035 written; this file created; read-only check of budgets, DynamoDB tables and CloudFormation stacks; fixed a ruff E731 in `tests/unit/simulator/test_model.py` (left over from Phase 1).
- **Files:** `docs/DECISIONS.md`, `docs/devlog/phase-2.md`, `tests/unit/simulator/test_model.py`.
- **Tests:** whole suite 829 passed, 5 skipped (Docker smoke, by design) in 12:34; ruff clean.
- **Decisions:** D-035.
- **Surprises / friction:** the first suite run failed at import (`No module named boto3`) because it was started outside the `fairtable` conda env; use `conda run -n fairtable`.
- **Follow-ups:** P2-1 started after the suite showed 829 passed; first resource waits for "wire X".
