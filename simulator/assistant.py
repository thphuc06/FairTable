"""The simulated Alexa+ assistant: one Strands agent wired to the FairTable MCP server.

It carries the diner's access token in ``x-ft-user-token`` (the server re-verifies it) and has exactly
the server's eight tools. It has no way to approve a consent request; ``SimulatedUser`` does that.
"""

from dataclasses import dataclass
from typing import Self

from strands import Agent
from strands.models import Model
from strands.tools.mcp import MCPClient

from simulator.events import Step, transcript

USER_TOKEN_HEADER = "x-ft-user-token"
GATEWAY_PREFIX = "ft___"  # the Gateway target is called ft, and tools are named <target>___<tool>
SYSTEM_PROMPT = (
    "You are a voice assistant booking restaurant tables for the user through FairTable tools. "
    "Answer briefly, in plain spoken sentences. Follow each tool's next_step. If a booking needs the "
    "user's approval, give them the approval link and wait; never claim something is booked before "
    "reservation_confirm succeeds. Give every tool call that needs an idempotency_key its own new, unique key; "
    "repeat a key only when you retry the same call after being asked to."
)


@dataclass(frozen=True)
class Reply:
    text: str
    steps: list[Step]  # the tool calls made during this turn, in order
    tokens: int = 0  # tokens the model used this turn (0 for the scripted model)

    @property
    def consent_url(self) -> str | None:
        return next((s.result["consent_url"] for s in reversed(self.steps) if s.result.get("consent_url")), None)


class Assistant:
    """``async with Assistant(url, token, model) as a: reply = await a.say("book ...")``"""

    def __init__(self, mcp_url: str, user_token: str, model: Model, system_prompt: str = SYSTEM_PROMPT,
                 via_gateway: bool = False, tool_prefix: str = "") -> None:
        # Direct to the server: the token travels in x-ft-user-token. Through the Gateway it is a bearer token;
        # the Gateway checks it and its interceptor makes x-ft-user-token of it (infra/gateway/interceptor).
        headers = {"Authorization": f"Bearer {user_token}"} if via_gateway else {USER_TOKEN_HEADER: user_token}
        self._prefix = tool_prefix
        self._client = MCPClient(url=mcp_url, headers=headers)
        self._model = model
        self._system_prompt = system_prompt
        self._agent: Agent | None = None

    def __enter__(self) -> Self:
        self._client.__enter__()
        self._agent = Agent(model=self._model, tools=self._client.list_tools_sync(),
                            system_prompt=self._system_prompt, callback_handler=None)
        return self

    def __exit__(self, *exc: object) -> None:
        self._client.__exit__(*exc)

    @property
    def tool_names(self) -> list[str]:
        assert self._agent is not None
        return sorted(n[len(self._prefix):] if self._prefix and n.startswith(self._prefix) else n
                      for n in self._agent.tool_names)

    async def say(self, text: str) -> Reply:
        assert self._agent is not None, "use `with Assistant(...)`"
        before = len(transcript(self._agent.messages, self._prefix))
        used_before = self._agent.event_loop_metrics.accumulated_usage.get("totalTokens", 0)
        result = await self._agent.invoke_async(text)
        steps = [e for e in transcript(self._agent.messages, self._prefix)[before:] if isinstance(e, Step)]
        used = self._agent.event_loop_metrics.accumulated_usage.get("totalTokens", 0) - used_before
        return Reply(str(result).strip(), steps, used)
