# Auto Forex Backend

The backend will ingest broker price streams, execute trades from SQS messages, and expose APIs for accounts, users, market data, and stored trading results. It uses Python 3.11, uv for environments and dependencies, ty for type checking, and Ruff for linting and formatting.

The first working path ingests OANDA v20 Pricing Stream events in an ARM64 Fargate service, publishes normalized prices to SQS FIFO, and invokes a Lambda consumer that logs and stores price history in DynamoDB `Prices`.

## Getting started

Install uv, then run these commands from `backend/`:

```sh
uv sync --locked
uv run ty check
uv run ruff check src
uv run ruff format --check src
uv run python -m unittest discover -s tests -v
```

uv uses the Python 3.11 version specified in `.python-version` and creates `.venv/` in this directory. `pyproject.toml` contains package and tool settings; `uv.lock` fixes dependency versions. Add runtime dependencies with `uv add <package>` and development tools with `uv add --dev <package>`.

`uv build` creates Python distributions in `dist/`. Packaging dependencies into a Linux-compatible Lambda deployment asset remains to be implemented in the [CDK project](../infrastructure/README.md).

## Code layout

All application code belongs in `src/autoforex/`:

| Path | Intended responsibility |
| --- | --- |
| `handlers/stream.py` | Long-running Fargate process for OANDA prices and SQS publication |
| `handlers/prices.py` | SQS Lambda that logs and stores price history |
| `handlers/trades.py` | Process queued prices, execute trades, and persist results |
| `handlers/api/` | One Lambda entry point per API operation |
| `application/` | Coordinate use cases through domain models and ports |
| `domain/` | Define account, user, market-data, and trading concepts |
| `ports/` | Define interfaces for brokers, identity, settings, queues, and results |
| `adapters/brokers/` | Translate between broker APIs and application models |
| `adapters/aws/` | Implement AWS integrations behind the ports |

API modules are grouped under `accounts/`, `streams/`, `users/`, `prices/`, and `results/`. See the [API plan](../docs/api-plan.md) for the proposed operations.

## Adding functionality

Keep handlers focused on event validation, authorization, and response mapping. Put shared behavior in `application/`, depending on `domain/` and `ports/`; implement external calls in `adapters/`. Broker-specific payloads should be converted at the adapter boundary, with provider-neutral module and class names throughout the package.

For example, implementing the result-detail endpoint starts in `handlers/api/results/get.py`. Once it defines a `handler` function, its Lambda handler name will be `autoforex.handlers.api.results.get.handler`. The associated API route, permissions, and deployment asset belong in the CDK project.

## Configuring the price stream

The deployed AppConfig configuration starts with `ingestion_enabled: false` and contains only environment-wide operational settings. Per-user stream settings live in DynamoDB `Users`, keyed by the immutable Cognito `sub`. Cognito Post Confirmation creates the initial disabled `Users` record. The OANDA token registration API creates or updates a per-user Secrets Manager secret whose name uses a SHA-256 digest of `sub`; Cognito stores no broker credentials or secret references.

The `Users` schema uses `user_id` (Cognito `sub`) as its partition key and `stream_status-index` to discover enabled streams. The `Prices` schema uses `symbol` as its partition key and `created_at` as its sort key. Alpha and beta share both development tables; prod has separate tables with the same names.

## User API

Each application environment exposes these API Gateway HTTP API routes:

| Route | Authentication | Request body |
| --- | --- | --- |
| `POST /users/signup` | Public | `{"email":"...","password":"..."}` |
| `POST /auth/login` | Public | `{"email":"...","password":"..."}` |
| `GET /users/me` | Cognito access JWT | None |
| `PUT /users/me/oanda-token` | Cognito access JWT | `{"token":"..."}` |

Cognito sends an email confirmation code after signup. The user must complete Cognito's standard `ConfirmSignUp` flow before login. Send the access token returned by login as `Authorization: Bearer <access_token>` for protected routes. OANDA token values are stored only in Secrets Manager and are never returned by the user API.
