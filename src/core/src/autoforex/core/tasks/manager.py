"""Task manager facade for starting and controlling local task executions."""

from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import timedelta
from types import TracebackType
from typing import Self
from uuid import UUID

from autoforex.core.clock import Clock
from autoforex.core.events.bus import EventBus, EventHandler
from autoforex.core.ports.brokers import Broker
from autoforex.core.sources.base import DataSource
from autoforex.core.strategies.base import Strategy
from autoforex.core.tasks.definitions import BacktestTaskDefinition, TradingTaskDefinition
from autoforex.core.tasks.execution import ExecutableTask
from autoforex.core.tasks.launching import TaskLauncher, TaskRunnerFactory
from autoforex.core.tasks.management import (
    TaskControlService,
    TaskEventPublisher,
    TaskLaunchService,
    TaskProgressService,
)
from autoforex.core.tasks.monitors import StrategyRequestTimeoutMonitor
from autoforex.core.tasks.observers import TaskObserver
from autoforex.core.tasks.profiling import TaskProfile, TaskProfilingConfig
from autoforex.core.tasks.progress import TaskProgress, TaskProgressReporter
from autoforex.core.tasks.registry import InMemoryTaskRegistry, TaskRegistry
from autoforex.core.tasks.runtime import RunnerType, TaskRuntimeRegistry
from autoforex.core.tasks.state import TaskStatus
from autoforex.core.tasks.waiting import TaskWaiter

type Task = ExecutableTask


@dataclass(frozen=True, slots=True)
class TaskRun:
    """Handle for a started task execution."""

    task: Task
    _manager: TaskManager = field(repr=False, compare=False)

    @property
    def id(self) -> UUID:
        """Return the executable task id."""
        return self.task.id

    def current(self) -> Task:
        """Return the latest task snapshot."""
        return self._manager.get(self.id)

    def wait(
        self,
        *,
        timeout: float | None = None,
        progress: TaskProgressReporter | None = None,
        refresh_seconds: float = 0.5,
    ) -> Task:
        """Wait for the run to finish and return the final task snapshot."""
        return self._manager.wait(
            self.id,
            timeout=timeout,
            progress=progress,
            refresh_seconds=refresh_seconds,
        )

    def progress(self) -> TaskProgress:
        """Return the latest progress snapshot."""
        return self._manager.progress(self.id)

    def profile(self) -> TaskProfile:
        """Return the latest profiling snapshot."""
        return self._manager.profile(self.id)

    def pause(self) -> Task:
        """Request a graceful pause and return the latest task snapshot."""
        return self._manager.pause(self.id)

    def stop(self) -> Task:
        """Request a graceful stop and return the latest task snapshot."""
        return self._manager.stop(self.id)

    def restart(self, *, timeout: float | None = None) -> TaskRun:
        """Restart this task and return a handle for the restarted run."""
        task = self._manager.restart(self.id, timeout=timeout)
        return TaskRun(task=task, _manager=self._manager)


