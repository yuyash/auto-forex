from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from uuid import UUID

import grpc
from autoforex.core import (
    BacktestTaskDefinition,
    CurrencyPair,
    DataSource,
    ExecutableTask,
    Strategy,
    StrategyContext,
    StrategyResult,
    Tick,
)
from autoforex.protobuf.task.v1 import task_service_pb2 as task_pb
from autoforex.protobuf.task.v1 import task_service_pb2_grpc as task_grpc
from google.protobuf.timestamp_pb2 import Timestamp  # ty: ignore[unresolved-import]

from autoforex.server.components import (
    BacktestTaskBinding,
    ComponentName,
    DataSourceReference,
    DataSourceRegistry,
    StrategyReference,
    StrategyRegistry,
    TradingProviderRegistry,
)
from autoforex.server.composition import ServerApplication, ServerComponentCatalog
from autoforex.server.process import ServerProcess
from autoforex.server.recovery import TaskExecutionDisposition, TaskExecutionIntent
from autoforex.server.settings import ServerSettings


class LifecycleHoldStrategy(Strategy):
    def on_tick(self, tick: Tick, context: StrategyContext) -> StrategyResult:
        _ = tick
        _ = context
        return StrategyResult()


class LifecycleInterruptibleSource(DataSource):
    def __init__(
        self,
        ticks: tuple[Tick, Tick],
        *,
        release_after_pause: Event,
    ) -> None:
        self._ticks = ticks
        self.release_after_pause = release_after_pause

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
        yield self._ticks[0]
        self.release_after_pause.wait(timeout=5)
        yield self._ticks[1]

    def close(self) -> None:
        self.release_after_pause.set()


class LifecycleReplaySource(DataSource):
    def __init__(self, ticks: tuple[Tick, Tick]) -> None:
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


