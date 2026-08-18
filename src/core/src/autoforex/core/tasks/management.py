"""Task management services used by the TaskManager facade."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from autoforex.core.clock import Clock
from autoforex.core.events.bus import EventBus
from autoforex.core.events.event import Event
from autoforex.core.events.types import EventSource, EventType
from autoforex.core.models.metadata import Metadata
from autoforex.core.ports.brokers import Broker
from autoforex.core.sources.base import DataSource
from autoforex.core.strategies.base import Strategy
from autoforex.core.tasks.definitions import BacktestTaskDefinition
from autoforex.core.tasks.execution import ExecutableTask
from autoforex.core.tasks.launching import TaskLauncher
from autoforex.core.tasks.profiling import TaskProfilingConfig
from autoforex.core.tasks.progress import TaskProgress
from autoforex.core.tasks.registry import TaskRegistry
from autoforex.core.tasks.runtime import RunnerType, TaskRuntimeRegistry
from autoforex.core.tasks.state import TaskAction, TaskStatus
from autoforex.core.tasks.waiting import BacktestProgressCalculator

type Task = ExecutableTask


class TaskAlreadyRunningError(RuntimeError):
    """Raised when a task already has an active runner."""


class StrategyAlreadyRunningError(RuntimeError):
    """Raised when one strategy instance is assigned to multiple active tasks."""


class TaskEventPublisher:
    """Publish task lifecycle events to the event bus."""

    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus

    def publish(
        self,
        event_type: EventType,
        task: Task,
        *,
        clock: Clock,
    ) -> None:
        """Publish a task lifecycle event."""
        self.event_bus.publish(
            Event(
                type=event_type,
                timestamp=clock.now(),
                task_id=task.id,
                source=EventSource.CORE,
                metadata=Metadata.of(
                    task_status=task.status.value,
                    task_type=task.task_type.value,
                ),
            )
        )


class TaskControlService:
    """Apply external control requests to active task runtimes."""

    def __init__(
        self,
        *,
        registry: TaskRegistry,
        runtimes: TaskRuntimeRegistry,
        events: TaskEventPublisher,
    ) -> None:
        self.registry = registry
        self.runtimes = runtimes
        self.events = events

    def pause(self, task_id: UUID) -> Task:
        """Request a graceful task pause."""
        runtime = self.runtimes.get(task_id)
        runtime.control.request_pause()
        task = self.registry.get(task_id)
        if task.can(TaskAction.PAUSE):
            paused = self.registry.save(task.pause(clock=runtime.clock))
            self.events.publish(EventType.TASK_PAUSED, paused, clock=runtime.clock)
            return paused
        return task

    def stop(self, task_id: UUID) -> Task:
        """Request a graceful task stop."""
        runtime = self.runtimes.get(task_id)
        runtime.control.request_stop()
        task = self.registry.get(task_id)
        if task.can(TaskAction.STOP):
            stopped = self.registry.save(task.stop(clock=runtime.clock))
            self.events.publish(EventType.TASK_STOPPED, stopped, clock=runtime.clock)
            return stopped
        return task


class TaskLaunchService:
    """Validate and launch task runtimes."""

    def __init__(
        self,
        *,
        registry: TaskRegistry,
        runtimes: TaskRuntimeRegistry,
        launcher: TaskLauncher,
    ) -> None:
        self.registry = registry
        self.runtimes = runtimes
        self.launcher = launcher

    def launch(
        self,
        task: Task,
        *,
        type: RunnerType,
        data_source: DataSource,
        strategy: Strategy,
        broker: Broker | None,
        clock: Clock,
        profiling: TaskProfilingConfig | None = None,
        recovering: bool = False,
    ) -> None:
        """Launch a task after validating active runtime constraints."""
        self._ensure_task_has_no_active_runner(task)
        self._ensure_strategy_has_no_active_runner(strategy, task=task)
        runtime = self.launcher.launch(
            task,
            type=type,
            data_source=data_source,
            strategy=strategy,
            broker=broker,
            clock=clock,
            profiling=profiling,
            recovering=recovering,
        )
        self.runtimes.save(task.id, runtime)

    def _ensure_task_has_no_active_runner(self, task: Task) -> None:
        current = self.runtimes.current(task.id)
        if current is None or current.future.done():
            return
        current_task = self.registry.get(task.id)
        if self.runtimes.is_active_task(current_task):
            msg = f"task already has an active runner: {task.id}"
            raise TaskAlreadyRunningError(msg)

    def _ensure_strategy_has_no_active_runner(self, strategy: Strategy, *, task: Task) -> None:
        active_strategy_task_id = self.runtimes.active_strategy_task_id(
            strategy,
            exclude_task_id=task.id,
            active_tasks=self.active_task_snapshots(),
        )
        if active_strategy_task_id is None:
            return
        msg = (
            "strategy instance already has an active runner: "
            f"{strategy.name} for task {active_strategy_task_id}"
        )
        raise StrategyAlreadyRunningError(msg)

    def active_task_snapshots(self) -> tuple[Task, ...]:
        """Return latest task snapshots for active runtimes."""
        snapshots: list[Task] = []
        for task_id, runtime in self.runtimes.items():
            if runtime.future.done():
                continue
            try:
                snapshots.append(self.registry.get(task_id))
            except Exception:
                continue
        return tuple(snapshots)


class TaskProgressService:
    """Create progress snapshots for active task runtimes."""

    def __init__(
        self,
        *,
        registry: TaskRegistry,
        runtimes: TaskRuntimeRegistry,
    ) -> None:
        self.registry = registry
        self.runtimes = runtimes

    def progress(self, task_id: UUID) -> TaskProgress:
        """Return a point-in-time progress snapshot for a task run."""
        runtime = self.runtimes.get(task_id)
        task = self.registry.get(task_id)
        current_at = runtime.clock.now()
        if isinstance(task.definition, BacktestTaskDefinition):
            return self._backtest_progress(task, current_at=current_at)
        return TaskProgress(
            task_id=task.id,
            task_name=task.name,
            status=task.status,
            current_at=current_at,
            start_at=task.started_at,
            end_at=None,
            completed_units=None,
            total_units=None,
            unit="tick",
        )

    @classmethod
    def _backtest_progress(cls, task: Task, *, current_at: datetime) -> TaskProgress:
        if not isinstance(task.definition, BacktestTaskDefinition):
            msg = "backtest progress requires BacktestTaskDefinition"
            raise TypeError(msg)
        definition = task.definition
        if task.status == TaskStatus.COMPLETED:
            current_at = definition.end_at
        total_seconds = (definition.end_at - definition.start_at).total_seconds()
        completed_seconds = BacktestProgressCalculator.completed_seconds(
            start_at=definition.start_at,
            end_at=definition.end_at,
            current_at=current_at,
        )
        return TaskProgress(
            task_id=task.id,
            task_name=task.name,
            status=task.status,
            current_at=current_at,
            start_at=definition.start_at,
            end_at=definition.end_at,
            completed_units=completed_seconds,
            total_units=total_seconds,
            unit="s",
        )
