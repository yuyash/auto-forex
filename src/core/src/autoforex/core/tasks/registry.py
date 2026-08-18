"""Task registries used by local task managers and runners."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from threading import RLock
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from autoforex.core.tasks.context import ContextStore
from autoforex.core.tasks.execution import ExecutableTask
from autoforex.core.tasks.state import TaskStatus

if TYPE_CHECKING:
    from autoforex.core.strategies.base import StrategyContext
    from autoforex.core.strategies.execution import StrategyExecutionResponse

type Task = ExecutableTask


class TaskNotFoundError(KeyError):
    """Raised when a task does not exist in the registry."""


class TaskRegistry(Protocol):
    """Storage boundary for task records and lifecycle state."""

    def save(self, task: Task) -> Task:
        """Persist and return a task."""

    def get(self, task_id: UUID) -> Task:
        """Return a task by id."""

    def list(self, *, status: TaskStatus | None = None) -> Sequence[Task]:
        """Return tasks, optionally filtered by status."""

    def initialize_context(self, task: Task, *, strategy_name: str) -> StrategyContext:
        """Return the context for the current task run."""

    def current_context(self, task_id: UUID) -> StrategyContext:
        """Return the current runtime context for a task."""

    def stage_context(self, context: StrategyContext) -> StrategyContext:
        """Replace the in-memory task context."""

    def save_context(self, context: StrategyContext) -> Task:
        """Store context and persist changed strategy state."""

    def apply_execution_response(self, response: StrategyExecutionResponse) -> None:
        """Apply an execution response to registry-owned runtime context."""


class InMemoryTaskRegistry:
    """Thread-safe in-memory task registry for local execution and tests."""

    def __init__(self, tasks: Iterable[Task] = ()) -> None:
        self._tasks: dict[UUID, Task] = {}
        self._lock = RLock()
        for task in tasks:
            self._tasks[task.id] = task
        self._context_store = ContextStore(
            task_getter=self.get,
            task_saver=self.save,
        )

    def save(self, task: Task) -> Task:
        """Persist and return a task."""
        with self._lock:
            self._tasks[task.id] = task
            return task

    def get(self, task_id: UUID) -> Task:
        """Return a task by id."""
        with self._lock:
            try:
                return self._tasks[task_id]
            except KeyError as exc:
                msg = f"task not found: {task_id}"
                raise TaskNotFoundError(msg) from exc

    def list(self, *, status: TaskStatus | None = None) -> Sequence[Task]:
        """Return tasks, optionally filtered by status."""
        with self._lock:
            tasks = tuple(self._tasks.values())
        if status is None:
            return tasks
        return tuple(task for task in tasks if task.status == status)

    def initialize_context(self, task: Task, *, strategy_name: str) -> StrategyContext:
        """Return the context for the current task run."""
        return self._context_store.initialize(task, strategy_name=strategy_name)

    def current_context(self, task_id: UUID) -> StrategyContext:
        """Return the current runtime context for a task."""
        return self._context_store.current(task_id)

    def stage_context(self, context: StrategyContext) -> StrategyContext:
        """Replace the in-memory task context."""
        return self._context_store.stage(context)

    def save_context(self, context: StrategyContext) -> Task:
        """Store context and persist changed strategy state."""
        return self._context_store.save(context)

    def apply_execution_response(self, response: StrategyExecutionResponse) -> None:
        """Apply an execution response to registry-owned runtime context."""
        self._context_store.apply_execution_response(response)
