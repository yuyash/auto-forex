from __future__ import annotations

import sys
from collections.abc import Iterable
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event as ThreadEvent
from threading import Timer
from types import ModuleType
from typing import Any

import pytest

from autoforex.core import (
    Account,
    AccountId,
    BacktestTaskDefinition,
    CurrencyPair,
    DataSource,
    EventBus,
    InMemoryTaskRegistry,
    Metadata,
    Money,
    Strategy,
    StrategyAction,
    StrategyAlreadyRunningError,
    StrategyContext,
    StrategyEvent,
    StrategyEventRequest,
    StrategyExecutionResponse,
    StrategyParameters,
    StrategyResult,
    StrategyState,
    TaskManager,
    TaskProfilingConfig,
    TaskProgress,
    TaskStatus,
    Tick,
    TradeSide,
    TradingTaskDefinition,
    Units,
)


class OneTickDataSource(DataSource):
    def __init__(self, tick: Tick) -> None:
        self.tick = tick

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
        yield self.tick


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


class SequenceTickDataSource(DataSource):
    def __init__(self, ticks: tuple[Tick, ...]) -> None:
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


class BlockingLiveDataSource(DataSource):
    def __init__(self) -> None:
        self.entered = ThreadEvent()
        self.release = ThreadEvent()

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
        self.entered.set()
        self.release.wait(timeout=2)
        yield from ()


class CountingTaskRegistry(InMemoryTaskRegistry):
    def __init__(self) -> None:
        super().__init__()
        self.save_count = 0

    def save(self, task: Any) -> Any:
        self.save_count += 1
        return super().save(task)


class HoldStrategy(Strategy):
    def on_tick(self, tick: Tick, context: StrategyContext) -> StrategyResult:
        _ = tick
        _ = context
        return StrategyResult()


class RecordingBalanceStrategy(Strategy):
    def __init__(self) -> None:
        super().__init__(name="recording-balance")
        self.account_balances: list[Money] = []

    def on_start(self, context: StrategyContext) -> StrategyResult:
        self.account_balances.append(context.account_balance)
        return StrategyResult()

    def on_tick(self, tick: Tick, context: StrategyContext) -> StrategyResult:
        _ = tick
        _ = context
        return StrategyResult()


class AccountBalanceTradingStrategy(Strategy):
    def __init__(self) -> None:
        super().__init__(name="account-balance-trading")
        self.account_balances: list[Money] = []

    def on_tick(self, tick: Tick, context: StrategyContext) -> StrategyResult:
        seen_ticks = int(context.state.get("seen_ticks", 0))
        self.account_balances.append(context.account_balance)
        events: tuple[StrategyEventRequest, ...] = ()
        if seen_ticks == 0:
            events = (
                StrategyEventRequest(
                    timestamp=tick.timestamp,
                    task_id=context.task_id,
                    display_id="T1",
                    action=StrategyAction.OPEN_TRADE,
                    instrument=tick.instrument,
                    side=TradeSide.BUY,
                    units=Units("100"),
                    price=tick.ask,
                ),
            )
        elif seen_ticks == 1:
            events = (
                StrategyEventRequest(
                    timestamp=tick.timestamp,
                    task_id=context.task_id,
                    display_id="T1",
                    action=StrategyAction.CLOSE_TRADE,
                    instrument=tick.instrument,
                    side=TradeSide.SELL,
                    units=Units("100"),
                    price=tick.bid,
                ),
            )
        return StrategyResult(
            events=events,
            state=StrategyState.of(seen_ticks=seen_ticks + 1),
        )


class CountingStateStrategy(Strategy):
    def on_tick(self, tick: Tick, context: StrategyContext) -> StrategyResult:
        _ = tick
        seen_ticks = int(context.state.get("seen_ticks", 0)) + 1
        return StrategyResult(state=StrategyState.of(seen_ticks=seen_ticks))


class FailingFinishedObserver:
    def on_tick(self, task: object, tick: Tick) -> None:
        _ = task
        _ = tick

    def on_task_finished(self, task: object) -> None:
        _ = task
        msg = "result store failed"
        raise RuntimeError(msg)


