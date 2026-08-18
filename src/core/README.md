# auto-forex-core

`auto-forex-core` contains the provider-neutral domain model and execution
contracts used by AutoForex packages. It provides typed value objects, market
data and broker ports, strategy lifecycle APIs, task state management, event
handling, result stores, and backtest/live execution primitives.

The distribution is installed as `auto-forex-core` and imported as
`autoforex.core`.

> **Project status:** Alpha. Public APIs may change before a stable release.
> Automated trading involves financial risk; this package does not provide
> investment advice or a profitable strategy.

## Requirements

- Python 3.14 or newer
- Platforms supported by the package's Python dependencies

## Installation

```bash
pip install auto-forex-core
```

Optional task profiling support is available as an extra:

```bash
pip install "auto-forex-core[profiling]"
```

## Quick start

Create validated domain values and an immutable task definition:

```python
from datetime import UTC, datetime

from autoforex.core import (
    BacktestTaskDefinition,
    CurrencyPair,
    ExecutableTask,
    StrategyParameters,
    TaskStatus,
)

definition = BacktestTaskDefinition(
    name="USD/JPY example",
    instrument=CurrencyPair.of("USD_JPY"),
    start_at=datetime(2026, 1, 1, tzinfo=UTC),
    end_at=datetime(2026, 1, 2, tzinfo=UTC),
    parameters=StrategyParameters.of(window=20),
)

created = ExecutableTask.from_definition(definition)
running = created.start()

assert created.status == TaskStatus.CREATED
assert running.status == TaskStatus.RUNNING
```

Task and domain objects are immutable. Lifecycle methods return updated values
instead of modifying the previous instance.

Create a market-data tick:

```python
from datetime import UTC, datetime

from autoforex.core import CurrencyPair, Money, Tick

tick = Tick(
    instrument=CurrencyPair.of("USD_JPY"),
    timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    bid=Money.of("150.10", "JPY"),
    ask=Money.of("150.12", "JPY"),
)

print(tick.instrument, tick.spread)
```

## Package scope

### Domain models

Core exports validated models for:

- currencies, currency pairs, money, pips, percentages, margin rates, and
  trading units;
- accounts, orders, positions, trades, and transactions;
- broker and provider identifiers;
- immutable metadata and UUID generation.

Values reject incompatible currencies and invalid ranges close to the point
where they enter the system.

### Market data

`DataSource` is the provider-neutral market-data interface. Implementations can
produce:

- historical or live `Tick` values;
- `Candle` values with `CandleGranularity`;
- sampled tick streams using `TickGranularity`;
- filtered streams through `DataSourceFilter`.

`CSVDataSource` is included for local historical data. Cloud and broker-backed
implementations are provided separately by `auto-forex-aws` and
`auto-forex-oanda`.

### Strategies

Subclass `Strategy` to implement an algorithm:

```python
from autoforex.core import (
    Strategy,
    StrategyAction,
    StrategyContext,
    StrategyDecisionCode,
    StrategyDecisionReason,
    StrategyEventRequest,
    StrategyResult,
    Tick,
)


class HoldStrategy(Strategy):
    def __init__(self) -> None:
        super().__init__(name="hold")

    def on_tick(self, tick: Tick, context: StrategyContext) -> StrategyResult:
        return StrategyResult(
            events=(
                StrategyEventRequest(
                    timestamp=tick.timestamp,
                    task_id=context.task_id,
                    action=StrategyAction.HOLD,
                    instrument=tick.instrument,
                    reason=StrategyDecisionReason(
                        code=StrategyDecisionCode.HOLD,
                    ),
                ),
            )
        )
```

Strategies receive a `StrategyContext`, emit immutable
`StrategyEventRequest` values, and may persist `StrategyState`. Lifecycle hooks
include start, recovery, tick, candle, execution-report, and stop processing.

### Broker and provider ports

The main extension contracts are:

| Contract | Responsibility |
| --- | --- |
| `AccountManager` | Accounts, balances, and instrument access |
| `Broker` | Orders, positions, trades, and mutation reconciliation |
| `DataSource` | Historical and live market data |
| `TradingProvider` | One bundle containing account, broker, and data services |

Provider implementations belong in adapter packages. Core itself does not
contain broker credentials or provider-specific HTTP clients.

### Task execution

Core distinguishes immutable definitions from executable state:

- `BacktestTaskDefinition` describes a historical replay window.
- `TradingTaskDefinition` describes a live or dry-run account task.
- `ExecutableTask` holds lifecycle state and checkpoints.
- `TaskManager`, `BacktestRunner`, and `TradingRunner` coordinate execution.
- `TaskRegistry` defines durable task persistence.

The lifecycle state machine validates start, pause, resume, stop, complete,
restart, and failure transitions.

### Events and results

`EventBus` provides typed publication and subscription. Result APIs include:

- `TaskResultRecorder`;
- in-memory, CSV, and SQL result stores;
- task, cycle, trade, and profit summaries;
- `ProfitMetricStore` for external metric sinks.

## Logging

Core uses standard-library logging under the stable `core` logger hierarchy.
Applications can configure logging themselves or use:

```python
from autoforex.core import LogLevel, configure_logging

configure_logging(level=LogLevel.INFO)
```

The lifecycle and strategy log records include structured fields such as task
ID, task type, action, status, instrument, and strategy name.

## Related packages

| Distribution | Relationship |
| --- | --- |
| `auto-forex-snowball` | Strategy implementation built on Core |
| `auto-forex-aws` | Athena, DynamoDB, and CloudWatch adapters |
| `auto-forex-oanda` | OANDA REST v20 provider adapter |
| `auto-forex-server` | Durable gRPC task service |

## Development

From `src/core` in the repository:

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
```

The source distribution includes an Apache-2.0 license and `py.typed` marker.
