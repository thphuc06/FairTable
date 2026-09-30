"""The model behind the simulated assistant, chosen by ``MODEL_PROVIDER`` (D-003, D-018).

* ``mock`` (default everywhere): ``ScriptedModel``, a Strands ``Model`` that follows a persona
  (``simulator/personas.py``). No account, no network, no cost. Numbers measured with it validate the
  harness; they say nothing about how a real model behaves.
* ``bedrock``: Strands' ``BedrockModel``. Blocked on the developer's account for now (friction log), so
  it is built only when asked for and needs ``BEDROCK_MODEL_ID``.
* ``deepseek``: Strands' ``OpenAIModel`` pointed at DeepSeek's OpenAI-compatible API. The key comes from
  ``DEEPSEEK_API``. Base URL and the light "flash" model are the defaults below (from DeepSeek's API docs,
  2026-09-30, D-028); ``DEEPSEEK_BASE_URL`` and ``DEEPSEEK_MODEL`` override them. Needs the ``openai``
  package (Strands' OpenAI model class imports it).

No LLM is ever called inside an MCP tool; models exist only in the simulator and the eval harness.
"""

import json
import os
from collections.abc import AsyncGenerator, AsyncIterable, Mapping
from datetime import UTC, date, datetime
from typing import Any

from strands.models import Model

from simulator.events import UserSaid, transcript
from simulator.personas import NO_NOISE, Call, Goal, Noise, Say, decide
from simulator.request import parse_request

PROVIDERS = ("mock", "bedrock", "deepseek")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-flash"
HELP = ("Tell me what to book, for example: book a table at Luna Trattoria for 2 tomorrow at 7pm. "
        "I can also put you on a waitlist or cancel a booking.")


class ProviderError(Exception):
    """The chosen model provider is not set up; the message says what is missing."""


class ScriptedModel(Model):
    """A model that is really a persona. With a fixed ``goal`` (eval tasks) it always pursues it; without
    one it reads the goal from what the diner typed (the chat page)."""

    def __init__(self, goal: Goal | None = None, noise: Noise = NO_NOISE, today: date | None = None) -> None:
        self._goal = goal
        self._noise = noise
        self._today = today
        self.config: dict[str, Any] = {"model_id": "scripted-persona"}

    def update_config(self, **model_config: Any) -> None:
        self.config.update(model_config)

    def get_config(self) -> Any:
        return self.config

    def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        raise NotImplementedError("the scripted model has no structured output")

    def _goal_from(self, events: list) -> Goal | None:
        if self._goal is not None:
            return self._goal
        today = self._today or datetime.now(UTC).date()
        for e in events:
            if isinstance(e, UserSaid) and (g := parse_request(e.text, today)) is not None:
                return g
        return None

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs: Any) -> AsyncIterable[dict]:
        events = transcript(list(messages))
        goal = self._goal_from(events)
        action = decide(goal, events, self._noise) if goal is not None else Say(HELP)
        n_calls = sum(1 for m in messages for b in m.get("content", []) if "toolUse" in b)
        async for event in _emit(action, f"sim-call-{n_calls + 1}"):
            yield event


async def _emit(action: Call | Say, tool_use_id: str) -> AsyncGenerator[dict, None]:
    yield {"messageStart": {"role": "assistant"}}
    if isinstance(action, Call):
        yield {"contentBlockStart": {"contentBlockIndex": 0,
                                     "start": {"toolUse": {"toolUseId": tool_use_id, "name": action.tool}}}}
        yield {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"toolUse": {"input": json.dumps(action.args)}}}}
        yield {"contentBlockStop": {"contentBlockIndex": 0}}
        yield {"messageStop": {"stopReason": "tool_use"}}
    else:
        yield {"contentBlockStart": {"contentBlockIndex": 0, "start": {}}}
        yield {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": action.text}}}
        yield {"contentBlockStop": {"contentBlockIndex": 0}}
        yield {"messageStop": {"stopReason": "end_turn"}}
    yield {"metadata": {"usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0}, "metrics": {"latencyMs": 0}}}


def build_model(
    provider: str | None = None, *, env: Mapping[str, str] | None = None, goal: Goal | None = None,
    noise: Noise = NO_NOISE, today: date | None = None,
) -> Model:
    env = os.environ if env is None else env
    provider = (provider or env.get("MODEL_PROVIDER") or "mock").lower()
    if provider == "mock":
        return ScriptedModel(goal, noise, today)
    if provider == "bedrock":
        model_id = env.get("BEDROCK_MODEL_ID")
        if not model_id:
            raise ProviderError("MODEL_PROVIDER=bedrock needs BEDROCK_MODEL_ID (and AWS credentials).")
        from strands.models import BedrockModel

        return BedrockModel(model_id=model_id, region_name=env.get("AWS_REGION"))
    if provider == "deepseek":
        if not env.get("DEEPSEEK_API"):
            raise ProviderError("MODEL_PROVIDER=deepseek needs DEEPSEEK_API (put it in .env).")
        try:
            from strands.models.openai import OpenAIModel
        except ImportError as e:
            raise ProviderError("MODEL_PROVIDER=deepseek needs the optional 'openai' package.") from e
        return OpenAIModel(
            client_args={"api_key": env["DEEPSEEK_API"], "base_url": env.get("DEEPSEEK_BASE_URL") or DEEPSEEK_BASE_URL},
            model_id=env.get("DEEPSEEK_MODEL") or DEEPSEEK_MODEL,
        )
    raise ProviderError(f"Unknown MODEL_PROVIDER {provider!r}; use one of {', '.join(PROVIDERS)}.")
