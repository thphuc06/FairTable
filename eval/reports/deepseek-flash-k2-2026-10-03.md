# Evaluation report: configuration A1

> Model provider: `deepseek (deepseek-flash)`.

40 tasks, 80 trials (k = 2); 0 trial(s) crashed in the harness.

| Metric | Value | Note |
|---|---|---|
| pass@1 | 1.000 | HAPPY and ROB tasks |
| pass^2 | 1.000 | 20 tasks with at least 2 trials |
| C_out | 1.000 | 1 = always or never passes, 0 = coin flip |
| Safety violations | 0 | in 0 trial(s); target 0 |
| Refusals handled (NEG) | 16/16 | trials that ended in the expected safe state |
| Attacks blocked (ADV) | 24/24 | trials that ended in the expected safe state |
| False-block rate | 0.000 | legitimate trials that failed after a rule refused |
| Time per trial p50 / p95 | 5.01 s / 9.85 s | conversation only |
| Tool calls per trial | 3.6 | |
| Tokens per trial | 18726 | input and output of the model |
| Misbehaviour not attempted | 8/40 | ADV and ROB trials in which the model, asked to misbehave, did not; they passed on the end state, not by a rule refusing |

# Evaluation report: configuration A0

> Model provider: `deepseek (deepseek-flash)`.

40 tasks, 80 trials (k = 2); 0 trial(s) crashed in the harness.

| Metric | Value | Note |
|---|---|---|
| pass@1 | 0.850 | HAPPY and ROB tasks |
| pass^2 | 0.850 | 20 tasks with at least 2 trials |
| C_out | 1.000 | 1 = always or never passes, 0 = coin flip |
| Safety violations | 6 | in 6 trial(s); target 0 |
| Refusals handled (NEG) | 12/16 | trials that ended in the expected safe state |
| Attacks blocked (ADV) | 15/24 | trials that ended in the expected safe state |
| False-block rate | 0.000 | legitimate trials that failed after a rule refused |
| Time per trial p50 / p95 | 5.34 s / 7.85 s | conversation only |
| Tool calls per trial | 3.7 | |
| Tokens per trial | 19450 | input and output of the model |
| Misbehaviour not attempted | 21/40 | ADV and ROB trials in which the model, asked to misbehave, did not; they passed on the end state, not by a rule refusing |

# Evaluation report: configuration A2

> Model provider: `deepseek (deepseek-flash)`.

40 tasks, 80 trials (k = 2); 0 trial(s) crashed in the harness.

| Metric | Value | Note |
|---|---|---|
| pass@1 | 0.850 | HAPPY and ROB tasks |
| pass^2 | 0.850 | 20 tasks with at least 2 trials |
| C_out | 1.000 | 1 = always or never passes, 0 = coin flip |
| Safety violations | 6 | in 6 trial(s); target 0 |
| Refusals handled (NEG) | 16/16 | trials that ended in the expected safe state |
| Attacks blocked (ADV) | 24/24 | trials that ended in the expected safe state |
| False-block rate | 0.000 | legitimate trials that failed after a rule refused |
| Time per trial p50 / p95 | 4.99 s / 7.57 s | conversation only |
| Tool calls per trial | 3.5 | |
| Tokens per trial | 18080 | input and output of the model |
| Misbehaviour not attempted | 17/40 | ADV and ROB trials in which the model, asked to misbehave, did not; they passed on the end state, not by a rule refusing |

# Ablation: A0 (open store) vs A1 (FairTable) vs A2 (no voice guards)

| Metric | A1 | A0 | A2 | Note |
|---|---|---|---|---|
| pass@1 (HAPPY + ROB) | 1.000 | 0.850 | 0.850 |  |
| pass^2 (HAPPY + ROB) | 1.000 | 0.850 | 0.850 |  |
| C_out | 1.000 | 1.000 | 1.000 |  |
| Safety violations | 0 | 6 | 6 | target for A1: 0 |
| Trials with a violation | 0 | 6 | 6 |  |
| Refusals handled (NEG) | 16/16 | 12/16 | 16/16 |  |
| Attacks blocked (ADV) | 24/24 | 15/24 | 24/24 |  |
| False-block rate | 0.000 | 0.000 | 0.000 | legitimate trials refused by a rule |
| Crashed trials | 0 | 0 | 0 | must be 0 |
| Misbehaviour not attempted | 8/40 | 21/40 | 17/40 | a real model was asked to misbehave and did not; passed on the end state |
