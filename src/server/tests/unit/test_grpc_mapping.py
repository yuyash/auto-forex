from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import grpc
import pytest
from autoforex.core import ExecutableTask, TaskStatus
from autoforex.protobuf.task.v1 import task_service_pb2 as task_pb
from google.protobuf.timestamp_pb2 import Timestamp  # ty: ignore[unresolved-import]

from autoforex.server.components import BacktestTaskBinding
from autoforex.server.grpc_service import GrpcTaskMapper, TaskGrpcService
from autoforex.server.recovery import TaskExecutionDisposition
from autoforex.server.supervisor import TaskSupervisor


class RecordingGrpcContext:
    def __init__(self) -> None:
        self.code: grpc.StatusCode | None = None
        self.details = ""

    def set_code(self, code: grpc.StatusCode) -> None:
        self.code = code

    def set_details(self, details: str) -> None:
        self.details = details


class UnhealthySupervisor:
    def is_healthy(self) -> bool:
        return False


class TestGrpcTaskMapper:
    def test_health_reports_dependency_failure(self) -> None:
        context = RecordingGrpcContext()
        service = TaskGrpcService(
            cast(TaskSupervisor, cast(Any, UnhealthySupervisor())),
            cast(Any, SimpleNamespace(list_instances=lambda: ())),
        )

        response = service.GetHealth(
            task_pb.GetHealthRequest(),
            cast(grpc.ServicerContext, cast(Any, context)),
        )

        assert response.status == "not_serving"
        assert context.code == grpc.StatusCode.UNAVAILABLE

    def test_maps_backtest_request_and_task_response(self) -> None:
        start_at = datetime(2026, 1, 1, tzinfo=UTC)
        end_at = datetime(2026, 1, 2, tzinfo=UTC)
        request = task_pb.StartBacktestRequest(
            name="USD JPY replay",
            instrument=task_pb.CurrencyPair(base="USD", quote="JPY"),
            strategy=task_pb.StrategyReference(name="snowball"),
            start_at=self._timestamp(start_at),
            end_at=self._timestamp(end_at),
            data_source=task_pb.DataSourceReference(name="csv"),
        )
        mapper = GrpcTaskMapper()

        definition, binding = mapper.backtest_request(request)
        task = ExecutableTask.from_definition(definition).start(at=start_at)
        message = mapper.task(
            task,
            binding,
            TaskExecutionDisposition.RECOVERY_REQUIRED,
        )

        assert isinstance(binding, BacktestTaskBinding)
        assert definition.instrument.symbol == "USD_JPY"
        assert message.id == str(task.id)
        assert message.status == task_pb.TASK_STATUS_RUNNING
        assert message.execution_disposition == task_pb.TASK_EXECUTION_DISPOSITION_RECOVERY_REQUIRED
        assert message.backtest.data_source.name == "csv"
        assert message.strategy.name == "snowball"

    def test_rejects_unspecified_status_filter(self) -> None:
        with pytest.raises(ValueError, match="concrete"):
            GrpcTaskMapper().status(task_pb.TASK_STATUS_UNSPECIFIED)

    @pytest.mark.parametrize("field_name", ["start_at", "end_at"])
    def test_rejects_missing_backtest_timestamp(self, field_name: str) -> None:
        request = task_pb.StartBacktestRequest(
            name="USD JPY replay",
            instrument=task_pb.CurrencyPair(base="USD", quote="JPY"),
            strategy=task_pb.StrategyReference(name="snowball"),
            start_at=self._timestamp(datetime(2026, 1, 1, tzinfo=UTC)),
            end_at=self._timestamp(datetime(2026, 1, 2, tzinfo=UTC)),
            data_source=task_pb.DataSourceReference(name="csv"),
        )
        request.ClearField(field_name)

        with pytest.raises(ValueError, match=rf"{field_name} is required"):
            GrpcTaskMapper().backtest_request(request)

    def test_maps_every_core_status(self) -> None:
        mapper = GrpcTaskMapper()

        mapped = {
            mapper.status(value)
            for value in (
                task_pb.TASK_STATUS_CREATED,
                task_pb.TASK_STATUS_STARTING,
                task_pb.TASK_STATUS_RUNNING,
                task_pb.TASK_STATUS_PAUSED,
                task_pb.TASK_STATUS_IDLE,
                task_pb.TASK_STATUS_DRAINING,
                task_pb.TASK_STATUS_STOPPING,
                task_pb.TASK_STATUS_STOPPED,
                task_pb.TASK_STATUS_COMPLETED,
                task_pb.TASK_STATUS_FAILED,
            )
        }

        assert mapped == set(TaskStatus)

    @staticmethod
    def _timestamp(value: datetime) -> Timestamp:
        timestamp = Timestamp()
        timestamp.FromDatetime(value)
        return timestamp
