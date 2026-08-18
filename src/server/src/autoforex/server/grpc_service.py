"""gRPC transport adapters for durable task supervision."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import ClassVar
from uuid import UUID

import grpc
from autoforex.core import (
    Account,
    AccountId,
    AccountProvider,
    BacktestTaskDefinition,
    CurrencyPair,
    ExecutableTask,
    TaskNotFoundError,
    TaskStateError,
    TaskStatus,
    TaskType,
    TradingTaskDefinition,
)
from autoforex.protobuf.task.v1 import task_service_pb2 as task_pb
from autoforex.protobuf.task.v1 import task_service_pb2_grpc as task_grpc
from google.protobuf import json_format
from google.protobuf.timestamp_pb2 import Timestamp  # ty: ignore[unresolved-import]
from pydantic import ValidationError

from autoforex.server.components import (
    BacktestTaskBinding,
    ComponentName,
    ComponentNotFoundError,
    DataSourceReference,
    ProviderReference,
    StrategyReference,
    TaskBinding,
    TradingTaskBinding,
)
from autoforex.server.discovery import (
    ServiceInstance,
    ServiceInstanceStatus,
    ServiceRegistry,
)
from autoforex.server.recovery import (
    TaskBindingConflictError,
    TaskExecutionDisposition,
    TaskIntentConflictError,
)
from autoforex.server.security import GrpcServerSecurity
from autoforex.server.settings import ServerSettings
from autoforex.server.submissions import (
    TaskSubmissionConflictError,
    TaskSubmissionId,
    TaskSubmissionInProgressError,
)
from autoforex.server.supervisor import TaskRecoveryError, TaskSupervisor

_LOGGER = logging.getLogger(__name__)


class GrpcTaskMapper:
    """Map protobuf DTOs to validated domain and application objects."""

    _TASK_TYPE_TO_PROTO: ClassVar[dict[TaskType, str]] = {
        TaskType.BACKTEST: "TASK_TYPE_BACKTEST",
        TaskType.TRADING: "TASK_TYPE_TRADING",
    }
    _TASK_STATUS_TO_PROTO: ClassVar[dict[TaskStatus, str]] = {
        TaskStatus.CREATED: "TASK_STATUS_CREATED",
        TaskStatus.STARTING: "TASK_STATUS_STARTING",
        TaskStatus.RUNNING: "TASK_STATUS_RUNNING",
        TaskStatus.PAUSED: "TASK_STATUS_PAUSED",
        TaskStatus.IDLE: "TASK_STATUS_IDLE",
        TaskStatus.DRAINING: "TASK_STATUS_DRAINING",
        TaskStatus.STOPPING: "TASK_STATUS_STOPPING",
        TaskStatus.STOPPED: "TASK_STATUS_STOPPED",
        TaskStatus.COMPLETED: "TASK_STATUS_COMPLETED",
        TaskStatus.FAILED: "TASK_STATUS_FAILED",
    }
    _PROTO_TO_TASK_STATUS: ClassVar[dict[int, TaskStatus]] = {
        task_pb.TaskStatus.Value(value): key for key, value in _TASK_STATUS_TO_PROTO.items()
    }
    _DISPOSITION_TO_PROTO: ClassVar[dict[TaskExecutionDisposition, str]] = {
        TaskExecutionDisposition.RUNNING: "TASK_EXECUTION_DISPOSITION_RUNNING",
        TaskExecutionDisposition.PAUSED: "TASK_EXECUTION_DISPOSITION_PAUSED",
        TaskExecutionDisposition.STOPPED: "TASK_EXECUTION_DISPOSITION_STOPPED",
        TaskExecutionDisposition.COMPLETED: "TASK_EXECUTION_DISPOSITION_COMPLETED",
        TaskExecutionDisposition.FAILED: "TASK_EXECUTION_DISPOSITION_FAILED",
        TaskExecutionDisposition.RECOVERY_REQUIRED: (
            "TASK_EXECUTION_DISPOSITION_RECOVERY_REQUIRED"
        ),
    }
    _SERVICE_STATUS_TO_PROTO: ClassVar[dict[ServiceInstanceStatus, str]] = {
        ServiceInstanceStatus.SERVING: "SERVICE_INSTANCE_STATUS_SERVING",
        ServiceInstanceStatus.DRAINING: "SERVICE_INSTANCE_STATUS_DRAINING",
    }

    def service_instance(self, instance: ServiceInstance) -> task_pb.ServerInstance:
        """Map one discoverable server instance to protobuf."""
        return task_pb.ServerInstance(
            instance_id=instance.instance_id,
            host=instance.host,
            port=instance.port,
            transport_security=instance.transport_security,
            status=self._SERVICE_STATUS_TO_PROTO[instance.status],
            version=instance.version,
            started_at=self._timestamp(instance.started_at),
            heartbeat_at=self._timestamp(instance.heartbeat_at),
            expires_at=self._timestamp(instance.expires_at),
            capabilities=instance.capabilities,
            metadata=instance.metadata,
        )

    def backtest_request(
        self,
        request: task_pb.StartBacktestRequest,
    ) -> tuple[BacktestTaskDefinition, BacktestTaskBinding]:
        """Map a start-backtest request."""
        if not request.HasField("start_at"):
            raise ValueError("start_at is required")
        if not request.HasField("end_at"):
            raise ValueError("end_at is required")
        strategy = self._strategy(request.strategy)
        definition = BacktestTaskDefinition(
            name=request.name,
            instrument=self._instrument(request.instrument),
            parameters=strategy.parameters,
            start_at=self._datetime(request.start_at),
            end_at=self._datetime(request.end_at),
        )
        binding = BacktestTaskBinding(
            strategy=strategy,
            data_source=DataSourceReference(
                name=ComponentName.of(request.data_source.name),
            ),
            broker_provider=(
                ProviderReference(name=ComponentName.of(request.broker_provider.name))
                if request.HasField("broker_provider")
                else None
            ),
        )
        return definition, binding

    def trading_request(
        self,
        request: task_pb.StartTradingRequest,
    ) -> tuple[TradingTaskDefinition, TradingTaskBinding]:
        """Map a start-trading request."""
        strategy = self._strategy(request.strategy)
        provider = ProviderReference(name=ComponentName.of(request.provider.name))
        if request.account.HasField("provider"):
            account_provider = ComponentName.of(request.account.provider.name)
            if account_provider != provider.name:
                raise ValueError("account provider and task provider must match")
        definition = TradingTaskDefinition(
            name=request.name,
            instrument=self._instrument(request.instrument),
            parameters=strategy.parameters,
            account=Account(
                id=AccountId.of(request.account.id),
                provider=AccountProvider.of(provider.name.value),
            ),
            dry_run=request.dry_run,
        )
        return definition, TradingTaskBinding(
            strategy=strategy,
            provider=provider,
        )

    def task(
        self,
        task: ExecutableTask,
        binding: TaskBinding,
        disposition: TaskExecutionDisposition | None = None,
    ) -> task_pb.Task:
        """Map a durable task snapshot to protobuf."""
        message = task_pb.Task(
            id=str(task.id),
            definition_id=str(task.definition_id),
            name=task.name,
            type=self._TASK_TYPE_TO_PROTO[task.task_type],
            status=self._TASK_STATUS_TO_PROTO[task.status],
            instrument=task_pb.CurrencyPair(
                base=task.instrument.base.code,
                quote=task.instrument.quote.code,
            ),
            strategy=self._strategy_message(binding.strategy),
            created_at=self._timestamp(task.created_at),
            run_count=task.run_count,
            execution_disposition=(
                "TASK_EXECUTION_DISPOSITION_UNSPECIFIED"
                if disposition is None
                else self._DISPOSITION_TO_PROTO[disposition]
            ),
        )
        self._set_timestamp(message.started_at, task.started_at)
        self._set_timestamp(message.paused_at, task.paused_at)
        self._set_timestamp(message.stopped_at, task.stopped_at)
        self._set_timestamp(message.completed_at, task.completed_at)
        self._set_timestamp(message.last_processed_at, task.last_processed_at)
        if task.failure is not None:
            message.failure.CopyFrom(
                task_pb.TaskFailure(
                    message=task.failure.message,
                    code=task.failure.code.value,
                    category=task.failure.category.value,
                    where=task.failure.where,
                    cause_type=task.failure.cause_type,
                    traceback=task.failure.traceback,
                    occurred_at=self._timestamp(task.failure.occurred_at),
                )
            )
        if isinstance(task.definition, BacktestTaskDefinition):
            if not isinstance(binding, BacktestTaskBinding):
                raise TypeError("backtest task requires BacktestTaskBinding")
            backtest = task_pb.BacktestDefinition(
                start_at=self._timestamp(task.definition.start_at),
                end_at=self._timestamp(task.definition.end_at),
                data_source=task_pb.DataSourceReference(name=binding.data_source.name.value),
            )
            if binding.broker_provider is not None:
                backtest.broker_provider.name = binding.broker_provider.name.value
            message.backtest.CopyFrom(backtest)
        else:
            if not isinstance(binding, TradingTaskBinding):
                raise TypeError("trading task requires TradingTaskBinding")
            account = task.definition.account
            message.trading.CopyFrom(
                task_pb.TradingDefinition(
                    account=task_pb.AccountReference(
                        id=account.id.value,
                        provider=task_pb.ProviderReference(
                            name=(
                                account.provider.value
                                if account.provider is not None
                                else binding.provider.name.value
                            )
                        ),
                    ),
                    provider=task_pb.ProviderReference(name=binding.provider.name.value),
                    dry_run=task.definition.dry_run,
                )
            )
        return message

    def task_id(self, value: str) -> UUID:
        """Parse a protocol task identifier."""
        try:
            return UUID(value)
        except ValueError as exc:
            raise ValueError(f"invalid task_id: {value}") from exc

    def status(self, value: int) -> TaskStatus:
        """Map a protobuf task status filter."""
        try:
            return self._PROTO_TO_TASK_STATUS[value]
        except KeyError as exc:
            raise ValueError("status filter must be a concrete task status") from exc

    def submission_id(self, value: str) -> TaskSubmissionId:
        """Parse a required idempotent start-request identifier."""
        if not value.strip():
            raise ValueError("request_id is required")
        try:
            return TaskSubmissionId.of(value)
        except ValueError as exc:
            raise ValueError(f"invalid request_id: {value}") from exc

    def _strategy(self, message: task_pb.StrategyReference) -> StrategyReference:
        parameters = json_format.MessageToDict(
            message.parameters,
            preserving_proto_field_name=True,
        )
        return StrategyReference(
            name=ComponentName.of(message.name),
            parameters=parameters,
        )

    def _strategy_message(
        self,
        reference: StrategyReference,
    ) -> task_pb.StrategyReference:
        message = task_pb.StrategyReference(name=reference.name.value)
        json_format.ParseDict(reference.parameters.to_jsonable(), message.parameters)
        return message

    def _instrument(self, message: task_pb.CurrencyPair) -> CurrencyPair:
        return CurrencyPair.of((message.base, message.quote))

    def _datetime(self, value: Timestamp) -> datetime:
        return value.ToDatetime(tzinfo=UTC)

    def _timestamp(self, value: datetime) -> Timestamp:
        timestamp = Timestamp()
        timestamp.FromDatetime(value)
        return timestamp

    def _set_timestamp(
        self,
        target: Timestamp,
        value: datetime | None,
    ) -> None:
        if value is not None:
            target.FromDatetime(value)


class GrpcFailureHandler:
    """Translate application failures to stable gRPC status codes."""

    def abort(self, context: grpc.ServicerContext, exc: Exception) -> None:
        """Abort the current RPC with an appropriate status."""
        if isinstance(exc, TaskNotFoundError | KeyError):
            context.abort(grpc.StatusCode.NOT_FOUND, str(exc))
        if isinstance(exc, ComponentNotFoundError):
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))
        if isinstance(exc, TaskSubmissionConflictError | TaskBindingConflictError):
            context.abort(grpc.StatusCode.ALREADY_EXISTS, str(exc))
        if isinstance(exc, TaskSubmissionInProgressError | TaskIntentConflictError):
            context.abort(grpc.StatusCode.ABORTED, str(exc))
        if isinstance(exc, TaskStateError | TaskRecoveryError):
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))
        if isinstance(exc, ValidationError | ValueError | TypeError):
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        _LOGGER.exception("Unhandled gRPC task service failure", exc_info=exc)
        context.abort(grpc.StatusCode.INTERNAL, "internal server error")


class TaskGrpcService(task_grpc.TaskServiceServicer):
    """Thin gRPC adapter over TaskSupervisor."""

    def __init__(
        self,
        supervisor: TaskSupervisor,
        service_registry: ServiceRegistry,
        *,
        mapper: GrpcTaskMapper | None = None,
        failures: GrpcFailureHandler | None = None,
    ) -> None:
        self.supervisor = supervisor
        self.service_registry = service_registry
        self.mapper = mapper or GrpcTaskMapper()
        self.failures = failures or GrpcFailureHandler()

    def GetHealth(self, request, context):
        _ = request
        if self.supervisor.is_healthy() and self.service_registry.is_healthy():
            return task_pb.GetHealthResponse(status="serving")
        context.set_code(grpc.StatusCode.UNAVAILABLE)
        context.set_details("server dependencies are not healthy")
        return task_pb.GetHealthResponse(status="not_serving")

    def ListServerInstances(self, request, context):
        _ = request
        try:
            return task_pb.ListServerInstancesResponse(
                instances=[
                    self.mapper.service_instance(instance)
                    for instance in self.service_registry.list_instances()
                ]
            )
        except Exception as exc:
            self.failures.abort(context, exc)

    def StartBacktest(self, request, context):
        try:
            definition, binding = self.mapper.backtest_request(request)
            task = self.supervisor.submit_backtest(
                definition,
                binding,
                self.mapper.submission_id(request.request_id),
            )
            return self._response(task)
        except Exception as exc:
            self.failures.abort(context, exc)

    def StartTrading(self, request, context):
        try:
            definition, binding = self.mapper.trading_request(request)
            task = self.supervisor.submit_trading(
                definition,
                binding,
                self.mapper.submission_id(request.request_id),
            )
            return self._response(task)
        except Exception as exc:
            self.failures.abort(context, exc)

    def GetTask(self, request, context):
        try:
            return self._response(self.supervisor.get(self.mapper.task_id(request.task_id)))
        except Exception as exc:
            self.failures.abort(context, exc)

    def ListTasks(self, request, context):
        try:
            status = self.mapper.status(request.status) if request.filter_by_status else None
            return task_pb.ListTasksResponse(
                tasks=[self._task_message(task) for task in self.supervisor.list(status=status)]
            )
        except Exception as exc:
            self.failures.abort(context, exc)

    def PauseTask(self, request, context):
        try:
            return self._response(self.supervisor.pause(self.mapper.task_id(request.task_id)))
        except Exception as exc:
            self.failures.abort(context, exc)

    def ResumeTask(self, request, context):
        try:
            run = self.supervisor.resume(self.mapper.task_id(request.task_id))
            return self._response(run.task)
        except Exception as exc:
            self.failures.abort(context, exc)

    def StopTask(self, request, context):
        try:
            return self._response(self.supervisor.stop(self.mapper.task_id(request.task_id)))
        except Exception as exc:
            self.failures.abort(context, exc)

    def RestartTask(self, request, context):
        try:
            run = self.supervisor.restart(self.mapper.task_id(request.task_id))
            return self._response(run.task)
        except Exception as exc:
            self.failures.abort(context, exc)

    def RecoverTask(self, request, context):
        try:
            run = self.supervisor.recover(self.mapper.task_id(request.task_id))
            return self._response(run.task)
        except Exception as exc:
            self.failures.abort(context, exc)

    def _response(self, task: ExecutableTask) -> task_pb.TaskResponse:
        return task_pb.TaskResponse(task=self._task_message(task))

    def _task_message(self, task: ExecutableTask) -> task_pb.Task:
        return self.mapper.task(
            task,
            self.supervisor.binding_for(task),
            self.supervisor.intent_for(task.id).disposition,
        )


class GrpcTaskServer:
    """Lifecycle wrapper around the synchronous gRPC server."""

    def __init__(
        self,
        service: TaskGrpcService,
        *,
        host: str,
        port: int,
        max_workers: int,
        settings: ServerSettings | None = None,
    ) -> None:
        self.host = host
        self.requested_port = port
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self.security = GrpcServerSecurity(settings) if settings is not None else None
        self._server = grpc.server(
            self._executor,
            interceptors=(() if self.security is None else self.security.interceptors()),
        )
        task_grpc.add_TaskServiceServicer_to_server(service, self._server)
        address = f"{host}:{port}"
        credentials = None if self.security is None else self.security.credentials()
        self.port = (
            self._server.add_insecure_port(address)
            if credentials is None
            else self._server.add_secure_port(address, credentials)
        )
        if self.port == 0:
            raise RuntimeError(f"failed to bind gRPC server to {host}:{port}")

    @property
    def address(self) -> str:
        """Return the bound host and port."""
        return f"{self.host}:{self.port}"

    def start(self) -> None:
        """Start accepting RPCs."""
        self._server.start()

    def wait(self) -> None:
        """Block until the server terminates."""
        self._server.wait_for_termination()

    def stop(self, *, grace_seconds: float) -> None:
        """Stop accepting RPCs and wait for in-flight calls."""
        event = self._server.stop(grace_seconds)
        event.wait()
        self._executor.shutdown(wait=True)