class RecordingProgressReporter:
    def __init__(self) -> None:
        self.starts: list[TaskProgress] = []
        self.updates: list[TaskProgress] = []
        self.finishes: list[TaskProgress] = []
        self.close_count = 0

    def on_start(self, progress: TaskProgress) -> None:
        self.starts.append(progress)

    def on_update(self, progress: TaskProgress) -> None:
        self.updates.append(progress)

    def on_finish(self, progress: TaskProgress) -> None:
        self.finishes.append(progress)

    def close(self) -> None:
        self.close_count += 1


class FakePyinstrumentProfiler:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.resample_interval: float | None = None

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def output_html(self, resample_interval: float | None = None) -> str:
        assert self.started
        assert self.stopped
        self.resample_interval = resample_interval
        return f"<html><body>profile {resample_interval}</body></html>"


class TwoTickBlockingDataSource(DataSource):
    def __init__(
        self,
        *,
        first_tick: Tick,
        second_tick: Tick,
        first_tick_processed: ThreadEvent,
        release_second_tick: ThreadEvent,
    ) -> None:
        self.first_tick = first_tick
        self.second_tick = second_tick
        self.first_tick_processed = first_tick_processed
        self.release_second_tick = release_second_tick

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
        yield self.first_tick
        self.first_tick_processed.set()
        released = self.release_second_tick.wait(timeout=2)
        if not released:
            msg = "second tick was not released"
            raise TimeoutError(msg)
        yield self.second_tick


class FailingDataSource(DataSource):
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
        msg = "source failed"
        raise RuntimeError(msg)


