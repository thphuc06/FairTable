# infra/

AWS profile only (plan Phase 2). Not needed to run the project locally.

- CDK app (Python): DynamoDB table, Cognito, Lambdas, AWS Budgets.
- AgentCore configuration: Runtime, Gateway (interceptor, Policy). Gateway-side Cedar policies live here because the Gateway generates its own schema.
- `local/` – compose file used by the Phase 0 spikes; folded into the root `docker-compose.yml` in task P1-23.

Nothing account-specific is committed: account IDs, ARNs and regions come from environment or config. Resources are created for tests and the demo, then torn down with the scripted command described in `docs/aws-integration.md`.
