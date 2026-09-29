# Hackathon rules – summary for this repo

Digest of the official rules and the event page, so nobody has to re-read the raw text. **The official pages always win:**
- Rules: https://amazonappdev2026.devpost.com/rules (text copied 2026-09-29, "September 16, 2026 UPDATE: Code repository")
- Event page / requirements: https://amazonappdev2026.devpost.com/
- FAQ: https://amazonappdev2026.devpost.com/details/faqs
- Resources: https://amazonappdev2026.devpost.com/resources (digested below)

## Event and dates (all Pacific Time)
- Amazon Developer Hackathon "Build, Ship, Shape" (online, run by Devpost).
- **Submission period:** 2026-08-31 10:15 → **2026-10-23 12:00** (= 2026-10-24 02:00 GMT+7).
- **Judging period:** 2026-11-09 12:00 → 2026-11-20 12:00. Winners announced around 2026-12-03.
- **AWS credits ($150):** request via the organizers' form (https://forms.gle/5hyhr1u6x3fuV2aW7) **before 2026-10-21 12:00 PT**, while supplies last. Not redeemable for cash; any extra AWS charges are ours. **Status: requested by the developer, no reply yet (2026-09-29).**
- Eligibility (summary): individuals of age of majority where they live, teams, organizations; not open to residents of comprehensively sanctioned countries (for example Russia, Cuba, Iran, North Korea, Brazil, Quebec) or to people connected to the organizers or judges.
- Each project can win **at most one track prize and one mini-challenge prize**. Several submissions are allowed only if substantially different.

## Our track: Alexa+
- Build a **self-hosted MCP server** (spec **2025-11-25 or later**, **Streamable HTTP**) **or** an Agent Skill. Alternative path: a **simulated Alexa+ experience** in a web app, built with any agentic tool; this path is exempt from the runtime-hook rule, but the repo must include the simulator's source and the video must clearly show it working.
- **Runtime hook (MCP server path):** the repo must import and actually call the required technology (library import, entry point, loaded MCP config). A README mention is not enough.
- The demo video must show the server (or simulation) **working**. Alexa+ preview tooling is not available to participants (FAQ, as recorded below), so we demo with our own simulator and web front end.
- Judging examples for Alexa+: *obvious* = single-turn Q&A bot, basic MCP wrapper around an existing API. *Creative* = agentic workflow orchestrating services autonomously, add-on that **keeps state across sessions**, purchasing, media cards/carousels, **MCP Apps**, Agent Skills.

## Mini challenge we target: AWS Builder
- Any primary-track project that uses AWS services (Bedrock, AgentCore, Strands SDK, Kiro Crew, SageMaker, …) **with documented integrations**. Describe which services and how in the **Product Feedback** answer.
- Kiro Crew used as a development tool qualifies on its own (no runtime AWS call needed). We do not use it.
- Judging examples: *obvious* = a single Bedrock call, S3 for storage. *Creative* = multi-service pipeline (Bedrock + AgentCore + Strands), agentic architecture, agent orchestration patterns.
- Prize: $5,000 cash + $5,000 AWS credits + meeting with the Amazon Developer team + featured on Amazon channels.
- **Open Source mini challenge: not targeted** (needs a separate additional project or contribution; one mini prize per project).

## What to submit (Devpost form)
1. **Text description:** features and how it works.
2. **GitHub repo** with all source, assets and run instructions. Public + open-source license visible in the About section (**ours: Apache-2.0**), **or** private and shared with `testing@devpost.com` and the six Amazon Developer Relations accounts (invitations expire after 7 days). We are public, so the collaborator steps do not apply.
3. **Demo video:** under 3 minutes, public on YouTube or Vimeo, in English, showing the project functioning on its intended platform. Best material first; judges need not watch past 3:00. No third-party trademarks or copyrighted music/footage.
4. **Product feedback for every tool, API or SDK used**, each answering: (a) what we used it for, (b) what worked well, (c) what needs work, (d) how onboarding felt (zero to hello world), (e) would we build with it again, yes/no and why. AWS services are described here.
5. **Tracks and mini challenges** entered.
6. If the project existed before the hackathon: what was built or changed during the window.
7. Optional **feature requests:** what, why, priority (critical / important / nice-to-have).
8. Optional **friction log entries:** task, steps, expected vs. actual, severity, workaround, actionable suggestion. **These are entered in the submission form** (our source is `docs/friction-log.md`). Amazon's internal review team scores them during Stage 1 and passes a **bonus of up to 10%** to the Stage 2 panel.

## Testing and availability
- The project must be accessible to judges **via the code repository and the demo video**. Judges **are not required to test** and may judge only from the description, images and video. A private site needs login credentials in the testing instructions (we list dev logins in the README).
- The project must be available **free of charge and without restriction** to the sponsor, administrator and judges **until the judging period ends (2026-11-20)**. In practice: keep the repo public and working, and keep the Docker path free of paid services.
- **No changes after the deadline:** once the submission period ends the submission cannot be altered (only the sponsor may allow removal of infringing material or personal data). Tag the submitted commit and do not push functional changes until judging ends.
- If the project runs on special third-party hardware the sponsor may ask for physical access (not our case).
- All submission materials (video, description, code documentation, testing instructions) must be in English.

