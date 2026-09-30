"""Run tasks: one isolated environment and one conversation per trial, then grade it.

The conversation is the same code the demo uses: a Strands assistant (``simulator.Assistant``) with the
diner's token, and a simulated diner (``simulator.SimulatedUser``) who answers approval links on the
real consent page. Nothing is faked between the assistant and the server.
"""

import asyncio
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from eval.configs import kernel_for
from eval.env import EvalEnv
from eval.graders import safety_grade, snapshot, state_grade
from eval.tasks import Task
from server.domain.clock import iso_z
from simulator.assistant import Assistant
from simulator.events import Step
from simulator.model import build_model
from simulator.personas import Goal, Noise
from simulator.user import ConsentError, SimulatedUser

MAX_CONSENT_ROUNDS = 3


@dataclass(frozen=True)
class TrialResult:
    task_id: str
    category: str
    trial: int
    passed: bool
    state_problems: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    error_codes: list[str] = field(default_factory=list)
    rule_ids: list[str] = field(default_factory=list)
    seconds: float = 0.0
    crashed: str | None = None  # the harness or environment failed; the trial says nothing about the system
    config: str = "A1"

    @property
    def refused(self) -> bool:
        return bool(self.rule_ids) or "POLICY_DENIED" in self.error_codes


def opening_text(goal: Goal) -> str:
    """What the diner says first. The scripted model ignores it (it has the goal); a real model reads it."""
    verb = "Put me on the waitlist at" if goal.kind == "watch" else "Book a table at"
    where = goal.restaurant or "a restaurant"
    return f"{verb} {where} for {goal.party_size} on {goal.date} at {goal.time}"


async def run_trial(
    task: Task, trial: int, *, config: str = "A1", env_factory: Callable[..., EvalEnv] = EvalEnv,
    provider: str | None = None,
) -> TrialResult:
    try:
        with env_factory(kernel=kernel_for(config)) as env:
            goal = task.goal.resolve(env.clock.now().date())
            noise = Noise(seed=trial, duplicate_hold=task.noise.duplicate_hold)
            model = build_model(provider, goal=goal, noise=noise, today=env.clock.now().date())
            browser, username, password = env.browser(task.user)
            diner = SimulatedUser(browser, username, password)
            steps: list[Step] = []
            problems: list[str] = []
            started = time.perf_counter()
            with Assistant(env.mcp_url, env.token(task.user, task.agent), model) as assistant:
                reply = await assistant.say(opening_text(goal))
                steps += reply.steps
                for _ in range(MAX_CONSENT_ROUNDS):
                    if not reply.consent_url or task.consent == "ignore":
                        break
                    try:
                        if task.consent == "approve":
                            diner.approve_consent(reply.consent_url)
                            said = "I approved it"
                        else:
                            diner.decline(reply.consent_url)
                            said = "I declined it"
                    except ConsentError as e:
                        problems.append(f"the diner could not answer the approval link: {e}")
                        break
                    reply = await assistant.say(said)
                    steps += reply.steps
            seconds = time.perf_counter() - started
            now_iso = iso_z(env.clock.now())
            problems += state_grade(task.expect, snapshot(env.store, env.subs[task.user], now_iso), steps)
            violations = [str(v) for v in safety_grade(env.store, now_iso)]
            return TrialResult(
                task.id, task.category, trial, not problems and not violations, problems, violations,
                [s.tool for s in steps], [s.error for s in steps if s.error],
                sorted({s.result["rule_id"] for s in steps if s.is_error and s.result.get("rule_id")}), seconds,
                config=config,
            )
    except Exception as e:  # noqa: BLE001 - the harness itself failed: report it, never count it as a pass or a block
        return TrialResult(task.id, task.category, trial, False, crashed=f"{type(e).__name__}: {e}", config=config)


async def run_suite(
    tasks: list[Task], k: int, *, config: str = "A1", provider: str | None = None,
    progress: Callable[[TrialResult], None] | None = None,
) -> list[TrialResult]:
    """``k`` trials of every task, one after the other (they share DynamoDB Local and the CPU)."""
    provider = provider or os.environ.get("MODEL_PROVIDER")
    results: list[TrialResult] = []
    for task in tasks:
        for trial in range(k):
            result = await run_trial(task, trial, config=config, provider=provider)
            results.append(result)
            if progress is not None:
                progress(result)
    return results


def run_all(tasks: list[Task], k: int, **kwargs) -> list[TrialResult]:
    return asyncio.run(run_suite(tasks, k, **kwargs))
