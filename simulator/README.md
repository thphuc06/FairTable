# simulator/

Alexa+ simulator: one Strands agent plus a simple chat page (plan tasks P1-18, P1-19). It is our own client for the MCP server, since Alexa+ preview tooling is not available to participants.

- `MODEL_PROVIDER=mock` is the default everywhere. The mock is a Strands `Model` that follows a scripted persona with seeded noise, so the eval harness is exercised without any model account. Numbers measured with it validate the harness, not model reliability.
- Other providers are opt-in through environment variables (`bedrock`: `BEDROCK_MODEL_ID`; `deepseek`: `DEEPSEEK_API`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`, plus the optional `openai` package). Nothing in the repo requires one.

| File | Role |
|---|---|
| `events.py` | Turns Strands messages into `UserSaid` / `Step` events the personas can read |
| `personas.py` | `decide(goal, events, noise)`: a pure function that picks the next tool call or sentence |
| `request.py` | Reads a diner's sentence into a `Goal` (chat page, mock only) |
| `model.py` | `ScriptedModel` and `build_model()` (`MODEL_PROVIDER`) |
| `assistant.py` | The Strands agent with the server's seven tools; it carries the diner's token in `x-ft-user-token` |
| `user.py` | `SimulatedUser`: the diner who answers the read-back aloud: yes, no or nothing (the evaluation harness knows what was said) |

## Scripted behaviours (`Goal.behaviour`)
After a hold the persona reads the details back and ends its turn; only when the diner has answered yes does it call `reservation_confirm` with the read-back token (D-051). The misbehaving variants exist so the evaluation has something to catch:

| Behaviour | What it does |
|---|---|
| `polite` | the flow above |
| `hot_direct` | tries a Fair Drop seat by hold instead of entering the draw |
| `eager` | confirms in the same breath as the hold, claiming a yes it never heard (rule S5b refuses) |
| `forgetful` | asks properly, but leaves the read-back token out of its first confirm (rule S5a refuses and hands over a new one) |
