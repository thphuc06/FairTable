# Dev log

One file per **phase** (`phase-0.md`, `phase-1.md`, …). Each phase file has three parts, in this order:

1. **Plan** – goal of the phase, the batches, and the tasks in each batch (a working copy of the relevant part of `docs/PLAN.md`, with any change made during the work).
2. **Progress** – a status table, one row per task: `todo`, `in progress`, `done`, `blocked`, or `cut`, with the date it changed.
3. **Entries** – what happened, newest first. Each entry carries a **feature tag** (for example `[trust-kernel]`, `[identity]`, `[store]`, `[booking-tools]`, `[waitlist]`, `[fairdrop]`, `[web]`, `[simulator]`, `[eval]`, `[docker]`, `[docs]`, `[aws]`) so one feature can be followed across phases with a search for its tag.

How it relates to the other docs:

| File | Owns |
|---|---|
| `docs/PLAN.md` | The master plan: tasks, dates, acceptance criteria, risks, verified APIs. Changes only when the plan itself changes. |
| `docs/DECISIONS.md` | Decisions and their reasons. |
| `docs/devlog/phase-N.md` | Live status of the phase: what is planned in the current batch, what is done, what surprised us. |
| `docs/friction-log.md` | Only problems with AWS / MCP tooling (feeds the judging bonus). A tooling surprise goes here in detail and gets a one-line pointer in the devlog. |

If PLAN.md and a devlog Plan section disagree, PLAN.md wins until someone updates it; fix the disagreement in the same session.

## Entry template

```markdown
### <YYYY-MM-DD> · <task ID> · [feature-tag] · <short title>
- **Goal:** one sentence, in plain words.
- **Done:** what now exists or behaves differently.
- **Files:** new and changed paths.
- **Tests:** test files and the result (for example `53 passed`).
- **Decisions:** choices made and why (link `DECISIONS.md` ids).
- **Surprises / friction:** what did not go as expected (link `friction-log.md`).
- **Follow-ups:** open questions or deferred work, with the task ID that owns it.
```

A later change to a finished feature gets a new entry whose title starts with `Change:`; never rewrite an old entry.
