# Demo video script (target 2:45, limit 3:00) and preparation

Rules of the form (see `hackathon-rules.md`): under 3 minutes, public on YouTube or Vimeo, in English, shows the project
working on its intended platform, best material first (judges need not watch past 3:00), no third-party trademarks or
copyrighted music or footage. Our own decision (D-011): show the local Docker profile **and** the AWS path once.

## Story in one sentence
Independent restaurants cannot trust an AI booking agent; FairTable is the front door the restaurant controls: verified
identity, the owner's rules, a spoken yes that the server guards, and a fair lottery for the hot tables.

## As made (final video, 2:53, 2026-10-06)
The video was cut from recordings of the real system and is not part of the repository (it is uploaded to YouTube; the link is in the Devpost form). Order of the scenes:

| Time | Scene | What it shows |
|---|---|---|
| 0:00-0:10 | The problem, as animated cards with their sources | one AI agent pinged a booking site hundreds of times an hour and its owner was banned (CNN, 23 Sep 2026); a $200 cancellation fee for a table nobody chose (CNN); 17x more diners seated through AI integrations in a year (OpenTable, Aug 2026); New York's fine of $1,000 a day for reselling a reservation (Restaurant Reservation Anti-Piracy Act); 412,000+ independent US restaurants |
| 0:10-0:22 | Who it is for, and how it differs from what exists | restaurants, diners and assistants; closed platforms decide for the restaurant (only approved agents), tools that drive a diner's own account leave nobody in charge (the diner can be banned), FairTable lets the restaurant decide |
| 0:22-0:48 | The AWS architecture, with a spotlight on each part | Cognito, the Gateway and its interceptor, Policy, the Runtime, one DynamoDB transaction, the schedule that draws the lottery, S3 and SNS |
| 0:48-1:26 | **By voice, on AWS** (a Polly voice as the diner, Amazon Nova 2 Sonic as the assistant) | a table at Ember Grill; the $25 fee is read back; the diner says yes; the booking code; every tool call stays on screen |
| 1:26-1:31 | The owner console | the owner lowers the assistants' share of seats to zero |
| 1:31-2:00 | Two refusals by voice | a party of twelve (rule G3 at the Gateway) and a day whose share is used up (rule S2), each with the server's reason in the trace |
| 2:00-2:24 | A Fair Drop | eight diners already in (entered by a script), one enters by voice |
| 2:24-2:42 | The public proof page of that draw | the diner pastes her ticket and finds her place (number 8 of 9, not picked); Verify passes six checks in the browser; one changed result fails two |
| 2:42-2:49 | The numbers | 0 violations in 320 trials against 28 without rules; 12 of 12 attacks blocked |
| 2:49-2:53 | Close | open source, one command |

Honest notes (also in the video description): the narration and the diner are Amazon Polly voices; the assistant's long answers are fast-forwarded and then held on screen with the full text and tool calls; the draw time was set to a few minutes after entry (labelled "Demo" on screen; normally 24, 12, 6 or 2 hours before the seat); the draw itself ran on AWS (the Lambda every minute, a seed from KMS); the example diner lost, and that result is shown as it came.

## Original plan (before recording; kept for reference)

### Storyboard of the plan

