# Friction log

Problems hit with AWS / MCP tooling while building FairTable. Counts toward judging (up to a 10% bonus), so record as you go.

Format per entry: **task attempted · steps · expected vs. actual · severity (low/med/high) · workaround · actionable suggestion**.

| Date | Tool | Entry |
|---|---|---|
| 2026-09-29 | Bedrock | Model access blocked on the account; AWS Support case pending. Workaround: `MODEL_PROVIDER=mock` first (see `docs/DECISIONS.md` D-003). Severity: high. |
