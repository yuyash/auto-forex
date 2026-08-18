from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from threading import Event
from time import sleep

from autoforex.core import (
    BacktestTaskDefinition,
    CurrencyPair,
    DataSource,
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
from autoforex.server.persistence import SqlPersistence
from autoforex.server.supervisor import TaskSupervisor


class DistributedHoldStrategy(Strategy):
    def on_tick(self, tick: Tick, context: StrategyContext) -> StrategyResult:
        _ = tick
        _ = context
        return StrategyResult()


class SlowReplaySource(DataSource):
    def __init__(self, ticks: tuple[Tick, ...], *, delay_seconds: float = 0.005) -> None:
        self._ticks = ticks
        self._delay_seconds = delay_seconds

    def _raw_ticks(
        self,
        *,
        instrument: CurrencyPair,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Tick]:
        _ = start_at
        _ = end_at
        for tick in self._ticks:
            if tick.instrument == instrument:
                sleep(self._delay_seconds)
                yield tick


class InterruptedSource(DataSource):
    def __init__(self, first_tick: Tick) -> None:
        self._first_tick = first_tick
        self._closed = Event()

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
        yield self._first_tick
        self._closed.wait(timeout=5)
        raise RuntimeError("simulated process interruption")

    def close(self) -> None:
        self._closed.set()


class TestDistributedTaskSupervision:
    def test_non_owner_stop_is_applied_by_the_lease_owner(
        self,
        sqlite_persistence: SqlPersistence,
        condition_waiter,
        supervisor_resources,
    ) -> None:
        instrument = CurrencyPair.of("EUR_USD")
        start = datetime(2026, 1, 1, tzinfo=UTC)
        ticks = tuple(
            self._tick(instrument, start + timedelta(seconds=index)) for index in range(200)
        )
        owner = supervisor_resources.track(
            self._supervisor(
                sqlite_persistence,
                server_id="server-a",
                source_factory=lambda: SlowReplaySource(ticks),
            )
        )
        standby = supervisor_resources.track(
            self._supervisor(
                sqlite_persistence,
                server_id="server-b",
                source_factory=lambda: SlowReplaySource(ticks),
            )
        )
        definition, binding = self._definition_and_binding(instrument, start)

        run = owner.start_backtest(definition, binding)
        condition_waiter.until(
            lambda: owner.get(run.id).last_processed_at is not None,
            description="the lease owner to persist execution progress",
        )
        standby_runtime = standby.manager.runtimes.current(run.id)
        assert standby_runtime is None, standby.intent_for(run.id)
        returned = standby.stop(run.id)
        condition_waiter.until(
            lambda: (
                owner.manager.runtimes.get(run.id).future.done()
                or owner.get(run.id).status
                in {TaskStatus.STOPPED, TaskStatus.COMPLETED, TaskStatus.FAILED}
            ),
            description="the lease owner to apply the remote stop intent",
        )

        assert returned.id == run.id
        stopped = owner.get(run.id)
        runtime_error = owner.manager.runtimes.get(run.id).future.exception()
        assert stopped.status == TaskStatus.STOPPED, (stopped.failure, runtime_error)

    def test_hot_standby_recovers_after_owner_shutdown_without_restart(
        self,
        sqlite_persistence: SqlPersistence,
        condition_waiter,
        supervisor_resources,
    ) -> None:
        instrument = CurrencyPair.of("USD_JPY")
        start = datetime(2026, 1, 1, tzinfo=UTC)
        ticks = (
            self._tick(instrument, start),
            self._tick(instrument, start + timedelta(hours=1)),
        )
        owner = supervisor_resources.track(
            self._supervisor(
                sqlite_persistence,
                server_id="server-a",
                source_factory=lambda: InterruptedSource(ticks[0]),
            )
        )
        standby = supervisor_resources.track(
            self._supervisor(
                sqlite_persistence,
                server_id="server-b",
                source_factory=lambda: SlowReplaySource(ticks, delay_seconds=0),
            )
        )
        definition, binding = self._definition_and_binding(instrument, start)

        run = owner.start_backtest(definition, binding)
        condition_waiter.until(
            lambda: owner.get(run.id).last_processed_at == ticks[0].timestamp,
            description="the original owner to persist its checkpoint",
        )
        owner.shutdown()
        condition_waiter.until(
            lambda: standby.get(run.id).status == TaskStatus.COMPLETED,
            description="the hot standby to acquire the lease and finish the task",
        )

        recovered = standby.get(run.id)
        assert recovered.id == run.id
        assert recovered.last_processed_at == ticks[1].timestamp

    @staticmethod
    def _supervisor(
        persistence: SqlPersistence,
        *,
        server_id: str,
        source_factory,
    ) -> TaskSupervisor:
        strategies = StrategyRegistry()
        strategies.register(
            ComponentName.of("hold"),
            lambda parameters: DistributedHoldStrategy(
                name="hold",
                parameters=parameters,
            ),
        )
        sources = DataSourceRegistry()
        sources.register(ComponentName.of("replay"), source_factory)
        return TaskSupervisor.create(
            registry=persistence.task_registry(),
            recovery_store=persistence.recovery_store(),
            execution_store=persistence.execution_store(),
            dependency_resolver=TaskDependencyResolver(
                strategies=strategies,
                data_sources=sources,
                providers=TradingProviderRegistry(),
            ),
            server_id=server_id,
            max_workers=1,
            heartbeat_interval_seconds=0.01,
            lease_duration_seconds=5,
            lease_renewal_seconds=0.05,
            reconciliation_interval_seconds=0.01,
        )

    @staticmethod
    def _definition_and_binding(
        instrument: CurrencyPair,
        start: datetime,
    ) -> tuple[BacktestTaskDefinition, BacktestTaskBinding]:
        definition = BacktestTaskDefinition(
            name="Distributed replay",
            instrument=instrument,
            start_at=start,
            end_at=start + timedelta(days=1),
        )
        binding = BacktestTaskBinding(
            strategy=StrategyReference(name=ComponentName.of("hold")),
            data_source=DataSourceReference(name=ComponentName.of("replay")),
        )
        return definition, binding

    @staticmethod
    def _tick(instrument: CurrencyPair, timestamp: datetime) -> Tick:
        return Tick(
            instrument=instrument,
            timestamp=timestamp,
            bid=Money.of("1.10", instrument.quote),
            ask=Money.of("1.11", instrument.quote),
        )
