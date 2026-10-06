# Answers for the Devpost product-feedback questions

Generated from `product-feedback.md` (same facts, regrouped by question). Plain text: paste each block into its box.

## Feedback Question 1: Which developer tools, APIs, and SDKs did you use and for what?

```text
Amazon Bedrock AgentCore Runtime: hosting the MCP server (FastMCP, stateless Streamable HTTP) from a zip on Runtime V2, callers authenticated with IAM, the diner's token in the allowed header x-ft-user-token.

Amazon Bedrock AgentCore Gateway: the front door. Callers present a Cognito access token only (no AWS credentials); the Gateway validates it (CUSTOM_JWT), a Lambda request interceptor hands the token to the server in x-ft-user-token, and the Gateway calls the Runtime with SigV4 and its own role.

Amazon Bedrock AgentCore Policy: rules G1 to G4 repeated at the Gateway as defence in depth: one policy engine and six Cedar policies (reads for any signed-in caller; writes need a signed-in user with the booking scope; a party above 10 refused on the three tools that take one; writes only from a verified agent). The server evaluates the same rules itself as well.

Amazon Bedrock AgentCore Observability (CloudWatch Transaction Search): one trace per booking: Gateway spans (tool, latency, policy decision and the determining policy) and Runtime spans, searched in CloudWatch Transaction Search.

Amazon Bedrock with Amazon Nova 2 Sonic (voice): the voice page. A browser microphone feeds a web app, which streams to a bidirectional Bedrock session (Strands BidiAgent); Nova 2 Sonic hears the diner, calls our seven MCP tools through the Gateway with the diner's own token, and speaks the answer.

Amazon Bedrock models in the evaluation (Claude Haiku 4.5, Amazon Nova Lite): real-model runs of the same 40 evaluation tasks, with a model playing the diner and the assistant, through Strands BedrockModel.

Amazon Cognito, with an AWS Lambda pre token trigger: sign-in (USER_PASSWORD_AUTH, demo only), machine tokens (client credentials), and the claims the server's rules read (agent tier, agent id, restaurant of an owner), added by one pre token generation trigger (event version V3_0, a 128 MB arm64 Python function).

Amazon DynamoDB: the single table of the whole system (slots, holds, reservations, counters, idempotency records, audit, waitlists, Fair Drops); every state change is one TransactWriteItems.

AWS Lambda and Amazon EventBridge Scheduler (the background workers): a rate(1 minute) schedule calls one Lambda (arm64, Python 3.12, the same zip as the Runtime) that releases expired holds, offers the freed table to waiting diners, and draws Fair Drops that are due.

AWS Lambda and Amazon API Gateway (HTTP API): the owner console: the restaurant owner's console (sign-in through Cognito, cancellation terms, Fair Drops, audit). One arm64 Lambda runs the same FastAPI app as the local profile through Mangum, behind an HTTP API with a $default route and a throttled stage.

Amazon SNS: one topic for waitlist and Fair Drop notices. Our own e-mail address is the one subscriber (a real service would need a contact per user; the README says so).

Amazon S3: a private copy of every Fair Drop audit (drops/<id>.json), so that anyone given the object can recompute the draw.

AWS KMS: GenerateRandom, the secret seed of each Fair Drop (the draw order is HMAC-SHA256(seed, ticket) and the commitment SHA-256(seed) is published first).

AWS Secrets Manager: generated HMAC keys (slot tokens, the owner-console session cookie), handed to the functions as CloudFormation dynamic references, so no value is in the repository or in a command.

AWS CDK (Python) and CloudFormation: all infrastructure, with scripted up, status and down.

AWS Budgets: one monthly budget with actual-spend alerts (credits excluded): $5 with alerts at $1, $3 and $4.5 on our test account.

FastMCP 3.4.7 and the MCP Python SDK 1.30.0: the MCP server (spec 2025-11-25, Streamable HTTP, stateless) with seven tools and two resources.

Strands Agents SDK 1.57.1: the simulated assistant (an agent with an MCP client, on a scripted mock, DeepSeek or Bedrock model) and the voice agent (BidiAgent with BedrockNovaSonicModel).

Cedar and cedarpy 4.12.1: the rules, in one language at two enforcement points: G1 to G4 (stateless, at the Gateway as AgentCore Policy and again in the server) and P0, S1, S2, S4, S5a to S5c and S6 (stateful, in the server).

MCP Inspector: manual checks of the server in the first days.

Amazon DynamoDB Local (Docker): every integration test and the local profile (docker compose up), with the same table definition and the same TransactWriteItems as on AWS.

DeepSeek API: one of the real models of the evaluation (the light deepseek-flash model, through its OpenAI-compatible API and Strands).
```

