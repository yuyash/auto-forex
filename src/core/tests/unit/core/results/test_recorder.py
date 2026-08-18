from __future__ import annotations

import csv
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from autoforex.core import (
    BacktestTaskDefinition,
    CsvResultStore,
    CurrencyPair,
    CycleSummary,
    DataSource,
    Metadata,
    Money,
    ProfitMetric,
    ResultBatch,
    SqlResultStore,
    Strategy,
    StrategyAction,
    StrategyContext,
    StrategyDecisionCode,
    StrategyDecisionReason,
    StrategyEvent,
    StrategyEventRecord,
    StrategyEventRequest,
    StrategyResult,
    TaskManager,
    TaskResultRecorder,
    TaskStatus,
    TaskSummary,
    Tick,
    TradeSide,
    TradeSummary,
    Units,
    new_uuid,
)


class TwoTickDataSource(DataSource):
    def __init__(self, ticks: tuple[Tick, Tick]) -> None:
        self._ticks = ticks

    def _raw_ticks(
        self,
        *,
        instrument: CurrencyPair,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Tick]:
        _ = instrument
        _ = start_at
        _ = end_at
        yield from self._ticks


class OpenCloseStrategy(Strategy):
    def __init__(self) -> None:
        super().__init__(name="open-close")
        self._count = 0

    def on_tick(self, tick: Tick, context: StrategyContext) -> StrategyResult:
        self._count += 1
        if self._count == 1:
            return StrategyResult(
                events=(
                    StrategyEventRequest(
                        timestamp=tick.timestamp,
                        task_id=context.task_id,
                        display_id="C1L1R0B1",
                        action=StrategyAction.OPEN_TRADE,
                        instrument=tick.instrument,
                        side=TradeSide.BUY,
                        units=Units.of("1000"),
                        price=Money.of("150.12", "JPY"),
                        reason=StrategyDecisionReason(
                            code=StrategyDecisionCode.ENTRY_SIGNAL,
                            rule_id="test.open",
                        ),
                        metadata=Metadata.of(
                            strategy_type="test",
                            cycle_id=1,
                            direction="long",
                            entry_id="C1:L1:S0:REQ:B1",
                            entry_role="forward",
                            layer_number=1,
                            slot_number=0,
                            build_number=1,
                            planned_units="1000",
                            planned_entry_price="150.12 JPY",
                            planned_take_profit_price="150.22 JPY",
                            planned_stop_loss_price="150.02 JPY",
                        ),
                    ),
                )
            )
        return StrategyResult(
            events=(
                StrategyEventRequest(
                    timestamp=tick.timestamp,
                    task_id=context.task_id,
                    display_id="C1L1R0B1",
                    action=StrategyAction.CLOSE_TRADE,
                    instrument=tick.instrument,
                    side=TradeSide.SELL,
                    units=Units.of("1000"),
                    price=Money.of("150.22", "JPY"),
                    reason=StrategyDecisionReason(
                        code=StrategyDecisionCode.EXIT_SIGNAL,
                        rule_id="test.close.take_profit",
                    ),
                    metadata=Metadata.of(
                        strategy_type="test",
                        cycle_id=1,
                        direction="long",
                        entry_id="C1:L1:S0:FIL:B1",
                        entry_role="forward",
                        layer_number=1,
                        slot_number=0,
                        build_number=1,
                        close_reason="take_profit",
                        filled_units="1000",
                        planned_entry_price="150.12 JPY",
                        filled_entry_price="150.12 JPY",
                        planned_take_profit_price="150.22 JPY",
                        planned_stop_loss_price="150.02 JPY",
                        realized_pl="100.00 JPY",
                    ),
                ),
            )
        )


class OpenOnlyStrategy(Strategy):
    def __init__(self) -> None:
        super().__init__(name="open-only")
        self._opened = False

    def on_tick(self, tick: Tick, context: StrategyContext) -> StrategyResult:
        if self._opened:
            return StrategyResult()
        self._opened = True
        return StrategyResult(
            events=(
                StrategyEventRequest(
                    timestamp=tick.timestamp,
                    task_id=context.task_id,
                    display_id="C1L1R0B1",
                    action=StrategyAction.OPEN_TRADE,
                    instrument=tick.instrument,
                    side=TradeSide.BUY,
                    units=Units.of("1000"),
                    price=Money.of("150.12", "JPY"),
                    reason=StrategyDecisionReason(
                        code=StrategyDecisionCode.ENTRY_SIGNAL,
                        rule_id="test.open",
                    ),
                    metadata=Metadata.of(
                        strategy_type="test",
                        cycle_id=1,
                        direction="long",
                        entry_id="C1:L1:S0:REQ:B1",
                        entry_role="forward",
                        layer_number=1,
                        slot_number=0,
                        build_number=1,
                        planned_units="1000",
                        planned_entry_price="150.12 JPY",
                        filled_entry_price="150.12 JPY",
                        planned_take_profit_price="150.22 JPY",
                        planned_stop_loss_price="150.02 JPY",
                    ),
                ),
            )
        )