| Time | Screen | What is said or done | Proof it shows |
|---|---|---|---|
| 0:00–0:12 | The architecture diagram (AWS page), then the chat page | "AI agents can book tables, but a small restaurant cannot tell a real diner from a bot. FairTable is a self-hosted MCP server that gives it a front door." | the problem and the product |
| 0:12–0:50 | **Local profile**, chat page, signed in as `diner-alice` | Type: *Book a table at Luna Trattoria for 2 tomorrow at 7pm*. The assistant holds and reads the details back. Type *Yes, please*. Open the tool calls under the answer. Then type *Book Luna for eleven people*: refused, "call the restaurant". | the 7 tools; read-back then yes; rule G3; no AWS account needed |
| 0:50–1:35 | **AWS path**, voice page (`/voice`), `diner-bob`, headphones | Say: *Book a table at amber grill for two people tomorrow at seven in the evening.* The assistant asks whether it means Ember Grill; say *yes*. It reads the $25 cancellation fee back; wait the 6 seconds, say *Yes, book it*. Show the lights, the status line while a tool runs, and the tool calls under the answer. | Nova 2 Sonic through the Gateway, Policy and Runtime; a misheard name is confirmed; the fee guard (6 s pause) |
| 1:35–2:10 | A Fair Drop: the owner creates it in the hosted console (`owner-luna`: pick a seat, the commitment appears; 10 seconds), then two diners are entered and the draw of a drop prepared earlier (the schedule fires within a minute); the winner's notice in the mailbox; the audit JSON | "The hot Friday seat is not first come, first served. Entries are drawn by an order that anyone can recompute." Show the e-mail from SNS and `verify_audit` passing on the S3 copy. | Fair Drop, commitment and reveal; EventBridge Scheduler and Lambda; SNS; S3; KMS |
| 2:10–2:40 | `eval/reports/mock-k4-2026-10-02.svg` and the red-team table | "A0 is an open storefront, A1 is FairTable. Under 40 tasks and 12 attacks: A0 had 28 violations and let all 48 attacks through, A1 had none and blocked 12 of 12." Say that the numbers use a scripted model (they validate the harness and the rules, not a real model). | measured evidence, honestly labelled |
| 2:40–2:50 | Repo page and the services table | "Apache-2.0, runs with `docker compose up`. Built with AgentCore, Cognito, DynamoDB, Lambda, SNS, S3, KMS and Nova 2 Sonic." | the AWS Builder claim |

Keep the best material first: if the cut is long, drop the Fair Drop scene before the voice scene.

Not yet verified by voice (check in the rehearsal): that the Ember booking is read back with its fee and the 6 second pause, and the exact wording of the question about Ember Grill.

## Before recording (one day earlier)
0. If the owner console is shown from AWS: deploy it (`OWNER_WEB=true` with `aws_ctl.py up --runtime`, or `cdk deploy FairTableOwnerWeb` alone) and open `/login` once just before the take: the first request after a deploy or a quiet hour can take 5 to 15 seconds (cold start, D-068). A draw cannot be shown for a drop created on camera (the earliest draw is 2 hours before its seat), so prepare the drop to be drawn beforehand.
1. Bring the AWS side back (about 15 minutes, a few tens of cents for the day; remove it again when the footage is done):
   `NOTIFY_EMAIL=<address> MCP_ALLOWED_HOSTS='*.lambda-microvm.*.on.aws' GATEWAY_POLICY=ENFORCE OBSERVABILITY=true OBSERVABILITY_RUNTIME=true python infra/aws_ctl.py up --runtime`
2. Reseed with fresh dates and KMS seeds: `SEED_PROVIDER=kms python infra/aws_ctl.py seed` (the Fair Drop dates move forward).
3. Run the real-AWS tests once: `pytest -m aws tests/aws` (set `AWS_TEST_DINER` and `AWS_TEST_WAITER` to diners that hold nothing).
4. Start the web app for the voice page: `.\scripts\voice_demo.ps1 -Profile <aws-profile> -Python <path to the fairtable env python>`; open `/voice`.
5. Run one full rehearsal of every scene. Check the mailbox receives the notice and that the S3 audit object appears.
6. Local scene: `docker compose up -d --build --wait`; seed is part of the stack.
7. Hide the e-mail address and the account id in anything that is shown (blur or crop); show only `diner-*` logins.

## Things to avoid
- Reading ids or codes aloud; the assistant must say only names, dates and the booking code after a booking.
- Claims the numbers cannot carry: say "scripted model" for the evaluation; say that the server cannot hear the diner (the yes is relayed and guarded, not proven).
- Logos of Amazon or Alexa (third-party marks); text names are fine.
