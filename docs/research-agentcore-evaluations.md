# Research: Amazon Bedrock AgentCore Evaluations (2026-10-03)

Written before any wiring (D-016: nothing is created in AWS until the developer says "wire AgentCore Evaluations"). Every
statement carries its source. **Verified** = read in the AWS documentation or seen in a live read-only call on the second account;
**Estimate** = our own arithmetic on stated assumptions; **Not verified** = open, to be checked when wiring.

Sources (AWS developer guide, `docs.aws.amazon.com/bedrock-agentcore/latest/devguide/`): `evaluations.html`,
`evaluations-types.html`, `evaluators.html`, `built-in-evaluators-overview.html`, `prompt-templates-builtin.html`,
`code-based-evaluators.html`, `ground-truth-evaluations.html`, `on-demand-evaluations.html`, `getting-started-on-demand.html`,
`batch-evaluations.html`, `online-evaluations.html`, `results-and-output.html`, `dataset-evaluations.html`, `simulation.html`,
`supported-frameworks.html`, `supported-frameworks-telemetry.html`, `supported-frameworks-strands.html`,
`supported-frameworks-generic.html`, `evaluations-prerequisites.html`, `bedrock-agentcore-limits.html`; the official price page
`aws.amazon.com/bedrock/agentcore/pricing/` (downloaded raw with curl and read as text, 2026-10-03).

## 1. What it is
A managed service that scores how well an AI **agent** did, from the **telemetry the agent emits** (OpenTelemetry spans in
Amazon CloudWatch), using LLM judges, programmatic checks or your own code. It answers "did the agent reach the user's goal, did it pick
and call the right tools, was the answer correct, helpful, safe", not "is the tool server correct". It is GA (the price page
and the release notes speak of general availability; some neighbours are still preview, see section 8).
- Works for agents hosted on **AgentCore Runtime** and for agents hosted **anywhere else** (ECS, EKS, Lambda, a laptop) if they export
  spans to CloudWatch with ADOT (`how-it-works-evaluations.html`, `supported-frameworks-telemetry.html`). Verified.
- Frameworks: Strands (Python and TypeScript, built-in telemetry, scope `strands.telemetry.tracer`), LangGraph, OpenAI Agents,
  LlamaIndex, Google ADK, Claude Agent SDK, Vercel AI SDK, and any agent that emits OpenTelemetry GenAI or OpenInference conventions
  (`supported-frameworks.html`). Verified.

## 2. Use cases (from the documentation)
- **Before release:** regression tests on a fixed set of scenarios, baseline then pre/post comparison after a prompt or model change.
- **In production:** continuous scoring of a sample of live sessions, dashboards, alarms on score drops.
- **Investigation:** score one chosen session or trace (a bad customer interaction, a fix to validate).
- **Domain rules:** custom evaluators for business rules a generic judge does not know.

## 3. Features
**Three evaluation types** (`evaluations-types.html`):

| Type | Trigger | Input | Output | Best for |
|---|---|---|---|---|
| On-demand | caller, synchronous (`Evaluate` API) | spans of one session, sent inline (downloaded from CloudWatch first) | immediate result | dev-time checks, CI |
| Batch | caller, asynchronous job | a CloudWatch log group, a time range or session ids; the service finds the sessions | per-evaluator averages and token usage, per-session detail in CloudWatch Logs | baselines, before/after, regression sets |
| Online | continuous | a log group it watches; percentage sampling and filters | CloudWatch Logs and metrics (`Bedrock-AgentCore/Evaluations`) | production monitoring |

**Evaluators.** Listed live with `aws bedrock-agentcore-control list-evaluators` (us-east-1, second account, read-only, 2026-10-03). Verified.
- *Built-in, LLM judge* (managed model, cannot be changed): trace level `Correctness`, `Faithfulness`, `Helpfulness`, `ResponseRelevance`,
  `Conciseness`, `Coherence`, `InstructionFollowing`, `Refusal`, `Harmfulness`, `Stereotyping`; session level `GoalSuccessRate`; tool-call level
  `ToolSelectionAccuracy`, `ToolParameterAccuracy`; skill level `SkillSelectionAccuracy`, `SkillInstructionFollowing`.
- *Built-in, programmatic* (no LLM call, session level): `TrajectoryExactOrderMatch`, `TrajectoryInOrderMatch`, `TrajectoryAnyOrderMatch`: compare the
  tool-call sequence with an expected one.
- *Third-party* (DeepEval, AutoEval, managed the same way): `Bias`, `Toxicity`, `PIILeakage`, `TaskCompletion`, `ConversationCompleteness`, `GoalAccuracy`, `ToolUse`, `Security`, and others.
- *Custom:* (a) **LLM-as-a-judge** with your own model, instructions and scoring scheme; (b) **code-based**: your own Lambda gets the session spans
  (schema `1.0`, levels `TRACE`, `TOOL_CALL`, `SESSION`, 6 MB payload, 5 minutes) and returns `{label, value, explanation}`; (c) an evaluator
  derived from a built-in one but run on your own model.
