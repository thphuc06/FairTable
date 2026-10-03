"""Run the evaluation: ``python -m eval [--tasks eval/tasks] [--k 2] [--config A0,A1,A2] [--redteam] [--out report.md]``.

``--merge a.json b.json --out report.md`` builds one report from runs made separately (for example one process per
configuration, in parallel); ``python -m eval.gate report.json`` then checks it (P3-2).

Needs DynamoDB Local (``DDB_ENDPOINT_URL``, default http://localhost:8000). ``MODEL_PROVIDER`` picks the
assistant's model (``mock`` by default: no account, no cost; numbers validate the harness only).
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from eval.configs import CONFIGS
from eval import gate
from eval.redteam import Outcome, run_redteam
from eval.redteam import to_markdown as redteam_markdown
from eval.report import compare_markdown, summarize, to_markdown
from eval.runner import TrialResult, run_all
from simulator.model import model_label
from eval.tasks import load_tasks


def merged(paths: list[Path]):
    """Summaries, trials and red-team outcomes of several saved runs, in the order given."""
    summaries, trials, redteam = [], [], {}
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        summaries += [gate.summary_from_dict(x) for x in data["summaries"]]
        trials += [TrialResult(**t) for t in data["trials"]]
        for config, outs in data.get("redteam", {}).items():
            redteam[config] = [Outcome(**{**o, "accept": tuple(o.get("accept", ()))}) for o in outs]
    return summaries, trials, redteam


def report_text(summaries, redteam) -> str:
    nl = chr(10)
    text = nl.join(to_markdown(s) for s in summaries)
    if len(summaries) > 1:
        text += nl + compare_markdown(summaries)
    if redteam:
        text += nl + "# Red team (RT1 to RT12)" + nl + nl + redteam_markdown(redteam)
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval")
    parser.add_argument("--tasks", type=Path, default=Path(__file__).parent / "tasks")
    parser.add_argument("--k", type=int, default=2, help="trials per task")
    parser.add_argument("--config", default="A1", help=f"comma-separated, from {', '.join(CONFIGS)} (default A1)")
    parser.add_argument("--redteam", action="store_true", help="also run the twelve attacks under each configuration")
    parser.add_argument("--merge", type=Path, nargs="+", help="build the report from saved runs instead of running")
    parser.add_argument("--out", type=Path, help="write the Markdown report here (a .json with the trials goes beside it)")
    args = parser.parse_args(argv)

    if args.merge:
        summaries, trials, redteam = merged(args.merge)
    else:
        tasks = load_tasks(args.tasks)
        provider = os.environ.get("MODEL_PROVIDER", "mock")
        label = model_label(provider)  # what the report says: the provider and its model id

        def show(r: TrialResult) -> None:
            mark = "CRASH" if r.crashed else ("pass " if r.passed else "FAIL ")
            print(f"{mark} {r.task_id} #{r.trial} {' '.join(r.state_problems + r.violations)} {r.crashed or ''}".rstrip(),
                  file=sys.stderr)

        names = [c.strip().upper() for c in args.config.split(",") if c.strip()]
        unknown = [c for c in names if c not in CONFIGS]
        if unknown:
            parser.error(f"unknown configuration(s) {unknown}; use {', '.join(CONFIGS)}")
        runs = {c: run_all(tasks, args.k, config=c, provider=provider, progress=show) for c in names}
        summaries = [summarize(rs, k=args.k, provider=label, config=c) for c, rs in runs.items()]
        trials = [r for rs in runs.values() for r in rs]
        redteam = {c: asyncio.run(run_redteam(c)) for c in names} if args.redteam else {}
    text = report_text(summaries, redteam)
    print(text)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        gate.save(args.out.with_suffix(".json"), summaries, trials, redteam)
    return 1 if any(s.crashed for s in summaries) else 0


if __name__ == "__main__":
    raise SystemExit(main())
