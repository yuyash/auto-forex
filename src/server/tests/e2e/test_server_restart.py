from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import cast
from uuid import UUID

import grpc
import pytest
from autoforex.core import (
    AccountManager,
    AccountProvider,
    Broker,
    CurrencyPair,
    DataSource,
    Strategy,
    StrategyContext,
    StrategyResult,
    StrategyState,
    Tick,
    TradingProvider,
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
from autoforex.server.settings import ServerSettings


class HoldStrategy(Strategy):
    def on_tick(self, tick: Tick, context: StrategyContext) -> StrategyResult:
        _ = tick
        _ = context
        return StrategyResult()


class CountingStrategy(Strategy):
    def on_start(self, context: StrategyContext) -> StrategyResult:
        _ = context
        return StrategyResult(state=StrategyState.of(processed_ticks=0))

    def on_tick(self, tick: Tick, context: StrategyContext) -> StrategyResult:
        _ = tick
        count = int(context.state.get("processed_ticks", 0))
        return StrategyResult(
            state=StrategyState.of(processed_ticks=count + 1),
        )


class InterruptibleDataSource(DataSource):
    def __init__(self, ticks: tuple[Tick, ...], *, ticks_before_block: int = 1) -> None:
        self._ticks = ticks
        self._ticks_before_block = ticks_before_block
        self._closed = Event()

    def _raw_ticks(
        self,
        *,
        instrument: CurrencyPair,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Tick]:
        _ = start_at
        _ = end_at
        yield from self._ticks[: self._ticks_before_block]
        self._closed.wait(timeout=5)
        if self._closed.is_set():
            raise RuntimeError("server process stopped")

    def close(self) -> None:
        self._closed.set()


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


class TestServerRestartE2E:
    def test_start_request_is_idempotent_and_rejects_request_id_reuse(
        self,
        tmp_path: Path,
        market_ticks: tuple[Tick, Tick],
        scenario_resources,
    ) -> None:
        ticks = market_ticks[:1]
        process = scenario_resources.track_process(
            self._process(
                f"sqlite:///{tmp_path / 'idempotency.db'}",
                source_factory=lambda: ReplayDataSource(ticks),
            )
        )
        process.start()
        channel = scenario_resources.track_channel(
            grpc.insecure_channel(process.grpc_server.address)
        )
        client = task_grpc.TaskServiceStub(channel)
        request = task_pb.StartBacktestRequest(
            request_id="6a08ac28-7ac1-4161-a887-f0363f0e363c",
            name="Idempotent start",
            instrument=task_pb.CurrencyPair(base="USD", quote="JPY"),
            strategy=task_pb.StrategyReference(name="hold"),
            start_at=self._timestamp(datetime(2026, 1, 1, tzinfo=UTC)),
            end_at=self._timestamp(datetime(2026, 1, 2, tzinfo=UTC)),
            data_source=task_pb.DataSourceReference(name="replay"),
        )

        first = client.StartBacktest(request).task
        second = client.StartBacktest(request).task

        assert second.id == first.id
        assert len(client.ListTasks(task_pb.ListTasksRequest()).tasks) == 1
        conflicting = task_pb.StartBacktestRequest()
        conflicting.CopyFrom(request)
        conflicting.name = "Different payload"
        with pytest.raises(grpc.RpcError) as raised:
            client.StartBacktest(conflicting)
        assert isinstance(raised.value, grpc.Call)
        assert raised.value.code() == grpc.StatusCode.ALREADY_EXISTS

    def test_recovers_running_task_through_real_grpc_after_process_restart(
        self,
        tmp_path: Path,
        market_ticks: tuple[Tick, Tick],
        condition_waiter,
        scenario_resources,
    ) -> None:
        ticks = market_ticks
        database_url = f"sqlite:///{tmp_path / 'server.db'}"
        first = scenario_resources.track_process(
            self._process(
                database_url,
                source_factory=lambda: InterruptibleDataSource(ticks),
            )
        )
        first.start()
        channel = scenario_resources.track_channel(grpc.insecure_channel(first.grpc_server.address))
        client = task_grpc.TaskServiceStub(channel)

        started = client.StartBacktest(
            task_pb.StartBacktestRequest(
                request_id="4a59ab22-46b7-42a1-96f8-f73a1c23d9b1",
                name="Restart recovery",
                instrument=task_pb.CurrencyPair(base="USD", quote="JPY"),
                strategy=task_pb.StrategyReference(name="hold"),
                start_at=self._timestamp(datetime(2026, 1, 1, tzinfo=UTC)),
                end_at=self._timestamp(datetime(2026, 1, 2, tzinfo=UTC)),
                data_source=task_pb.DataSourceReference(name="replay"),
            )
        )
        task_id = started.task.id
        condition_waiter.until(
            lambda: (
                first.application.supervisor.get(UUID(task_id)).last_processed_at
                == ticks[0].timestamp
            ),
            description="the first process to persist its backtest checkpoint",
        )
        first.stop()

        second = scenario_resources.track_process(
            self._process(
                database_url,
                source_factory=lambda: ReplayDataSource(ticks),
            )
        )
        second.start()
        second_channel = scenario_resources.track_channel(
            grpc.insecure_channel(second.grpc_server.address)
        )
        second_client = task_grpc.TaskServiceStub(second_channel)
        completed = self._wait_for_task(
            second_client,
            task_id,
            expected_status=task_pb.TASK_STATUS_COMPLETED,
            condition_waiter=condition_waiter,
        )

        assert completed.id == task_id
        assert completed.last_processed_at.ToDatetime(tzinfo=UTC) == ticks[1].timestamp

    def test_recovers_trading_task_and_strategy_state_after_process_restart(
        self,
        tmp_path: Path,
        market_ticks: tuple[Tick, Tick],
        condition_waiter,
        scenario_resources,
    ) -> None:
        ticks = market_ticks
        database_url = f"sqlite:///{tmp_path / 'trading-server.db'}"
        first = scenario_resources.track_process(
            self._trading_process(
                database_url,
                source_factory=lambda: InterruptibleDataSource(ticks),
            )
        )
        first.start()
        channel = scenario_resources.track_channel(grpc.insecure_channel(first.grpc_server.address))
        client = task_grpc.TaskServiceStub(channel)

        started = client.StartTrading(
            task_pb.StartTradingRequest(
                request_id="01b77759-0343-4e03-b180-85a576d2b1ae",
                name="Restart live trading",
                instrument=task_pb.CurrencyPair(base="USD", quote="JPY"),
                strategy=task_pb.StrategyReference(name="counting"),
                account=task_pb.AccountReference(
                    id="paper-account",
                    provider=task_pb.ProviderReference(name="paper"),
                ),
                provider=task_pb.ProviderReference(name="paper"),
                dry_run=True,
            )
        )
        task_id = UUID(started.task.id)
        condition_waiter.until(
            lambda: (
                first.application.supervisor.get(task_id).last_processed_at == ticks[0].timestamp
            ),
            description="the first process to persist live strategy state",
        )
        first.stop()

        second = scenario_resources.track_process(
            self._trading_process(
                database_url,
                source_factory=lambda: InterruptibleDataSource(
                    ticks,
                    ticks_before_block=2,
                ),
            )
        )
        second.start()
        second_channel = scenario_resources.track_channel(
            grpc.insecure_channel(second.grpc_server.address)
        )
        second_client = task_grpc.TaskServiceStub(second_channel)
        condition_waiter.until(
            lambda: (
                second.application.supervisor.get(task_id).last_processed_at == ticks[1].timestamp
            ),
            description="the replacement process to advance the live checkpoint",
        )
        recovered = second.application.supervisor.get(task_id)

        assert recovered.id == task_id
        assert recovered.run_count == 1
        assert recovered.strategy_state == StrategyState.of(processed_ticks=2)
        stopped = second_client.StopTask(
            task_pb.StopTaskRequest(task_id=str(task_id)),
        ).task
        assert stopped.status == task_pb.TASK_STATUS_STOPPED

    def _process(
        self,
        database_url: str,
        *,
        source_factory,
    ) -> ServerProcess:
        strategies = StrategyRegistry()
        strategies.register(
            ComponentName.of("hold"),
            lambda parameters: HoldStrategy(name="hold", parameters=parameters),
        )
        sources = DataSourceRegistry()
        sources.register(ComponentName.of("replay"), source_factory)
        catalog = ServerComponentCatalog(
            strategies=strategies,
            data_sources=sources,
            providers=TradingProviderRegistry(),
        )
        application = ServerApplication.build(
            ServerSettings(
                port=0,
                database_url=database_url,
                task_workers=1,
                grpc_workers=2,
                heartbeat_interval_seconds=0.001,
            ),
            catalog=catalog,
        )
        return ServerProcess.create(application)

    def _trading_process(
        self,
        database_url: str,
        *,
        source_factory,
    ) -> ServerProcess:
        strategies = StrategyRegistry()
        strategies.register(
            ComponentName.of("counting"),
            lambda parameters: CountingStrategy(name="counting", parameters=parameters),
        )
        providers = TradingProviderRegistry()
        providers.register(
            ComponentName.of("paper"),
            lambda: TradingProvider(
                provider=AccountProvider.of("paper"),
                account_manager=cast(AccountManager, object()),
                broker=cast(Broker, object()),
                data=source_factory(),
            ),
        )
        catalog = ServerComponentCatalog(
            strategies=strategies,
            data_sources=DataSourceRegistry(),
            providers=providers,
        )
        application = ServerApplication.build(
            ServerSettings(
                port=0,
                database_url=database_url,
                task_workers=1,
                grpc_workers=2,
                heartbeat_interval_seconds=0.001,
            ),
            catalog=catalog,
        )
        return ServerProcess.create(application)

    def _wait_for_task(
        self,
        client,
        task_id: str,
        *,
        expected_status: int,
        condition_waiter,
    ) -> task_pb.Task:
        result: task_pb.Task | None = None

        def completed() -> bool:
            nonlocal result
            result = client.GetTask(task_pb.GetTaskRequest(task_id=task_id)).task
            return result.status == expected_status

        condition_waiter.until(
            completed,
            description=f"task {task_id} to reach status {expected_status}",
        )
        assert result is not None
        return result

    @staticmethod
    def _timestamp(value: datetime) -> Timestamp:
        timestamp = Timestamp()
        timestamp.FromDatetime(value)
        return timestamp
