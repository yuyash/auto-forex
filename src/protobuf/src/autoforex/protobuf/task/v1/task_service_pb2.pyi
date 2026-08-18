import datetime

from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ServiceInstanceStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SERVICE_INSTANCE_STATUS_UNSPECIFIED: _ClassVar[ServiceInstanceStatus]
    SERVICE_INSTANCE_STATUS_SERVING: _ClassVar[ServiceInstanceStatus]
    SERVICE_INSTANCE_STATUS_DRAINING: _ClassVar[ServiceInstanceStatus]

class TaskType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    TASK_TYPE_UNSPECIFIED: _ClassVar[TaskType]
    TASK_TYPE_BACKTEST: _ClassVar[TaskType]
    TASK_TYPE_TRADING: _ClassVar[TaskType]

class TaskStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    TASK_STATUS_UNSPECIFIED: _ClassVar[TaskStatus]
    TASK_STATUS_CREATED: _ClassVar[TaskStatus]
    TASK_STATUS_STARTING: _ClassVar[TaskStatus]
    TASK_STATUS_RUNNING: _ClassVar[TaskStatus]
    TASK_STATUS_PAUSED: _ClassVar[TaskStatus]
    TASK_STATUS_IDLE: _ClassVar[TaskStatus]
    TASK_STATUS_DRAINING: _ClassVar[TaskStatus]
    TASK_STATUS_STOPPING: _ClassVar[TaskStatus]
    TASK_STATUS_STOPPED: _ClassVar[TaskStatus]
    TASK_STATUS_COMPLETED: _ClassVar[TaskStatus]
    TASK_STATUS_FAILED: _ClassVar[TaskStatus]

