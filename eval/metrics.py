"""Metrics over trial outcomes (design section 9.4). Pure functions on counts, so they are checked
against hand-computed values.

For each task there are ``n`` trials of which ``c`` passed.

* pass@1     mean over tasks of c/n.
* pass^k     mean over tasks of C(c,k)/C(n,k): the chance that k trials drawn without replacement all
             pass. It punishes flakiness that pass@1 hides.
* C_out      (1/T) * sum over tasks of (2*p - 1)^2 with p = c/n: 1 when a task always or never passes,
             0 when it passes half the time (outcome consistency).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from math import comb


@dataclass(frozen=True)
class TaskCounts:
    task_id: str
    trials: int
    passed: int


def _check(counts: Sequence[TaskCounts]) -> None:
    if not counts:
        raise ValueError("no tasks")
    for c in counts:
        if c.trials <= 0 or not 0 <= c.passed <= c.trials:
            raise ValueError(f"bad counts for {c.task_id}: {c.passed} of {c.trials}")


def pass_at_1(counts: Sequence[TaskCounts]) -> float:
    _check(counts)
    return sum(c.passed / c.trials for c in counts) / len(counts)


def pass_hat_k(counts: Sequence[TaskCounts], k: int) -> float:
    _check(counts)
    if k < 1:
        raise ValueError("k must be at least 1")
    short = [c.task_id for c in counts if c.trials < k]
    if short:
        raise ValueError(f"k={k} needs at least {k} trials per task; too few for {short}")
    return sum(comb(c.passed, k) / comb(c.trials, k) for c in counts) / len(counts)


def c_out(counts: Sequence[TaskCounts]) -> float:
    _check(counts)
    return sum((2 * c.passed / c.trials - 1) ** 2 for c in counts) / len(counts)


def rate(part: int, whole: int) -> float | None:
    """``part / whole``, or None when there is nothing to divide by (never a made-up 0)."""
    return part / whole if whole else None


def percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile, ``q`` in [0, 100]."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * q // 100))  # ceil
    return ordered[int(rank) - 1]
