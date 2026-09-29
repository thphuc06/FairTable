# eval/

Evaluation harness (plan tasks P1-20, P1-21, P3-1 to P3-4).

- `tasks/` – task YAML: HAPPY 12, NEG 8, ROB 8, ADV 12. Each task has a target state and invariants I1–I5.
- Harness – per-run DynamoDB namespace, runner, state grader, safety grader.
- Configurations: **A0** open store (no Trust Kernel), **A1** full FairTable, **A2** FairTable without step-up.
- Metrics: pass@1, pass^k, C_out, violations, red-team blocked x/12, false-block rate, cost per booking.
- `reports/` – committed reports containing **measured values only**. Runs using the mock model are labelled as harness validation, not model reliability.
