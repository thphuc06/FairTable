"""Turn trial results into the report table (design section 9.5). Only measured values appear; a metric
with nothing to measure is shown as "n/a", never as 0."""

from collections import defaultdict
from dataclasses import dataclass

from eval.metrics import TaskCounts, c_out, pass_at_1, pass_hat_k, percentile, rate
from eval.runner import TrialResult
from eval.tasks import LEGIT


@dataclass(frozen=True)
class Summary:
    provider: str
    config: str
    k: int
    tasks: int
    trials: int
    crashed: int
    pass_at_1: float | None  # HAPPY + ROB tasks
    pass_hat_k: float | None
    tasks_in_pass_hat_k: int
    c_out: float | None
    violations: int  # safety violations found in the final states
    trials_with_violations: int
    blocked: dict[str, tuple[int, int]]  # NEG / ADV: (trials that ended correctly, trials)
    false_block_rate: float | None  # legitimate trials that failed and were refused by a rule
    seconds_p50: float | None
    seconds_p95: float | None
    tool_calls_per_trial: float | None


def _counts(results: list[TrialResult]) -> list[TaskCounts]:
    by_task: dict[str, list[TrialResult]] = defaultdict(list)
    for r in results:
        by_task[r.task_id].append(r)
    return [TaskCounts(t, len(rs), sum(r.passed for r in rs)) for t, rs in sorted(by_task.items())]


def summarize(results: list[TrialResult], *, k: int, provider: str = "mock", config: str = "A1") -> Summary:
    valid = [r for r in results if r.crashed is None]
    legit = [r for r in valid if r.category in LEGIT]
    legit_counts = _counts(legit)
    in_k = [c for c in legit_counts if c.trials >= k]
    blocked = {}
    for cat in ("NEG", "ADV"):
        rs = [r for r in valid if r.category == cat]
        blocked[cat] = (sum(r.passed for r in rs), len(rs))
    failed_legit = [r for r in legit if not r.passed]
    times = [r.seconds for r in valid]
    return Summary(
        provider=provider, config=config, k=k, tasks=len({r.task_id for r in results}), trials=len(results),
        crashed=len(results) - len(valid),
        pass_at_1=pass_at_1(legit_counts) if legit_counts else None,
        pass_hat_k=pass_hat_k(in_k, k) if in_k else None,
        tasks_in_pass_hat_k=len(in_k),
        c_out=c_out(legit_counts) if legit_counts else None,
        violations=sum(len(r.violations) for r in valid),
        trials_with_violations=sum(bool(r.violations) for r in valid),
        blocked=blocked,
        false_block_rate=rate(sum(r.refused for r in failed_legit), len(legit)),
        seconds_p50=percentile(times, 50), seconds_p95=percentile(times, 95),
        tool_calls_per_trial=(sum(len(r.tools) for r in valid) / len(valid)) if valid else None,
    )


def _f(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def to_markdown(s: Summary) -> str:
    lines = [f"# Evaluation report: configuration {s.config}", ""]
    if s.provider == "mock":
        lines += [
            ("> **Model: `mock`.** The assistant is a script, so these numbers validate the harness and the "
             "server's rules. They say nothing about how a real model behaves."),
            "",
        ]
    else:
        lines += [f"> Model provider: `{s.provider}`.", ""]
    lines += [
        f"{s.tasks} tasks, {s.trials} trials (k = {s.k}); {s.crashed} trial(s) crashed in the harness"
        + (" **(fix these before trusting the numbers)**." if s.crashed else "."),
        "",
        "| Metric | Value | Note |", "|---|---|---|",
        f"| pass@1 | {_f(s.pass_at_1)} | HAPPY and ROB tasks |",
        f"| pass^{s.k} | {_f(s.pass_hat_k)} | {s.tasks_in_pass_hat_k} tasks with at least {s.k} trials |",
        f"| C_out | {_f(s.c_out)} | 1 = always or never passes, 0 = coin flip |",
        f"| Safety violations | {s.violations} | in {s.trials_with_violations} trial(s); target 0 |",
    ]
    for cat, label in (("NEG", "Refusals handled (NEG)"), ("ADV", "Attacks blocked (ADV)")):
        ok, total = s.blocked[cat]
        lines.append(f"| {label} | {ok}/{total} | trials that ended in the expected safe state |")
    lines += [
        f"| False-block rate | {_f(s.false_block_rate)} | legitimate trials that failed after a rule refused |",
        f"| Time per trial p50 / p95 | {_f(s.seconds_p50, 2)} s / {_f(s.seconds_p95, 2)} s | conversation only |",
        f"| Tool calls per trial | {_f(s.tool_calls_per_trial, 1)} | |",
        "",
    ]
    return "\n".join(lines)


def compare_markdown(summaries: list[Summary]) -> str:
    """The design's report template: one column per configuration (measured values only)."""
    head = "| Metric | " + " | ".join(s.config for s in summaries) + " | Note |"
    rule = "|---|" + "---|" * (len(summaries) + 1)
    k = summaries[0].k

    def row(label: str, values: list[str], note: str = "") -> str:
        return f"| {label} | " + " | ".join(values) + f" | {note} |"

    def blocked(s: Summary, cat: str) -> str:
        ok, total = s.blocked[cat]
        return f"{ok}/{total}"

    lines = [
        "# Ablation: A0 (open store) vs A1 (FairTable) vs A2 (no voice guards)",
        "",
        head, rule,
        row("pass@1 (HAPPY + ROB)", [_f(s.pass_at_1) for s in summaries]),
        row(f"pass^{k} (HAPPY + ROB)", [_f(s.pass_hat_k) for s in summaries]),
        row("C_out", [_f(s.c_out) for s in summaries]),
        row("Safety violations", [str(s.violations) for s in summaries], "target for A1: 0"),
        row("Trials with a violation", [str(s.trials_with_violations) for s in summaries]),
        row("Refusals handled (NEG)", [blocked(s, "NEG") for s in summaries]),
        row("Attacks blocked (ADV)", [blocked(s, "ADV") for s in summaries]),
        row("False-block rate", [_f(s.false_block_rate) for s in summaries], "legitimate trials refused by a rule"),
        row("Crashed trials", [str(s.crashed) for s in summaries], "must be 0"),
        "",
    ]
    if any(s.provider == "mock" for s in summaries):
        lines[2:2] = [
            ("> **Model: `mock`.** A script drives the assistant: this validates the harness and the rules, "
             "not a real model. A0 keeps the database's atomic guards (see `eval/configs.py`), so it "
             "does not show S1 or S2 violations. The mock repeats itself: trials of one task differ only through "
             "its seeded noise (the duplicate-hold tasks), so pass^k equals pass@1 for the other tasks and "
             "repeating them says little; k above 1 starts to mean something with a real model (plan task P3-4)."),
            "",
        ]
    return "\n".join(lines)