- **Ground truth** (`ground-truth-evaluations.html`): `expectedResponse` (for `Correctness`), `assertions` (natural-language statements for
  `GoalSuccessRate`), `expectedTrajectory` (tool names, for the trajectory evaluators); also available to custom evaluators.
- **Datasets and simulation** (`dataset-evaluations.html`, `simulation.html`): a runner invokes your agent over a set of scenarios, waits for the
  telemetry and evaluates; an LLM-backed *user simulator* with a persona and a goal can drive the conversation. **Dataset evaluation is public
  preview.**
- Results: CloudWatch Logs (a dedicated group `/aws/bedrock-agentcore/evaluations/results/<config-id>` or the source group), CloudWatch metrics, the
  GenAI Observability console (Agents, Evaluations tab). Optional customer-managed KMS key.
- Interfaces: AgentCore CLI (`agentcore run eval`), AgentCore Python SDK (`EvaluationClient`, `BatchEvaluationRunner`), AWS SDK
  (`bedrock-agentcore` for `Evaluate`, `bedrock-agentcore-control` for evaluators and configurations), console.

## 4. How it works
1. The agent emits spans. Each span says what it is through `gen_ai.operation.name`: `invoke_agent` (a whole run), `execute_tool` (one tool call),
   `chat` (one model call). Strands does this itself.
2. ADOT exports the spans to CloudWatch. **Transaction Search must be on** (both delivery modes). *Unified* telemetry (default for agents created
   from 2026-07-20; needs `aws-opentelemetry-distro>=0.18.0`) keeps prompts and tool inputs and outputs on the span; *split* sends them as
   separate event records. Both are read.
3. An evaluation reads the session's spans, rebuilds the conversation (user prompts, tool calls, assistant answers; the available tools) and fills a
   prompt template (placeholders `context`, `available_tools`, `assistant_turn`, `tool_turn`), or calls your Lambda, or does the programmatic
   comparison. Level decides the unit: a **session**, a **trace** (one turn), or a **tool call**.
4. A result is a label, a numeric value and an explanation, written to CloudWatch.
- Spans take **a couple of minutes** to appear in CloudWatch; evaluating immediately gives empty or partial input (`getting-started-on-demand.html`).
- An `Evaluate` call returns at most 10 results; one evaluator per on-demand call (`bedrock-agentcore-limits.html`).
- Judge model runs with **cross-region inference** inside the geography (`evaluations-cross-region-inference.html`); data stays stored in the source region.

## 5. How it fits AgentCore Runtime, and what that means for FairTable
- **For an agent on Runtime** the Runtime injects `session.id` and exports spans and logs to `/aws/bedrock-agentcore/runtimes/<agent_id>-<endpoint>`;
  the agent only needs ADOT in its requirements (`getting-started-on-demand.html`). Online evaluation then watches that log group
  (`dataSourceConfig.cloudWatchLogs.logGroupNames` and `serviceNames`).
- **FairTable's Runtime does not host an agent.** It hosts the MCP **server** (seven tools). The agent is the Strands simulator (text chat and the
  Nova 2 Sonic voice agent) that runs on the developer's machine. Consequences, all from the documentation:
  1. The server's own spans cannot be scored: the service explicitly **excludes MCP, `botocore` and HTTP-framework scopes** from generic support
     (`supported-frameworks-generic.html`). Evaluations judges the **agent's behaviour**, not the server's rules.
  2. The agent counts as "hosted outside Runtime": its spans must be exported to a log group of our choice with ADOT
     (`OTEL_EXPORTER_OTLP_TRACES_HEADERS`; the exact variables are in `observability-configure.html#observability-configure-3p`, **not read yet**).
  3. The tool results the agent sees (structured errors with `rule_id`, `next_step`) are in the `execute_tool` spans, so a judge or a Lambda can use them.
  4. The agent does not have to talk to the deployed Gateway. It can call the local server (free) and still be evaluated on AWS: only CloudWatch
     and the evaluation are billed. That decouples this feature from the 15-minute redeploy of Runtime and Gateway. (If the footage should show
     the whole chain, the agent calls the Gateway as in the voice demo and the same spans are produced.)
  5. Running the simulator **on a second Runtime** would give the "agent on Runtime" picture but adds the service that cost most so far
     (AgentCore $0.479 of $0.631, mostly Runtime). Not recommended.
