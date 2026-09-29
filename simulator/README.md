# simulator/

Alexa+ simulator: one Strands agent plus a simple chat page (plan tasks P1-18, P1-19). It is our own client for the MCP server, since Alexa+ preview tooling is not available to participants.

- `MODEL_PROVIDER=mock` is the default everywhere. The mock uses scripted personas with seeded noise so the eval harness is exercised without any model account.
- Other providers (for example Bedrock) are opt-in through environment variables; nothing in the repo requires one.
- Simulator tools for the user side: `say`, `approve_consent`, `decline`.
