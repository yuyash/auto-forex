# Auto Forex

auto-forex is an AWS-based platform for algorithmic foreign exchange trading across broker accounts. Its first implemented application path ingests OANDA prices continuously, queues them, and stores price history by symbol and timestamp.

The infrastructure provisions a GitHub-connected CDK Pipeline that deploys alpha and beta to the development AWS account and prod to the production AWS account. Each application environment includes ARM Fargate, AppConfig, Cognito, SQS FIFO, a Lambda consumer, and DynamoDB `Users` and `Prices`. User-specific OANDA settings are stored in `Users`, while credentials remain in per-user Secrets Manager secrets. Trading and HTTP API resources are not implemented yet.

## Repository

| Directory | Purpose |
| --- | --- |
| [infrastructure/](infrastructure/README.md) | TypeScript CDK project, YAML configuration, account provisioning, and delivery pipeline |
| [backend/](backend/README.md) | Python 3.11 package, managed with uv and checked with ty and Ruff |
| [docs/](docs/architecture.md) | Architecture, API plan, and deployment guide |

## Local development

Use Node.js 22 or newer, npm, and uv. Run infrastructure commands in `infrastructure/` and Python commands in `backend/`.

```sh
cd infrastructure
npm ci
npm run typecheck
npm test

cd ../backend
uv sync --locked
uv run ty check
uv run ruff check src
uv run ruff format --check src
```

These checks do not create AWS resources. CDK synthesis additionally requires the configuration for the selected deployment target.

## Environment configuration

[environments.yaml](infrastructure/config/environments.yaml) supplies file defaults. `AUTO_FOREX_*` environment variables take precedence; the region defaults to `us-west-2`. Account IDs are strings and must be quoted in YAML.

Account IDs and local profiles are selected through environment variables with these defaults:

| Purpose | Account variable / default | Profile variable / default |
| --- | --- | --- |
| Development | `AUTO_FOREX_ACCOUNT_DEV=571846855296` | `AUTO_FOREX_PROFILE_DEV=auto-forex-dev` |
| Production | `AUTO_FOREX_ACCOUNT_PROD=956112821771` | `AUTO_FOREX_PROFILE_PROD=auto-forex-prod` |
| Pipeline | `AUTO_FOREX_ACCOUNT_PIPELINE=786888028645` | `AUTO_FOREX_PROFILE_PIPELINE=auto-forex-pipeline` |

Account-ID fallbacks are declared in `environments.yaml`; profile fallbacks live in the local command configuration. Account IDs are non-secret deployment coordinates. AWS credentials remain in the local AWS CLI configuration and are never committed or passed into CodeBuild.

## Deployment

Follow the [deployment guide](docs/deployment.md) for pipeline setup and initial installation. The [infrastructure guide](infrastructure/README.md) documents the environment variables and CDK targets.

The pipeline uses AWS CodeConnections to watch `main` in GitHub and deploys `alpha`, `beta`, then `prod`. All three accounts must be bootstrapped once using the supplied npm commands, and the GitHub connection requires one manual authorization in the AWS console.
