"""A real model (DeepSeek, D-018) as the assistant, through the AgentCore Gateway.

Opt-in like the other tests of this folder, and skipped without ``DEEPSEEK_API`` (taken from the environment, or from
the git-ignored ``.env`` file: only the ``DEEPSEEK_*`` lines are read, nothing else, and nothing is printed).
Costs a few thousandths of a dollar per run. What it settles: a model that only sees the Gateway's prefixed tool
names (``ft___restaurant_search`` ...) and the bare names in the server's hints can still book a table, and it
stays inside the rules.
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_gateway import call, gateway  # noqa: F401  (a fixture and a helper)
from test_runtime_smoke import cognito  # noqa: F401  (a fixture)

import test_tokens as tokens
from simulator.assistant import GATEWAY_PREFIX, SYSTEM_PROMPT, Assistant
from simulator.model import build_model

pytestmark = pytest.mark.aws
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def deepseek_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k.startswith("DEEPSEEK_")}
    if "DEEPSEEK_API" not in env and ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip().startswith("DEEPSEEK_") and value.strip():
                env.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return env


@pytest.fixture(scope="module")
def model_env():
    env = deepseek_env()
    if "DEEPSEEK_API" not in env:
        pytest.skip("no DEEPSEEK_API in the environment or in .env")
    return env


@pytest.mark.asyncio
async def test_a_real_model_books_a_table_through_the_gateway(model_env, gateway, cognito):  # noqa: F811
    token = tokens.sign_in(cognito, "alexa-plus-sim", "diner-alice")
    day = (datetime.now(UTC).date() + timedelta(days=12)).isoformat()
    prompt = f"{SYSTEM_PROMPT} Today is {datetime.now(UTC):%A, %Y-%m-%d} (UTC). Dates you give to tools are YYYY-MM-DD."
    assistant = Assistant(gateway["url"], token, build_model("deepseek", env=model_env), prompt,
                          via_gateway=True, tool_prefix=GATEWAY_PREFIX)
    await asyncio.to_thread(assistant.__enter__)
    reply = None
    try:
        assert "restaurant_search" in assistant.tool_names  # bare names for us, the Gateway's prefix underneath
        reply = await assistant.say(f"Please book a table at Luna Trattoria for 2 people on {day} at 7pm.")
        names = [s.tool for s in reply.steps]
        print("steps:", [(s.tool, s.error, bool(s.result.get("idempotent_replay"))) for s in reply.steps], "| tokens:", reply.tokens, "| reply:", reply.text[:160])
        confirmed = [s for s in reply.steps if s.tool == "reservation_confirm" and not s.is_error]
        assert confirmed, f"the model did not complete the booking: {names} / {reply.text[:200]}"
        assert reply.tokens < 60_000  # a booking should not cost more than a few cents
    finally:
        await asyncio.to_thread(assistant.__exit__, None, None, None)
        reservation_id = next((s.result.get("reservation_id") for s in (reply.steps if reply else [])
                               if s.tool == "reservation_confirm" and not s.is_error), None)
        if reservation_id:
            await call(gateway, token, "reservation_manage", action="cancel", reservation_id=reservation_id,
                       idempotency_key=f"realmodel-cancel-{reservation_id}"[:60])
