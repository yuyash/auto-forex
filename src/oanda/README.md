# auto-forex-oanda

`auto-forex-oanda` is an AutoForex adapter for the OANDA REST v20 API. It maps
OANDA accounts, pricing, orders, trades, positions, and transactions into
provider-neutral models from `auto-forex-core`.

The distribution is installed as `auto-forex-oanda` and imported as
`autoforex.oanda`.

> **Project status:** Alpha. Start with an OANDA practice account. Live order
> methods can create, replace, cancel, or close real positions. This software
> does not provide investment advice.

## Requirements

- Python 3.14 or newer
- An OANDA REST v20 account and personal access token
- Network access to the selected OANDA practice or live endpoints

## Installation

Install the adapter directly:

```bash
pip install auto-forex-oanda
```

Or install it as an optional server feature:

```bash
pip install "auto-forex-server[oanda]"
```

## Configuration

`OandaSettings` reads `.env` and variables prefixed with `OANDA_`:

```env
OANDA_ACCOUNT_ID=001-001-1234567-001
OANDA_ACCESS_TOKEN=replace-with-a-secret
OANDA_ENVIRONMENT=practice
```

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `OANDA_ACCOUNT_ID` | required | Account used by provider services |
| `OANDA_ACCESS_TOKEN` | required | Secret REST v20 token |
| `OANDA_ENVIRONMENT` | `practice` | `practice` or `live` |
| `OANDA_HOSTNAME` | environment default | REST API host override |
| `OANDA_STREAM_HOSTNAME` | environment default | Streaming host override |
| `OANDA_PORT` | `443` | API port |
| `OANDA_SSL` | `true` | Use HTTPS |
| `OANDA_APPLICATION` | `AutoForexV2` | User-Agent application name |
| `OANDA_RETRY_ATTEMPTS` | `3` | Maximum retry attempts |
| `OANDA_RETRY_MULTIPLIER` | `2` | Exponential retry multiplier |

Timeout and retry delay fields can also be supplied through
`OandaSettings(...)` when a deployment needs explicit `timedelta` values.
Tokens are stored as Pydantic `SecretStr` values and are not included in normal
string representations.

## Quick start

`OandaProvider` creates one shared gateway and exposes Core account, broker,
and market-data services:

```python
from autoforex.oanda import OandaProvider, OandaSettings

settings = OandaSettings()
provider = OandaProvider.from_settings(settings)
try:
    accounts = provider.accounts.list_accounts()
    summary = provider.accounts.get_account_summary(accounts[0].id)
    print(summary)
finally:
    provider.close()
```

Construct settings directly when environment loading is not appropriate:

```python
from pydantic import SecretStr

from autoforex.oanda import OandaEnvironment, OandaSettings

settings = OandaSettings(
    account_id="001-001-1234567-001",
    access_token=SecretStr("token"),
    environment=OandaEnvironment.PRACTICE,
)
```

## Components

| Component | Purpose |
| --- | --- |
| `OandaProvider` | Shared account, broker, and data-source bundle |
| `OandaGateway` | Low-level facade over REST v20 endpoint clients |
| `OandaAccountManager` | Core account-management implementation |
| `OandaBroker` | Core broker implementation |
| `OandaDataSource` | Core pricing and candle data source |
| `OandaSettings` | Validated environment-backed settings |
| `OandaRetryPolicy` | Transport retry configuration |

The public package also exports typed OANDA response models, snapshots,
mappers, and categorized adapter exceptions.

## Market data

Read the latest prices:

```python
from autoforex.core import CurrencyPair
from autoforex.oanda import OandaDataSource, OandaSettings

source = OandaDataSource.from_settings(OandaSettings())
try:
    ticks = source.prices(
        instruments=(CurrencyPair.of("EUR_USD"), CurrencyPair.of("USD_JPY")),
    )
    for tick in ticks:
        print(tick.instrument, tick.bid, tick.ask)
finally:
    source.close()
```

`OandaDataSource` supports:

- latest account prices;
- live pricing streams;
- OANDA candlesticks mapped to Core candles;
- Core tick sampling and filters.

OANDA does not expose arbitrary historical tick ranges. Calling
`ticks(..., end_at=...)` raises `NotImplementedError`; use candles or a
historical data adapter such as `auto-forex-aws` for bounded backtests.

## Accounts and broker operations

`OandaAccountManager` exposes account listing, summaries, instruments, account
changes, alias changes, and margin-rate configuration.

`OandaBroker` exposes:

- order placement, replacement, cancellation, and client extensions;
- trade listing, lookup, closure, dependent orders, and streaming;
- position listing, lookup, and closure;
- transaction pages, ranges, lookup, and streaming;
- mutation cursors and reconciliation for interrupted broker operations.

Domain inputs and outputs use Core types such as `Order`, `Trade`, `Position`,
`Transaction`, `CurrencyPair`, `Money`, and `Units`.

## Low-level gateway

Use `OandaGateway` when direct REST response access is required:

```python
from autoforex.oanda import OandaGateway, OandaSettings

gateway = OandaGateway.from_settings(OandaSettings())
response = gateway.accounts.list_accounts()
```

Endpoint groups are available as:

- `gateway.accounts`
- `gateway.orders`
- `gateway.positions`
- `gateway.pricing`
- `gateway.trades`
- `gateway.transactions`

The gateway returns typed `OandaResponse` objects and should be preferred only
when the provider-neutral Core interfaces do not expose a required operation.

## Errors and retries

Transport and API failures are categorized:

- authentication and authorization failures;
- bad requests and missing resources;
- rate limiting;
- connection and timeout failures;
- retryable and non-retryable server responses.

The transport retries only operations declared safe by the endpoint policy.
Mutation retries and post-failure reconciliation require stable client IDs and
transaction history; `auto-forex-server` adds a durable execution journal
around these operations.

## Live-trading safety

- Keep `OANDA_ENVIRONMENT=practice` until the complete workflow is validated.
- Use separate practice and live credentials.
- Never log or commit access tokens.
- Apply account-level risk limits outside the adapter.
- Treat network timeouts as unknown outcomes until transaction reconciliation
  proves whether a mutation was applied.
- Close providers and data sources to release streaming HTTP resources.

## Development

From `src/oanda` in the repository:

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest tests/unit tests/integration
```

Live E2E tests require practice credentials. The suite covers every public
gateway endpoint and includes mutating practice-account scenarios.
