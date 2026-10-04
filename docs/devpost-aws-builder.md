Yes. FairTable runs on AWS, and every service below was deployed with the AWS CDK and tested on a real AWS account (us-east-1). The same code also runs locally with `docker compose up`, so judges do not need an AWS account.

A booking request goes through these services, in this order:

1. Amazon Cognito signs in diners, restaurant owners and machine clients. A small AWS Lambda function (a pre-token trigger) adds the claims our rules need, such as the agent's verification level.
2. Amazon Bedrock AgentCore Gateway is the front door. It checks the token, and an AWS Lambda request interceptor passes the diner's token to the server in a fixed header and removes any value the caller tried to send.
3. Amazon Bedrock AgentCore Policy checks our Cedar rules at the Gateway before a tool runs (a signed-in diner is required, a verified agent is required for writes, no party above 10). The server checks the same rules again, so the Gateway is a second layer and not the only one.
4. Amazon Bedrock AgentCore Runtime hosts our MCP server, deployed as a zip file with no container.
5. Amazon DynamoDB holds all data in one table. Each booking change is one transaction with conditions, so two people cannot take the same table.
6. AgentCore Observability with Amazon CloudWatch Transaction Search records a trace of each booking, including which policy allowed or refused it.

Around that:
- Amazon EventBridge Scheduler calls an AWS Lambda function every minute. It releases expired holds, offers the freed table to diners on the waitlist, and draws Fair Drops (the lottery for hot tables) when their time comes.
- AWS KMS provides the random secret seed of each lottery. Amazon S3 stores a copy of each draw record so anyone can recompute the result. Amazon SNS sends the waitlist and lottery notices by e-mail.
- Amazon API Gateway (HTTP API) and AWS Lambda host the restaurant owner's console, where an owner sets the share of seats for assistants, the cancellation terms and Fair Drops.
- Amazon Bedrock: Amazon Nova 2 Sonic powers a voice demo where a diner books a table by speaking, and Claude Haiku 4.5 and Amazon Nova Lite are two of the models in our evaluation of 40 tasks.
- The Strands Agents SDK runs the simulated assistant and the voice agent.
- AWS Secrets Manager holds generated signing keys, AWS Budgets sends cost alerts, and AWS CDK with AWS CloudFormation creates and removes everything with one script.

Not used: AgentCore Evaluations, Memory, Identity and Amazon Nova Act. They appear in grey italics on our architecture diagram as future ideas.

Each service, what we used it for, what worked and what did not is written up in docs/aws-integration.md, docs/product-feedback.md and docs/friction-log.md in the repository, and the AWS architecture diagram is in docs/diagram_image/aws-architecture.png.