## Feedback Question 2: what worked well?

```text
Amazon Bedrock AgentCore Runtime: direct code deployment (a 39 MB zip with arm64 wheels, no Docker, no ECR); the execution role from the documentation was enough; header allowlist, V2 and stateless mode behaved as documented; a full booking with DynamoDB transactions ran from the zip.

Amazon Bedrock AgentCore Gateway: an MCP server target pointing at a Runtime with the gateway role needed no OAuth provider and no AgentCore Identity; creating the target synchronised the tools at once; the interceptor contract (headers in, headers and body out, or an immediate 401) behaved as documented; a forged header was replaced reliably; the whole stack came up in under a minute.

Amazon Bedrock AgentCore Policy: the policies are plain Cedar files in the repository, tested locally with cedarpy against the same scenario table as the server's rules; the service accepted all six on the first try; LOG_ONLY and then ENFORCE is one parameter; a refusal names the policy that matched, and tools/list hides tools a caller may not use.

Amazon Bedrock AgentCore Observability (CloudWatch Transaction Search): the policy engine leaves its own span with the decision and the policy that decided; no token or argument appears in the attributes; a test day costs a few MB of logs.

Amazon Bedrock with Amazon Nova 2 Sonic (voice): speech in, tool calls and speech out in one stream; the model called our tools in the right order (search, availability, hold, read back, confirm); a whole booking conversation cost under two cents (about 3,300 tokens in and 1,400 out, at $3 and $12 per million speech tokens); the transcript arrives with the audio.

Amazon Bedrock models in the evaluation (Claude Haiku 4.5, Amazon Nova Lite): switching the model is one setting; with FairTable's rules every model had zero violations; per-trial token counts are available.

Amazon Cognito, with an AWS Lambda pre token trigger: the claims a trigger can add matched what the design needed; real tokens passed the server's verifier with configuration changes only; Essentials with 10,000 free monthly users costs nothing for a demo; machine tokens are billed per request ($0.00225 each: 37 requests from our tests and the red team cost $0.083 in the first days) with no standing fee.

Amazon DynamoDB: conditions inside transactions gave exactly one winner in 30 of 30 rounds of 20 simultaneous writers; on-demand pricing means an idle demo costs next to nothing; the table, its two indexes and the tags came up from CDK in under a minute.

AWS Lambda and Amazon EventBridge Scheduler (the background workers): a real ten-minute hold that nobody touched was released by the clock, and a due Fair Drop was drawn by the clock; the ticks came about a minute apart; the same pure functions the server runs lazily were reused unchanged; free at 43,200 invocations a month.

AWS Lambda and Amazon API Gateway (HTTP API): the owner console: the same code runs locally and on AWS with only a different entry point; the stack deployed in 65 seconds; stage throttling is two properties.

Amazon SNS: topic and subscription from CDK in seconds; the confirmation e-mail arrived at once; the first 1,000 e-mails a month are free.

Amazon S3: block-public-access, encryption and a TLS-only policy are three lines in CDK; autoDeleteObjects empties the bucket on teardown.

AWS KMS: 32 random bytes with no key to create, manage or pay for ($0.03 per 10,000 requests after 20,000 free a month); it also worked from the owner-console Lambda with a single permission.

AWS Secrets Manager: one construct generates and stores the secret; teardown removes it; the cost is small and known ($0.40 per secret per month).

AWS CDK (Python) and CloudFormation: cdk diff before every deploy; stacks deployed in 1 to 2 minutes; the rollback of a failed Runtime creation left nothing behind.

AWS Budgets: free for cost budgets without actions; created from CDK.

FastMCP 3.4.7 and the MCP Python SDK 1.30.0: typed arguments with readOnlyHint annotations; stateless mode matches what AgentCore Runtime and the Alexa+ client send; middleware for telemetry and error mapping; mask_error_details=True hides unexpected exceptions and leaves structured results alone.

Strands Agents SDK 1.57.1: an MCP client that lists and calls our tools, through the Gateway as well as directly; model providers switch by one setting; the bidirectional agent streams audio, transcripts and tool calls as events.

Cedar and cedarpy 4.12.1: the policies read like the owner's rules; forbid and permit with default deny map cleanly to "refuse unless allowed"; annotations (@id, @on_deny) let us return the rule that refused; the same files are tested locally, and AgentCore Policy accepted G1 to G4 (one statement needed a rewrite after the service called it "overly restrictive").

MCP Inspector: custom headers and structured results are easy to inspect.

Amazon DynamoDB Local (Docker): it behaves like the service for conditional writes and transaction cancellations, which our concurrency tests need; it starts in seconds.

DeepSeek API: the OpenAI-compatible interface worked with our agent code unchanged; it kept the rules at zero violations in 80 trials.
```

