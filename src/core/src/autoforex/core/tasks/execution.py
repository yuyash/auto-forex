"""Executable task instances."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, fields
from datetime import datetime
from logging import Logger
from typing import Self
from uuid import UUID

from pydantic import AwareDatetime, Field

from autoforex.core.clock import Clock, now
from autoforex.core.logging import get_logger
from autoforex.core.models.base import DomainModel
from autoforex.core.models.identifiers import new_uuid
from autoforex.core.models.money import CurrencyPair
from autoforex.core.strategies.models import StrategyParameters, StrategyState
from autoforex.core.tasks.definitions import TaskDefinition, TaskType
from autoforex.core.tasks.failure import TaskFailure
from autoforex.core.tasks.state import (
    DEFAULT_TASK_STATE_MACHINE,
    TaskAction,
    TaskStateError,
    TaskStatus,
)

_LOGGER: Logger = get_logger(__name__)


@dataclass(frozen=True)
class TaskLogContext(Mapping[str, "str | int | bool | None"]):
    """Structured logging context for an executable task lifecycle event.

    Implements the mapping protocol so it can be passed straight to the
    standard logging ``extra`` argument while remaining a typed object.
    """

    task_id: str
    task_definition_id: str
    task_name: str
    task_type: str
    task_action: str
    task_status: str
    task_run_count: int
    instrument: str
    task_previous_status: str
    failure_reason: str = ""
    lifecycle_timestamp: str = ""
    transition_allowed: bool | None = None
    is_resume: bool | None = None

    def __getitem__(self, key: str) -> str | int | bool | None:
        try:
            return getattr(self, key)
        except AttributeError as exc:
            raise KeyError(key) from exc

    def __iter__(self) -> Iterator[str]:
        return (field.name for field in fields(self))

    def __len__(self) -> int:
        return len(fields(self))


class ExecutableTask(DomainModel):
    """Runtime execution state for a task definition."""

    id: UUID = Field(default_factory=new_uuid)
    definition: TaskDefinition
    status: TaskStatus = TaskStatus.CREATED
    created_at: AwareDatetime = Field(default_factory=now)
    started_at: AwareDatetime | None = None
    paused_at: AwareDatetime | None = None
    stopped_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    last_processed_at: AwareDatetime | None = None
    failure: TaskFailure | None = None
    run_count: int = Field(default=0, ge=0)
    strategy_state: StrategyState = Field(default_factory=StrategyState)

    @classmethod
    def from_definition(
        cls,
        definition: TaskDefinition,
        *,
        task_id: UUID | None = None,
        clock: Clock | None = None,
    ) -> ExecutableTask:
        """Create a new executable task from a task definition."""
        task = cls(
            id=task_id or new_uuid(),
            definition=definition,
            created_at=now(clock),
        )
        _LOGGER.debug(
            "Created executable task %s",
            task.id,
            extra=task._log_extra(task_action="create"),
        )
        return task

    @property
    def definition_id(self) -> UUID:
        """Return the immutable task definition id."""
        return self.definition.id

    @property
    def task_type(self) -> TaskType:
        """Return this task's executable type."""
        return self.definition.task_type

    @property
    def name(self) -> str:
        """Return the task definition name."""
        return self.definition.name

    @property
    def instrument(self) -> CurrencyPair:
        """Return the traded instrument."""
        return self.definition.instrument

    @property
    def parameters(self) -> StrategyParameters:
        """Return strategy parameters."""
        return self.definition.parameters

    @property
    def is_running(self) -> bool:
        """Return whether the task is actively running."""
        return self.status == TaskStatus.RUNNING

    @property
    def is_paused(self) -> bool:
        """Return whether the task is paused."""
        return self.status == TaskStatus.PAUSED

    @property
    def is_terminal(self) -> bool:
        """Return whether the task has reached a terminal state."""
        return self.status in {TaskStatus.STOPPED, TaskStatus.COMPLETED, TaskStatus.FAILED}

    def can(self, action: TaskAction) -> bool:
        """Return whether the lifecycle action is valid for the current status."""
        allowed = DEFAULT_TASK_STATE_MACHINE.can(self.status, action)
        _LOGGER.debug(
            "Checked executable task action permission",
            extra=self._log_extra(
                task_action=action.value,
                transition_allowed=allowed,
            ),
        )
        return allowed

    def start(self, *, at: datetime | None = None, clock: Clock | None = None) -> Self:
        """Start a new task run or resume a paused task."""
        timestamp = at or now(clock)
        is_resume = self.status == TaskStatus.PAUSED
        _LOGGER.debug(
            "Starting executable task %s",
            self.id,
            extra=self._log_extra(
                task_action=TaskAction.START.value,
                lifecycle_timestamp=timestamp.isoformat(),
                is_resume=is_resume,
            ),
        )
        task = self.evolve(
            status=self._next_status(TaskAction.START),
            started_at=self.started_at if is_resume else timestamp,
            paused_at=None,
            stopped_at=None,
            completed_at=None,
            failure=None,
            run_count=self.run_count if is_resume else self.run_count + 1,
        )
        self._log_transition(TaskAction.START, task)
        return task

    def pause(self, *, at: datetime | None = None, clock: Clock | None = None) -> Self:
        """Pause a running task without discarding its runtime state."""
        timestamp = at or now(clock)
        _LOGGER.debug(
            "Pausing executable task %s",
            self.id,
            extra=self._log_extra(
                task_action=TaskAction.PAUSE.value,
                lifecycle_timestamp=timestamp.isoformat(),
            ),
        )
        task = self.evolve(
            status=self._next_status(TaskAction.PAUSE),
            paused_at=timestamp,
        )
        self._log_transition(TaskAction.PAUSE, task)
        return task

    def stop(self, *, at: datetime | None = None, clock: Clock | None = None) -> Self:
        """Stop a running or paused task."""
        timestamp = at or now(clock)
        _LOGGER.debug(
            "Stopping executable task %s",
            self.id,
            extra=self._log_extra(
                task_action=TaskAction.STOP.value,
                lifecycle_timestamp=timestamp.isoformat(),
            ),
        )
        task = self.evolve(
            status=self._next_status(TaskAction.STOP),
            paused_at=None,
            stopped_at=timestamp,
        )
        self._log_transition(TaskAction.STOP, task)
        return task

    def restart(self, *, at: datetime | None = None, clock: Clock | None = None) -> Self:
        """Start the task again as a fresh run."""
        timestamp = at or now(clock)
        _LOGGER.debug(
            "Restarting executable task %s",
            self.id,
            extra=self._log_extra(
                task_action=TaskAction.RESTART.value,
                lifecycle_timestamp=timestamp.isoformat(),
            ),
        )
        task = self.evolve(
            status=self._next_status(TaskAction.RESTART),
            started_at=timestamp,
            paused_at=None,
            stopped_at=None,
            completed_at=None,
            last_processed_at=None,
            failure=None,
            run_count=self.run_count + 1,
            strategy_state=StrategyState(),
        )
        self._log_transition(TaskAction.RESTART, task)
        return task

    def recover(self, *, at: datetime | None = None, clock: Clock | None = None) -> Self:
        """Recover an interrupted run without resetting its durable checkpoint."""
        if self.status not in {TaskStatus.STOPPED, TaskStatus.FAILED}:
            msg = f"cannot recover task {self.id} while status is {self.status.value}"
            raise TaskStateError(msg)
        timestamp = at or now(clock)
        task = self.evolve(
            status=TaskStatus.RUNNING,
            started_at=self.started_at or timestamp,
            paused_at=None,
            stopped_at=None,
            completed_at=None,
            failure=None,
            run_count=max(self.run_count, 1),
        )
        _LOGGER.info(
            "Recovered interrupted task %s",
            self.id,
            extra=task._log_extra(
                task_action="recover",
                task_previous_status=self.status.value,
                lifecycle_timestamp=timestamp.isoformat(),
            ),
        )
        return task

    def with_strategy_state(self, state: StrategyState) -> Self:
        """Return a task snapshot carrying the latest strategy state."""
        if state == self.strategy_state:
            return self
        return self.evolve(strategy_state=state)

    def with_last_processed_at(self, timestamp: datetime) -> Self:
        """Return a task snapshot checkpointed after processing one market tick."""
        if self.last_processed_at == timestamp:
            return self
        return self.evolve(last_processed_at=timestamp)

    def complete(self, *, at: datetime | None = None, clock: Clock | None = None) -> Self:
        """Mark a running task as completed."""
        timestamp = at or now(clock)
        _LOGGER.debug(
            "Completing executable task %s",
            self.id,
            extra=self._log_extra(
                task_action=TaskAction.COMPLETE.value,
                lifecycle_timestamp=timestamp.isoformat(),
            ),
        )
        task = self.evolve(
            status=self._next_status(TaskAction.COMPLETE),
            paused_at=None,
            completed_at=timestamp,
        )
        self._log_transition(TaskAction.COMPLETE, task)
        return task

    def fail(
        self,
        reason: str | TaskFailure | BaseException,
        *,
        at: datetime | None = None,
        clock: Clock | None = None,
    ) -> Self:
        """Mark the task as failed.

        ``reason`` may be a plain message, a prebuilt :class:`TaskFailure`, or an
        exception (whose type and traceback are captured).
        """
        timestamp = at or now(clock)
        failure = self._coerce_failure(reason, occurred_at=timestamp)
        _LOGGER.debug(
            "Failing executable task %s",
            self.id,
            extra=self._log_extra(
                task_action=TaskAction.FAIL.value,
                lifecycle_timestamp=timestamp.isoformat(),
                failure_reason=failure.message,
            ),
        )
        task = self.evolve(
            status=self._next_status(TaskAction.FAIL),
            paused_at=None,
            stopped_at=timestamp,
            failure=failure,
        )
        self._log_transition(TaskAction.FAIL, task, failure_reason=failure.message)
        return task

    @staticmethod
    def _coerce_failure(
        reason: str | TaskFailure | BaseException,
        *,
        occurred_at: datetime,
    ) -> TaskFailure:
        if isinstance(reason, TaskFailure):
            return reason
        if isinstance(reason, BaseException):
            return TaskFailure.from_exception(reason, occurred_at=occurred_at)
        return TaskFailure.of(reason, occurred_at=occurred_at)

    def _next_status(self, action: TaskAction) -> TaskStatus:
        _LOGGER.debug(
            "Resolving executable task next status",
            extra=self._log_extra(task_action=action.value),
        )
        return DEFAULT_TASK_STATE_MACHINE.transition(
            task_id=self.id,
            status=self.status,
            action=action,
        )

    def _log_transition(
        self,
        action: TaskAction,
        task: ExecutableTask,
        *,
        failure_reason: str = "",
    ) -> None:
        _LOGGER.log(
            self._level_for_action(action),
            "Task %s lifecycle action %s transitioned %s to %s",
            self.id,
            action.value,
            self.status.value,
            task.status.value,
            extra=task._log_extra(
                task_action=action.value,
                task_previous_status=self.status.value,
                failure_reason=failure_reason,
            ),
        )

    @staticmethod
    def _level_for_action(action: TaskAction) -> int:
        if action == TaskAction.FAIL:
            return logging.ERROR
        return logging.INFO

    def _log_extra(
        self,
        *,
        task_action: str,
        task_previous_status: str | None = None,
        failure_reason: str = "",
        lifecycle_timestamp: str = "",
        transition_allowed: bool | None = None,
        is_resume: bool | None = None,
    ) -> TaskLogContext:
        return TaskLogContext(
            task_id=str(self.id),
            task_definition_id=str(self.definition_id),
            task_name=self.name,
            task_type=self.task_type.value,
            task_action=task_action,
            task_previous_status=task_previous_status or self.status.value,
            task_status=self.status.value,
            task_run_count=self.run_count,
            instrument=str(self.instrument),
            failure_reason=failure_reason,
            lifecycle_timestamp=lifecycle_timestamp,
            transition_allowed=transition_allowed,
            is_resume=is_resume,
        )
