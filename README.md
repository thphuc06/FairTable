# FairTable

> Bots scalp tables; restaurants ban agents. FairTable is the Alexa+ front door that lets agents book fairly, with verified identity, scoped consent, and rules owners control.

**Status:** 🚧 in progress – Amazon Developer Hackathon "Build, Ship, Shape"
**Track:** Alexa+ · **Mini challenge:** AWS Builder

## What it does
FairTable is a self-hosted **MCP server** (spec 2025-11-25, Streamable HTTP) that independent restaurants publish so AI agents such as Alexa+ can book tables safely:
- **Verified identity:** every booking is tied to a real, signed-in diner.
- **Standing mandate + step-up consent:** bookings within what the diner pre-approved confirm instantly; anything beyond is approved on their phone.
- **Owner-controlled rules:** enforced with Cedar policies, including a cap on how many covers agents can book.
- **Standing waitlists:** no polling – agents register once and get notified.
- **Fair Drop:** an auditable commit–reveal lottery for hot tables.
- **Measured reliability:** pass^k evaluations against an open-storefront baseline.

## Documentation
- Design: [`docs/fairtable-solution-design.md`](docs/fairtable-solution-design.md)
- Diagrams (open with app.diagrams.net): [`docs/fairtable-aws-architecture.drawio`](docs/fairtable-aws-architecture.drawio), [`docs/fairtable-flows.drawio`](docs/fairtable-flows.drawio)
- Hackathon requirements: [`docs/hackathon-rules.md`](docs/hackathon-rules.md)

## Run locally
_Coming soon._

## AWS services (planned)
Amazon Bedrock AgentCore (Runtime, Gateway, Policy, Identity, Evaluations), Amazon Bedrock, Amazon DynamoDB, AWS Lambda, Amazon EventBridge Scheduler, Amazon Cognito, Amazon API Gateway, AWS KMS, Amazon S3, Amazon CloudWatch, AWS Budgets.

## License
[Apache-2.0](LICENSE)
