from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import ClassVar

from autoforex.core import (
    BacktestTaskDefinition,
    CurrencyPair,
    DataSource,
    ExecutableTask,
    Money,
    Strategy,
    StrategyContext,
    StrategyResult,
    TaskStatus,
    Tick,
)

from autoforex.server.components import (
    BacktestTaskBinding,
    ComponentName,
    DataSourceReference,
    DataSourceRegistry,
    StrategyReference,
    StrategyRegistry,
    TaskDependencyResolver,
    TradingProviderRegistry,
)
from autoforex.server.lease import TaskLeaseCoordinator
from autoforex.server.persistence import SqlPersistence
from autoforex.server.recovery import TaskExecutionDisposition, TaskExecutionIntent
from autoforex.server.supervisor import TaskSupervisor


class RecordingStrategy(Strategy):
    processed: ClassVar[list[datetime]] = []

    def on_tick(self, tick: Tick, context: StrategyContext) -> StrategyResult:
        _ = context
        self.processed.append(tick.timestamp)
        return StrategyResult()


class ReplayDataSource(DataSource):
    def __init__(self, ticks: tuple[Tick, ...]) -> None:
        self._ticks = ticks

    def _raw_ticks(
        self,
        *,
        instrument: CurrencyPair,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Tick]:
        _ = start_at
        _ = end_at
        return (tick for tick in self._ticks if tick.instrument == instrument)


