"""Run the evaluation: ``python -m eval [--tasks eval/tasks] [--k 2] [--out report.md]``.

Needs DynamoDB Local (``DDB_ENDPOINT_URL``, default http://localhost:8000). ``MODEL_PROVIDER`` picks the
assistant's model (``mock`` by default: no account, no cost; numbers validate the harness only).
"""

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from eval.configs import CONFIGS
from eval.report import compare_markdown, summarize, to_markdown
from eval.runner import TrialResult, run_all
from eval.tasks import load_tasks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval")
    parser.add_argument("--tasks", type=Path, default=Path(__file__).parent / "tasks")
    parser.add_argument("--k", type=int, default=2, help="trials per task")
    parser.add_argument("--config", default="A1", help=f"comma-separated, from {', '.join(CONFIGS)} (default A1)")
    parser.add_argument("--out", type=Path, help="write the Markdown report here (a .json with the trials goes beside it)")
    args = parser.parse_args(argv)

    tasks = load_tasks(args.tasks)
    provider = os.environ.get("MODEL_PROVIDER", "mock")

    def show(r: TrialResult) -> None:
        mark = "CRASH" if r.crashed else ("pass " if r.passed else "FAIL ")
        print(f"{mark} {r.task_id} #{r.trial} {' '.join(r.state_problems + r.violations)} {r.crashed or ''}".rstrip(),
              file=sys.stderr)

    names = [c.strip().upper() for c in args.config.split(",") if c.strip()]
    unknown = [c for c in names if c not in CONFIGS]
    if unknown:
        parser.error(f"unknown configuration(s) {unknown}; use {', '.join(CONFIGS)}")
    runs = {c: run_all(tasks, args.k, config=c, provider=provider, progress=show) for c in names}
    summaries = [summarize(rs, k=args.k, provider=provider, config=c) for c, rs in runs.items()]
    text = "\n".join(to_markdown(s) for s in summaries)
    if len(summaries) > 1:
        text += "\n" + compare_markdown(summaries)
    print(text)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        args.out.with_suffix(".json").write_text(
            json.dumps({"summaries": [asdict(s) for s in summaries],
                        "trials": [asdict(r) for rs in runs.values() for r in rs]}, indent=2),
            encoding="utf-8",
        )
    return 1 if any(s.crashed for s in summaries) else 0


if __name__ == "__main__":
    raise SystemExit(main())