## Feedback Question 3: what needs work?

```text
Amazon Bedrock AgentCore Runtime: (1) the Host header the proxy forwards (<uuid>.lambda-microvm.<region>.on.aws) is not documented, and an MCP server with Host validation then fails every call with a 421 whose cause the log does not show; (2) every environment change takes about 4.4 minutes; (3) the L1 CDK class lacks PlatformVersion; (4) on a new account the Runtime quotas can be 0 with an error that names no quota.

Amazon Bedrock AgentCore Gateway: (1) the Gateway pages never name the IAM action for calling a Runtime (InvokeAgentRuntime; we found it in the service reference); (2) an interceptor's Authorization header is forwarded to the target and would clash with SigV4 (we avoid it); (3) tool names always get a <target>___ prefix and it cannot be turned off; (4) there is no documented way to see why a request was refused (401 or 403).

Amazon Bedrock AgentCore Policy: (1) the generated Cedar schema cannot be read, so a statement can only be tested by creating it; (2) CreatePolicy returns before validation and CloudFormation does not wait for it, so a forbid created next to its permit can be refused as "overly restrictive" and the stack then hangs (two deploys avoid it); (3) a refusal is a JSON-RPC error without our next_step.

Amazon Bedrock AgentCore Observability (CloudWatch Transaction Search): (1) no tracing property on the Runtime or Gateway CloudFormation resources; (2) the Runtime delivery works but is documented nowhere; (3) filter-log-events shows nothing on aws/spans while Logs Insights does; (4) Transaction Search takes about 7 minutes to deploy and changes the whole account.

Amazon Bedrock with Amazon Nova 2 Sonic (voice): (1) the stream ends with a ValidationException ("Timed out waiting for audio bytes") if the client stops sending audio, so a client must stream silence while the user is quiet; (2) one sentence in a system prompt made Bedrock answer "blocked by our content filters", and the message does not say which; (3) the model changed one character of a 295-character signed token in nine of nine tries, but copied an 8-character id, an 11-character code and a 32-character id correctly every time, so identifiers meant for speech models must be short; (4) it stays silent while it calls tools (14 to 19 seconds here) and a prompt sentence asking it to say something first had no effect; (5) its audio arrives in 80 ms pieces with gaps of up to 0.4 s, so a player needs a head start; (6) the user guide's Strands example uses module names that strands-agents 1.57.1 does not have.

Amazon Bedrock models in the evaluation (Claude Haiku 4.5, Amazon Nova Lite): (1) Nova Lite fell into tool-call loops that ended in maximum recursion depth exceeded; every turn re-sends the whole conversation, so three loops and a few cut-short jobs cost about $4.2 (94 million input tokens) while our own report counted 2.3 million, because failed trials report no tokens, and the agent loop has no default cap on model calls or tokens; (2) modelStreamErrorException ("invalid sequence as part of ToolUse") ends a conversation; (3) ValidationException: A conversation must start with a user message after a long conversation; (4) on a new account the real spend showed in Cost Explorer only a day later.

Amazon Cognito, with an AWS Lambda pre token trigger: (1) password sign-in tokens carry only aws.cognito.signin.user.admin, so the trigger has to add the booking scope and should remove that one; (2) a function cannot be wired to an app client id without a dependency cycle; (3) CDK leaves ExplicitAuthFlows out for a machine client and Cognito then turns on its defaults; (4) the L2 property user_pool_client_secret adds a custom resource to the stack, while the L1 GetAtt does not.

Amazon DynamoDB: TransactionConflict only appears on the real service (DynamoDB Local serialises transactions) and the SDKs do not retry a cancelled transaction, so the retry policy must be written and tested against the real service; creating and deleting a table with two indexes takes 25 to 45 s each.

AWS Lambda and Amazon EventBridge Scheduler (the background workers): a new account's Lambda concurrency limit is 10, so reserving one instance fails (a reservation must leave 10 unreserved); the CDK logRetention option is deprecated in favour of an explicit log group.

AWS Lambda and Amazon API Gateway (HTTP API): the owner console: (1) the first request after a deploy took 7.8 s (cold start of a 95 MB package) and a page request once took 14.7 s; (2) under 60 concurrent requests we saw 503 answers that we could not tell apart, in the API's own logs, from the account's Lambda concurrency limit of 10; (3) the API Gateway price page loads its numbers by script, so it cannot be read with a plain download.

Amazon SNS: nothing found beyond the confirmation link, which must be clicked by hand, so it cannot be scripted end to end.

Amazon S3: autoDeleteObjects adds a hidden Lambda and its log group to the stack, which is easy to forget when listing what a teardown leaves.

AWS KMS: nothing found.

AWS Secrets Manager: CloudFormation resolves a dynamic reference at deploy time, so the value ends up in the function's environment variables, readable by anyone who may read the function configuration; reading the secret at run time would be better for production.

AWS CDK (Python) and CloudFormation: the L1 Runtime class lacked PlatformVersion; a Node stack trace on every command on Windows (harmless); aws login credentials need awscrt, which a locked-down PC may block.

AWS Budgets: IncludeCredit defaults to true, which silences the alerts while a credit lasts; a budget only warns, it does not stop spending.

FastMCP 3.4.7 and the MCP Python SDK 1.30.0: (1) raising UrlElicitationRequiredError in a tool did not reach the client as error -32042; (2) Host and Origin protection are off by default, which the quick start does not say; (3) an ordinary exception in a tool logs a full traceback at ERROR for every business refusal (we raise a ToolError with log_level=INFO); (4) a wrong-typed argument becomes a ValidationError that is not a ToolError, so a middleware catching ToolError misses it; (5) get_http_headers() hides Authorization by default, so a server that reads a bearer token finds nothing until it passes include={"authorization"}, which only the function's docstring mentions; (6) task=True needs the optional pydocket package.

Strands Agents SDK 1.57.1: (1) the MCP client with sse-starlette and uvicorn in one pytest process hung the whole suite; (2) with a thinking model through the Chat Completions class, every turn after the first logs that reasoningContent is not supported; (3) the voice features need the bidi extra and the module names differ from the Nova 2 user guide; (4) no default cap on model calls or tokens per run (see our note on Amazon Bedrock models).

Cedar and cedarpy 4.12.1: cedarpy reports reasons as policy0…policyN (an index), so the table from index to @id must be built from the same text that was evaluated; a forbid whose condition touches a missing attribute is skipped and only appears under diagnostics.errors (we guard with has).

MCP Inspector: in CLI mode a tool call that ended in JSON-RPC error -32042 printed nothing and never returned.

Amazon DynamoDB Local (Docker): nothing found beyond pinning the image by digest.

DeepSeek API: nothing specific beyond the log noise a thinking model causes in Strands Agents (every turn after the first logs that reasoningContent is not supported).
```

