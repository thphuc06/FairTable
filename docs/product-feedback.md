# Product feedback for the Devpost form (draft, written 2026-10-03)

The form asks, for **every tool, API or SDK used**, five things: (a) what we used it for, (b) what worked well,
(c) what needs work, (d) how onboarding felt (zero to hello world), (e) would we build with it again, and why.
Every statement below comes from something we ran or read; the evidence is in [`friction-log.md`](friction-log.md),
[`aws-integration.md`](aws-integration.md) and [`devlog/`](devlog/). Re-read before pasting: the form is the last step.

| Tool or service | Where its five answers are |
|---|---|
| Amazon DynamoDB, Cognito, Lambda (Cognito trigger), AWS Budgets, AWS CDK, AgentCore Runtime, Gateway, Policy, Observability | [`aws-integration.md`](aws-integration.md), "Per-service notes" |
| Amazon SNS, EventBridge Scheduler and the workers Lambda, Amazon S3, AWS KMS, Amazon Bedrock with Nova 2 Sonic, the owner console on Lambda and API Gateway, the Bedrock models and the DeepSeek API of the evaluation, DynamoDB Local | below |
| FastMCP and the MCP Python SDK, Strands Agents SDK, Cedar and `cedarpy`, MCP Inspector | below |

## Amazon Bedrock, Amazon Nova 2 Sonic (voice)
- *Used for:* the voice page. Browser microphone to a local web app to a bidirectional Bedrock stream (through the Strands `BidiAgent`); Nova 2 Sonic hears the diner, calls our seven MCP tools through the AgentCore Gateway with the diner's own token, and speaks the answer.
- *Worked well:* speech in, tool calls and speech out in one stream; the model called our tools in the right order (search, availability, hold, read back, confirm) with the diner's token; a whole booking conversation cost under two cents (about 3,300 tokens in, 1,400 out at $3 and $12 per million speech tokens); the transcript arrives with the audio.
- *Needs work:* (1) the stream ends with a `ValidationException` ("Timed out waiting for audio bytes") if the client stops sending audio, so a client must stream silence while the user is quiet; (2) one sentence in a system prompt made Bedrock answer "blocked by our content filters", and the message does not say which sentence; (3) the model changed one character of a 295-character signed token in nine of nine tries, but copied an 8-character id, an 11-character code and a 32-character id correctly in every trial, so identifiers meant for speech models must be short; (4) it stays silent while it calls tools (14 to 19 s here), and a prompt sentence asking it to say something first had no effect; (5) its audio arrives in 80 ms pieces at about the speed of speech, with gaps of up to 0.4 s, so a player needs a head start (0.3 s removed every gap in a replay of our measurements); (6) the user guide's Strands example uses module names that the installed `strands-agents` 1.57.1 does not have.
- *Onboarding:* about a day to a reliable spoken booking; most of it went into the points above, none of which is in the quick start.
- *Build again:* yes, with a client that streams silence and a short-identifier rule.

## Amazon SNS
- *Used for:* one topic for waitlist and Fair Drop notices; the developer's e-mail address is the one subscriber (a real service would need a per-user contact, which we say plainly).
- *Worked well:* topic and subscription from CDK in seconds; the confirmation e-mail arrived at once; free for the first 1,000 e-mails a month.
- *Needs work:* nothing found; the confirmation link must be clicked by hand, so it cannot be scripted end to end.
- *Onboarding:* minutes. *Build again:* yes.

## Amazon EventBridge Scheduler and AWS Lambda (the background workers)
- *Used for:* a schedule `rate(1 minute)` calls one Lambda (arm64, Python 3.12, the same zip as the Runtime) that releases expired holds, which offers the freed table to waiting diners, and draws Fair Drops that are due.
- *Worked well:* a real ten-minute hold that nobody touched was released by the clock; a due Fair Drop was drawn by the clock; the schedule produced ticks about a minute apart; the same pure functions that the server runs lazily were reused unchanged; free at 43,200 invocations a month.
- *Needs work:* a new account's Lambda concurrency limit is 10, so reserving one instance fails (a reservation must leave 10 unreserved); the CDK `logRetention` option is deprecated in favour of an explicit log group.
- *Onboarding:* quick; the L1 `CfnSchedule` needs its own role, which the L2 construct would hide. *Build again:* yes.

## Amazon S3
- *Used for:* a private copy of every Fair Drop audit (`drops/<id>.json`) so that anyone given the object can recompute the draw.
- *Worked well:* block-public-access, encryption and a TLS-only policy are three lines in CDK; `autoDeleteObjects` empties the bucket on teardown.
- *Needs work:* `autoDeleteObjects` adds a hidden Lambda and its log group to the stack, which is easy to forget in an inventory of what a teardown leaves.
- *Onboarding:* minutes. *Build again:* yes.

## AWS KMS
- *Used for:* `GenerateRandom`, the secret seed of each Fair Drop (the draw order is `HMAC-SHA256(seed, ticket)`, and the commitment `SHA-256(seed)` is published first).
- *Worked well:* 32 random bytes with no key to create, manage or pay for; $0.03 per 10,000 requests after 20,000 free a month.
- *Needs work:* nothing found. *Onboarding:* one API call. *Build again:* yes.

