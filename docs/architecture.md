# Architecture

`auto-forex` version `0.0.1` combines TypeScript AWS CDK infrastructure with Python 3.11 application code in one repository. Python dependencies and environments use uv; type checking uses ty.

The infrastructure provisions a GitHub-connected CDK delivery pipeline that deploys alpha and beta to the development account and prod to the production account. Each application stack currently creates only an SSM parameter identifying its environment. Python Lambda handlers, API Gateway integrations, trading logic, queues, user pools, and application data stores remain scaffolds. The [deployment guide](deployment.md) is the canonical setup walkthrough.

## Accounts and deployment boundaries

| Account | Identifier | Responsibility |
| --- | --- | --- |
| pipeline | `786888028645` / `auto-forex-pipeline` | CDK Pipelines, builds, and deployments |
| dev | `571846855296` / `auto-forex-dev` | Alpha and beta application environments |
| prod | `956112821771` / `auto-forex-prod` | Production application environment |

The default region is `us-west-2`. The accounts already exist. Standard CDK bootstrap roles are installed once with the account-specific local profiles before the pipeline is deployed.

## Implemented infrastructure

| Component | Behavior |
| --- | --- |
| Bootstrap script | Bootstraps pipeline, dev, and prod using their local profiles; dev and prod trust the pipeline account. |
| `PipelineStack` | Creates a GitHub.com CodeConnections connection and a CDK Pipeline triggered by pushes to the configured branch, defaulting to `main`. |
| `ApplicationStage` | Instantiates a separate application stack for alpha, beta, and prod. |
| `ApplicationStack` | Creates `/auto-forex/<environment>/deployment/environment` in SSM Parameter Store. Application resources are added here later. |

The repository does not provision AWS accounts. Account IDs use environment variables with YAML fallbacks. Local profile names use environment variables with code defaults and are not sent to CodeBuild. The default bootstrap execution policy is `AdministratorAccess` and can be replaced with a narrower policy before initial bootstrap.

## Configuration and pipeline flow

`infrastructure/config/environments.yaml` contains non-secret deployment settings. `infrastructure/lib/config/environment.ts` validates and resolves them in this order: environment variables, YAML values, then defaults. `AUTO_FOREX_CONFIG_FILE` selects another file. Strings support `${VARIABLE}` and `${VARIABLE:-default}`.

CDK context `target=pipeline` selects the pipeline stack. The `bootstrapComplete=true` context includes alpha, beta, and prod stages. The supplied full-deploy command uses both after all accounts have been bootstrapped.

All three accounts are bootstrapped locally once. Subsequent pipeline executions:

1. Fetch the repository through CodeConnections.
2. Install Node dependencies in `infrastructure/`, then run TypeScript checks and tests.
3. Build TypeScript and synthesize `target=pipeline` with `bootstrapComplete=true` into `infrastructure/cdk.out`.
4. Self-update the pipeline, publish assets as applicable, and deploy alpha, beta, and prod in order.

Deployment coordinates are passed into the synth environment. Local AWS profile names, credentials, and absolute configuration paths are not. Alpha and beta use separate stacks and environment-qualified SSM paths even though they share one AWS account.

