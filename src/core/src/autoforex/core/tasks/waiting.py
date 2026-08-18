"""Task wait and progress reporting services."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import datetime
from time import perf_counter
from uuid import UUID

from autoforex.core.tasks.execution import ExecutableTask
from autoforex.core.tasks.progress import TaskProgress, TaskProgressReporter
from autoforex.core.tasks.registry import TaskRegistry
from autoforex.core.tasks.runtime import TaskRuntime

type Task = ExecutableTask
type ProgressSnapshot = Callable[[UUID], TaskProgress]


class TaskWaiter:
    """Wait for task futures and optionally report progress."""

    def __init__(self, *, registry: TaskRegistry, progress_snapshot: ProgressSnapshot) -> None:
        self.registry = registry
        self.progress_snapshot = progress_snapshot

    def wait(
        self,
        task_id: UUID,
        *,
        runtime: TaskRuntime,
        timeout: float | None,
        progress: TaskProgressReporter | None,
        refresh_seconds: float,
    ) -> Task:
        """Wait for the current runner to finish and return the latest task."""
        if progress is None:
            runtime.future.result(timeout=timeout)
            return self.registry.get(task_id)
        return self._wait_with_progress(
            task_id,
            runtime=runtime,
            timeout=timeout,
            progress=progress,
            refresh_seconds=refresh_seconds,
        )

    def _wait_with_progress(
        self,
        task_id: UUID,
        *,
        runtime: TaskRuntime,
        timeout: float | None,
        progress: TaskProgressReporter,
        refresh_seconds: float,
    ) -> Task:
        if refresh_seconds <= 0:
            msg = "refresh_seconds must be greater than zero"
            raise ValueError(msg)

        deadline = None if timeout is None else perf_counter() + timeout
        finished = False
        progress.on_start(self.progress_snapshot(task_id))
        try:
            while True:
                if runtime.future.done():
                    runtime.future.result(timeout=0)
                    task = self.registry.get(task_id)
                    progress.on_finish(self.progress_snapshot(task_id))
                    finished = True
                    return task

                poll_seconds = self._poll_seconds(
                    deadline=deadline,
                    refresh_seconds=refresh_seconds,
                )
                try:
                    runtime.future.result(timeout=poll_seconds)
                except FutureTimeoutError:
                    progress.on_update(self.progress_snapshot(task_id))
                    continue

                task = self.registry.get(task_id)
                progress.on_finish(self.progress_snapshot(task_id))
                finished = True
                return task
        finally:
            if not finished:
                progress.close()

    @staticmethod
    def _poll_seconds(*, deadline: float | None, refresh_seconds: float) -> float:
        if deadline is None:
            return refresh_seconds
        remaining_seconds = deadline - perf_counter()
        if remaining_seconds <= 0:
            raise FutureTimeoutError()
        return min(refresh_seconds, remaining_seconds)


class BacktestProgressCalculator:
    """Build progress snapshots for finite backtest periods."""

    @staticmethod
    def completed_seconds(*, start_at: datetime, end_at: datetime, current_at: datetime) -> float:
        """Return elapsed backtest seconds clamped to the task period."""
        total_seconds = (end_at - start_at).total_seconds()
        elapsed_seconds = (current_at - start_at).total_seconds()
        return max(0.0, min(total_seconds, elapsed_seconds))
