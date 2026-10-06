# Product feedback for the Devpost form

The form asks, for **every tool, API or SDK used**, five things: what we used it for, what worked well, what needs work, how onboarding went
(zero to hello world), and whether we would build with it again. The same text answers the AWS Builder question ("describe which AWS services
you used and how"). Every statement comes from something we ran or read; the evidence is in [`friction-log.md`](friction-log.md),
[`aws-integration.md`](aws-integration.md) and [`devlog/`](devlog/). Numbers are from our own runs on one AWS account (us-east-1).

**Contents.** AWS: AgentCore Runtime, Gateway, Policy and Observability · Bedrock with Nova 2 Sonic · Bedrock models in the evaluation ·
Cognito and its trigger Lambda · DynamoDB · Lambda with EventBridge Scheduler · Lambda with API Gateway · SNS · S3 · KMS · Secrets Manager ·
CDK · Budgets. Other tools: FastMCP and the MCP SDK · Strands Agents · Cedar and `cedarpy` · MCP Inspector · DynamoDB Local · the DeepSeek API.

---

## Amazon Bedrock AgentCore Runtime
- *Used for:* hosting the MCP server (FastMCP, stateless Streamable HTTP) from a zip on Runtime V2, callers authenticated with IAM, the diner's token in the allowed header `x-ft-user-token`.
- *Worked well:* direct code deployment (a 39 MB zip with arm64 wheels, no Docker, no ECR); the execution role from the documentation was enough; header allowlist, V2 and stateless mode behaved as documented; a full booking with DynamoDB transactions ran from the zip.
- *Needs work:* (1) the Host header the proxy forwards (`<uuid>.lambda-microvm.<region>.on.aws`) is not documented, and an MCP server with Host validation then fails every call with a 421 whose cause the log does not show; (2) every environment change takes about 4.4 minutes; (3) the L1 CDK class lacks `PlatformVersion`; (4) on a new account the Runtime quotas can be 0 with an error that names no quota.
- *Onboarding:* the MCP contract page is short and clear; the CloudFormation reference was the most useful page for CDK.
- *Build again:* yes.

## Amazon Bedrock AgentCore Gateway
- *Used for:* the front door. Callers present a Cognito access token only (no AWS credentials); the Gateway validates it (`CUSTOM_JWT`), a Lambda request interceptor hands the token to the server in `x-ft-user-token`, and the Gateway calls the Runtime with SigV4 and its own role.
- *Worked well:* an MCP server target pointing at a Runtime with the gateway role needed no OAuth provider and no AgentCore Identity; creating the target synchronised the tools at once; the interceptor contract (headers in, headers and body out, or an immediate 401) behaved as documented; a forged header was replaced reliably; the whole stack came up in under a minute.
- *Needs work:* (1) the Gateway pages never name the IAM action for calling a Runtime (`InvokeAgentRuntime`; we found it in the service reference); (2) an interceptor's `Authorization` header is forwarded to the target and would clash with SigV4 (we avoid it); (3) tool names always get a `<target>___` prefix and it cannot be turned off; (4) there is no documented way to see why a request was refused (401 or 403).
- *Onboarding:* the CloudFormation reference and the interceptor and header-propagation pages were enough; the permissions page is the weakest.
- *Build again:* yes.

## Amazon Bedrock AgentCore Policy
- *Used for:* rules G1 to G4 repeated at the Gateway as defence in depth: one policy engine and six Cedar policies (reads for any signed-in caller; writes need a signed-in user with the booking scope; a party above 10 refused on the three tools that take one; writes only from a verified agent). The server evaluates the same rules itself as well.
- *Worked well:* the policies are plain Cedar files in the repository, tested locally with `cedarpy` against the same scenario table as the server's rules; the service accepted all six on the first try; `LOG_ONLY` and then `ENFORCE` is one parameter; a refusal names the policy that matched, and `tools/list` hides tools a caller may not use.
- *Needs work:* (1) the generated Cedar schema cannot be read, so a statement can only be tested by creating it; (2) `CreatePolicy` returns before validation and CloudFormation does not wait for it, so a `forbid` created next to its `permit` can be refused as "overly restrictive" and the stack then hangs (two deploys avoid it); (3) a refusal is a JSON-RPC error without our `next_step`, and its text names only the policy ("Tool Execution Denied ... denied due to ft_g3_party_size_restaurant_search-..."), no reason a model could pass on to the diner; a voice model then invented one.
- *Onboarding:* the Policy permissions page (three actions on the Gateway role, `InvokeGateway` for the creator) was what mattered; the rest was in the CloudFormation reference.
- *Build again:* yes, with the two-deploy order.

## Amazon Bedrock AgentCore Observability (CloudWatch Transaction Search)
- *Used for:* one trace per booking: Gateway spans (tool, latency, policy decision and the determining policy) and Runtime spans, searched in CloudWatch Transaction Search.
- *Worked well:* the policy engine leaves its own span with the decision and the policy that decided; no token or argument appears in the attributes; a test day costs a few MB of logs.
- *Needs work:* (1) no tracing property on the Runtime or Gateway CloudFormation resources; (2) the Runtime delivery works but is documented nowhere; (3) `filter-log-events` shows nothing on `aws/spans` while Logs Insights does; (4) Transaction Search takes about 7 minutes to deploy and changes the whole account.
- *Onboarding:* the Observability pages are long and mix Runtime-hosted and outside agents; the CloudWatch CloudFormation page for Transaction Search was the clearest.
- *Build again:* yes.

## Amazon Bedrock with Amazon Nova 2 Sonic (voice)
- *Used for:* the voice page. A browser microphone feeds a web app, which streams to a bidirectional Bedrock session (Strands `BidiAgent`); Nova 2 Sonic hears the diner, calls our seven MCP tools through the Gateway with the diner's own token, and speaks the answer.
- *Worked well:* speech in, tool calls and speech out in one stream; the model called our tools in the right order (search, availability, hold, read back, confirm); a whole booking conversation cost under two cents (about 3,300 tokens in and 1,400 out, at $3 and $12 per million speech tokens); the transcript arrives with the audio.
- *Needs work:* (1) the stream ends with a `ValidationException` ("Timed out waiting for audio bytes") if the client stops sending audio, so a client must stream silence while the user is quiet; (2) one sentence in a system prompt made Bedrock answer "blocked by our content filters", and the message does not say which; (3) the model changed one character of a 295-character signed token in nine of nine tries, but copied an 8-character id, an 11-character code and a 32-character id correctly every time, so identifiers meant for speech models must be short; (4) it stays silent while it calls tools (14 to 19 seconds here) and a prompt sentence asking it to say something first had no effect; (5) its audio arrives in 80 ms pieces with gaps of up to 0.4 s, so a player needs a head start; (6) the user guide's Strands example uses module names that `strands-agents` 1.57.1 does not have. (7) in recorded calls it sometimes issued every tool call twice, and when a refusal gave no reason it made one up ("maximum party size is eight"; the real limit is 10): a prompt sentence forbidding invented limits cut this down but did not remove it, so the refusal text itself must carry the reason; (8) in one call it spoke its own reasoning ("Okay, the user wanted to enter the lottery...") instead of answering.
- *Onboarding:* about a day to a reliable spoken booking; most of it went into the points above, none of which is in the quick start.
- *Build again:* yes, with a client that streams silence and short identifiers.

## Amazon Bedrock models in the evaluation (Claude Haiku 4.5, Amazon Nova Lite)
- *Used for:* real-model runs of the same 40 evaluation tasks, with a model playing the diner and the assistant, through Strands `BedrockModel`.
- *Worked well:* switching the model is one setting; with FairTable's rules every model had zero violations; per-trial token counts are available.
- *Needs work:* (1) Nova Lite fell into tool-call loops that ended in `maximum recursion depth exceeded`; every turn re-sends the whole conversation, so three loops and a few cut-short jobs cost about $4.2 (94 million input tokens) while our own report counted 2.3 million, because failed trials report no tokens, and the agent loop has no default cap on model calls or tokens; (2) `modelStreamErrorException` ("invalid sequence as part of ToolUse") ends a conversation; (3) `ValidationException: A conversation must start with a user message` after a long conversation; (4) on a new account the real spend showed in Cost Explorer only a day later.
- *Onboarding:* minutes to the first call; learning the cost control took a day.
- *Build again:* yes, with a hard cap per trial and the cost read from CloudWatch.

## Amazon Cognito, with an AWS Lambda pre token trigger
- *Used for:* sign-in (`USER_PASSWORD_AUTH`, demo only), machine tokens (client credentials), and the claims the server's rules read (agent tier, agent id, restaurant of an owner), added by one pre token generation trigger (event version V3_0, a 128 MB arm64 Python function).
- *Worked well:* the claims a trigger can add matched what the design needed; real tokens passed the server's verifier with configuration changes only; Essentials with 10,000 free monthly users costs nothing for a demo; machine tokens are billed per request ($0.00225 each: 37 requests from our tests and the red team cost $0.083 in the first days) with no standing fee.
- *Needs work:* (1) password sign-in tokens carry only `aws.cognito.signin.user.admin`, so the trigger has to add the booking scope and should remove that one; (2) a function cannot be wired to an app client id without a dependency cycle; (3) CDK leaves `ExplicitAuthFlows` out for a machine client and Cognito then turns on its defaults; (4) the L2 property `user_pool_client_secret` adds a custom resource to the stack, while the L1 `GetAtt` does not.
- *Onboarding:* the trigger page is thorough; its table of claims a trigger cannot change is the most useful part.
- *Build again:* yes.

## Amazon DynamoDB
- *Used for:* the single table of the whole system (slots, holds, reservations, counters, idempotency records, audit, waitlists, Fair Drops); every state change is one `TransactWriteItems`.
- *Worked well:* conditions inside transactions gave exactly one winner in 30 of 30 rounds of 20 simultaneous writers; on-demand pricing means an idle demo costs next to nothing; the table, its two indexes and the tags came up from CDK in under a minute.
- *Needs work:* `TransactionConflict` only appears on the real service (DynamoDB Local serialises transactions) and the SDKs do not retry a cancelled transaction, so the retry policy must be written and tested against the real service; creating and deleting a table with two indexes takes 25 to 45 s each.
- *Onboarding:* clear; the condition-expression and reserved-word traps cost a few failed runs.
- *Build again:* yes.

## AWS Lambda and Amazon EventBridge Scheduler (the background workers)
- *Used for:* a `rate(1 minute)` schedule calls one Lambda (arm64, Python 3.12, the same zip as the Runtime) that releases expired holds, offers the freed table to waiting diners, and draws Fair Drops that are due.
- *Worked well:* a real ten-minute hold that nobody touched was released by the clock, and a due Fair Drop was drawn by the clock; the ticks came about a minute apart; the same pure functions the server runs lazily were reused unchanged; free at 43,200 invocations a month.
- *Needs work:* a new account's Lambda concurrency limit is 10, so reserving one instance fails (a reservation must leave 10 unreserved); the CDK `logRetention` option is deprecated in favour of an explicit log group.
- *Onboarding:* quick; the L1 `CfnSchedule` needs its own role, which the L2 construct would hide.
- *Build again:* yes.

## AWS Lambda and Amazon API Gateway (HTTP API): the owner console
- *Used for:* the restaurant owner's console (sign-in through Cognito, cancellation terms, Fair Drops, audit). One arm64 Lambda runs the same FastAPI app as the local profile through Mangum, behind an HTTP API with a `$default` route and a throttled stage.
- *Worked well:* the same code runs locally and on AWS with only a different entry point; the stack deployed in 65 seconds; stage throttling is two properties.
- *Needs work:* (1) the first request after a deploy took 7.8 s (cold start of a 95 MB package) and a page request once took 14.7 s; (2) under 60 concurrent requests we saw 503 answers that we could not tell apart, in the API's own logs, from the account's Lambda concurrency limit of 10; (3) the API Gateway price page loads its numbers by script, so it cannot be read with a plain download.
- *Onboarding:* about an hour from the synthesised stack to a working sign-in; most of it went into packaging.
- *Build again:* yes.

## Amazon SNS
- *Used for:* one topic for waitlist and Fair Drop notices. Our own e-mail address is the one subscriber (a real service would need a contact per user; the README says so).
- *Worked well:* topic and subscription from CDK in seconds; the confirmation e-mail arrived at once; the first 1,000 e-mails a month are free.
- *Needs work:* nothing found beyond the confirmation link, which must be clicked by hand, so it cannot be scripted end to end.
- *Onboarding:* minutes.
- *Build again:* yes.

## Amazon S3
- *Used for:* a private copy of every Fair Drop audit (`drops/<id>.json`), so that anyone given the object can recompute the draw.
- *Worked well:* block-public-access, encryption and a TLS-only policy are three lines in CDK; `autoDeleteObjects` empties the bucket on teardown.
- *Needs work:* `autoDeleteObjects` adds a hidden Lambda and its log group to the stack, which is easy to forget when listing what a teardown leaves.
- *Onboarding:* minutes.
- *Build again:* yes.

## AWS KMS
- *Used for:* `GenerateRandom`, the secret seed of each Fair Drop (the draw order is `HMAC-SHA256(seed, ticket)` and the commitment `SHA-256(seed)` is published first).
- *Worked well:* 32 random bytes with no key to create, manage or pay for ($0.03 per 10,000 requests after 20,000 free a month); it also worked from the owner-console Lambda with a single permission.
- *Needs work:* nothing found.
- *Onboarding:* one API call.
- *Build again:* yes.

## AWS Secrets Manager
- *Used for:* generated HMAC keys (slot tokens, the owner-console session cookie), handed to the functions as CloudFormation dynamic references, so no value is in the repository or in a command.
- *Worked well:* one construct generates and stores the secret; teardown removes it; the cost is small and known ($0.40 per secret per month).
- *Needs work:* CloudFormation resolves a dynamic reference at deploy time, so the value ends up in the function's environment variables, readable by anyone who may read the function configuration; reading the secret at run time would be better for production.
- *Onboarding:* minutes.
- *Build again:* yes, reading the value at run time.

## AWS CDK (Python) and CloudFormation
- *Used for:* all infrastructure, with scripted `up`, `status` and `down`.
- *Worked well:* `cdk diff` before every deploy; stacks deployed in 1 to 2 minutes; the rollback of a failed Runtime creation left nothing behind.
- *Needs work:* the L1 Runtime class lacked `PlatformVersion`; a Node stack trace on every command on Windows (harmless); `aws login` credentials need `awscrt`, which a locked-down PC may block.
- *Onboarding:* a day to a first reliable deploy of the AgentCore resources.
- *Build again:* yes.

## AWS Budgets
- *Used for:* one monthly budget with actual-spend alerts (credits excluded): $5 with alerts at $1, $3 and $4.5 on our test account.
- *Worked well:* free for cost budgets without actions; created from CDK.
- *Needs work:* `IncludeCredit` defaults to true, which silences the alerts while a credit lasts; a budget only warns, it does not stop spending.
- *Onboarding:* minutes.
- *Build again:* yes.

---

## FastMCP 3.4.7 and the MCP Python SDK 1.30.0
- *Used for:* the MCP server (spec 2025-11-25, Streamable HTTP, stateless) with seven tools and two resources.
- *Worked well:* typed arguments with `readOnlyHint` annotations; stateless mode matches what AgentCore Runtime and the Alexa+ client send; middleware for telemetry and error mapping; `mask_error_details=True` hides unexpected exceptions and leaves structured results alone.
- *Needs work:* (1) raising `UrlElicitationRequiredError` in a tool did not reach the client as error -32042; (2) Host and Origin protection are off by default, which the quick start does not say; (3) an ordinary exception in a tool logs a full traceback at ERROR for every business refusal (we raise a `ToolError` with `log_level=INFO`); (4) a wrong-typed argument becomes a `ValidationError` that is not a `ToolError`, so a middleware catching `ToolError` misses it; (5) `get_http_headers()` hides `Authorization` by default, so a server that reads a bearer token finds nothing until it passes `include={"authorization"}`, which only the function's docstring mentions; (6) `task=True` needs the optional `pydocket` package.
- *Onboarding:* an hour to a working server; the traps above were found in the source, not in the documentation.
- *Build again:* yes.

## Strands Agents SDK 1.57.1
- *Used for:* the simulated assistant (an agent with an MCP client, on a scripted mock, DeepSeek or Bedrock model) and the voice agent (`BidiAgent` with `BedrockNovaSonicModel`).
- *Worked well:* an MCP client that lists and calls our tools, through the Gateway as well as directly; model providers switch by one setting; the bidirectional agent streams audio, transcripts and tool calls as events.
- *Needs work:* (1) the MCP client with `sse-starlette` and `uvicorn` in one pytest process hung the whole suite; (2) with a thinking model through the Chat Completions class, every turn after the first logs that `reasoningContent` is not supported; (3) the voice features need the `bidi` extra and the module names differ from the Nova 2 user guide; (4) no default cap on model calls or tokens per run (see the Bedrock models above).
- *Onboarding:* a working agent in minutes.
- *Build again:* yes.

## Cedar and `cedarpy` 4.12.1
- *Used for:* the rules, in one language at two enforcement points: G1 to G4 (stateless, at the Gateway as AgentCore Policy and again in the server) and P0, S1, S2, S4, S5a to S5c and S6 (stateful, in the server).
- *Worked well:* the policies read like the owner's rules; `forbid` and `permit` with default deny map cleanly to "refuse unless allowed"; annotations (`@id`, `@on_deny`) let us return the rule that refused; the same files are tested locally, and AgentCore Policy accepted G1 to G4 (one statement needed a rewrite after the service called it "overly restrictive").
- *Needs work:* `cedarpy` reports reasons as `policy0…policyN` (an index), so the table from index to `@id` must be built from the same text that was evaluated; a `forbid` whose condition touches a missing attribute is skipped and only appears under `diagnostics.errors` (we guard with `has`).
- *Onboarding:* a day to a first useful rule set.
- *Build again:* yes.

## MCP Inspector
- *Used for:* manual checks of the server in the first days.
- *Worked well:* custom headers and structured results are easy to inspect.
- *Needs work:* in CLI mode a tool call that ended in JSON-RPC error -32042 printed nothing and never returned.
- *Onboarding:* one `npx` line.
- *Build again:* yes, for manual checks.

## Amazon DynamoDB Local (Docker)
- *Used for:* every integration test and the local profile (`docker compose up`), with the same table definition and the same `TransactWriteItems` as on AWS.
- *Worked well:* it behaves like the service for conditional writes and transaction cancellations, which our concurrency tests need; it starts in seconds.
- *Needs work:* nothing found beyond pinning the image by digest.
- *Onboarding:* minutes.
- *Build again:* yes.

## DeepSeek API
- *Used for:* one of the real models of the evaluation (the light `deepseek-flash` model, through its OpenAI-compatible API and Strands).
- *Worked well:* the OpenAI-compatible interface worked with our agent code unchanged; it kept the rules at zero violations in 80 trials.
- *Needs work:* nothing specific beyond the thinking-model log noise listed under Strands.
- *Onboarding:* minutes.
- *Build again:* yes.

---

## Feature requests

1. **Amazon Nova 2 Sonic: speak a short filler sentence while a tool is running.**
   Why it matters: in our voice booking the model stayed silent for 14 to 19 seconds during tool calls, and asking for a filler in the prompt had no effect. A diner on a call would think the line had dropped.
   Priority: Important.
2. **AgentCore Policy: return the validation result of `CreatePolicy`, and let the generated Cedar schema be read.**
   Why it matters: we could only test a policy statement by creating it. CloudFormation does not wait for validation, so a `forbid` created next to its `permit` can be refused as "overly restrictive" and the stack hangs; we need two deploys to avoid it.
   Priority: Important.
3. **Strands Agents and Bedrock: a default cap on model calls and tokens per agent run.**
   Why it matters: tool-call loops of Amazon Nova Lite cost about $4.2 (94 million input tokens) before anything stopped them, and failed runs report no tokens, so the cost was invisible in our own report.
   Priority: Important.
4. **AgentCore Runtime: document the Host header it forwards (`<uuid>.lambda-microvm.<region>.on.aws`).**
   Why it matters: an MCP server with Host validation answers 421 to every call and its log does not show the cause. We found it by trial.
   Priority: Important.
5. **AgentCore Gateway: tell the caller why a request was refused (401 or 403).**
   Why it matters: there is no documented way to see the reason, which makes debugging a token or policy problem slow.
   Priority: Important.
6. **AgentCore Gateway: let the `<target>___` prefix on tool names be turned off.**
   Why it matters: our tools appear as `ft___restaurant_search` on AWS and `restaurant_search` locally, so prompts and docs have to explain both names.
   Priority: Nice-to-have.
