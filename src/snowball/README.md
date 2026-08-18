# auto-forex-snowball

`auto-forex-snowball` provides the Snowball grid strategy as an
`auto-forex-core` `Strategy`. It contains validated configuration, immutable
grid and entry state, event mapping, execution-report reconciliation, and
recovery-safe state serialization.

The distribution is installed as `auto-forex-snowball` and imported as
`autoforex.snowball`.

> **Project status:** Alpha. Snowball can generate broker order requests and
> can accumulate substantial leveraged exposure. Backtest and validate every
> configuration with realistic spreads, slippage, margin, and failure
> scenarios. No profitability is promised.

## Requirements

- Python 3.14 or newer
- `auto-forex-core`
- A Core-compatible data source and, for execution, broker/provider

## Installation

```bash
pip install auto-forex-snowball
```

Snowball is installed and registered automatically by `auto-forex-server`.

## Quick start

Create a strategy with nested Core parameters:

```python
from autoforex.core import StrategyParameters
from autoforex.snowball import SnowballStrategy

strategy = SnowballStrategy(
    parameters=StrategyParameters.of(
        cycle={"hedging_enabled": False},
        grid={
            "max_layers": 2,
            "max_retracements_per_layer": 3,
        },
        sizing={"base_units": "1000"},
        forward={"take_profit_pips": "20"},
    )
)

print(strategy.config)
```

Parameters are merged with defaults, normalized into typed values, and
validated during construction. Invalid combinations raise `ValueError` before
task execution starts.

Inspect default parameters:

```python
defaults = SnowballStrategy.default_parameters()
print(defaults.to_dict())
```

## Strategy behavior

Snowball maintains one or more grid layers. A market tick can produce Core
strategy events for:

- opening forward and counter entries;
- closing entries at take profit;
- stop-loss execution;
- rebuilding stopped entries;
- shrinking exposure under margin pressure;
- emergency protection.

Broker fills are applied through `on_execution_reports()`. The strategy
serializes its complete runtime state into Core `StrategyState`, allowing the
server to checkpoint and recover the same run.

## Configuration

`SnowballConfig` is divided into nine sections:

| Section | Controls |
| --- | --- |
| `sizing` | Fixed or balance-based units and layer multipliers |
| `grid` | Layer count, retracement count, and slot refill |
| `cycle` | Hedging and cycle reseeding |
| `forward` | Forward-entry take-profit distance |
| `counter` | Counter-entry spacing and take-profit progression |
| `stop_loss` | Stop-loss mode, distance, and protected retracements |
| `rebuild` | Re-entry price, stop-loss, and take-profit behavior |
| `protection` | Margin shrink and emergency thresholds |
| `account` | Initial balance, margin rate, and quote conversion |

### Important defaults

| Parameter | Default |
| --- | --- |
| `sizing.mode` | `fixed` |
| `sizing.base_units` | `1000` |
| `grid.max_retracements_per_layer` | `7` |
| `grid.max_layers` | `3` |
| `grid.refill.enabled` | `true` |
| `cycle.hedging_enabled` | `true` |
| `forward.take_profit_pips` | `50` |
| `counter.interval.mode` | `constant` |
| `stop_loss.enabled` | `false` |
| `rebuild.enabled` | `true` |
| `protection.shrink_enabled` | `false` |
| `protection.emergency_enabled` | `true` |
| `account.initial_balance` | `10000 USD` |
| `account.margin_rate` | `0.04` |

### Balance-based sizing

```python
from autoforex.core import StrategyParameters
from autoforex.snowball import SnowballStrategy

strategy = SnowballStrategy(
    parameters=StrategyParameters.of(
        account={
            "initial_balance": {
                "amount": "1000000",
                "currency": "JPY",
            }
        },
        sizing={
            "mode": "balance_based",
            "base_units": "1000",
            "balance_based": {
                "round_step_units": "100",
                "min_units": "100",
            },
        },
    )
)
```

At runtime, Core's current account balance scales the original base units
relative to `account.initial_balance`. `account.balance` and
`account.currency` are rejected because they are ambiguous; use the structured
`initial_balance` value.

### Stop loss and rebuild

```python
parameters = StrategyParameters.of(
    stop_loss={
        "enabled": True,
        "mode": "distance",
        "distance": {
            "mode": "constant",
            "head_pips": "10",
            "tail_pips": "10",
            "flat_steps": 0,
        },
    },
    rebuild={
        "enabled": True,
        "price": {
            "entry_price_mode": "stop_loss_exit_price",
            "buffer_pips": "0",
        },
    },
)
```

Interval progressions support constant, progressive, and manual values.
Manual arrays must be long enough for the configured retracement count.

### Margin protection

Protection settings model strategy-side estimates and do not replace broker
margin controls:

```python
parameters = StrategyParameters.of(
    protection={
        "shrink_enabled": True,
        "shrink_start_margin_percent": "70",
        "shrink_target_margin_percent": "50",
        "emergency_enabled": True,
        "emergency_margin_percent": "95",
    }
)
```

`stop_loss.enabled` and `protection.shrink_enabled` cannot both be enabled.
Protection thresholds must be ordered and within their validated ranges.

## Core lifecycle integration

`SnowballStrategy` implements:

- `on_start()` to initialize state;
- `on_recover()` to restore state without repeating start side effects;
- `on_tick()` to produce entry and close requests;
- `on_execution_reports()` to apply broker outcomes;
- `strategy_state()` to produce a durable Core state snapshot.

Always pass the returned state into the next `StrategyContext`. The Core
runners and `auto-forex-server` handle this automatically.

## Server integration

`auto-forex-server` registers Snowball under the component name `snowball`.
gRPC clients select it with:

```python
task_pb.StrategyReference(
    name="snowball",
    parameters={
        "grid": {"max_layers": 2},
        "sizing": {"base_units": "1000"},
    },
)
```

The protobuf `Struct` parameters must be JSON-compatible.

## Risk considerations

Snowball configurations should be evaluated for:

- maximum simultaneous units and layers;
- spread widening and slippage;
- gap behavior around stop-loss and rebuild levels;
- margin use under one-sided markets;
- currency conversion assumptions;
- partial fills and rejected orders;
- provider disconnects and reconciliation;
- backtest data quality and look-ahead bias.

Use broker-side limits and independent account monitoring in addition to
strategy protection.

## Architecture

The package separates:

- immutable domain state in `models`;
- Snowball domain events in `events`;
- policy decisions in `services/policies`;
- read-only grid selection in `services/selectors`;
- state-changing flows in `services/flows`;
- tick/cycle orchestration in `services/stages` and `engine`;
- Core adapters in `event_mapper`, `serialization`, and `strategy`.

## Development

From `src/snowball` in the repository:

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
```