CloudFormation-created CodeConnections connections start in `PENDING`. Complete GitHub installation and repository authorization in the AWS console to make the connection `AVAILABLE` before expecting source events to work. See the [connection resource reference](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-codeconnections-connection.html) and [CDK Pipelines bootstrap guidance](https://docs.aws.amazon.com/cdk/v2/guide/cdk-pipeline.html).

## Repository boundaries

`infrastructure/` and `backend/` are independent project roots with their own dependency locks and development-tool configuration. `docs/` holds architecture, API planning, and deployment instructions. Routine development commands are described in the [project overview](../README.md).

| Location | Responsibility |
| --- | --- |
| `infrastructure/bin/` | CDK application entry point and target selection |
| `infrastructure/lib/config/` | Typed configuration loading and validation |
| `infrastructure/lib/stacks/` | Pipeline and application stacks |
| `infrastructure/lib/stages/` | Deployment units for alpha, beta, and prod |
| `infrastructure/lib/constructs/` | Future reusable CDK resource compositions |
| `infrastructure/scripts/bootstrap-targets.ts` | Profile-aware pipeline and target CDK bootstrap execution |
| `backend/src/autoforex/handlers/` | One module per API operation or asynchronous Lambda workflow |
| `backend/src/autoforex/application/` | Application use cases and orchestration |
| `backend/src/autoforex/domain/` | Domain types and trading concepts independent of AWS and brokers |
| `backend/src/autoforex/ports/` | Interfaces for external services and persistence |
| `backend/src/autoforex/adapters/` | Broker and AWS SDK implementations |

Directory, class, and public API names use provider-neutral terms such as `broker`, `market_data`, and `trading`. OANDA is the initial broker integration; its formats and capabilities belong behind adapter boundaries. Concrete adapters remain to be implemented.

## Planned application flow

~~~mermaid
flowchart LR
  Broker[Broker price stream] --> Ingest[Price ingestion Lambda]
  Ingest --> Queue[SQS]
  Queue --> Execute[Trade execution Lambda]
  Execute --> BrokerAPI[Broker API]
  Execute --> Results[DynamoDB: execution results]
  Client[Client] --> Gateway[API Gateway]
  Gateway --> Api[Lambda per API operation]
  Api --> Results
  Api --> BrokerAPI
  Api --> Users[Cognito: users]
  Api --> Settings[Settings storage: integration unresolved]
~~~

This diagram describes the application to be implemented. The current SSM environment parameter is deployment metadata, not the stream-settings store.

## Open application decisions

| Topic | Constraint and decision |
| --- | --- |
| Settings in AWS Config | AWS Config is the current integration boundary. It tracks resource configuration, changes, and compliance; AWS AppConfig serves application configuration management. Define the resource representation and read/write mechanism for Config, or select another storage service. No settings store is implemented. See [AWS Config](https://docs.aws.amazon.com/config/latest/developerguide/WhatIsConfig.html) and [AWS AppConfig](https://docs.aws.amazon.com/appconfig/latest/userguide/what-is-appconfig.html). |
| Credentials and Cognito | Cognito is the user identity boundary; broker credential storage remains unresolved. Readable user attributes can appear in ID tokens, so credential values must not be exposed as ordinary readable attributes. One option is Secrets Manager for secret values with identity associations or references managed separately. Neither credential storage approach is implemented. See [Cognito attribute permissions](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-attributes.html) and [Secrets Manager](https://docs.aws.amazon.com/secretsmanager/latest/userguide/intro.html). |
| Stream continuity in Lambda | A standard Lambda invocation runs for at most 900 seconds. Continuous ingestion needs bounded sessions, handover, reconnection, concurrency control, and defined behavior during gaps. See [Lambda timeout](https://docs.aws.amazon.com/lambda/latest/dg/configuration-timeout.html). |
| Receiving frequency | OANDA's price stream publishes at most four prices per second per instrument and does not deliver every price change. Its public parameters do not provide an arbitrary delivery interval. Define application sampling and aggregation separately from connection or restart cadence. See [Pricing Stream](https://developer.oanda.com/rest-live-v20/pricing-ep/). |
| Historical ticks | The public v20 Pricing API provides current prices and a live stream. An API for arbitrary historical tick ranges is not established by that specification. Choose a historical data service or archive received prices. The current-price `since` parameter is not historical tick replay. See [Pricing API](https://developer.oanda.com/rest-live-v20/pricing-ep/). |
| Duplicate queue delivery and trading | Lambda's SQS event processing can deliver messages more than once. Define trade-execution idempotency, retries, failed-message handling, trading conditions, order quantities, and activation criteria before enabling execution. See [Lambda with SQS](https://docs.aws.amazon.com/lambda/latest/dg/with-sqs.html). |

The [API plan](api-plan.md) describes all 16 proposed HTTP operations and their data boundaries.