class TaskExecutionDisposition(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    TASK_EXECUTION_DISPOSITION_UNSPECIFIED: _ClassVar[TaskExecutionDisposition]
    TASK_EXECUTION_DISPOSITION_RUNNING: _ClassVar[TaskExecutionDisposition]
    TASK_EXECUTION_DISPOSITION_PAUSED: _ClassVar[TaskExecutionDisposition]
    TASK_EXECUTION_DISPOSITION_STOPPED: _ClassVar[TaskExecutionDisposition]
    TASK_EXECUTION_DISPOSITION_COMPLETED: _ClassVar[TaskExecutionDisposition]
    TASK_EXECUTION_DISPOSITION_FAILED: _ClassVar[TaskExecutionDisposition]
    TASK_EXECUTION_DISPOSITION_RECOVERY_REQUIRED: _ClassVar[TaskExecutionDisposition]
SERVICE_INSTANCE_STATUS_UNSPECIFIED: ServiceInstanceStatus
SERVICE_INSTANCE_STATUS_SERVING: ServiceInstanceStatus
SERVICE_INSTANCE_STATUS_DRAINING: ServiceInstanceStatus
TASK_TYPE_UNSPECIFIED: TaskType
TASK_TYPE_BACKTEST: TaskType
TASK_TYPE_TRADING: TaskType
TASK_STATUS_UNSPECIFIED: TaskStatus
TASK_STATUS_CREATED: TaskStatus
TASK_STATUS_STARTING: TaskStatus
TASK_STATUS_RUNNING: TaskStatus
TASK_STATUS_PAUSED: TaskStatus
TASK_STATUS_IDLE: TaskStatus
TASK_STATUS_DRAINING: TaskStatus
TASK_STATUS_STOPPING: TaskStatus
TASK_STATUS_STOPPED: TaskStatus
TASK_STATUS_COMPLETED: TaskStatus
TASK_STATUS_FAILED: TaskStatus
TASK_EXECUTION_DISPOSITION_UNSPECIFIED: TaskExecutionDisposition
TASK_EXECUTION_DISPOSITION_RUNNING: TaskExecutionDisposition
TASK_EXECUTION_DISPOSITION_PAUSED: TaskExecutionDisposition
TASK_EXECUTION_DISPOSITION_STOPPED: TaskExecutionDisposition
TASK_EXECUTION_DISPOSITION_COMPLETED: TaskExecutionDisposition
TASK_EXECUTION_DISPOSITION_FAILED: TaskExecutionDisposition
TASK_EXECUTION_DISPOSITION_RECOVERY_REQUIRED: TaskExecutionDisposition

class CurrencyPair(_message.Message):
    __slots__ = ("base", "quote")
    BASE_FIELD_NUMBER: _ClassVar[int]
    QUOTE_FIELD_NUMBER: _ClassVar[int]
    base: str
    quote: str
    def __init__(self, base: _Optional[str] = ..., quote: _Optional[str] = ...) -> None: ...

class StrategyReference(_message.Message):
    __slots__ = ("name", "parameters")
    NAME_FIELD_NUMBER: _ClassVar[int]
    PARAMETERS_FIELD_NUMBER: _ClassVar[int]
    name: str
    parameters: _struct_pb2.Struct
    def __init__(self, name: _Optional[str] = ..., parameters: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

class DataSourceReference(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class ProviderReference(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class AccountReference(_message.Message):
    __slots__ = ("id", "provider")
    ID_FIELD_NUMBER: _ClassVar[int]
    PROVIDER_FIELD_NUMBER: _ClassVar[int]
    id: str
    provider: ProviderReference
    def __init__(self, id: _Optional[str] = ..., provider: _Optional[_Union[ProviderReference, _Mapping]] = ...) -> None: ...

class BacktestDefinition(_message.Message):
    __slots__ = ("start_at", "end_at", "data_source", "broker_provider")
    START_AT_FIELD_NUMBER: _ClassVar[int]
    END_AT_FIELD_NUMBER: _ClassVar[int]
    DATA_SOURCE_FIELD_NUMBER: _ClassVar[int]
    BROKER_PROVIDER_FIELD_NUMBER: _ClassVar[int]
    start_at: _timestamp_pb2.Timestamp
    end_at: _timestamp_pb2.Timestamp
    data_source: DataSourceReference
    broker_provider: ProviderReference
    def __init__(self, start_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., end_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., data_source: _Optional[_Union[DataSourceReference, _Mapping]] = ..., broker_provider: _Optional[_Union[ProviderReference, _Mapping]] = ...) -> None: ...

class TradingDefinition(_message.Message):
    __slots__ = ("account", "provider", "dry_run")
    ACCOUNT_FIELD_NUMBER: _ClassVar[int]
    PROVIDER_FIELD_NUMBER: _ClassVar[int]
    DRY_RUN_FIELD_NUMBER: _ClassVar[int]
    account: AccountReference
    provider: ProviderReference
    dry_run: bool
    def __init__(self, account: _Optional[_Union[AccountReference, _Mapping]] = ..., provider: _Optional[_Union[ProviderReference, _Mapping]] = ..., dry_run: _Optional[bool] = ...) -> None: ...

class TaskFailure(_message.Message):
    __slots__ = ("message", "code", "category", "where", "cause_type", "traceback", "occurred_at")
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    CODE_FIELD_NUMBER: _ClassVar[int]
    CATEGORY_FIELD_NUMBER: _ClassVar[int]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    CAUSE_TYPE_FIELD_NUMBER: _ClassVar[int]
    TRACEBACK_FIELD_NUMBER: _ClassVar[int]
    OCCURRED_AT_FIELD_NUMBER: _ClassVar[int]
    message: str
    code: str
    category: str
    where: str
    cause_type: str
    traceback: str
    occurred_at: _timestamp_pb2.Timestamp
    def __init__(self, message: _Optional[str] = ..., code: _Optional[str] = ..., category: _Optional[str] = ..., where: _Optional[str] = ..., cause_type: _Optional[str] = ..., traceback: _Optional[str] = ..., occurred_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class Task(_message.Message):
    __slots__ = ("id", "definition_id", "name", "type", "status", "instrument", "strategy", "created_at", "started_at", "paused_at", "stopped_at", "completed_at", "run_count", "failure", "last_processed_at", "execution_disposition", "backtest", "trading")
    ID_FIELD_NUMBER: _ClassVar[int]
    DEFINITION_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    INSTRUMENT_FIELD_NUMBER: _ClassVar[int]
    STRATEGY_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    STARTED_AT_FIELD_NUMBER: _ClassVar[int]
    PAUSED_AT_FIELD_NUMBER: _ClassVar[int]
    STOPPED_AT_FIELD_NUMBER: _ClassVar[int]
    COMPLETED_AT_FIELD_NUMBER: _ClassVar[int]
    RUN_COUNT_FIELD_NUMBER: _ClassVar[int]
    FAILURE_FIELD_NUMBER: _ClassVar[int]
    LAST_PROCESSED_AT_FIELD_NUMBER: _ClassVar[int]
    EXECUTION_DISPOSITION_FIELD_NUMBER: _ClassVar[int]
    BACKTEST_FIELD_NUMBER: _ClassVar[int]
    TRADING_FIELD_NUMBER: _ClassVar[int]
    id: str
    definition_id: str
    name: str
    type: TaskType
    status: TaskStatus
    instrument: CurrencyPair
    strategy: StrategyReference
    created_at: _timestamp_pb2.Timestamp
    started_at: _timestamp_pb2.Timestamp
    paused_at: _timestamp_pb2.Timestamp
    stopped_at: _timestamp_pb2.Timestamp
    completed_at: _timestamp_pb2.Timestamp
    run_count: int
    failure: TaskFailure
    last_processed_at: _timestamp_pb2.Timestamp
    execution_disposition: TaskExecutionDisposition
    backtest: BacktestDefinition
    trading: TradingDefinition
    def __init__(self, id: _Optional[str] = ..., definition_id: _Optional[str] = ..., name: _Optional[str] = ..., type: _Optional[_Union[TaskType, str]] = ..., status: _Optional[_Union[TaskStatus, str]] = ..., instrument: _Optional[_Union[CurrencyPair, _Mapping]] = ..., strategy: _Optional[_Union[StrategyReference, _Mapping]] = ..., created_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., started_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., paused_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., stopped_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., completed_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., run_count: _Optional[int] = ..., failure: _Optional[_Union[TaskFailure, _Mapping]] = ..., last_processed_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., execution_disposition: _Optional[_Union[TaskExecutionDisposition, str]] = ..., backtest: _Optional[_Union[BacktestDefinition, _Mapping]] = ..., trading: _Optional[_Union[TradingDefinition, _Mapping]] = ...) -> None: ...

class GetHealthRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class GetHealthResponse(_message.Message):
    __slots__ = ("status",)
    STATUS_FIELD_NUMBER: _ClassVar[int]
    status: str
    def __init__(self, status: _Optional[str] = ...) -> None: ...

class ListServerInstancesRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ServerInstance(_message.Message):
    __slots__ = ("instance_id", "host", "port", "transport_security", "status", "version", "started_at", "heartbeat_at", "expires_at", "capabilities", "metadata")
    class MetadataEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    INSTANCE_ID_FIELD_NUMBER: _ClassVar[int]
    HOST_FIELD_NUMBER: _ClassVar[int]
    PORT_FIELD_NUMBER: _ClassVar[int]
    TRANSPORT_SECURITY_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    STARTED_AT_FIELD_NUMBER: _ClassVar[int]
    HEARTBEAT_AT_FIELD_NUMBER: _ClassVar[int]
    EXPIRES_AT_FIELD_NUMBER: _ClassVar[int]
    CAPABILITIES_FIELD_NUMBER: _ClassVar[int]
    METADATA_FIELD_NUMBER: _ClassVar[int]
    instance_id: str
    host: str
    port: int
    transport_security: str
    status: ServiceInstanceStatus
    version: str
    started_at: _timestamp_pb2.Timestamp
    heartbeat_at: _timestamp_pb2.Timestamp
    expires_at: _timestamp_pb2.Timestamp
    capabilities: _containers.RepeatedScalarFieldContainer[str]
    metadata: _containers.ScalarMap[str, str]
    def __init__(self, instance_id: _Optional[str] = ..., host: _Optional[str] = ..., port: _Optional[int] = ..., transport_security: _Optional[str] = ..., status: _Optional[_Union[ServiceInstanceStatus, str]] = ..., version: _Optional[str] = ..., started_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., heartbeat_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., expires_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., capabilities: _Optional[_Iterable[str]] = ..., metadata: _Optional[_Mapping[str, str]] = ...) -> None: ...

class ListServerInstancesResponse(_message.Message):
    __slots__ = ("instances",)
    INSTANCES_FIELD_NUMBER: _ClassVar[int]
    instances: _containers.RepeatedCompositeFieldContainer[ServerInstance]
    def __init__(self, instances: _Optional[_Iterable[_Union[ServerInstance, _Mapping]]] = ...) -> None: ...

class StartBacktestRequest(_message.Message):
    __slots__ = ("request_id", "name", "instrument", "strategy", "start_at", "end_at", "data_source", "broker_provider")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    INSTRUMENT_FIELD_NUMBER: _ClassVar[int]
    STRATEGY_FIELD_NUMBER: _ClassVar[int]
    START_AT_FIELD_NUMBER: _ClassVar[int]
    END_AT_FIELD_NUMBER: _ClassVar[int]
    DATA_SOURCE_FIELD_NUMBER: _ClassVar[int]
    BROKER_PROVIDER_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    name: str
    instrument: CurrencyPair
    strategy: StrategyReference
    start_at: _timestamp_pb2.Timestamp
    end_at: _timestamp_pb2.Timestamp
    data_source: DataSourceReference
    broker_provider: ProviderReference
    def __init__(self, request_id: _Optional[str] = ..., name: _Optional[str] = ..., instrument: _Optional[_Union[CurrencyPair, _Mapping]] = ..., strategy: _Optional[_Union[StrategyReference, _Mapping]] = ..., start_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., end_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., data_source: _Optional[_Union[DataSourceReference, _Mapping]] = ..., broker_provider: _Optional[_Union[ProviderReference, _Mapping]] = ...) -> None: ...

class StartTradingRequest(_message.Message):
    __slots__ = ("request_id", "name", "instrument", "strategy", "account", "provider", "dry_run")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    INSTRUMENT_FIELD_NUMBER: _ClassVar[int]
    STRATEGY_FIELD_NUMBER: _ClassVar[int]
    ACCOUNT_FIELD_NUMBER: _ClassVar[int]
    PROVIDER_FIELD_NUMBER: _ClassVar[int]
    DRY_RUN_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    name: str
    instrument: CurrencyPair
    strategy: StrategyReference
    account: AccountReference
    provider: ProviderReference
    dry_run: bool
    def __init__(self, request_id: _Optional[str] = ..., name: _Optional[str] = ..., instrument: _Optional[_Union[CurrencyPair, _Mapping]] = ..., strategy: _Optional[_Union[StrategyReference, _Mapping]] = ..., account: _Optional[_Union[AccountReference, _Mapping]] = ..., provider: _Optional[_Union[ProviderReference, _Mapping]] = ..., dry_run: _Optional[bool] = ...) -> None: ...

class GetTaskRequest(_message.Message):
    __slots__ = ("task_id",)
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    task_id: str
    def __init__(self, task_id: _Optional[str] = ...) -> None: ...

class ListTasksRequest(_message.Message):
    __slots__ = ("filter_by_status", "status")
    FILTER_BY_STATUS_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    filter_by_status: bool
    status: TaskStatus
    def __init__(self, filter_by_status: _Optional[bool] = ..., status: _Optional[_Union[TaskStatus, str]] = ...) -> None: ...

class PauseTaskRequest(_message.Message):
    __slots__ = ("task_id",)
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    task_id: str
    def __init__(self, task_id: _Optional[str] = ...) -> None: ...

class StopTaskRequest(_message.Message):
    __slots__ = ("task_id",)
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    task_id: str
    def __init__(self, task_id: _Optional[str] = ...) -> None: ...

class ResumeTaskRequest(_message.Message):
    __slots__ = ("task_id",)
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    task_id: str
    def __init__(self, task_id: _Optional[str] = ...) -> None: ...

class RestartTaskRequest(_message.Message):
    __slots__ = ("task_id",)
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    task_id: str
    def __init__(self, task_id: _Optional[str] = ...) -> None: ...

class RecoverTaskRequest(_message.Message):
    __slots__ = ("task_id",)
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    task_id: str
    def __init__(self, task_id: _Optional[str] = ...) -> None: ...

class TaskResponse(_message.Message):
    __slots__ = ("task",)
    TASK_FIELD_NUMBER: _ClassVar[int]
    task: Task
    def __init__(self, task: _Optional[_Union[Task, _Mapping]] = ...) -> None: ...

class ListTasksResponse(_message.Message):
    __slots__ = ("tasks",)
    TASKS_FIELD_NUMBER: _ClassVar[int]
    tasks: _containers.RepeatedCompositeFieldContainer[Task]
    def __init__(self, tasks: _Optional[_Iterable[_Union[Task, _Mapping]]] = ...) -> None: ...