## FastMCP 3.4.7 and the MCP Python SDK 1.30.0
- *Used for:* the MCP server (spec 2025-11-25, Streamable HTTP, stateless) with seven tools and one resource.
- *Worked well:* tools with typed arguments and `readOnlyHint` annotations; stateless mode matches what AgentCore Runtime and the Alexa+ client send; middleware for telemetry and error mapping; `mask_error_details=True` hides unexpected exceptions and leaves structured results alone.
- *Needs work:* (1) raising `UrlElicitationRequiredError` inside a tool did not reach the client as error -32042 (FastMCP turns it into a generic error); (2) Host and Origin protection are off by default (`host_origin_protection=False`), which the quick start does not say; (3) an ordinary exception in a tool logs a full traceback at ERROR for every business refusal, which drowns real bugs (we raise a `ToolError` with `log_level=INFO`); (4) a wrong-typed argument becomes a `fastmcp.exceptions.ValidationError` that is not a `ToolError`, so a middleware that catches `ToolError` misses it; (5) `task=True` needs the optional `pydocket` package.
- *Onboarding:* an hour to a working server; the traps above were found in the source, not the documentation.
- *Build again:* yes.

## Strands Agents SDK 1.57.1
- *Used for:* the simulated assistant (an agent with the MCP client, on a scripted mock, DeepSeek or Bedrock model) and the voice agent (`BidiAgent` with `BedrockNovaSonicModel`).
- *Worked well:* an MCP client that lists and calls the tools of our server, over the Gateway as well as directly; model providers switch by one setting; the bidirectional agent streams audio, transcripts and tool calls as events.
- *Needs work:* (1) the MCP client with `sse-starlette` and `uvicorn` in one pytest process hung the whole suite (the server closed the event stream while the client waited); (2) with a thinking model through the Chat Completions class every turn after the first logs that `reasoningContent` is not supported; (3) the voice features need the `bidi` extra and the module names differ from the Nova 2 user guide.
- *Onboarding:* a working agent in minutes. *Build again:* yes.

## Cedar and `cedarpy` 4.12.1
- *Used for:* the rules, in the same language at two enforcement points: G1 to G4 (stateless, at the Gateway as AgentCore Policy and again in the server) and P0 and S1 to S5 (stateful, in the server).
- *Worked well:* the policies read like the owner's rules; `forbid`/`permit` with default deny maps cleanly to "refuse unless allowed"; annotations (`@id`, `@on_deny`) let us return the rule that refused; the same policy files are tested locally, and G1 to G4 were accepted by AgentCore Policy (one statement needed a rewrite after the service called it "overly restrictive").
- *Needs work:* `cedarpy` reports reasons as `policy0…policyN` (an index), so the table from index to `@id` must be built from the same text that was evaluated; a forbid whose condition touches a missing attribute is skipped and only appears under `diagnostics.errors` (we guard with `has`).
- *Onboarding:* a day for a first useful rule set. *Build again:* yes.

## MCP Inspector
- *Used for:* manual checks of the server in the first days.
- *Worked well:* custom headers and structured results are easy to inspect.
- *Needs work:* in CLI mode a tool call that ends in JSON-RPC error -32042 printed nothing and never returned.
- *Onboarding:* one `npx` line. *Build again:* yes, for manual checks.

## AWS Lambda and Amazon API Gateway (HTTP API): the owner console
- *Used for:* the restaurant owner's console (sign-in through Cognito, cancellation terms, Fair Drops, audit). One arm64 Python 3.12 Lambda runs the same FastAPI app as the local profile through Mangum; an HTTP API with a `$default` route and a throttled stage fronts it.
- *Worked well:* the same code runs locally and on AWS with no change besides the entry point; the stack deployed in 65 seconds; the generated session secret is handed over as a dynamic reference; stage throttling is two properties.
- *Needs work:* (1) the first request after a deploy took 7.8 s (cold start of a 95 MB package); (2) under 60 concurrent requests we saw 503 answers that we could not tell apart from the account's Lambda concurrency limit of 10 in the API's own logs; (3) the CDK property `user_pool_client_secret` adds a custom resource to the identity stack, while the L1 `GetAtt` does not; (4) the price page of API Gateway loads its numbers by script, so it cannot be read with a plain download.
- *Onboarding:* about an hour from the synthesised stack to a working sign-in; most of it went into packaging. *Build again:* yes.

## Amazon Bedrock models used by the evaluation (Claude Haiku 4.5, Amazon Nova Lite) and the DeepSeek API
- *Used for:* the real-model runs of the evaluation (D-064): the same 40 tasks, with a model playing the diner and the assistant. Haiku and Nova Lite through Strands `BedrockModel`; DeepSeek flash through its OpenAI-compatible API.
- *Worked well:* switching the model is one setting; every model kept the rules at zero violations; per-trial token counts are available.
- *Needs work:* (1) Nova Lite fell into tool-call loops that ended in `maximum recursion depth exceeded`; each loop turn re-sends the whole conversation, so three loops and a few cut-short jobs cost about $4.2 (94 million input tokens) while our own report counted 2.3 million, because failed trials report no tokens; the agent loop has no default cap on model calls or tokens; (2) `modelStreamErrorException` ("invalid sequence as part of ToolUse") ends a conversation; (3) `ValidationException: A conversation must start with a user message` after a long conversation; (4) a new account's quotas and Cost Explorer lag made the real spend visible only a day later.
- *Onboarding:* minutes to the first call; the cost control took a day to learn the hard way. *Build again:* yes, with a hard cap per trial and the cost read from CloudWatch.

## Amazon DynamoDB Local (Docker)
- *Used for:* every integration test and the local profile (`docker compose up`): the same table definition and the same `TransactWriteItems` as on AWS.
- *Worked well:* behaves like the service for conditional writes and transaction cancellations, which is what our concurrency tests need; starts in seconds.
- *Needs work:* nothing found beyond pinning the image by digest. *Onboarding:* minutes. *Build again:* yes.