## Feedback Question 4: how was your onboarding experience?

```text
Amazon Bedrock AgentCore Runtime: the MCP contract page is short and clear, and the CloudFormation reference was the most useful page for CDK. It took us a day to get the first reliable deployment of the AgentCore resources.

Amazon Bedrock AgentCore Gateway: the CloudFormation reference plus the pages on the request interceptor and header propagation were enough to get a working Gateway. The permissions page is the weakest one.

Amazon Bedrock AgentCore Policy: the Policy permissions page (three actions on the Gateway role, and InvokeGateway for the person who creates the policies) was the page that mattered. The rest was in the CloudFormation reference.

Amazon Bedrock AgentCore Observability (CloudWatch Transaction Search): the Observability pages are long and mix agents hosted on Runtime with agents hosted elsewhere, so it was hard to find what applied to us. The CloudWatch CloudFormation page for Transaction Search was the clearest.

Amazon Bedrock with Amazon Nova 2 Sonic (voice): about a day to get a reliable spoken booking. Most of that time went into problems that are not in the quick start (the stream ending when the client stops sending audio, a long token being changed by the model, and silence while tools run).

Amazon Bedrock models in the evaluation (Claude Haiku 4.5, Amazon Nova Lite): a few minutes to the first call. Learning how to control the cost took a day.

Amazon Cognito with an AWS Lambda pre token trigger: the trigger page is thorough, and its table of claims that a trigger cannot change is the most useful part.

Amazon DynamoDB: the documentation is clear. The condition-expression rules and the long list of reserved words cost us a few failed runs.

AWS Lambda and Amazon EventBridge Scheduler (the background workers): quick. The low-level CfnSchedule construct needs its own IAM role, which the higher-level construct would hide.

AWS Lambda and Amazon API Gateway (HTTP API) for the owner console: about an hour from the generated stack to a working sign-in. Most of that hour went into packaging the code.

Amazon SNS: a few minutes. The topic and the e-mail subscription came from CDK.

Amazon S3: a few minutes.

AWS KMS: one API call to get random bytes.

AWS Secrets Manager: a few minutes.

AWS CDK (Python) and CloudFormation: about a day to a first reliable deployment of the AgentCore resources.

AWS Budgets: a few minutes.

FastMCP 3.4.7 and the MCP Python SDK 1.30.0: about an hour to a working server. The problems we met were found by reading the source, not the documentation.

Strands Agents SDK 1.57.1: a few minutes to a working agent.

Cedar and cedarpy 4.12.1: about a day to a first useful set of rules.

MCP Inspector: one npx command.

Amazon DynamoDB Local (Docker): a few minutes.

DeepSeek API: a few minutes.
```

