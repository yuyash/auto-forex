"""Runner construction and launch services for task management."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from typing import cast

from autoforex.core.clock import Clock, ManualClock, SystemClock
from autoforex.core.events.bus import EventBus
from autoforex.core.ports.brokers import Broker
from autoforex.core.sources.base import DataSource
from autoforex.core.strategies.base import Strategy
from autoforex.core.tasks.definitions import BacktestTaskDefinition, TradingTaskDefinition
from autoforex.core.tasks.execution import ExecutableTask
from autoforex.core.tasks.observers import TaskObserver
from autoforex.core.tasks.profiling import TaskProfiler, TaskProfilingConfig
from autoforex.core.tasks.registry import TaskRegistry
from autoforex.core.tasks.runner import BacktestRunner, TaskExecutionControl, TradingRunner
from autoforex.core.tasks.runtime import RunnerType, TaskRuntime

type Task = ExecutableTask


class TaskRunnerFactory:
    """Create concrete task runners and clocks."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        registry: TaskRegistry,
        observers: tuple[TaskObserver, ...],
    ) -> None:
        self.event_bus = event_bus
        self.registry = registry
        self.observers = observers

    def clock_for_definition(
        self,
        definition: BacktestTaskDefinition | TradingTaskDefinition,
    ) -> Clock:
        """Return the initial clock for a task definition."""
        if isinstance(definition, BacktestTaskDefinition):
            return ManualClock(definition.start_at)
        return SystemClock()

    def clock_for_task(self, task: Task, type: RunnerType) -> Clock:
        """Return a fresh clock for restarting a task."""
        if type == "backtest":
            if not isinstance(task.definition, BacktestTaskDefinition):
                msg = "backtest clock requires BacktestTaskDefinition"
                raise TypeError(msg)
            return ManualClock(task.definition.start_at)
        return SystemClock()

    def runner(
        self,
        task: Task,
        *,
        type: RunnerType,
        data_source: DataSource,
        strategy: Strategy,
        broker: Broker | None,
        clock: Clock,
        profiler: TaskProfiler,
        recovering: bool = False,
    ) -> BacktestRunner | TradingRunner:
        """Create a concrete task runner."""
        if type == "backtest":
            if not isinstance(task.definition, BacktestTaskDefinition):
                msg = "backtest runner requires BacktestTaskDefinition"
                raise TypeError(msg)
            return BacktestRunner(
                task=task,
                data_source=data_source,
                strategy=strategy,
                broker=broker,
                event_bus=self.event_bus,
                registry=self.registry,
                clock=clock,
                profiler=profiler,
                observers=self.observers,
                recovering=recovering,
            )

        if not isinstance(task.definition, TradingTaskDefinition):
            msg = "trading runner requires TradingTaskDefinition"
            raise TypeError(msg)
        return TradingRunner(
            task=task,
            data_source=data_source,
            strategy=strategy,
            broker=broker,
            event_bus=self.event_bus,
            registry=self.registry,
            clock=clock,
            profiler=profiler,
            observers=self.observers,
            recovering=recovering,
        )


class TaskLauncher:
    """Launch task runners on a thread pool."""

    def __init__(
        self,
        *,
        executor: ThreadPoolExecutor,
        runner_factory: TaskRunnerFactory,
        default_profiling: TaskProfilingConfig,
    ) -> None:
        self.executor = executor
        self.runner_factory = runner_factory
        self.default_profiling = default_profiling

    def launch(
        self,
        task: Task,
        *,
        type: RunnerType,
        data_source: DataSource,
        strategy: Strategy,
        broker: Broker | None,
        clock: Clock,
        profiling: TaskProfilingConfig | None,
        recovering: bool = False,
    ) -> TaskRuntime:
        """Create a runner, submit it to the executor, and return runtime state."""
        control = TaskExecutionControl()
        profiler = TaskProfiler(
            task_id=task.id,
            task_name=task.name,
            task_type=type,
            config=profiling or self.default_profiling,
        )
        runner = self.runner_factory.runner(
            task,
            type=type,
            data_source=data_source,
            strategy=strategy,
            broker=broker,
            clock=clock,
            profiler=profiler,
            recovering=recovering,
        )
        future = cast(Future[Task], self.executor.submit(profiler.run, runner.run, control))
        return TaskRuntime(
            type=type,
            data_source=data_source,
            strategy=strategy,
            broker=broker,
            clock=clock,
            control=control,
            profiler=profiler,
            future=future,
        )