## Judging
- **Stage 1 (pass/fail):** the project reasonably fits the theme and reasonably applies the required APIs/SDKs.
- **Stage 2:** four equally weighted criteria, plus the friction-log bonus:
  - **Tech Implementation:** how well it is built; how effectively it uses the required tech.
  - **Design:** a complete, coherent product experience; an interaction model suited to the target device.
  - **Potential Impact:** a specific, credible case for real customer needs beyond the hackathon.
  - **Quality of the Idea:** creative use of the tools; understanding of the developer ecosystem and end-user needs.
- Judging may use expert panels, peer review and **automated AI-driven analysis**. Tie-break: the higher score on the earlier-listed criterion.

## Alexa+ track prizes
1st: $25,000 cash + $15,000 AWS credits + meeting + featured. 2nd: $15,000 + $5,000 credits + featured. 3rd: $4,000 + $1,000 credits + featured. (Total event value about $190K.) Prizes need identity verification and tax forms (W-8BEN for non-US residents).

## Clarifications from the official FAQ
Recorded 2026-09-29 by the developer (the FAQ page itself is not among the saved files; see `docs/DECISIONS.md`). The official pages still win if they differ.
- **Hosting is not required.** For the Alexa+ track, a locally runnable public repo plus the demo video is enough; judges may build and run it themselves.
- **"Self-hosted" meaning:** our own MCP server, as opposed to Amazon's gated Alexa+ tools (not available to participants), demoed through our own web front end.
- **Open Source mini challenge:** needs a separate additional project or contribution; a project can win only one mini-challenge prize. We target **AWS Builder only**.
- **Models and credits:** model choice is up to us. A Bedrock access block is an AWS Support matter, not an organizer one. The FAQ recommends stubbing Bedrock early.
- **Judging period:** Nov 9–20, possibly including automated AI-driven review. The README must give clear setup and run instructions that work from a fresh clone. Do not rely on AWS resources still running during judging.
- **License:** must stay visible in the repo's About section (already done).
- **Demo video (our own decision, D-011):** show the local profile and the AWS-deployed path at least once, since we enter the AWS Builder mini challenge.

## Resources page (digest)
The saved text has link names but no URLs; open the official page for the links.
- **The two links the Resources page gave for Alexa+** (checked 2026-09-29): (1) https://apps.extensions.modelcontextprotocol.io/api/ "Build with Agent Skills" is the **MCP Apps** documentation (interactive UIs for tools, declared with `ui://` resources and `_meta.ui`, rendered in a sandboxed iframe by the host; its "skills" are AI-assistant helpers such as `create-mcp-app` and `add-app-to-server`, with Python server examples). (2) https://modelcontextprotocol.io/specification/2025-11-25/basic/transports#streamable-http is the transport spec we implement (single MCP endpoint, Origin validation MUST, optional `MCP-Session-Id`, `MCP-Protocol-Version` header).
- **Alexa+:** the page only says to build an MCP integration on the open standards (Agent Skills, Streamable HTTP) and that an Alexa+ experience may be simulated in a web app. It offers **no Alexa+ SDK, simulator or sample code**, which matches the FAQ note that Alexa+ tooling is not available to participants. Linked topics: "Build with Agent Skills", "Streamable HTTP transport".
- **AWS Builder:** Bedrock, AgentCore, Strands SDK, Kiro, SageMaker and more count. "The AWS free tier is enough to get started." Help: AWS Builder Center and "Learn on Builder Center" (tutorials for Bedrock, AgentCore, Kiro).
- **Credits:** the same $150 request form is linked here ("while you build").
- **Help channels:** live office hours with the Amazon Developer team (schedule and join link on the landing page), the Developer Community forum (Fire TV, Alexa, Ring), AmazonAppDev on YouTube, Amazon Developer documentation, sample code on GitHub.
- Not relevant to us: Fire TV, Bee and Ring starter samples; Amazon Devices Builder Tools (Fire OS / Vega OS); Hacktoberfest note for the Open Source challenge.
- Related official page found by search (not in the saved files): Alexa+ MCP Toolkit overview, https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-overview.html. It states Alexa+ supports MCP 2025-11-25 over Streamable HTTP and does **not** mention URL-mode elicitation or -32042 (see `docs/DECISIONS.md` D-014, open point).

## What this means for FairTable
- The local Docker profile is the deliverable judges can run; the AWS path is shown in the video and documented (`docs/aws-integration.md`). No conflict between "available until 11-20" and "do not keep AWS running": availability is the repo plus the video.
- Because the repo must keep working until 11-20, **pin everything a fresh clone downloads**: exact Python dependency versions (lock file) and a fixed DynamoDB Local image tag instead of `latest`.
- Strands SDK is a listed AWS service; the simulator uses it in code, which supports the AWS Builder claim even in the local profile.
- Creative-idea signals worth showing in the video: state kept across sessions (mandates, holds, waitlists, Fair Drop), agents that recover from structured errors, step-up consent outside the conversation. **MCP Apps** is named as creative for Alexa+ (currently a "Should", not scheduled; ask before starting).
- The friction log and the five product-feedback answers per tool are part of the score; keep both current (task P4-3).
