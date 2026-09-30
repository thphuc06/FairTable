# eval/

Evaluation harness (plan tasks P1-20, P1-21, P3-1 to P3-4).

- `tasks/` – task YAML: HAPPY 12, NEG 8, ROB 8, ADV 12. Each task has a target state and invariants I1–I5.
- Harness – per-run DynamoDB namespace, runner, state grader, safety grader.
- Configurations: **A0** open store (no Trust Kernel), **A1** full FairTable, **A2** FairTable without step-up.
- Metrics: pass@1, pass^k, C_out, violations, red-team blocked x/12, false-block rate, cost per booking.
- `reports/` – committed reports containing **measured values only**. Runs using the mock model are labelled as harness validation, not model reliability.

## Running it (P1-20)

```
docker compose -f infra/local/docker-compose.yml up -d      # DynamoDB Local (until the full compose file, P1-23)
python -m eval --k 2 --out eval/reports/run.md               # mock model by default
```

Each trial gets its own DynamoDB table (deleted afterwards), the dev issuer, the MCP server on a free port and the consent page, then runs one conversation with `simulator.Assistant` and a simulated diner. Graders: `graders.py` (expected end state; invariants I1-I5, counters, S1 and S2 limits read from the database). Metrics: `metrics.py` (pass@1, pass^k, C_out, checked against hand-computed values). A trial where the harness itself fails is reported as a crash and never counted as a pass or a block.

`tasks/*.yaml` holds the ten starter tasks (format in `tasks.py`); the 40-task generator is plan task P3-1. `--config A0,A1,A2` runs the ablation (`configs.py`, D-027).

## Red team (P1-22)

`python -m eval.redteam` runs the twelve attacks RT1 to RT12 (`redteam.py`) under A0, A1 and A2 and prints one table (blocked, or **SUCCEEDED**). The same scenarios run as tests in `tests/redteam/test_redteam_suite.py`. Under A1 all twelve are blocked; under A0 the four that only the policy layer stops get through, under A2 only the silent confirm.
