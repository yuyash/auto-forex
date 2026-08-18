from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from autoforex.core import (
    BacktestTaskDefinition,
    CSVDataSource,
    CurrencyPair,
    ExecutableTask,
    Metadata,
    Strategy,
    StrategyAction,
    StrategyContext,
    StrategyDecisionCode,
    StrategyDecisionReason,
    StrategyEventRequest,
    StrategyParameters,
    StrategyResult,
    TaskStatus,
    TaskType,
    Tick,
)


class HoldStrategy(Strategy):
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
                        rule_id="hold.default",
                        evidence=Metadata.of(mid=str(tick.effective_mid)),
                    ),
                ),
            )
        )


class TestBacktestHoldFlow:
    def test_backtest_task_processes_csv_ticks_end_to_end(self, tmp_path: Path) -> None:
        tick_path = tmp_path / "ticks.csv"
        tick_path.write_text(
            "\n".join(
                [
                    "timestamp,instrument,bid,ask",
                    "2026-01-01T00:00:00Z,USD_JPY,150.10,150.12",
                    "2026-01-01T00:01:00Z,USD_JPY,150.11,150.13",
                ]
            ),
            encoding="utf-8",
        )
        instrument = CurrencyPair.of("USD_JPY")
        definition = BacktestTaskDefinition(
            name="Backtest USD_JPY",
            instrument=instrument,
            parameters=StrategyParameters.of(risk_percent=Decimal("1.0")),
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        task = ExecutableTask.from_definition(definition).start()
        source = CSVDataSource(tick_path=tick_path)
        strategy = HoldStrategy(name="hold", parameters=definition.parameters)
        context = StrategyContext(
            task_id=task.id,
            task_type=TaskType.BACKTEST,
            instrument=instrument,
            metadata=Metadata.of(strategy_name=strategy.name),
        )

        events = [
            event
            for tick in source.ticks(instrument=instrument)
            for event in strategy.on_tick(tick, context).events
        ]
        completed = task.complete()

        assert completed.status == TaskStatus.COMPLETED
        assert len(events) == 2
        assert {event.action for event in events} == {StrategyAction.HOLD}
        assert all(event.task_id == task.id for event in events)