class RecordingResultStore:
    def __init__(self, *, fail_once: bool = False) -> None:
        self.fail_once = fail_once
        self.save_batch_count = 0
        self.batches: list[ResultBatch] = []

    def save_event(self, record: StrategyEventRecord) -> None:
        self.save_batch(ResultBatch(events=(record,)))

    def save_trade(self, summary: TradeSummary) -> None:
        self.save_batch(ResultBatch(trades=(summary,)))

    def save_cycle(self, summary: CycleSummary) -> None:
        self.save_batch(ResultBatch(cycles=(summary,)))

    def save_task(self, summary: TaskSummary) -> None:
        self.save_batch(ResultBatch(tasks=(summary,)))

    def save_metric(self, metric: ProfitMetric) -> None:
        self.save_batch(ResultBatch(metrics=(metric,)))

    def save_batch(self, batch: ResultBatch) -> None:
        self.save_batch_count += 1
        if self.fail_once:
            self.fail_once = False
            msg = "store failed once"
            raise RuntimeError(msg)
        self.batches.append(batch)


class TestTaskResultRecorder:
    def test_task_result_recorder_aggregates_events_trades_cycles_tasks_and_metrics(
        self,
        tmp_path: Path,
        sql_result_store: SqlResultStore,
    ) -> None:
        instrument = CurrencyPair.of("USD_JPY")
        ticks = (
            Tick(
                instrument=instrument,
                timestamp=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
                bid=Money.of("150.10", "JPY"),
                ask=Money.of("150.12", "JPY"),
            ),
            Tick(
                instrument=instrument,
                timestamp=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
                bid=Money.of("150.22", "JPY"),
                ask=Money.of("150.24", "JPY"),
            ),
        )
        definition = BacktestTaskDefinition(
            name="Backtest USD_JPY",
            instrument=instrument,
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
        )
        csv_store = CsvResultStore(tmp_path / "results")
        recorder = TaskResultRecorder(
            stores=(csv_store, sql_result_store),
            metric_interval=timedelta(minutes=1),
        )

        with TaskManager(
            max_workers=1,
            observers=(recorder,),
            event_handlers=(recorder,),
        ) as manager:
            run = manager.start_backtest(
                definition,
                data_source=TwoTickDataSource(ticks),
                strategy=OpenCloseStrategy(),
            )
            final_task = run.wait(timeout=2)

        assert final_task.status == TaskStatus.COMPLETED
        assert len(recorder.event_records(final_task.id)) == 2
        assert len(recorder.memory.metrics) == 2

        trade = recorder.trade_summaries(final_task.id)[0]
        assert trade.trade_id == "C1L1R0B1"
        assert trade.close_reason == "take_profit"
        assert trade.realized_pl == Money.of("100.00", "JPY")

        cycle = recorder.cycle_summaries(final_task.id)[0]
        assert cycle.trade_ids == ("C1L1R0B1",)
        assert cycle.realized_pl == Money.of("100.00", "JPY")

        task_summary = recorder.memory.tasks[0]
        assert task_summary.task_id == final_task.id
        assert task_summary.realized_pl == Money.of("100.00", "JPY")

        assert (tmp_path / "results" / "strategy_events.csv").exists()
        assert (tmp_path / "results" / "profit_metrics.csv").exists()
        with (tmp_path / "results" / "cycle_summaries.csv").open(encoding="utf-8") as handle:
            cycle_rows = tuple(csv.DictReader(handle))
        assert len(cycle_rows) >= 1
        assert csv_store.event_records(final_task.id)[0].display_id == "C1L1R0B1"
        assert csv_store.trade_summaries(final_task.id)[0].realized_pl == Money.of("100.00", "JPY")
        assert csv_store.cycle_summaries(final_task.id)[0].realized_pl == Money.of("100.00", "JPY")
        assert csv_store.task_summaries(final_task.id)[0].realized_pl == Money.of("100.00", "JPY")
        assert len(csv_store.profit_metrics(final_task.id)) == 2
        csv_store.save_batch(
            ResultBatch(
                events=recorder.event_records(final_task.id),
                metrics=recorder.memory.metrics,
            )
        )
        with (tmp_path / "results" / "strategy_events.csv").open(encoding="utf-8") as handle:
            event_rows = tuple(csv.DictReader(handle))
        with (tmp_path / "results" / "profit_metrics.csv").open(encoding="utf-8") as handle:
            metric_rows = tuple(csv.DictReader(handle))
        assert len(event_rows) == 2
        assert len(metric_rows) == 2

        with sql_result_store.engine.connect() as connection:
            event_count = connection.execute(
                text("select count(*) from strategy_events")
            ).scalar_one()
            trade_count = connection.execute(
                text("select count(*) from trade_summaries")
            ).scalar_one()
            metric_count = connection.execute(
                text("select count(*) from profit_metrics")
            ).scalar_one()

        assert event_count == 2
        assert trade_count == 1
        assert metric_count == 2
        assert sql_result_store.event_records(final_task.id)[0].display_id == "C1L1R0B1"
        assert sql_result_store.trade_summaries(final_task.id)[0].realized_pl == Money.of(
            "100.00", "JPY"
        )
        assert sql_result_store.cycle_summaries(final_task.id)[0].realized_pl == Money.of(
            "100.00", "JPY"
        )
        assert sql_result_store.task_summaries(final_task.id)[0].realized_pl == Money.of(
            "100.00", "JPY"
        )
        assert len(sql_result_store.profit_metrics(final_task.id)) == 2
        assert recorder.ledger.trades == {}
        assert recorder.metrics.last_metric_at == {}

    def test_task_result_recorder_persists_open_trades_at_task_finish(
        self,
        tmp_path: Path,
        sql_result_store: SqlResultStore,
    ) -> None:
        instrument = CurrencyPair.of("USD_JPY")
        ticks = (
            Tick(
                instrument=instrument,
                timestamp=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
                bid=Money.of("150.10", "JPY"),
                ask=Money.of("150.12", "JPY"),
            ),
            Tick(
                instrument=instrument,
                timestamp=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
                bid=Money.of("150.11", "JPY"),
                ask=Money.of("150.13", "JPY"),
            ),
        )
        definition = BacktestTaskDefinition(
            name="Backtest USD_JPY",
            instrument=instrument,
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
        )
        csv_store = CsvResultStore(tmp_path / "results")
        recorder = TaskResultRecorder(
            stores=(csv_store, sql_result_store),
            flush_every=100,
        )

        with TaskManager(
            max_workers=1,
            observers=(recorder,),
            event_handlers=(recorder,),
        ) as manager:
            run = manager.start_backtest(
                definition,
                data_source=TwoTickDataSource(ticks),
                strategy=OpenOnlyStrategy(),
            )
            final_task = run.wait(timeout=2)

        assert final_task.status == TaskStatus.COMPLETED
        trade = recorder.trade_summaries(final_task.id)[0]
        assert not trade.is_closed
        assert trade.trade_id == "C1L1R0B1"

        with (tmp_path / "results" / "trade_summaries.csv").open(encoding="utf-8") as handle:
            trade_rows = tuple(csv.DictReader(handle))
        assert len(trade_rows) == 1
        assert trade_rows[0]["trade_id"] == "C1L1R0B1"

        with sql_result_store.engine.connect() as connection:
            trade_count = connection.execute(
                text("select count(*) from trade_summaries")
            ).scalar_one()
        assert trade_count == 1
        assert recorder.ledger.trades == {}

    def test_task_result_recorder_keeps_store_buffers_independent_on_flush_failure(self) -> None:
        successful_store = RecordingResultStore()
        failing_store = RecordingResultStore(fail_once=True)
        recorder = TaskResultRecorder(
            stores=(successful_store, failing_store),
            flush_every=100,
        )
        task_id = new_uuid()
        request = StrategyEventRequest(
            task_id=task_id,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            action=StrategyAction.HOLD,
            instrument=CurrencyPair.of("USD_JPY"),
        )
        recorder.handle(
            StrategyEvent(
                task_id=task_id,
                instrument=request.instrument,
                request=request,
            )
        )

        with pytest.raises(RuntimeError, match="store failed once"):
            recorder.flush()

        recorder.flush()

        assert successful_store.save_batch_count == 1
        assert failing_store.save_batch_count == 2
        assert len(successful_store.batches) == 1
        assert len(failing_store.batches) == 1
