from __future__ import annotations

import os
from collections.abc import Iterable
from datetime import UTC, datetime
from threading import Event
from uuid import UUID, uuid4

import grpc
import pytest
from autoforex.core import (
    CurrencyPair,
    DataSource,
    Strategy,
    StrategyContext,
    StrategyResult,
    Tick,
)
from autoforex.protobuf.task.v1 import task_service_pb2 as task_pb
from autoforex.protobuf.task.v1 import task_service_pb2_grpc as task_grpc
from google.protobuf.timestamp_pb2 import Timestamp  # ty: ignore[unresolved-import]

from autoforex.server.components import (
    ComponentName,
    DataSourceRegistry,
    StrategyRegistry,
    TradingProviderRegistry,
)
from autoforex.server.composition import ServerApplication, ServerComponentCatalog
from autoforex.server.process import ServerProcess
from autoforex.server.settings import PersistenceBackend, ServerSettings


class BackendHoldStrategy(Strategy):
    def on_tick(self, tick: Tick, context: StrategyContext) -> StrategyResult:
        _ = tick
        _ = context
        return StrategyResult()


class BackendInterruptibleSource(DataSource):
    def __init__(self, ticks: tuple[Tick, ...]) -> None:
        self._ticks = ticks
        self.closed = Event()

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
        self.closed.wait(timeout=5)
        if self.closed.is_set():
            raise RuntimeError("server stopped")

    def close(self) -> None:
        self.closed.set()


class BackendReplaySource(DataSource):
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


class TestPersistentBackendRestartE2E:
    def test_recovers_through_postgresql(
        self,
        market_ticks: tuple[Tick, Tick],
        condition_waiter,
        scenario_resources,
    ) -> None:
        database_url = os.getenv("AUTO_FOREX_TEST_POSTGRESQL_URL")
        if not database_url:
            pytest.skip("AUTO_FOREX_TEST_POSTGRESQL_URL is not configured")
        self._exercise(
            ServerSettings(
                port=0,
                persistence_backend=PersistenceBackend.POSTGRESQL,
                database_url=database_url,
                heartbeat_interval_seconds=0.01,
                lease_renewal_seconds=0.1,
                lease_duration_seconds=1,
            ),
            ticks=market_ticks,
            condition_waiter=condition_waiter,
            scenario_resources=scenario_resources,
        )

    def test_recovers_through_dynamodb_local(
        self,
        market_ticks: tuple[Tick, Tick],
        condition_waiter,
        scenario_resources,
    ) -> None:
        endpoint_url = os.getenv("AUTO_FOREX_TEST_DYNAMODB_ENDPOINT_URL")
        if not endpoint_url:
            pytest.skip("AUTO_FOREX_TEST_DYNAMODB_ENDPOINT_URL is not configured")
        table_name = f"auto-forex-server-e2e-{uuid4()}"
        settings = ServerSettings(
            port=0,
            persistence_backend=PersistenceBackend.DYNAMODB,
            dynamodb_table_name=table_name,
            dynamodb_region_name="us-west-2",
            dynamodb_endpoint_url=endpoint_url,
            dynamodb_enable_point_in_time_recovery=False,
            heartbeat_interval_seconds=0.01,
            lease_renewal_seconds=0.1,
            lease_duration_seconds=1,
        )
        try:
            self._exercise(
                settings,
                ticks=market_ticks,
                condition_waiter=condition_waiter,
                scenario_resources=scenario_resources,
            )
        finally:
            boto3 = pytest.importorskip("boto3")
            boto3.client(
                "dynamodb",
                region_name="us-west-2",
                endpoint_url=endpoint_url,
            ).delete_table(TableName=table_name)

    def _exercise(
        self,
        settings: ServerSettings,
        *,
        ticks: tuple[Tick, Tick],
        condition_waiter,
        scenario_resources,
    ) -> None:
        first = scenario_resources.track_process(
            self._process(
                settings,
                source_factory=lambda: BackendInterruptibleSource(ticks),
            )
        )
        first.start()
        first_channel = scenario_resources.track_channel(
            grpc.insecure_channel(first.grpc_server.address)
        )
        first_client = task_grpc.TaskServiceStub(first_channel)
        started = first_client.StartBacktest(
            task_pb.StartBacktestRequest(
                request_id=str(uuid4()),
                name="Backend restart",
                instrument=task_pb.CurrencyPair(base="USD", quote="JPY"),
                strategy=task_pb.StrategyReference(name="hold"),
                start_at=self._timestamp(datetime(2026, 1, 1, tzinfo=UTC)),
                end_at=self._timestamp(datetime(2026, 1, 2, tzinfo=UTC)),
                data_source=task_pb.DataSourceReference(name="replay"),
            )
        ).task
        task_id = UUID(started.id)
        condition_waiter.until(
            lambda: (
                first.application.supervisor.get(task_id).last_processed_at == ticks[0].timestamp
            ),
            description="the first process to persist its checkpoint",
        )
        first.stop()

        second = scenario_resources.track_process(
            self._process(
                settings,
                source_factory=lambda: BackendReplaySource(ticks),
            )
        )
        second.start()
        second_channel = scenario_resources.track_channel(
            grpc.insecure_channel(second.grpc_server.address)
        )
        second_client = task_grpc.TaskServiceStub(second_channel)
        completed: task_pb.Task | None = None

        def is_complete() -> bool:
            nonlocal completed
            completed = second_client.GetTask(task_pb.GetTaskRequest(task_id=str(task_id))).task
            return completed.status == task_pb.TASK_STATUS_COMPLETED

        condition_waiter.until(
            is_complete,
            timeout=10,
            description="the replacement process to complete the recovered task",
        )
        assert completed is not None
        assert completed.id == str(task_id)
        assert completed.last_processed_at.ToDatetime(tzinfo=UTC) == ticks[1].timestamp

    @staticmethod
    def _process(settings: ServerSettings, *, source_factory) -> ServerProcess:
        strategies = StrategyRegistry()
        strategies.register(
            ComponentName.of("hold"),
            lambda parameters: BackendHoldStrategy(name="hold", parameters=parameters),
        )
        sources = DataSourceRegistry()
        sources.register(ComponentName.of("replay"), source_factory)
        application = ServerApplication.build(
            settings,
            catalog=ServerComponentCatalog(
                strategies=strategies,
                data_sources=sources,
                providers=TradingProviderRegistry(),
            ),
        )
        return ServerProcess.create(application)

    @staticmethod
    def _timestamp(value: datetime) -> Timestamp:
        timestamp = Timestamp()
        timestamp.FromDatetime(value)
        return timestamp
