"""Observer hooks for task runners."""

from __future__ import annotations

from typing import Protocol

from autoforex.core.sources.models import Tick
from autoforex.core.tasks.execution import ExecutableTask

type Task = ExecutableTask


class TaskObserver(Protocol):
    """Observer that can inspect market-data driven task execution."""

    def on_tick(self, task: Task, tick: Tick) -> None:
        """Observe a tick after strategy execution for that tick."""

    def on_task_finished(self, task: Task) -> None:
        """Observe a task after it reaches a terminal state."""
