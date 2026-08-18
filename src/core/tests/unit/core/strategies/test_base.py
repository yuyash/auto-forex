from datetime import UTC, datetime
from decimal import Decimal

from autoforex.core import (
    CurrencyPair,
    Metadata,
    Money,
    StrategyAction,
    StrategyDecisionCode,
    StrategyDecisionReason,
    StrategyEventRequest,
    StrategyParameters,
    StrategyState,
    Tick,
    new_uuid,
)
from autoforex.core.strategies import Strategy, StrategyContext, StrategyResult
from autoforex.core.tasks import TaskType


class HoldStrategy(Strategy):
    def on_tick(self, tick: Tick, context: StrategyContext) -> StrategyResult:
        return StrategyResult(
            events=(
                StrategyEventRequest(
                    timestamp=tick.timestamp,
                    task_id=context.task_id,
                    action=StrategyAction.HOLD,
                    instrument=tick.instrument,
                    reason=StrategyDecisionReason(code=StrategyDecisionCode.HOLD),
                ),
            ),
            state=StrategyState.of(seen_ticks=1),
        )


class TestBase:
    def test_strategy_normalizes_parameters_and_context(self) -> None:
        strategy = HoldStrategy(
            name="hold",
            parameters=StrategyParameters.of(risk_percent=Decimal("1.5")),
        )
        context = StrategyContext(
            task_id=new_uuid(),
            task_type=TaskType.BACKTEST,
            instrument=CurrencyPair.of("USD_JPY"),
            metadata=Metadata.of(source="unit"),
        )
        tick = Tick(
            instrument=CurrencyPair.of("USD_JPY"),
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            bid=Money.of("150.10", "JPY"),
            ask=Money.of("150.12", "JPY"),
        )

        result = strategy.on_tick(tick, context)
        log_extra = strategy._log_extra(context=context)

        assert strategy.parameters == StrategyParameters.of(risk_percent=Decimal("1.5"))
        assert context.pip_size == Decimal("0.01")
        assert context.account_balance == Money.of("10000", "USD")
        assert result.state == StrategyState.of(seen_ticks=1)
        assert result.events[0].task_id == context.task_id
        assert log_extra.strategy_name == "hold"
        assert dict(log_extra) == {
            "task_id": str(context.task_id),
            "task_type": TaskType.BACKTEST.value,
            "strategy_name": "hold",
            "strategy_class": "HoldStrategy",
            "instrument": "USD_JPY",
            "parameter_count": 1,
        }
