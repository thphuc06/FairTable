# Hackathon rules – summary for this repo

Summary of the requirements that matter for FairTable. **The official pages always win:**
- Rules: https://amazonappdev2026.devpost.com/rules
- FAQ: https://amazonappdev2026.devpost.com/details/faqs
- Resources: https://amazonappdev2026.devpost.com/resources

## Event
- Amazon Developer Hackathon "Build, Ship, Shape" (online, managed by Devpost).
- **Deadline: 2026-10-23 12:00 PT** (= 2026-10-24 02:00 GMT+7).
- Each project can win **at most one track prize and one mini-challenge prize**.

## Our track: Alexa+
- Build a **self-hosted MCP server** (spec **2025-11-25 or later**, **Streamable HTTP**) or an Agent Skill.
- The repo must **actually call** the required technology in code (imports, an entry point, a loaded MCP config) – a README mention is not enough.
- The demo video must show the MCP server **working**.
- Alexa+ preview tooling is not available to hackathon participants, so the demo uses our own client/simulator.

## Mini challenges we target
- **AWS Builder:** use AWS services (e.g. Bedrock, AgentCore, Strands SDK) with **documented integrations**, and describe which services we used and how in the product feedback.
- **Open Source (optional):** a new, additional open-source project (with a license) or a contribution (branch/fork/PR) to a public repo during the hackathon window. Needs the contribution URL, repo URL, GitHub username, and a short description. *Ask the organizers whether the main repo counts as "additional".*

## What to submit
1. **Text description**: what the project does and how it works.
2. **GitHub repo** with all source code, assets, and run instructions. Either:
   - public with an open-source LICENSE (**our choice: Apache-2.0**), or
   - private and shared with `testing@devpost.com` and the Amazon team (invitations expire after 7 days).
3. **Demo video**: under 3 minutes, public on YouTube or Vimeo, in English. Put the best material first (judges may stop at 3:00). No third-party trademarks or copyrighted music/footage without permission.
4. **Product feedback** for every tool, API, or SDK used: what it was used for, what worked well, what needs work, how onboarding felt, and whether we would build with it again. Describe the AWS services used here.
5. **Tracks and mini challenges** entered.
6. If the project existed before the hackathon: what was built or changed during the window.
7. Optional **feature requests**: what, why, urgency (critical / important / nice-to-have).
8. Optional **friction log**: task attempted, steps, expected vs. actual, severity, workaround, actionable suggestion. **Up to a 10% judging bonus** → keep `docs/friction-log.md` updated while building.

## Judging criteria
- **Tech Implementation:** how well it is built and how effectively it uses the required APIs/SDKs.
- **Design:** complete, coherent product experience; interaction model suited to the target device.
- **Potential Impact:** a specific, credible case for real customer needs beyond the hackathon.
- **Quality of the Idea:** creative use of the tools; understanding of the developer ecosystem and end-user needs.

## AWS credits
- Registered participants can request **$150 in AWS Promotional Credits** via the organizers' form, **before 2026-10-21 12:00 PT**, while supplies last.
