# eval/

Evaluation harness (plan tasks P1-20, P1-21, P3-1 to P3-4).

- `tasks/` – task YAML: HAPPY 12, NEG 8, ROB 8, ADV 12. Each task has a target state and invariants I1–I5.
- Harness – per-run DynamoDB namespace, runner, state grader, safety grader.
- Configurations: **A0** open store (no Trust Kernel), **A1** full FairTable, **A2** FairTable without the voice guards S5a-c (whatever the assistant sends counts as the diner's yes).
- Metrics: pass@1, pass^k, C_out, violations, red-team blocked x/12, false-block rate, cost per booking.
- `reports/` – committed reports containing **measured values only**. Runs using the mock model are labelled as harness validation, not model reliability.

## Running it (P1-20)

```
docker compose -f infra/local/docker-compose.yml up -d      # DynamoDB Local (until the full compose file, P1-23)
python -m eval --k 2 --out eval/reports/run.md               # mock model by default
```

Each trial gets its own DynamoDB table (deleted afterwards), the dev issuer and the MCP server on a free port, then runs one conversation with `simulator.Assistant` and a simulated diner. Graders: `graders.py` (expected end state; invariants I1-I5, counters, S1 and S2 limits read from the database). Metrics: `metrics.py` (pass@1, pass^k, C_out, checked against hand-computed values). A trial where the harness itself fails is reported as a crash and never counted as a pass or a block.

`tasks/*.yaml` holds the 40 tasks, written by `eval/generate.py` (`python -m eval.generate`, `--check` fails if the files differ from its table); format in `tasks.py`. The diner's answer is the task's `consent` field: `approve` (says yes), `decline` (says no), `ignore` (says nothing). `--config A0,A1,A2` runs the ablation (`configs.py`, D-027).

## Reports, the gate and the chart (P3-2, P3-3)

```
python -m eval --k 4 --config A1 --redteam --out run-A1.md       # one process per configuration can run in parallel
python -m eval --merge run-A1.json run-A0.json run-A2.json --out eval/reports/<name>.md
python -m eval.gate eval/reports/<name>.json [--baseline eval/reports/<earlier>.json]
python -m eval.charts eval/reports/<name>.json                    # writes <name>.svg
```

`eval/reports/` holds the committed runs (the `.md` report, the `.json` with every trial, the `.svg` chart). The date in a file name is the day of the run, and the report belongs to the code of that day: later changes to the rules (for example S6, one table per diner, restaurant and day) are not in it. The integration tests `test_eval_run`, `test_ablation` and `test_redteam_suite` repeat the scripted run (one trial per task) on every change, so a rule that broke the claims would fail the suite; only the real-model runs are never repeated. The gate (`gate.py`, D-057) exits 1 and names every failed rule: a crash in the harness, any safety violation under A1, a refusal or attack that did not end safe, a red-team attack that got through, an ablation (A0, A2) that looks as good as A1, and, against a baseline, a drop in pass@1 or pass^k or a rise in the false-block rate. A metric that was not measured fails, it never passes. The mock model repeats itself, so k above 1 adds little until a real model is used (P3-4).

## Running with a real model (P3-4, D-064)

```
MODEL_PROVIDER=deepseek python -m eval --k 2 --config A1 --out run-A1.md                 # DEEPSEEK_API in .env
MODEL_PROVIDER=bedrock BEDROCK_MODEL_ID=us.amazon.nova-lite-v1:0 AWS_PROFILE=<profile> python -m eval --k 2 --config A1 --out run-A1.md
```

The tasks, the server, the simulated diner and the graders are the same; only the assistant changes. A scripted persona misbehaves by
construction (it grabs a Fair Drop seat, confirms without asking, forgets the token, retries a hold). A real model does not, so its
system prompt gets one sentence that asks for the same misbehaviour (`MISBEHAVIOUR_PROMPTS` in `simulator/personas.py`). Two
consequences: a model may decline to play along, and then no rule has to refuse anything. Such a trial passes if the end state is
right and the safety invariants hold, and it is counted apart as **Misbehaviour not attempted** (the report says how many
of the ADV and ROB trials these were); a wrong end state is never excused. The report names the model, the tokens used per trial and
the numbers are per model: do not compare a scripted run with a real one. The red team does not depend on the model and is run once, with the scripted run.

## Red team (P1-22)

`python -m eval.redteam` runs the twelve attacks RT1 to RT12 (`redteam.py`) under A0, A1 and A2 and prints one table (blocked, or **SUCCEEDED**). The same scenarios run as tests in `tests/redteam/test_redteam_suite.py`. Under A1 all twelve are blocked; under A0 the four that only the policy layer stops get through, under A2 only the silent confirm.
