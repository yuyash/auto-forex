from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic, sleep
from typing import Any, cast
from uuid import uuid4

import grpc
import pytest
from autoforex.core import (
    BacktestTaskDefinition,
    CurrencyPair,
    ExecutableTask,
    Money,
    StrategyAction,
    StrategyEventRequest,
    Tick,
    TradeSide,
    Units,
)

from autoforex.server.components import (
    BacktestTaskBinding,
    ComponentName,
    DataSourceReference,
    StrategyReference,
)
from autoforex.server.execution import ExecutionBatch
from autoforex.server.persistence import SqlPersistence


class ConditionWaiter:
    """Wait for asynchronous scenario outcomes with a useful failure message."""

    def until(
        self,
        condition: Callable[[], bool],
        *,
        description: str,
        timeout: float = 5.0,
        interval: float = 0.01,
    ) -> None:
        deadline = monotonic() + timeout
        while monotonic() < deadline:
            if condition():
                return
            sleep(interval)
        raise AssertionError(f"timed out waiting for {description}")


@dataclass(slots=True)
class DurablePersistenceCase:
    """One configured persistence backend exercising the server contracts."""

    name: str
    persistence: Any


class ScenarioResources:
    """Own process and channel cleanup even when an E2E assertion fails."""

    def __init__(self) -> None:
        self.processes: list[Any] = []
        self.channels: list[grpc.Channel] = []

    def track_process(self, process: Any) -> Any:
        self.processes.append(process)
        return process

    def track_channel(self, channel: grpc.Channel) -> grpc.Channel:
        self.channels.append(channel)
        return channel

    def close(self) -> None:
        for channel in reversed(self.channels):
            channel.close()
        for process in reversed(self.processes):
            process.stop()


class SupervisorResources:
    """Own supervisor shutdown for integration scenarios."""

    def __init__(self) -> None:
        self.supervisors: list[Any] = []

    def track(self, supervisor: Any) -> Any:
        self.supervisors.append(supervisor)
        return supervisor

    def close(self) -> None:
        for supervisor in reversed(self.supervisors):
            supervisor.shutdown()


@pytest.fixture
def condition_waiter() -> ConditionWaiter:
    """Provide deterministic polling for process and distributed tests."""
    return ConditionWaiter()


@pytest.fixture
def scenario_resources() -> Iterator[ScenarioResources]:
    """Guarantee cleanup for every channel and process opened by an E2E scenario."""
    resources = ScenarioResources()
    try:
        yield resources
    finally:
        resources.close()


@pytest.fixture
def supervisor_resources() -> Iterator[SupervisorResources]:
    """Guarantee background workers stop when an integration assertion fails."""
    resources = SupervisorResources()
    try:
        yield resources
    finally:
        resources.close()


@pytest.fixture
def market_instrument() -> CurrencyPair:
    """Provide the representative instrument shared by server scenarios."""
    return CurrencyPair.of("USD_JPY")


@pytest.fixture
def market_ticks(market_instrument: CurrencyPair) -> tuple[Tick, Tick]:
    """Provide two ordered ticks so recovery can prove checkpoint advancement."""
    return (
        Tick(
            instrument=market_instrument,
            timestamp=datetime(2026, 1, 1, 0, tzinfo=UTC),
            bid=Money.of("150.10", "JPY"),
            ask=Money.of("150.12", "JPY"),
        ),
        Tick(
            instrument=market_instrument,
            timestamp=datetime(2026, 1, 1, 1, tzinfo=UTC),
            bid=Money.of("150.20", "JPY"),
            ask=Money.of("150.22", "JPY"),
        ),
    )


@pytest.fixture
def backtest_definition(market_instrument: CurrencyPair) -> BacktestTaskDefinition:
    """Provide a complete definition suitable for persistence contract tests."""
    return BacktestTaskDefinition(
        name="Persistence contract replay",
        instrument=market_instrument,
        start_at=datetime(2026, 1, 1, tzinfo=UTC),
        end_at=datetime(2026, 1, 2, tzinfo=UTC),
    )


@pytest.fixture
def executable_task(backtest_definition: BacktestTaskDefinition) -> ExecutableTask:
    """Provide a running task so status filters and checkpoints are observable."""
    return ExecutableTask.from_definition(backtest_definition).start(
        at=backtest_definition.start_at
    )


@pytest.fixture
def backtest_binding() -> BacktestTaskBinding:
    """Provide an immutable component binding used to reconstruct a task."""
    return BacktestTaskBinding(
        strategy=StrategyReference(name=ComponentName.of("hold")),
        data_source=DataSourceReference(name=ComponentName.of("replay")),
    )


@pytest.fixture
def execution_request() -> StrategyEventRequest:
    """Provide a broker-requiring strategy request for journal contract tests."""
    return StrategyEventRequest(
        task_id=uuid4(),
        action=StrategyAction.OPEN_TRADE,
        instrument=CurrencyPair.of("EUR_USD"),
        side=TradeSide.BUY,
        units=Units("10"),
        price=Money.of("1.10", "USD"),
    )


@pytest.fixture
def execution_batch(execution_request: StrategyEventRequest) -> ExecutionBatch:
    """Provide a prepared execution batch with a durable checkpoint."""
    return ExecutionBatch(
        batch_id=uuid4(),
        task_id=execution_request.task_id,
        requests=(execution_request,),
        checkpoint_at=execution_request.timestamp,
    )


@pytest.fixture
def sqlite_persistence(tmp_path: Path) -> Iterator[SqlPersistence]:
    """Provide an isolated file-backed SQLite persistence and dispose it."""
    persistence = SqlPersistence(f"sqlite:///{tmp_path / 'server.db'}")
    persistence.create_schema()
    try:
        yield persistence
    finally:
        persistence.close()


@pytest.fixture(params=("sqlite", "postgresql", "dynamodb"), ids=str)
def durable_persistence(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> Iterator[DurablePersistenceCase]:
    """Provide every supported durable backend under one behavioral contract."""
    backend = str(request.param)
    if backend == "sqlite":
        persistence = SqlPersistence(f"sqlite:///{tmp_path / 'contract.db'}")
        persistence.create_schema()
        try:
            yield DurablePersistenceCase(name=backend, persistence=persistence)
        finally:
            persistence.close()
        return

    if backend == "postgresql":
        database_url = os.getenv("AUTO_FOREX_TEST_POSTGRESQL_URL")
        if not database_url:
            pytest.skip("AUTO_FOREX_TEST_POSTGRESQL_URL is required for PostgreSQL contracts")
        persistence = SqlPersistence(database_url)
        persistence.create_schema()
        try:
            yield DurablePersistenceCase(name=backend, persistence=persistence)
        finally:
            persistence.close()
        return

    endpoint_url = os.getenv("AUTO_FOREX_TEST_DYNAMODB_ENDPOINT_URL")
    if not endpoint_url:
        pytest.skip("AUTO_FOREX_TEST_DYNAMODB_ENDPOINT_URL is required for DynamoDB contracts")
    from autoforex.server.dynamodb import DynamoDbServerPersistence

    table_name = f"auto-forex-contract-{uuid4()}"
    persistence = DynamoDbServerPersistence(
        table_name=table_name,
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-west-2"),
        endpoint_url=endpoint_url,
        consistent_reads=True,
        enable_point_in_time_recovery=False,
    )
    persistence.create_schema()
    try:
        yield DurablePersistenceCase(name=backend, persistence=persistence)
    finally:
        persistence.close()
        store = cast(Any, persistence.store)
        store.client.delete_table(TableName=table_name)
