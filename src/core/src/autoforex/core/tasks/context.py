"""Hierarchical runtime context storage for task execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from typing import TYPE_CHECKING
from uuid import UUID

from autoforex.core.models.metadata import Metadata
from autoforex.core.tasks.accounting import AccountBalance
from autoforex.core.tasks.execution import ExecutableTask

if TYPE_CHECKING:
    from autoforex.core.strategies.base import StrategyContext
    from autoforex.core.strategies.execution import StrategyExecutionResponse

type Task = ExecutableTask
type TaskGetter = Callable[[UUID], Task]
type TaskSaver = Callable[[Task], Task]


class TaskContextNotInitializedError(RuntimeError):
    """Raised when runtime context is requested before task initialization."""


@dataclass(frozen=True, slots=True)
class TaskContextEntry:
    """One task context associated with a specific execution run."""

    context: StrategyContext
    run_count: int


class ContextStore:
    """Own runtime contexts, including account balance, beneath a task registry."""

    def __init__(
        self,
        *,
        task_getter: TaskGetter,
        task_saver: TaskSaver,
        account_balance: AccountBalance | None = None,
    ) -> None:
        self._task_getter = task_getter
        self._task_saver = task_saver
        self.account_balance = account_balance or AccountBalance()
        self._entries: dict[UUID, TaskContextEntry] = {}
        self._lock = RLock()

    def initialize(self, task: Task, *, strategy_name: str) -> StrategyContext:
        """Return the context for the current task run, creating it when needed."""
        from autoforex.core.strategies.base import StrategyContext

        with self._lock:
            entry = self._entries.get(task.id)
            if entry is not None and entry.run_count == task.run_count:
                context = entry.context
                if context.state != task.strategy_state:
                    context = context.with_state(task.strategy_state)
                    self._entries[task.id] = TaskContextEntry(
                        context=context,
                        run_count=task.run_count,
                    )
                return context

            self.account_balance.reset(task.id)
            context = StrategyContext(
                task_id=task.id,
                task_type=task.task_type,
                instrument=task.instrument,
                account_balance=self.account_balance.initial(task),
                state=task.strategy_state,
                metadata=Metadata.of(strategy_name=strategy_name),
            )
            self._entries[task.id] = TaskContextEntry(
                context=context,
                run_count=task.run_count,
            )
            return context

    def current(self, task_id: UUID) -> StrategyContext:
        """Return the current runtime context for a task."""
        with self._lock:
            entry = self._entries.get(task_id)
            if entry is None:
                msg = f"task context is not initialized: {task_id}"
                raise TaskContextNotInitializedError(msg)
            return entry.context

    def stage(self, context: StrategyContext) -> StrategyContext:
        """Replace the in-memory context without persisting task state."""
        with self._lock:
            entry = self._entries.get(context.task_id)
            if entry is None:
                msg = f"task context is not initialized: {context.task_id}"
                raise TaskContextNotInitializedError(msg)
            self._entries[context.task_id] = TaskContextEntry(
                context=context,
                run_count=entry.run_count,
            )
        return context

    def save(self, context: StrategyContext) -> Task:
        """Store the current context and persist changed strategy state."""
        self.stage(context)
        task = self._task_getter(context.task_id)
        if task.strategy_state == context.state:
            return task
        return self._task_saver(task.with_strategy_state(context.state))

    def apply_execution_response(self, response: StrategyExecutionResponse) -> None:
        """Apply one execution response to its stored task context."""
        task_id = response.event.task_id
        with self._lock:
            entry = self._entries.get(task_id)
            if entry is None:
                msg = f"task context is not initialized: {task_id}"
                raise TaskContextNotInitializedError(msg)
            balance = self.account_balance.apply(entry.context.account_balance, response)
            context = entry.context
            if balance != context.account_balance:
                context = context.with_account_balance(balance)
            self._entries[task_id] = TaskContextEntry(
                context=context,
                run_count=entry.run_count,
            )
