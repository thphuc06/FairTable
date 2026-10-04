## Inspiration

On 23 September 2026 CNN reported what happens when AI agents meet restaurant booking systems. A diner's agent pinged Resy "hundreds of times every hour" and the diner's account was locked ("Of course I got banned. Resy figured it was a bot."). Another agent booked a Tokyo restaurant its owner had never suggested and cost him a $200 cancellation fee. A restaurateur warned: "When the entire system is gamed, you create an environment where those excited by a place can't even go." ([CNN, via KTVZ](https://ktvz.com/money/cnn-business-consumer/2026/09/23/now-ai-is-trying-to-gobble-up-dinner-reservations/))

Both sides lose. Diners get banned for using an assistant, and independent restaurants, which have no platform to protect them, have nothing to tell a good agent from a bad one. Missed reservations are already a cost: in OpenTable's survey, 30% of Americans said they had not shown up for a booking in the past year ([Restaurant Dive, 2021](https://www.restaurantdive.com/news/opentable-launches-initiative-to-combat-diner-no-shows/602034/)). Alexa+ will make agent bookings ordinary. The restaurant needs a front door it controls.

## What it does

FairTable is a self-hosted **MCP server** (spec 2025-11-25, Streamable HTTP) that an independent restaurant publishes for assistants such as Alexa+. It has seven plain, deterministic tools (search, availability, hold, confirm, manage, waitlist watch, waitlist status); there is no language model inside them.

- **Verified identity.** A booking needs a signed-in diner and a verified agent. A machine client can read but not write.
- **Rules the restaurant owns.** Written in Cedar and checked on every call: party size, active holds per diner, one table per diner and day, and the share of seats that assistants may take. The owner changes the share, the cancellation terms and Fair Drops in a console.
- **Confirmation by voice.** After a hold, the assistant reads the terms back and the diner says yes. The server checks that the read-back belongs to this hold, that a short pause has passed, and that the assistant states the diner said yes. It cannot hear the diner, so this stops mistakes (not asking, asking too fast, confirming other terms), not an assistant that lies on purpose.
- **Fair Drop.** A hot seat is given by lottery. The secret seed is committed (SHA-256) first and revealed after the draw, so anyone can recompute the result.
- **Standing waitlists.** An agent registers once; a freed table is held for the diner without polling.

**Who it is for:** independent restaurants (owners and their staff), diners who use an assistant, and the assistant vendors, Alexa+ first. Scope: reservations, waitlists and hot-table drops for a restaurant. Not payments, not a marketplace.

## How we built it

Python 3.12, FastMCP 3.4.7 on MCP SDK 1.30.0, `cedarpy` for the rules, Strands Agents for the simulated assistant. Every state change is one DynamoDB `TransactWriteItems` (slot, counters, hold, idempotency record, audit), so conditions in the database are the final word under concurrency.

- **Local profile (what you run):** `docker compose up` starts the server, DynamoDB Local, a token issuer, and the chat page and owner console. No AWS account, no model account.
- **AWS profile (built and tested on a real account):** AgentCore Runtime runs the server from a zip; AgentCore Gateway is the front door (Cognito tokens, a request interceptor, and AgentCore Policy repeating the stateless Cedar rules); AgentCore Observability traces each booking; DynamoDB, Cognito, EventBridge Scheduler + Lambda (expired holds, Fair Drop draws), SNS, S3, KMS, API Gateway + Lambda (owner console), Bedrock (Nova 2 Sonic voice demo, Claude Haiku 4.5 and Nova Lite in the evaluation), all deployed with CDK.

## Challenges we ran into

- **The Alexa+ client cannot do a phone step-up.** My first design used an MCP consent request. It did not survive the AgentCore Gateway, and Amazon's client documentation does not support it, so I replaced it with the guarded voice confirmation above and stated its limit openly.
- **Speech models mangle long identifiers.** Nova 2 Sonic changed one character of a 295-character signed token in nine of nine tries, but copied 8-, 11- and 32-character codes correctly every time. Identifiers now are short.
- **Real-model evaluation can be costly.** Nova Lite fell into tool-call loops: about 94 million input tokens and roughly $4.2 while our report counted 2.3 million, because failed trials report no tokens. Future real-model runs get a hard cap per trial.
- **AgentCore Policy** validates after `CreatePolicy` returns, so a `forbid` created next to its `permit` can fail and hang the stack; two deploys avoid it. All of this is in the friction log.

## Accomplishments that we're proud of

- **Measured, not claimed.** The same 40 tasks run against an open storefront (A0) and FairTable (A1). Under A1 there were **0 violations in 320 trials** (scripted 160, DeepSeek 80, Claude Haiku 4.5 40, Nova Lite 40); the open storefront had 28 in the scripted run, 6 with DeepSeek and 13 with Nova Lite. A 12-attack red team (forged token, machine client writing, confirm without read-back, twenty simultaneous holds on one table, prompt injection, and more) was blocked 12 of 12. The runs are small and models sometimes decline to misbehave, so this is evidence, not proof.
- **The same rules everywhere.** One set of Cedar files runs in the server and at the AWS Gateway, tested by one behavioural suite.
- **A fully local, reproducible demo,** 1281 passing tests, and the owner console running on Lambda behind an API Gateway.

## What we learned

Put the rules outside the model. The assistant may be good, bad or manipulated; what keeps a booking honest is a deterministic check in the server and a database condition behind it. We also learned how much of an agent's reliability is in details nobody puts in a quick start: short identifiers for speech, stream silence to keep a voice session open, caps on loops. Details and our feedback on each tool are in the product feedback answer and the friction log.

## What's next for FairTable

- Test with a real Alexa+ (nobody outside Amazon can today); only a simulator was used.
- Owner sign-in with hosted login and MFA instead of the demo flow; onboarding a restaurant from its website (Amazon Nova Act with AgentCore Browser); editing Cedar rules from the console; changing the day or time of a booking.
- A way to prove the diner's yes, beyond the guarded relay.

Code: [github.com/thphuc06/FairTable](https://github.com/thphuc06/FairTable) (Apache-2.0). Run it with `docker compose up --build`; the README has test logins and a two-minute walkthrough.
