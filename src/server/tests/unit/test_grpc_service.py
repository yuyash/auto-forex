from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import grpc
import pytest
from autoforex.core import ExecutableTask, TaskNotFoundError
from autoforex.protobuf.task.v1 import task_service_pb2 as task_pb

from autoforex.server.components import BacktestTaskBinding
from autoforex.server.discovery import ServiceInstance
from autoforex.server.grpc_service import GrpcFailureHandler, TaskGrpcService
from autoforex.server.recovery import (
    TaskExecutionDisposition,
    TaskExecutionIntent,
    TaskIntentConflictError,
)
from autoforex.server.submissions import TaskSubmissionConflictError


class RpcAborted(RuntimeError):
    def __init__(self, code: grpc.StatusCode, details: str) -> None:
        super().__init__(details)
        self.code = code


class AbortingContext:
    def abort(self, code: grpc.StatusCode, details: str) -> None:
        raise RpcAborted(code, details)


class RecordingSupervisor:
    def __init__(
        self,
        task: ExecutableTask,
        binding: BacktestTaskBinding,
    ) -> None:
        self.task = task
        self.binding = binding
        self.calls: list[tuple[str, Any]] = []
        self.intent = TaskExecutionIntent(
            task_id=task.id,
            definition_id=task.definition_id,
            disposition=TaskExecutionDisposition.RUNNING,
            owner_id="server-a",
        )

    def is_healthy(self) -> bool:
        return True

    def get(self, task_id):
        self.calls.append(("get", task_id))
        return self.task

    def list(self, *, status=None):
        self.calls.append(("list", status))
        return (self.task,)

    def pause(self, task_id):
        self.calls.append(("pause", task_id))
        return self.task

    def resume(self, task_id):
        self.calls.append(("resume", task_id))
        return SimpleNamespace(task=self.task)

    def stop(self, task_id):
        self.calls.append(("stop", task_id))
        return self.task

    def restart(self, task_id):
        self.calls.append(("restart", task_id))
        return SimpleNamespace(task=self.task)

    def recover(self, task_id):
        self.calls.append(("recover", task_id))
        return SimpleNamespace(task=self.task)

    def binding_for(self, task):
        return self.binding

    def intent_for(self, task_id):
        return self.intent


class RecordingServiceRegistry:
    def __init__(self, instances: tuple[ServiceInstance, ...] = ()) -> None:
        self.instances = instances

    def list_instances(self) -> tuple[ServiceInstance, ...]:
        return self.instances

    def is_healthy(self) -> bool:
        return True


class TestGrpcFailureHandler:
    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (TaskNotFoundError("missing"), grpc.StatusCode.NOT_FOUND),
            (KeyError("missing"), grpc.StatusCode.NOT_FOUND),
            (TaskSubmissionConflictError("reused"), grpc.StatusCode.ALREADY_EXISTS),
            (TaskIntentConflictError("stale"), grpc.StatusCode.ABORTED),
            (ValueError("invalid"), grpc.StatusCode.INVALID_ARGUMENT),
            (RuntimeError("unexpected"), grpc.StatusCode.INTERNAL),
        ],
    )
    def test_maps_application_failures_to_stable_rpc_status(
        self,
        error: Exception,
        expected: grpc.StatusCode,
    ) -> None:
        context = AbortingContext()

        with pytest.raises(RpcAborted) as raised:
            GrpcFailureHandler().abort(
                cast(grpc.ServicerContext, cast(Any, context)),
                error,
            )

        assert raised.value.code == expected


class TestTaskGrpcService:
    @pytest.mark.parametrize(
        ("rpc_name", "request_type", "expected_call"),
        [
            ("GetTask", task_pb.GetTaskRequest, "get"),
            ("PauseTask", task_pb.PauseTaskRequest, "pause"),
            ("ResumeTask", task_pb.ResumeTaskRequest, "resume"),
            ("StopTask", task_pb.StopTaskRequest, "stop"),
            ("RestartTask", task_pb.RestartTaskRequest, "restart"),
            ("RecoverTask", task_pb.RecoverTaskRequest, "recover"),
        ],
    )
    def test_control_and_read_rpcs_delegate_by_validated_task_id(
        self,
        rpc_name: str,
        request_type: Any,
        expected_call: str,
        executable_task: ExecutableTask,
        backtest_binding: BacktestTaskBinding,
    ) -> None:
        supervisor = RecordingSupervisor(executable_task, backtest_binding)
        service = TaskGrpcService(cast(Any, supervisor), cast(Any, RecordingServiceRegistry()))
        request = request_type(task_id=str(executable_task.id))

        response = getattr(service, rpc_name)(request, AbortingContext())

        assert response.task.id == str(executable_task.id)
        assert supervisor.calls[-1] == (expected_call, executable_task.id)

    def test_list_rpc_applies_optional_status_filter_and_maps_intent(
        self,
        executable_task: ExecutableTask,
        backtest_binding: BacktestTaskBinding,
    ) -> None:
        supervisor = RecordingSupervisor(executable_task, backtest_binding)
        service = TaskGrpcService(cast(Any, supervisor), cast(Any, RecordingServiceRegistry()))

        response = service.ListTasks(
            task_pb.ListTasksRequest(
                filter_by_status=True,
                status=task_pb.TASK_STATUS_RUNNING,
            ),
            AbortingContext(),
        )

        assert [item.id for item in response.tasks] == [str(executable_task.id)]
        assert supervisor.calls == [("list", executable_task.status)]
        assert response.tasks[0].execution_disposition == task_pb.TASK_EXECUTION_DISPOSITION_RUNNING

    def test_invalid_task_id_is_rejected_before_supervisor_call(
        self,
        executable_task: ExecutableTask,
        backtest_binding: BacktestTaskBinding,
    ) -> None:
        supervisor = RecordingSupervisor(executable_task, backtest_binding)
        service = TaskGrpcService(cast(Any, supervisor), cast(Any, RecordingServiceRegistry()))

        with pytest.raises(RpcAborted) as raised:
            service.GetTask(
                task_pb.GetTaskRequest(task_id=str(uuid4()) + "-invalid"),
                AbortingContext(),
            )

        assert raised.value.code == grpc.StatusCode.INVALID_ARGUMENT
        assert supervisor.calls == []

    def test_lists_discoverable_server_instances(
        self,
        executable_task: ExecutableTask,
        backtest_binding: BacktestTaskBinding,
    ) -> None:
        current = datetime(2026, 8, 16, tzinfo=UTC)
        instance = ServiceInstance(
            instance_id="server-a",
            host="10.0.0.5",
            port=50051,
            transport_security="plaintext",
            version="0.1.1",
            started_at=current,
            heartbeat_at=current,
            expires_at=current + timedelta(seconds=20),
            capabilities=("task-service-v1",),
            metadata={"zone": "us-west-2a"},
        )
        service = TaskGrpcService(
            cast(Any, RecordingSupervisor(executable_task, backtest_binding)),
            cast(Any, RecordingServiceRegistry((instance,))),
        )

        response = service.ListServerInstances(
            task_pb.ListServerInstancesRequest(),
            AbortingContext(),
        )

        assert len(response.instances) == 1
        assert response.instances[0].instance_id == "server-a"
        assert response.instances[0].host == "10.0.0.5"
        assert response.instances[0].metadata["zone"] == "us-west-2a"