class TaskManager:
    """Start, stop, pause, restart, and inspect local task executions."""

    def __init__(
        self,
        *,
        registry: TaskRegistry | None = None,
        event_bus: EventBus | None = None,
        profiling: TaskProfilingConfig | None = None,
        observers: Iterable[TaskObserver] = (),
        event_handlers: Iterable[EventHandler] = (),
        max_workers: int = 4,
        strategy_request_timeout: timedelta | None = None,
        strategy_request_timeout_check_interval: timedelta | None = None,
    ) -> None:
        self.registry = registry or InMemoryTaskRegistry()
        self.event_bus = event_bus or EventBus(strategy_request_timeout=strategy_request_timeout)
        if event_bus is not None and strategy_request_timeout is not None:
            self.event_bus.strategy_request_timeout = strategy_request_timeout
        self.profiling = profiling or TaskProfilingConfig()
        self.observers = tuple(observers)
        self.event_handlers = tuple(event_handlers)
        for handler in self.event_handlers:
            self.event_bus.subscribe(handler)
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self.runtimes = TaskRuntimeRegistry()
        self.runner_factory = TaskRunnerFactory(
            event_bus=self.event_bus,
            registry=self.registry,
            observers=self.observers,
        )
        self.launcher = TaskLauncher(
            executor=self._executor,
            runner_factory=self.runner_factory,
            default_profiling=self.profiling,
        )
        self.events = TaskEventPublisher(self.event_bus)
        self.launch_service = TaskLaunchService(
            registry=self.registry,
            runtimes=self.runtimes,
            launcher=self.launcher,
        )
        self.control = TaskControlService(
            registry=self.registry,
            runtimes=self.runtimes,
            events=self.events,
        )
        self.progress_service = TaskProgressService(
            registry=self.registry,
            runtimes=self.runtimes,
        )
        self.waiter = TaskWaiter(registry=self.registry, progress_snapshot=self.progress)
        interval = StrategyRequestTimeoutMonitor.interval_for(
            configured=strategy_request_timeout_check_interval,
            timeout=self.event_bus.strategy_request_timeout,
        )
        self.strategy_request_timeout_monitor = StrategyRequestTimeoutMonitor(
            event_bus=self.event_bus,
            registry=self.registry,
            runtimes=self.runtimes,
            interval=interval,
        )

    def __enter__(self) -> Self:
        """Return this manager for context-managed task execution."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Request active tasks to stop and shut down the executor."""
        _ = exc_type
        _ = exc
        _ = traceback
        self.shutdown(wait=True)

    def start_backtest(
        self,
        definition: BacktestTaskDefinition,
        *,
        data_source: DataSource,
        strategy: Strategy,
        broker: Broker | None = None,
        profiling: TaskProfilingConfig | None = None,
        task_id: UUID | None = None,
    ) -> TaskRun:
        """Start a backtest task in the background."""
        clock = self.runner_factory.clock_for_definition(definition)
        started = ExecutableTask.from_definition(
            definition,
            task_id=task_id,
            clock=clock,
        ).start(clock=clock)
        self.registry.save(started)
        self._launch(
            started,
            type="backtest",
            data_source=data_source,
            strategy=strategy,
            broker=broker,
            clock=clock,
            profiling=profiling,
        )
        return TaskRun(task=started, _manager=self)

    def start_trading(
        self,
        definition: TradingTaskDefinition,
        *,
        data_source: DataSource,
        strategy: Strategy,
        broker: Broker | None = None,
        profiling: TaskProfilingConfig | None = None,
        task_id: UUID | None = None,
    ) -> TaskRun:
        """Start a trading task in the background."""
        if not definition.dry_run and broker is None:
            msg = "trading task requires broker when dry_run is false"
            raise ValueError(msg)
        clock = self.runner_factory.clock_for_definition(definition)
        started = ExecutableTask.from_definition(
            definition,
            task_id=task_id,
            clock=clock,
        ).start(clock=clock)
        self.registry.save(started)
        self._launch(
            started,
            type="trading",
            data_source=data_source,
            strategy=strategy,
            broker=broker,
            clock=clock,
            profiling=profiling,
        )
        return TaskRun(task=started, _manager=self)

    def get(self, task_id: UUID) -> Task:
        """Return the latest task state."""
        return self.registry.get(task_id)

    def pause(self, task_id: UUID) -> Task:
        """Request a graceful task pause."""
        return self.control.pause(task_id)

    def stop(self, task_id: UUID) -> Task:
        """Request a graceful task stop."""
        return self.control.stop(task_id)

    def restart(self, task_id: UUID, *, timeout: float | None = None) -> Task:
        """Restart a task using the same runtime dependencies."""
        runtime = self.runtimes.get(task_id)
        if not runtime.future.done():
            runtime.control.request_stop()
            runtime.future.result(timeout=timeout)

        current_task = self.registry.get(task_id)
        clock = self.runner_factory.clock_for_task(current_task, runtime.type)
        restarted = self.registry.save(current_task.restart(clock=clock))
        self._launch(
            restarted,
            type=runtime.type,
            data_source=runtime.data_source,
            strategy=runtime.strategy,
            broker=runtime.broker,
            clock=clock,
            profiling=runtime.profiler.config,
        )
        return restarted

    def recover(
        self,
        task_id: UUID,
        *,
        data_source: DataSource,
        strategy: Strategy,
        broker: Broker | None = None,
        profiling: TaskProfilingConfig | None = None,
    ) -> TaskRun:
        """Recover a persisted task with newly constructed runtime dependencies."""
        task = self.registry.get(task_id)
        runner_type: RunnerType = (
            "backtest" if isinstance(task.definition, BacktestTaskDefinition) else "trading"
        )
        clock = self.runner_factory.clock_for_task(task, runner_type)
        if task.status == TaskStatus.PAUSED:
            task = self.registry.save(task.start(clock=clock))
        elif task.status in {TaskStatus.CREATED, TaskStatus.STOPPED, TaskStatus.FAILED}:
            if task.status == TaskStatus.CREATED:
                task = self.registry.save(task.start(clock=clock))
            else:
                task = self.registry.save(task.recover(clock=clock))
        elif task.status != TaskStatus.RUNNING:
            msg = f"cannot recover task {task.id} while status is {task.status.value}"
            raise ValueError(msg)

        if isinstance(task.definition, TradingTaskDefinition) and not task.definition.dry_run:
            if broker is None:
                msg = "trading task requires broker when dry_run is false"
                raise ValueError(msg)

        self._launch(
            task,
            type=runner_type,
            data_source=data_source,
            strategy=strategy,
            broker=broker,
            clock=clock,
            profiling=profiling,
            recovering=True,
        )
        return TaskRun(task=task, _manager=self)

    def restart_with_dependencies(
        self,
        task_id: UUID,
        *,
        data_source: DataSource,
        strategy: Strategy,
        broker: Broker | None = None,
        profiling: TaskProfilingConfig | None = None,
    ) -> TaskRun:
        """Start a fresh run using newly constructed runtime dependencies."""
        current = self.registry.get(task_id)
        runner_type: RunnerType = (
            "backtest" if isinstance(current.definition, BacktestTaskDefinition) else "trading"
        )
        clock = self.runner_factory.clock_for_task(current, runner_type)
        restarted = self.registry.save(current.restart(clock=clock))
        if isinstance(restarted.definition, TradingTaskDefinition):
            if not restarted.definition.dry_run and broker is None:
                msg = "trading task requires broker when dry_run is false"
                raise ValueError(msg)
        self._launch(
            restarted,
            type=runner_type,
            data_source=data_source,
            strategy=strategy,
            broker=broker,
            clock=clock,
            profiling=profiling,
        )
        return TaskRun(task=restarted, _manager=self)

    def wait(
        self,
        task_id: UUID,
        *,
        timeout: float | None = None,
        progress: TaskProgressReporter | None = None,
        refresh_seconds: float = 0.5,
    ) -> Task:
        """Wait for the current runner to finish and return the latest task."""
        return self.waiter.wait(
            task_id,
            runtime=self.runtimes.get(task_id),
            timeout=timeout,
            progress=progress,
            refresh_seconds=refresh_seconds,
        )

    def progress(self, task_id: UUID) -> TaskProgress:
        """Return a point-in-time progress snapshot for the task run."""
        return self.progress_service.progress(task_id)

    def profile(self, task_id: UUID) -> TaskProfile:
        """Return a point-in-time profiling snapshot for the task run."""
        return self.runtimes.get(task_id).profiler.snapshot()

    def shutdown(self, *, wait: bool = True) -> None:
        """Shut down the task executor."""
        self.strategy_request_timeout_monitor.shutdown(wait=wait)
        for runtime in self.runtimes.values():
            if not runtime.future.done():
                runtime.control.request_stop()
        self._executor.shutdown(wait=wait)

    def _launch(
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
        self.launch_service.launch(
            task,
            type=type,
            data_source=data_source,
            strategy=strategy,
            broker=broker,
            clock=clock,
            profiling=profiling,
            recovering=recovering,
        )