class TestTaskManagerExecution:
    def test_task_manager_start_backtest_returns_task_run_handle(self) -> None:
        instrument = CurrencyPair.of("USD_JPY")
        definition = BacktestTaskDefinition(
            name="Backtest USD_JPY",
            instrument=instrument,
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        tick = Tick(
            instrument=instrument,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            bid=Money.of("150.10", "JPY"),
            ask=Money.of("150.12", "JPY"),
            metadata=Metadata.of(source="test"),
        )

        with TaskManager(max_workers=1) as manager:
            run = manager.start_backtest(
                definition,
                data_source=OneTickDataSource(tick),
                strategy=HoldStrategy(name="hold"),
            )
            final_task = run.wait(timeout=2)

        assert run.task.status == TaskStatus.RUNNING
        assert run.current().status == TaskStatus.COMPLETED
        assert final_task.id == run.id
        assert final_task.status == TaskStatus.COMPLETED

    def test_backtest_strategy_context_uses_account_initial_balance_parameter(self) -> None:
        instrument = CurrencyPair.of("USD_JPY")
        definition = BacktestTaskDefinition(
            name="Backtest USD_JPY",
            instrument=instrument,
            parameters=StrategyParameters.of(
                account={
                    "initial_balance": {
                        "amount": "3000000",
                        "currency": "JPY",
                    }
                }
            ),
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        tick = Tick(
            instrument=instrument,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            bid=Money.of("150.10", "JPY"),
            ask=Money.of("150.12", "JPY"),
        )
        strategy = RecordingBalanceStrategy()

        with TaskManager(max_workers=1) as manager:
            run = manager.start_backtest(
                definition,
                data_source=OneTickDataSource(tick),
                strategy=strategy,
            )
            final_task = run.wait(timeout=2)

        assert final_task.status == TaskStatus.COMPLETED
        assert strategy.account_balances == [Money.of("3000000", "JPY")]

    def test_strategy_context_account_balance_tracks_realized_profit(self) -> None:
        instrument = CurrencyPair.of("EUR_USD")
        definition = BacktestTaskDefinition(
            name="Backtest EUR_USD",
            instrument=instrument,
            parameters=StrategyParameters.of(
                account={
                    "initial_balance": {
                        "amount": "1000",
                        "currency": "USD",
                    }
                }
            ),
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        ticks = (
            Tick(
                instrument=instrument,
                timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                bid=Money.of("10", "USD"),
                ask=Money.of("10", "USD"),
            ),
            Tick(
                instrument=instrument,
                timestamp=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
                bid=Money.of("12", "USD"),
                ask=Money.of("12", "USD"),
            ),
            Tick(
                instrument=instrument,
                timestamp=datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
                bid=Money.of("12", "USD"),
                ask=Money.of("12", "USD"),
            ),
        )
        strategy = AccountBalanceTradingStrategy()

        with TaskManager(max_workers=1) as manager:
            run = manager.start_backtest(
                definition,
                data_source=SequenceTickDataSource(ticks),
                strategy=strategy,
            )
            final_task = run.wait(timeout=2)

        assert final_task.status == TaskStatus.COMPLETED
        assert strategy.account_balances == [
            Money.of("1000", "USD"),
            Money.of("1000", "USD"),
            Money.of("1200", "USD"),
        ]

    def test_task_manager_configures_strategy_request_timeout(self) -> None:
        timeout = timedelta(seconds=30)

        manager = TaskManager(strategy_request_timeout=timeout)
        try:
            assert manager.event_bus.strategy_request_timeout == timeout
        finally:
            manager.shutdown()

    def test_task_manager_persists_latest_strategy_state(self) -> None:
        instrument = CurrencyPair.of("USD_JPY")
        definition = BacktestTaskDefinition(
            name="Backtest USD_JPY",
            instrument=instrument,
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        ticks = (
            Tick(
                instrument=instrument,
                timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                bid=Money.of("150.10", "JPY"),
                ask=Money.of("150.12", "JPY"),
            ),
            Tick(
                instrument=instrument,
                timestamp=datetime(2026, 1, 1, 1, tzinfo=UTC),
                bid=Money.of("150.20", "JPY"),
                ask=Money.of("150.22", "JPY"),
            ),
        )

        with TaskManager(max_workers=1) as manager:
            run = manager.start_backtest(
                definition,
                data_source=TwoTickDataSource(ticks),
                strategy=CountingStateStrategy(name="counting"),
            )
            final_task = run.wait(timeout=2)

        assert final_task.status == TaskStatus.COMPLETED
        assert final_task.strategy_state == StrategyState.of(seen_ticks=2)

    def test_task_manager_persists_checkpoint_when_strategy_state_is_unchanged(self) -> None:
        instrument = CurrencyPair.of("USD_JPY")
        definition = BacktestTaskDefinition(
            name="Backtest USD_JPY",
            instrument=instrument,
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        ticks = (
            Tick(
                instrument=instrument,
                timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                bid=Money.of("150.10", "JPY"),
                ask=Money.of("150.12", "JPY"),
            ),
            Tick(
                instrument=instrument,
                timestamp=datetime(2026, 1, 1, 1, tzinfo=UTC),
                bid=Money.of("150.20", "JPY"),
                ask=Money.of("150.22", "JPY"),
            ),
        )
        registry = CountingTaskRegistry()

        with TaskManager(registry=registry, max_workers=1) as manager:
            run = manager.start_backtest(
                definition,
                data_source=TwoTickDataSource(ticks),
                strategy=HoldStrategy(name="hold"),
            )
            final_task = run.wait(timeout=2)

        assert final_task.status == TaskStatus.COMPLETED
        assert final_task.last_processed_at == ticks[-1].timestamp
        assert registry.save_count == 4

    def test_task_manager_executes_bus_published_requests_for_active_task(self) -> None:
        instrument = CurrencyPair.of("USD_JPY")
        data_source = BlockingLiveDataSource()
        bus = EventBus(record_history=True)
        definition = TradingTaskDefinition(
            name="Trading USD_JPY",
            instrument=instrument,
            account=Account(id=AccountId.of("test-account")),
            dry_run=True,
        )

        with TaskManager(
            event_bus=bus,
            max_workers=1,
        ) as manager:
            run = manager.start_trading(
                definition,
                data_source=data_source,
                strategy=HoldStrategy(name="hold"),
            )
            assert data_source.entered.wait(timeout=2)
            request = StrategyEventRequest(
                timestamp=datetime.now().astimezone() - timedelta(seconds=1),
                task_id=run.id,
                action=StrategyAction.OPEN_TRADE,
                instrument=instrument,
                side=TradeSide.BUY,
                units=Units("1000"),
                price=Money.of("150.10", "JPY"),
                display_id="C1L1R0B1",
            )

            bus.publish(request)
            assert bus.pending_strategy_request_count == 0
            run.stop()
            data_source.release.set()
            final_task = run.wait(timeout=2)

        assert final_task.status == TaskStatus.STOPPED
        assert any(
            isinstance(event, StrategyExecutionResponse) and event.event.id == request.id
            for event in bus.history
        )
        assert any(
            isinstance(event, StrategyEvent) and event.request.id == request.id
            for event in bus.history
        )

    def test_task_manager_rejects_active_strategy_instance_reuse(self) -> None:
        instrument = CurrencyPair.of("USD_JPY")
        definition = BacktestTaskDefinition(
            name="Backtest USD_JPY",
            instrument=instrument,
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        second_definition = BacktestTaskDefinition(
            name="Second Backtest USD_JPY",
            instrument=instrument,
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        first_tick = Tick(
            instrument=instrument,
            timestamp=datetime(2026, 1, 1, 12, tzinfo=UTC),
            bid=Money.of("150.10", "JPY"),
            ask=Money.of("150.12", "JPY"),
        )
        second_tick = Tick(
            instrument=instrument,
            timestamp=datetime(2026, 1, 1, 18, tzinfo=UTC),
            bid=Money.of("150.20", "JPY"),
            ask=Money.of("150.22", "JPY"),
        )
        first_tick_processed = ThreadEvent()
        release_second_tick = ThreadEvent()
        strategy = HoldStrategy(name="hold")

        with TaskManager(max_workers=2) as manager:
            run = manager.start_backtest(
                definition,
                data_source=TwoTickBlockingDataSource(
                    first_tick=first_tick,
                    second_tick=second_tick,
                    first_tick_processed=first_tick_processed,
                    release_second_tick=release_second_tick,
                ),
                strategy=strategy,
            )
            assert first_tick_processed.wait(timeout=2)
            with pytest.raises(StrategyAlreadyRunningError):
                manager.start_backtest(
                    second_definition,
                    data_source=OneTickDataSource(first_tick),
                    strategy=strategy,
                )
            release_second_tick.set()
            assert run.wait(timeout=2).status == TaskStatus.COMPLETED

    def test_task_manager_preserves_failure_exception_details(self) -> None:
        instrument = CurrencyPair.of("USD_JPY")
        definition = BacktestTaskDefinition(
            name="Backtest USD_JPY",
            instrument=instrument,
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )

        with TaskManager(max_workers=1) as manager:
            run = manager.start_backtest(
                definition,
                data_source=FailingDataSource(),
                strategy=HoldStrategy(name="hold"),
            )
            final_task = run.wait(timeout=2)

        assert final_task.status == TaskStatus.FAILED
        assert final_task.failure is not None
        assert final_task.failure.message == "source failed"
        assert final_task.failure.cause_type == "RuntimeError"
        assert "_raw_ticks" in final_task.failure.traceback
        assert "RuntimeError: source failed" in final_task.failure.traceback

    def test_task_manager_marks_task_failed_when_finish_observer_fails(self) -> None:
        instrument = CurrencyPair.of("USD_JPY")
        definition = BacktestTaskDefinition(
            name="Backtest USD_JPY",
            instrument=instrument,
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        tick = Tick(
            instrument=instrument,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            bid=Money.of("150.10", "JPY"),
            ask=Money.of("150.12", "JPY"),
        )

        with TaskManager(max_workers=1, observers=(FailingFinishedObserver(),)) as manager:
            run = manager.start_backtest(
                definition,
                data_source=OneTickDataSource(tick),
                strategy=HoldStrategy(name="hold"),
            )
            final_task = run.wait(timeout=2)

        assert final_task.status == TaskStatus.FAILED
        assert final_task.failure is not None
        assert final_task.failure.message == "result store failed"

    def test_task_run_progress_reports_backtest_clock_position(self) -> None:
        instrument = CurrencyPair.of("USD_JPY")
        definition = BacktestTaskDefinition(
            name="Backtest USD_JPY",
            instrument=instrument,
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        first_tick = Tick(
            instrument=instrument,
            timestamp=datetime(2026, 1, 1, 12, tzinfo=UTC),
            bid=Money.of("150.10", "JPY"),
            ask=Money.of("150.12", "JPY"),
            metadata=Metadata.of(source="test"),
        )
        second_tick = Tick(
            instrument=instrument,
            timestamp=datetime(2026, 1, 1, 18, tzinfo=UTC),
            bid=Money.of("150.20", "JPY"),
            ask=Money.of("150.22", "JPY"),
            metadata=Metadata.of(source="test"),
        )
        first_tick_processed = ThreadEvent()
        release_second_tick = ThreadEvent()

        with TaskManager(max_workers=1) as manager:
            run = manager.start_backtest(
                definition,
                data_source=TwoTickBlockingDataSource(
                    first_tick=first_tick,
                    second_tick=second_tick,
                    first_tick_processed=first_tick_processed,
                    release_second_tick=release_second_tick,
                ),
                strategy=HoldStrategy(name="hold"),
            )
            assert first_tick_processed.wait(timeout=2)

            progress = run.progress()
            assert progress.task_id == run.id
            assert progress.status == TaskStatus.RUNNING
            assert progress.current_at == first_tick.timestamp
            assert progress.completed_units == 43200
            assert progress.total_units == 86400
            assert progress.fraction == 0.5
            assert progress.percent == 50
            assert progress.unit == "s"

            release_second_tick.set()
            final_task = run.wait(timeout=2)
            final_progress = run.progress()

        assert final_task.status == TaskStatus.COMPLETED
        assert final_progress.status == TaskStatus.COMPLETED
        assert final_progress.current_at == definition.end_at
        assert final_progress.completed_units == final_progress.total_units
        assert final_progress.fraction == 1

    def test_task_run_wait_can_report_progress(self) -> None:
        instrument = CurrencyPair.of("USD_JPY")
        definition = BacktestTaskDefinition(
            name="Backtest USD_JPY",
            instrument=instrument,
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        first_tick = Tick(
            instrument=instrument,
            timestamp=datetime(2026, 1, 1, 12, tzinfo=UTC),
            bid=Money.of("150.10", "JPY"),
            ask=Money.of("150.12", "JPY"),
            metadata=Metadata.of(source="test"),
        )
        second_tick = Tick(
            instrument=instrument,
            timestamp=datetime(2026, 1, 1, 18, tzinfo=UTC),
            bid=Money.of("150.20", "JPY"),
            ask=Money.of("150.22", "JPY"),
            metadata=Metadata.of(source="test"),
        )
        first_tick_processed = ThreadEvent()
        release_second_tick = ThreadEvent()
        reporter = RecordingProgressReporter()

        with TaskManager(max_workers=1) as manager:
            run = manager.start_backtest(
                definition,
                data_source=TwoTickBlockingDataSource(
                    first_tick=first_tick,
                    second_tick=second_tick,
                    first_tick_processed=first_tick_processed,
                    release_second_tick=release_second_tick,
                ),
                strategy=HoldStrategy(name="hold"),
            )
            release_timer = Timer(0.05, release_second_tick.set)
            release_timer.start()
            try:
                final_task = run.wait(timeout=2, progress=reporter, refresh_seconds=0.01)
            finally:
                release_timer.cancel()

        assert final_task.status == TaskStatus.COMPLETED
        assert len(reporter.starts) == 1
        assert reporter.starts[0].task_id == run.id
        assert reporter.updates
        assert reporter.finishes[-1].status == TaskStatus.COMPLETED
        assert reporter.finishes[-1].completed_units == reporter.finishes[-1].total_units
        assert reporter.close_count == 0

    def test_task_run_wait_closes_progress_reporter_on_timeout(self) -> None:
        instrument = CurrencyPair.of("USD_JPY")
        definition = BacktestTaskDefinition(
            name="Backtest USD_JPY",
            instrument=instrument,
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        first_tick = Tick(
            instrument=instrument,
            timestamp=datetime(2026, 1, 1, 12, tzinfo=UTC),
            bid=Money.of("150.10", "JPY"),
            ask=Money.of("150.12", "JPY"),
            metadata=Metadata.of(source="test"),
        )
        second_tick = Tick(
            instrument=instrument,
            timestamp=datetime(2026, 1, 1, 18, tzinfo=UTC),
            bid=Money.of("150.20", "JPY"),
            ask=Money.of("150.22", "JPY"),
            metadata=Metadata.of(source="test"),
        )
        first_tick_processed = ThreadEvent()
        release_second_tick = ThreadEvent()
        reporter = RecordingProgressReporter()

        with TaskManager(max_workers=1) as manager:
            run = manager.start_backtest(
                definition,
                data_source=TwoTickBlockingDataSource(
                    first_tick=first_tick,
                    second_tick=second_tick,
                    first_tick_processed=first_tick_processed,
                    release_second_tick=release_second_tick,
                ),
                strategy=HoldStrategy(name="hold"),
            )
            assert first_tick_processed.wait(timeout=2)

            with pytest.raises(FutureTimeoutError):
                run.wait(timeout=0.01, progress=reporter, refresh_seconds=0.01)

            release_second_tick.set()
            final_task = run.wait(timeout=2)

        assert final_task.status == TaskStatus.COMPLETED
        assert reporter.close_count == 1
        assert not reporter.finishes

    def test_task_run_profile_can_write_cprofile_output(self, tmp_path: Path) -> None:
        instrument = CurrencyPair.of("USD_JPY")
        definition = BacktestTaskDefinition(
            name="Backtest USD_JPY",
            instrument=instrument,
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        tick = Tick(
            instrument=instrument,
            timestamp=datetime(2026, 1, 1, 12, tzinfo=UTC),
            bid=Money.of("150.10", "JPY"),
            ask=Money.of("150.12", "JPY"),
            metadata=Metadata.of(source="test"),
        )

        with TaskManager(
            max_workers=1,
            profiling=TaskProfilingConfig(
                cprofile=True,
                cprofile_output_path=tmp_path,
            ),
        ) as manager:
            run = manager.start_backtest(
                definition,
                data_source=OneTickDataSource(tick),
                strategy=HoldStrategy(name="hold"),
            )
            final_task = run.wait(timeout=2)
            profile = run.profile()

        assert final_task.status == TaskStatus.COMPLETED
        cprofile_output_path = profile.cprofile_output_path
        assert cprofile_output_path is not None
        assert cprofile_output_path == tmp_path / f"{run.id}.prof"
        assert cprofile_output_path.exists()
        assert cprofile_output_path.stat().st_size > 0

    def test_task_run_profile_can_write_pyinstrument_output(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake_module: Any = ModuleType("pyinstrument")
        fake_module.Profiler = FakePyinstrumentProfiler
        monkeypatch.setitem(sys.modules, "pyinstrument", fake_module)
        instrument = CurrencyPair.of("USD_JPY")
        definition = BacktestTaskDefinition(
            name="Backtest USD_JPY",
            instrument=instrument,
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        tick = Tick(
            instrument=instrument,
            timestamp=datetime(2026, 1, 1, 12, tzinfo=UTC),
            bid=Money.of("150.10", "JPY"),
            ask=Money.of("150.12", "JPY"),
            metadata=Metadata.of(source="test"),
        )

        with TaskManager(
            max_workers=1,
            profiling=TaskProfilingConfig(
                pyinstrument=True,
                pyinstrument_output_path=tmp_path,
                pyinstrument_resample_interval=timedelta(milliseconds=250),
            ),
        ) as manager:
            run = manager.start_backtest(
                definition,
                data_source=OneTickDataSource(tick),
                strategy=HoldStrategy(name="hold"),
            )
            final_task = run.wait(timeout=2)
            profile = run.profile()

        assert final_task.status == TaskStatus.COMPLETED
        pyinstrument_output_path = profile.pyinstrument_output_path
        assert pyinstrument_output_path is not None
        assert pyinstrument_output_path == tmp_path / f"{run.id}.html"
        assert pyinstrument_output_path.read_text(encoding="utf-8") == (
            "<html><body>profile 0.25</body></html>"
        )

    def test_task_profiling_config_scales_pyinstrument_samples_for_backtest_period(
        self,
        tmp_path: Path,
    ) -> None:
        short = TaskProfilingConfig.for_backtest_period(
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 3, tzinfo=UTC),
            pyinstrument=True,
            pyinstrument_output_path=tmp_path,
        )
        month = TaskProfilingConfig.for_backtest_period(
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 31, tzinfo=UTC),
            pyinstrument=True,
            pyinstrument_output_path=tmp_path,
        )
        long = TaskProfilingConfig.for_backtest_period(
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 3, 31, tzinfo=UTC),
            pyinstrument=True,
            pyinstrument_output_path=tmp_path,
        )

        assert short.pyinstrument_target_html_samples == 20_000
        assert month.pyinstrument_target_html_samples == 10_000
        assert long.pyinstrument_target_html_samples == 5_000