## Feedback Question 5 (assumed): would you build with it again? Yes or no, and why

```text
Amazon Bedrock AgentCore Runtime: Yes, a plain zip with no Docker image ran the whole server.

Amazon Bedrock AgentCore Gateway: Yes, one front door with token checks and an interceptor, up in under a minute.

Amazon Bedrock AgentCore Policy: Yes, with the two-deploy order; plain Cedar files we could test locally.

Amazon Bedrock AgentCore Observability (CloudWatch Transaction Search): Yes, one trace per booking that shows which policy decided.

Amazon Bedrock with Amazon Nova 2 Sonic (voice): Yes, with a client that streams silence and short identifiers; a whole booking cost under two cents.

Amazon Bedrock models in the evaluation (Claude Haiku 4.5, Amazon Nova Lite): Yes, with a hard cap per trial; switching the model is one setting.

Amazon Cognito with an AWS Lambda pre token trigger: Yes, free for a demo and it added every claim our rules needed.

Amazon DynamoDB: Yes, conditional transactions gave exactly one winner in 30 of 30 concurrency rounds.

AWS Lambda and Amazon EventBridge Scheduler (the background workers): Yes, a one-minute clock released real holds and drew Fair Drops, free at this volume.

AWS Lambda and Amazon API Gateway (HTTP API) for the owner console: Yes, the same code runs locally and on AWS; watch the cold start.

Amazon SNS: Yes, a topic and e-mail subscription in seconds, free for the first 1,000 e-mails a month.

Amazon S3: Yes, a private encrypted bucket is a few lines of CDK.

AWS KMS: Yes, 32 random bytes with no key to manage.

AWS Secrets Manager: Yes, reading the value at run time; one construct generates and stores the secret.

AWS CDK (Python) and CloudFormation: Yes, cdk diff before every deploy and a clean rollback when one failed.

AWS Budgets: Yes, as a free alarm, remembering that it only warns.

FastMCP 3.4.7 and the MCP Python SDK 1.30.0: Yes, typed tools and stateless mode did what we needed once we knew the traps.

Strands Agents SDK 1.57.1: Yes, a working agent in minutes and models switch with one setting.

Cedar and cedarpy 4.12.1: Yes, the rules read like the owner's own rules and run in the server and at the Gateway.

MCP Inspector: Yes, for manual checks, though its command line hung on a -32042 error.

Amazon DynamoDB Local (Docker): Yes, it behaves like the real service for conditional writes and starts in seconds.

DeepSeek API: Yes, its OpenAI-compatible interface worked with our agent code unchanged.
```
