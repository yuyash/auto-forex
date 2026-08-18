"""Runtime registry for active task executions."""

from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import Future
from dataclasses import dataclass
from threading import RLock
from typing import Literal
from uuid import UUID

from autoforex.core.clock import Clock
from autoforex.core.ports.brokers import Broker
from autoforex.core.sources.base import DataSource
from autoforex.core.strategies.base import Strategy
from autoforex.core.tasks.execution import ExecutableTask
from autoforex.core.tasks.profiling import TaskProfiler
from autoforex.core.tasks.runner import TaskExecutionControl
from autoforex.core.tasks.state import TaskStatus

type Task = ExecutableTask
RunnerType = Literal["backtest", "trading"]


@dataclass(frozen=True, slots=True)
class TaskRuntime:
    """Runtime dependencies and state for a managed task."""

    type: RunnerType
    data_source: DataSource
    strategy: Strategy
    broker: Broker | None
    clock: Clock
    control: TaskExecutionControl
    profiler: TaskProfiler
    future: Future[Task]


class TaskRuntimeRegistry:
    """Thread-safe registry of active task runtimes."""

    def __init__(self) -> None:
        self._runtimes: dict[UUID, TaskRuntime] = {}
        self._lock = RLock()

    def get(self, task_id: UUID) -> TaskRuntime:
        """Return a runtime by task id."""
        with self._lock:
            return self._runtimes[task_id]

    def save(self, task_id: UUID, runtime: TaskRuntime) -> None:
        """Store a runtime for a task."""
        with self._lock:
            self._runtimes[task_id] = runtime

    def current(self, task_id: UUID) -> TaskRuntime | None:
        """Return the current runtime for a task when present."""
        with self._lock:
            return self._runtimes.get(task_id)

    def values(self) -> tuple[TaskRuntime, ...]:
        """Return a snapshot of runtimes."""
        with self._lock:
            return tuple(self._runtimes.values())

    def items(self) -> tuple[tuple[UUID, TaskRuntime], ...]:
        """Return a snapshot of task ids and runtimes."""
        with self._lock:
            return tuple(self._runtimes.items())

    def active_strategy_task_id(
        self,
        strategy: Strategy,
        *,
        exclude_task_id: UUID,
        active_tasks: Iterable[Task],
    ) -> UUID | None:
        """Return the active task using a strategy instance, if any."""
        active_by_id = {task.id: task for task in active_tasks}
        with self._lock:
            for task_id, runtime in self._runtimes.items():
                if task_id == exclude_task_id:
                    continue
                if runtime.strategy is not strategy or runtime.future.done():
                    continue
                task = active_by_id.get(task_id)
                if task is not None and self.is_active_task(task):
                    return task_id
        return None

    @staticmethod
    def is_active_task(task: Task) -> bool:
        """Return whether a task is in an active lifecycle state."""
        return task.status in {TaskStatus.STARTING, TaskStatus.RUNNING, TaskStatus.PAUSED}
