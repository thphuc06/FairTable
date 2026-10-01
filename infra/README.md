# infra/

AWS profile only (plan Phase 2). Not needed to run the project locally.

- `cdk/` CDK app (Python): DynamoDB table, Cognito and its trigger, Runtime, AWS Budgets. `cognito/` the pre token function. `runtime/` the Runtime package. `aws_ctl.py` one tool to deploy, inspect and remove everything (`status`, `up`, `seed`, `down`).
- AgentCore configuration: Runtime, Gateway (interceptor, Policy). Gateway-side Cedar policies live here because the Gateway generates its own schema.
- `local/` – DynamoDB Local only, on port 8000 (the Phase 0 spikes and the default of `pytest -m ddb`). It clashes with the MCP server of the root `docker-compose.yml`, so use one or the other: with the root stack running, point the tests at its database (`DDB_ENDPOINT_URL=http://localhost:8001`).

Nothing account-specific is committed: account IDs, ARNs and regions come from environment or config. Resources are created for tests and the demo, then torn down with the scripted command described in `docs/aws-integration.md`.