- **What it adds to what we have.** Our harness (D-057, D-064) grades end state and invariants with code. AgentCore Evaluations would add an
  independent, AWS-side, LLM-judged view of the same conversations (did the agent reach the goal, did it call the tools in the right order), managed
  dashboards and alarms, and a place for our deterministic rules as a **code-based evaluator** (for example "no `reservation_confirm` before a
  `reservation_hold` result and a user message that says yes", read from the spans). It does not replace the harness: the safety numbers still come from the harness.

## 6. Billing (official price page, 2026-10-03; us-east-1 list prices) Verified
| Item | Price |
|---|---|
| Built-in evaluators, input tokens | $0.0024 per 1,000 ($2.40 per million) |
| Built-in evaluators, output tokens | $0.012 per 1,000 ($12 per million) |
| Custom evaluators | $1.50 per 1,000 evaluations; **model usage billed separately** in our account (a code-based evaluator in Lambda: Lambda is free at this size) |
| Batch evaluations | $0.0018 per 1,000 input tokens, $0.009 per 1,000 output tokens (25 % below the standard rate) |
| Model usage of built-in evaluators | included |
| Insights (optimization) | free in public preview; Recommendations free |
| Spans, logs, metrics | standard CloudWatch prices (ingestion, storage, queries) |

The official example (3 built-in trace evaluators, 15,000 interactions a month, 15,000 input tokens each) comes to $1,804.50 a month; that is a
production sizing, not ours. Not verified: how the **programmatic trajectory evaluators** are billed (they use no LLM; the page speaks of tokens for built-ins).

**Estimate for FairTable** (assumptions: a judge sees the whole transcript, about 10,000 input and 300 output tokens for a session-level evaluation; the real
number must be measured on a first run, the batch result reports token usage):
- `GoalSuccessRate`, standard rate: 10,000 x $2.40/M + 300 x $12/M = $0.0276 per session. 40 sessions: about **$1.10**; 10 sessions: $0.28; batch rate: $0.0207 per session.
- Tool-call evaluators run once per tool call (about 4 per session in our runs), each with a growing context: roughly four times the session price. Skip them or use 5 sessions.
- One code-based evaluator on 40 sessions: 40 x $0.0015 = **$0.06**.
- Agent model for the sessions (Nova Lite, measured about 19,000 tokens a trial): well under $0.01 for 40 sessions. CloudWatch: not measured, expected cents.
- Plan: first 5 sessions with `GoalSuccessRate` plus the three trajectory evaluators plus the code-based one (about $0.15) to read the real token count, then the 40-task set once if the budget allows
  (about $1.2 in total). Against the $5 cap of the second account, of which $0.63 was used on 2026-10-02 (the Bedrock model costs of 2026-10-03 are not in Cost Explorer yet).

## 7. Quotas (`bedrock-agentcore-limits.html`) Verified
1,200 built-in evaluations a minute and 1,000,000 input tokens a minute (on-demand); 20,000 spans and 200 MB per on-demand evaluation and per sampled session;
200,000 input tokens per evaluation; 25 evaluators per online configuration; 1,000 online configurations per account; 1,000 evaluation configurations per region.
Far above anything we send.

## 8. Risks and open points
- **Not verified:** exact ADOT variables for an agent outside Runtime; whether the Strands 1.57.1 tracer (pinned, D-063) produces the attributes the service reads
  with a non-Bedrock model object (DeepSeek) and with `MCPClient` tools; whether Transaction Search is still on after the Observability stack was destroyed
  (an account setting, check `aws xray get-trace-segment-destination` or `aws logs describe-resource-policies` before starting); whether the voice agent (`BidiAgent`) spans are readable (use the text agent).
- **Not verified:** the service's availability in other regions. Seen in us-east-1 on the second account: the live `list-evaluators` call answered with 31 evaluators.
- **Preview parts** to avoid in the story: dataset evaluation (public preview), Insights.
- The built-in judge cannot be changed; a custom judge (Bedrock model of our choice) costs the $1.50 per 1,000 plus tokens.
- Telemetry arrives after minutes; the wait has to be scripted (poll the log group), never a fixed sleep.
- Teardown: evaluators, configurations and result log groups are resources; delete them with the rest (`aws_ctl.py down`) once the footage is done, and say what is left.

## 9. Proposed wiring (needs the developer's "wire AgentCore Evaluations")
1. Check Transaction Search; enable it if needed (CloudWatch ingestion prices apply; already used by D-050).
2. Add an opt-in telemetry switch to the Strands agent path of `simulator/` (off by default; the local profile and the judges' `docker compose up` do not change): ADOT env variables, a session id per trial.
3. Run 5 trials against the local server with Nova Lite; wait for the spans; read the real token count.
4. Create the evaluators: built-in `GoalSuccessRate` and `TrajectoryInOrderMatch` with ground truth derived from the YAML tasks (`assertions`, `expectedTrajectory`); one **code-based** evaluator (Lambda, CDK, tag `project=fairtable`) for the confirmation rule; a batch job over the 40 sessions.
5. Store the result as `eval/reports/agentcore-<date>.md` with the scores, the token usage and the price paid; write D-0xx, devlog, friction log, `docs/aws-integration.md`, product feedback.
6. Teardown script entries; `status` afterwards.
Size: 1 to 1.5 days, about $1 to $1.5 (estimate above). Alternative if the budget or the time is short: only the code-based evaluator on 5 sessions (about $0.10), which still shows the service and the integration.
