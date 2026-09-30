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
| `assistant.py` | The Strands agent with the server's eight tools; it carries the diner's token in `x-ft-user-token` |
| `user.py` | `SimulatedUser`: signs in and approves or declines on the consent page, which the assistant cannot do |