class TestTaskLifecycleE2E:
    def test_manages_a_backtest_through_its_complete_grpc_lifecycle(
        self,
        tmp_path: Path,
        market_ticks: tuple[Tick, Tick],
        condition_waiter,
        scenario_resources,
    ) -> None:
        source_creations = 0
        release_after_pause = Event()

        def source_factory() -> DataSource:
            nonlocal source_creations
            source_creations += 1
            if source_creations == 1:
                return LifecycleInterruptibleSource(
                    market_ticks,
                    release_after_pause=release_after_pause,
                )
            return LifecycleReplaySource(market_ticks)

        process = scenario_resources.track_process(
            self._process(
                database_url=f"sqlite:///{tmp_path / 'lifecycle.db'}",
                source_factory=source_factory,
            )
        )
        process.start()
        channel = scenario_resources.track_channel(
            grpc.insecure_channel(process.grpc_server.address)
        )
        client = task_grpc.TaskServiceStub(channel)

        assert client.GetHealth(task_pb.GetHealthRequest()).status == "serving"
        discovered = client.ListServerInstances(task_pb.ListServerInstancesRequest())
        assert len(discovered.instances) == 1
        assert discovered.instances[0].instance_id == process.application.supervisor.server_id
        assert discovered.instances[0].port == process.grpc_server.port
        started = client.StartBacktest(
            task_pb.StartBacktestRequest(
                request_id="98d08717-bcc5-4225-ab58-207d8306804c",
                name="Lifecycle scenario",
                instrument=task_pb.CurrencyPair(base="USD", quote="JPY"),
                strategy=task_pb.StrategyReference(name="hold"),
                start_at=self._timestamp(datetime(2026, 1, 1, tzinfo=UTC)),
                end_at=self._timestamp(datetime(2026, 1, 2, tzinfo=UTC)),
                data_source=task_pb.DataSourceReference(name="replay"),
            )
        ).task
        task_id = UUID(started.id)

        def first_checkpoint_persisted() -> bool:
            task = process.application.supervisor.get(task_id)
            if task.failure is not None:
                raise AssertionError(f"task failed before pause: {task.failure.model_dump_json()}")
            return task.last_processed_at == market_ticks[0].timestamp

        condition_waiter.until(
            first_checkpoint_persisted,
            description="the first run to persist a checkpoint before pause",
        )

        paused = client.PauseTask(task_pb.PauseTaskRequest(task_id=str(task_id))).task

        assert paused.status == task_pb.TASK_STATUS_PAUSED
        assert paused.execution_disposition == task_pb.TASK_EXECUTION_DISPOSITION_PAUSED

        release_after_pause.set()
        client.ResumeTask(task_pb.ResumeTaskRequest(task_id=str(task_id)))
        completed = self._wait_for_status(
            client,
            task_id,
            task_pb.TASK_STATUS_COMPLETED,
            condition_waiter,
        )

        assert completed.run_count == 1
        assert completed.last_processed_at.ToDatetime(tzinfo=UTC) == market_ticks[1].timestamp

        client.RestartTask(task_pb.RestartTaskRequest(task_id=str(task_id)))
        restarted = self._wait_for_status(
            client,
            task_id,
            task_pb.TASK_STATUS_COMPLETED,
            condition_waiter,
            run_count=2,
        )
        listed = client.ListTasks(
            task_pb.ListTasksRequest(
                filter_by_status=True,
                status=task_pb.TASK_STATUS_COMPLETED,
            )
        ).tasks

        assert restarted.id == started.id
        assert restarted.run_count == 2
        assert [task.id for task in listed] == [started.id]
        assert source_creations == 3

    def test_recovers_a_review_required_task_through_grpc_without_a_new_run(
        self,
        tmp_path: Path,
        market_ticks: tuple[Tick, Tick],
        condition_waiter,
        scenario_resources,
    ) -> None:
        process = scenario_resources.track_process(
            self._process(
                database_url=f"sqlite:///{tmp_path / 'manual-recovery.db'}",
                source_factory=lambda: LifecycleReplaySource(market_ticks),
            )
        )
        definition = BacktestTaskDefinition(
            name="Manual recovery scenario",
            instrument=market_ticks[0].instrument,
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        task = (
            ExecutableTask.from_definition(definition)
            .start(at=definition.start_at)
            .with_last_processed_at(market_ticks[0].timestamp)
            .fail("provider outcome requires review")
        )
        binding = BacktestTaskBinding(
            strategy=StrategyReference(name=ComponentName.of("hold")),
            data_source=DataSourceReference(name=ComponentName.of("replay")),
        )
        process.application.persistence.task_registry().save(task)
        process.application.persistence.recovery_store().save_binding(
            definition.id,
            binding,
        )
        process.application.persistence.recovery_store().save_intent(
            TaskExecutionIntent(
                task_id=task.id,
                definition_id=definition.id,
                disposition=TaskExecutionDisposition.RECOVERY_REQUIRED,
                owner_id="previous-server",
            )
        )
        process.start()
        channel = scenario_resources.track_channel(
            grpc.insecure_channel(process.grpc_server.address)
        )
        client = task_grpc.TaskServiceStub(channel)

        before = client.GetTask(task_pb.GetTaskRequest(task_id=str(task.id))).task
        client.RecoverTask(task_pb.RecoverTaskRequest(task_id=str(task.id)))
        recovered = self._wait_for_status(
            client,
            task.id,
            task_pb.TASK_STATUS_COMPLETED,
            condition_waiter,
        )

        assert before.execution_disposition == task_pb.TASK_EXECUTION_DISPOSITION_RECOVERY_REQUIRED
        assert recovered.id == str(task.id)
        assert recovered.run_count == task.run_count
        assert recovered.last_processed_at.ToDatetime(tzinfo=UTC) == market_ticks[1].timestamp

    @staticmethod
    def _process(*, database_url: str, source_factory) -> ServerProcess:
        strategies = StrategyRegistry()
        strategies.register(
            ComponentName.of("hold"),
            lambda parameters: LifecycleHoldStrategy(
                name="hold",
                parameters=parameters,
            ),
        )
        sources = DataSourceRegistry()
        sources.register(ComponentName.of("replay"), source_factory)
        application = ServerApplication.build(
            ServerSettings(
                port=0,
                database_url=database_url,
                task_workers=1,
                grpc_workers=2,
                heartbeat_interval_seconds=0.001,
                lease_renewal_seconds=0.1,
                lease_duration_seconds=1,
                service_discovery_enabled=True,
                service_discovery_heartbeat_interval_seconds=0.1,
                service_discovery_ttl_seconds=1,
            ),
            catalog=ServerComponentCatalog(
                strategies=strategies,
                data_sources=sources,
                providers=TradingProviderRegistry(),
            ),
        )
        return ServerProcess.create(application)

    @staticmethod
    def _wait_for_status(
        client,
        task_id: UUID,
        expected_status: int,
        condition_waiter,
        *,
        run_count: int | None = None,
    ) -> task_pb.Task:
        observed: task_pb.Task | None = None

        def reached() -> bool:
            nonlocal observed
            observed = client.GetTask(task_pb.GetTaskRequest(task_id=str(task_id))).task
            return observed.status == expected_status and (
                run_count is None or observed.run_count == run_count
            )

        condition_waiter.until(
            reached,
            description=(
                f"task {task_id} to reach status {expected_status}"
                + ("" if run_count is None else f" on run {run_count}")
            ),
        )
        assert observed is not None
        return observed

    @staticmethod
    def _timestamp(value: datetime) -> Timestamp:
        timestamp = Timestamp()
        timestamp.FromDatetime(value)
        return timestamp
