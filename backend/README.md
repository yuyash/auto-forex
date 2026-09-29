# Auto Forex Backend

The backend will ingest broker price streams, execute trades from SQS messages, and expose APIs for accounts, users, market data, and stored trading results. It uses Python 3.11, uv for environments and dependencies, ty for type checking, and Ruff for linting and formatting.

The package is currently a scaffold: Python modules contain only docstrings describing their intended responsibilities. There are no working Lambda handlers, broker integrations, trading operations, or AWS connections yet.

## Getting started

Install uv, then run these commands from `backend/`:

```sh
uv sync --locked
uv run ty check
uv run ruff check src
uv run ruff format --check src
```

uv uses the Python 3.11 version specified in `.python-version` and creates `.venv/` in this directory. `pyproject.toml` contains package and tool settings; `uv.lock` fixes dependency versions. Add runtime dependencies with `uv add <package>` and development tools with `uv add --dev <package>`.

`uv build` creates Python distributions in `dist/`. Packaging dependencies into a Linux-compatible Lambda deployment asset remains to be implemented in the [CDK project](../infrastructure/README.md).

## Code layout

All application code belongs in `src/auto_forex/`:

| Path | Intended responsibility |
| --- | --- |
| `handlers/stream_ingestion.py` | Receive broker prices and publish normalized events to SQS |
| `handlers/trade_execution.py` | Process queued prices, execute trades, and persist results |
| `handlers/api/` | One Lambda entry point per API operation |
| `application/` | Coordinate use cases through domain models and ports |
| `domain/` | Define account, user, market-data, and trading concepts |
| `ports/` | Define interfaces for brokers, identity, settings, queues, and results |
| `adapters/brokers/` | Translate between broker APIs and application models |
| `adapters/aws/` | Implement AWS integrations behind the ports |
| `bootstrap.py` | Assemble adapters and use cases during Lambda initialization |

API modules are grouped under `broker_accounts/`, `stream_settings/`, `users/`, `market_data/`, and `results/`. See the [API plan](../docs/api-plan.md) for the proposed operations.

## Adding functionality

Keep handlers focused on event validation, authorization, and response mapping. Put shared behavior in `application/`, depending on `domain/` and `ports/`; implement external calls in `adapters/`. Use `bootstrap.py` to wire those implementations together. Broker-specific payloads should be converted at the adapter boundary, with provider-neutral module and class names throughout the package.

For example, implementing the result-detail endpoint starts in `handlers/api/results/get.py`. Once it defines a `handler` function, its Lambda handler name will be `auto_forex.handlers.api.results.get.handler`. The associated API route, permissions, and deployment asset belong in the CDK project.

Storage choices, stream continuity, duplicate-message handling, and historical tick availability still need implementation decisions. Consult the [architecture notes](../docs/architecture.md) before integrating those areas.
