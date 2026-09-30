# Deployment guide

This project uses three AWS accounts in `us-west-2`:

| Purpose | AWS CLI profile | Account ID | CDK environments |
| --- | --- | --- | --- |
| Development | `auto-forex-dev` | `571846855296` | alpha, beta |
| Production | `auto-forex-prod` | `956112821771` | prod |
| Pipeline | `auto-forex-pipeline` | `786888028645` | AutoForexPipeline |

Account IDs are resolved from `AUTO_FOREX_ACCOUNT_*` variables, with the current IDs as fallbacks in `infrastructure/config/environments.yaml`. Profile names are resolved from `AUTO_FOREX_PROFILE_*` variables, with `auto-forex-dev`, `auto-forex-prod`, and `auto-forex-pipeline` as code defaults. Credentials and SSO sessions remain in the AWS CLI configuration and must not be committed.

## 1. Verify the profiles

Use Node.js 22 or later and AWS CLI v2. From the repository root:

```sh
aws sts get-caller-identity --profile auto-forex-dev
aws sts get-caller-identity --profile auto-forex-prod
aws sts get-caller-identity --profile auto-forex-pipeline
```

If an SSO session has expired, run `aws sso login --profile <profile>` for that profile.

## 2. Install and validate

```sh
cd infrastructure
npm ci
npm run typecheck
npm test
npm run synth -- -c target=pipeline
```

These checks do not modify AWS resources.

## 3. Bootstrap all accounts

```sh
npm run bootstrap:pipeline
npm run bootstrap:targets
```

The first command uses `auto-forex-pipeline`. The second uses `auto-forex-dev` and `auto-forex-prod` and configures their standard CDK bootstrap roles to trust account `786888028645` for pipeline deployments.

The configured CloudFormation execution policy is currently AWS `AdministratorAccess`. Change `bootstrap.executionPolicyArn` before bootstrapping if a narrower policy is required.

## 4. Deploy the pipeline

After all three bootstrap commands succeed:

```sh
npm run deploy:pipeline:full
```

This command always uses `auto-forex-pipeline`. It creates the pipeline in account `786888028645` and adds the application stages in this order:

1. alpha in the development account
2. beta in the development account
3. prod in the production account

The stack creates a GitHub.com CodeConnections connection and outputs `GitHubConnectionArn`. Open the connection in the pipeline account's AWS console, complete the GitHub installation and repository authorization, and wait until its status is `AVAILABLE`.

## 5. Run and verify

Push a commit to `main` or retry the pipeline execution in the AWS console. To inspect it from the CLI:

```sh
aws codepipeline get-pipeline-state \
  --name AutoForexPipeline \
  --region us-west-2 \
  --profile auto-forex-pipeline

aws codepipeline list-pipeline-executions \
  --pipeline-name AutoForexPipeline \
  --max-results 5 \
  --region us-west-2 \
  --profile auto-forex-pipeline
```

## Overrides

Environment variables override `config/environments.yaml`. The relevant variables are:

| Variable | Purpose |
| --- | --- |
| `AUTO_FOREX_ACCOUNT_DEV` | Development account ID |
| `AUTO_FOREX_ACCOUNT_PROD` | Production account ID |
| `AUTO_FOREX_ACCOUNT_PIPELINE` | Pipeline account ID |
| `AUTO_FOREX_PROFILE_DEV` | Development AWS CLI profile |
| `AUTO_FOREX_PROFILE_PROD` | Production AWS CLI profile |
| `AUTO_FOREX_PROFILE_PIPELINE` | Pipeline AWS CLI profile |
| `AUTO_FOREX_REGION` | AWS region; default `us-west-2` |

Profile variables affect only local commands. They are deliberately omitted from YAML and the CodeBuild environment.
