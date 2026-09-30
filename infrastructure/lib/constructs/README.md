# Application constructs

This directory is reserved for reusable CDK constructs composed by [`ApplicationStack`](../stacks/application-stack.ts). It currently contains no construct implementations or resource definitions.

Planned areas include:

| Area | Resources and responsibilities |
| --- | --- |
| Identity | Cognito and API authorization |
| Configuration | Broker account and stream settings |
| Market data | Stream-ingestion Lambda, SQS, and a dead-letter queue |
| Trading | Queue-consumer Lambda and DynamoDB results storage |
| HTTP API | API Gateway routes and a Python Lambda per operation |

Group resources that share a responsibility into a construct and compose them in the application stack. Keep broker API behavior in the [Python backend](../../../backend/README.md); constructs manage deployment resources and permissions.

Lambda entry-point modules live in `backend/src/autoforex/handlers/` relative to the repository root. Building their Python 3.11 dependencies into Linux-compatible deployment assets is still pending. See the [architecture notes](../../../docs/architecture.md) for outstanding integration decisions and the [CDK guide](../../README.md) for local commands.
