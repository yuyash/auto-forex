"""Task domain APIs."""

from autoforex.core.tasks.definitions import (
    BacktestTaskDefinition,
    BaseTaskDefinition,
    TaskDefinition,
    TaskType,
    TradingTaskDefinition,
)
from autoforex.core.tasks.execution import ExecutableTask
from autoforex.core.tasks.failure import TaskFailure
from autoforex.core.tasks.observers import TaskObserver
from autoforex.core.tasks.profiling import TaskProfile, TaskProfiler, TaskProfilingConfig
from autoforex.core.tasks.progress import TaskProgress, TaskProgressReporter, TqdmProgressReporter
from autoforex.core.tasks.registry import (
    InMemoryTaskRegistry,
    TaskNotFoundError,
    TaskRegistry,
)
from autoforex.core.tasks.state import (
    ALLOWED_TRANSITIONS,
    DEFAULT_TASK_STATE_MACHINE,
    TaskAction,
    TaskStateError,
    TaskStateMachine,
    TaskStatus,
    TaskTransition,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "DEFAULT_TASK_STATE_MACHINE",
    "BacktestTaskDefinition",
    "BaseTaskDefinition",
    "ExecutableTask",
    "InMemoryTaskRegistry",
    "TaskAction",
    "TaskDefinition",
    "TaskFailure",
    "TaskNotFoundError",
    "TaskObserver",
    "TaskProfile",
    "TaskProfiler",
    "TaskProfilingConfig",
    "TaskProgress",
    "TaskProgressReporter",
    "TaskRegistry",
    "TaskStateError",
    "TaskStateMachine",
    "TaskStatus",
    "TaskTransition",
    "TaskType",
    "TqdmProgressReporter",
    "TradingTaskDefinition",
]