class TestTaskRecovery:
    def test_recovers_backtest_after_last_durable_checkpoint(
        self,
        sqlite_persistence: SqlPersistence,
        supervisor_resources,
    ) -> None:
        RecordingStrategy.processed = []
        instrument = CurrencyPair.of("USD_JPY")
        ticks = (
            self._tick(instrument, datetime(2026, 1, 1, 0, tzinfo=UTC)),
            self._tick(instrument, datetime(2026, 1, 1, 1, tzinfo=UTC)),
            self._tick(instrument, datetime(2026, 1, 1, 2, tzinfo=UTC)),
        )
        definition = BacktestTaskDefinition(
            name="Recover replay",
            instrument=instrument,
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        persisted = (
            ExecutableTask.from_definition(definition)
            .start(at=definition.start_at)
            .with_last_processed_at(ticks[0].timestamp)
        )
        registry = sqlite_persistence.task_registry()
        recovery = sqlite_persistence.recovery_store()
        registry.save(persisted)
        binding = BacktestTaskBinding(
            strategy=StrategyReference(name=ComponentName.of("recording")),
            data_source=DataSourceReference(name=ComponentName.of("replay")),
        )
        recovery.save_binding(definition.id, binding)
        recovery.save_intent(
            TaskExecutionIntent(
                task_id=persisted.id,
                definition_id=definition.id,
                disposition=TaskExecutionDisposition.RUNNING,
                owner_id="dead-server",
            )
        )
        strategies = StrategyRegistry()
        strategies.register(
            ComponentName.of("recording"),
            lambda parameters: RecordingStrategy(
                name="recording",
                parameters=parameters,
            ),
        )
        sources = DataSourceRegistry()
        sources.register(
            ComponentName.of("replay"),
            lambda: ReplayDataSource(ticks),
        )
        supervisor = supervisor_resources.track(
            TaskSupervisor.create(
                registry=registry,
                recovery_store=recovery,
                dependency_resolver=TaskDependencyResolver(
                    strategies=strategies,
                    data_sources=sources,
                    providers=TradingProviderRegistry(),
                ),
                max_workers=1,
                heartbeat_interval_seconds=0.001,
            )
        )

        report = supervisor.recover_active()
        report.require_complete()
        finished = supervisor.manager.wait(persisted.id, timeout=2)

        assert finished.status == TaskStatus.COMPLETED
        assert finished.id == persisted.id
        assert finished.run_count == persisted.run_count
        assert RecordingStrategy.processed == [ticks[1].timestamp, ticks[2].timestamp]

    def test_releases_lease_when_recovery_dependencies_cannot_be_resolved(
        self,
        sqlite_persistence: SqlPersistence,
        supervisor_resources,
    ) -> None:
        definition = BacktestTaskDefinition(
            name="Missing components",
            instrument=CurrencyPair.of("USD_JPY"),
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        task = ExecutableTask.from_definition(definition).start(at=definition.start_at)
        registry = sqlite_persistence.task_registry()
        recovery = sqlite_persistence.recovery_store()
        registry.save(task)
        recovery.save_binding(
            definition.id,
            BacktestTaskBinding(
                strategy=StrategyReference(name=ComponentName.of("missing")),
                data_source=DataSourceReference(name=ComponentName.of("missing")),
            ),
        )
        recovery.save_intent(
            TaskExecutionIntent(
                task_id=task.id,
                definition_id=definition.id,
                disposition=TaskExecutionDisposition.RUNNING,
                owner_id="dead-server",
            )
        )
        supervisor = supervisor_resources.track(
            TaskSupervisor.create(
                registry=registry,
                recovery_store=recovery,
                dependency_resolver=TaskDependencyResolver(
                    strategies=StrategyRegistry(),
                    data_sources=DataSourceRegistry(),
                    providers=TradingProviderRegistry(),
                ),
                server_id="server-a",
                max_workers=1,
                lease_duration_seconds=30,
                lease_renewal_seconds=10,
            )
        )

        report = supervisor.recover_active()

        assert len(report.failures) == 1
        contender = TaskLeaseCoordinator(
            recovery,
            owner_id="server-b",
            duration_seconds=30,
        )
        assert contender.acquire(task.id) is not None

    def test_manual_recovery_continues_the_same_run_and_clears_required_state(
        self,
        sqlite_persistence: SqlPersistence,
        supervisor_resources,
        condition_waiter,
    ) -> None:
        RecordingStrategy.processed = []
        instrument = CurrencyPair.of("USD_JPY")
        ticks = (
            self._tick(instrument, datetime(2026, 1, 1, 0, tzinfo=UTC)),
            self._tick(instrument, datetime(2026, 1, 1, 1, tzinfo=UTC)),
        )
        definition = BacktestTaskDefinition(
            name="Manual recovery",
            instrument=instrument,
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        task = (
            ExecutableTask.from_definition(definition)
            .start(at=definition.start_at)
            .with_last_processed_at(ticks[0].timestamp)
            .fail("provider result requires review")
        )
        registry = sqlite_persistence.task_registry()
        recovery = sqlite_persistence.recovery_store()
        registry.save(task)
        recovery.save_binding(
            definition.id,
            BacktestTaskBinding(
                strategy=StrategyReference(name=ComponentName.of("recording")),
                data_source=DataSourceReference(name=ComponentName.of("replay")),
            ),
        )
        recovery.save_intent(
            TaskExecutionIntent(
                task_id=task.id,
                definition_id=definition.id,
                disposition=TaskExecutionDisposition.RECOVERY_REQUIRED,
                owner_id="server-a",
            )
        )
        strategies = StrategyRegistry()
        strategies.register(
            ComponentName.of("recording"),
            lambda parameters: RecordingStrategy(
                name="recording",
                parameters=parameters,
            ),
        )
        sources = DataSourceRegistry()
        sources.register(ComponentName.of("replay"), lambda: ReplayDataSource(ticks))
        supervisor = supervisor_resources.track(
            TaskSupervisor.create(
                registry=registry,
                recovery_store=recovery,
                dependency_resolver=TaskDependencyResolver(
                    strategies=strategies,
                    data_sources=sources,
                    providers=TradingProviderRegistry(),
                ),
                server_id="server-a",
                max_workers=1,
                reconciliation_interval_seconds=0.01,
            )
        )

        run = supervisor.recover(task.id)
        finished = run.wait(timeout=2)

        assert finished.status == TaskStatus.COMPLETED
        assert finished.id == task.id
        assert finished.run_count == task.run_count
        assert RecordingStrategy.processed == [ticks[1].timestamp]
        condition_waiter.until(
            lambda: (
                supervisor.intent_for(task.id).disposition == TaskExecutionDisposition.COMPLETED
            ),
            description="manual recovery intent to become completed",
        )
        assert supervisor.intent_for(task.id).disposition == TaskExecutionDisposition.COMPLETED

    @staticmethod
    def _tick(instrument: CurrencyPair, timestamp: datetime) -> Tick:
        return Tick(
            instrument=instrument,
            timestamp=timestamp,
            bid=Money.of("150.10", "JPY"),
            ask=Money.of("150.12", "JPY"),
        )
