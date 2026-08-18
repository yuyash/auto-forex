"""Task runners that feed market data into strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from threading import Event as ThreadEvent
from threading import RLock
from types import TracebackType
from typing import Literal, Self
from uuid import UUID, uuid5

from autoforex.core.clock import Clock, ManualClock, SystemClock
from autoforex.core.events.bus import EventBus
from autoforex.core.events.event import Event
from autoforex.core.events.routing import EventSubscription
from autoforex.core.events.types import EventSource, EventType
from autoforex.core.models.metadata import Metadata
from autoforex.core.orders.event_handler import StrategyEventHandler
from autoforex.core.orders.recovery import BrokerExecutionCoordinator
from autoforex.core.ports.brokers import Broker
from autoforex.core.sources.base import DataSource
from autoforex.core.sources.models import Tick
from autoforex.core.strategies.base import Strategy, StrategyContext, StrategyResult
from autoforex.core.strategies.execution import StrategyEventRequest, StrategyExecutionResponse
from autoforex.core.tasks.definitions import BacktestTaskDefinition, TradingTaskDefinition
from autoforex.core.tasks.execution import ExecutableTask
from autoforex.core.tasks.failure import TaskFailure
from autoforex.core.tasks.observers import TaskObserver
from autoforex.core.tasks.profiling import TaskProfiler
from autoforex.core.tasks.publishing import StrategyPublisher, StrategyResponseHandler
from autoforex.core.tasks.registry import TaskRegistry
from autoforex.core.tasks.runner_support import ObserverNotifier, TaskExecutionMode
from autoforex.core.tasks.state import TaskAction

type Task = ExecutableTask


@dataclass(frozen=True, slots=True)
class TaskExecutionControl:
    """Cancellation and pause signals for a running task."""

    _stop_requested: ThreadEvent = field(default_factory=ThreadEvent)
    _pause_requested: ThreadEvent = field(default_factory=ThreadEvent)

    def request_stop(self) -> None:
        """Request a graceful task stop."""
        self._stop_requested.set()

    def request_pause(self) -> None:
        """Request a graceful task pause."""
        self._pause_requested.set()

    @property
    def stop_requested(self) -> bool:
        """Return whether stop has been requested."""
        return self._stop_requested.is_set()

    @property
    def pause_requested(self) -> bool:
        """Return whether pause has been requested."""
        return self._pause_requested.is_set()


class TaskLifecycle:
    """Persist task lifecycle transitions and publish lifecycle events."""

    def __init__(
        self,
        *,
        task_id: UUID,
        event_bus: EventBus,
        registry: TaskRegistry,
        clock: Clock,
    ) -> None:
        self.task_id = task_id
        self.event_bus = event_bus
        self.registry = registry
        self.clock = clock

    def ensure_running(self) -> Task:
        """Return a running task, starting it when needed."""
        task = self.registry.get(self.task_id)
        if not task.is_running:
            task = self.registry.save(task.start(clock=self.clock))
        self.publish_task_event(EventType.TASK_STARTED, task)
        return task

    def pause_current(self) -> Task:
        """Pause the current task when the transition is allowed."""
        task = self.registry.get(self.task_id)
        if task.can(TaskAction.PAUSE):
            task = self.registry.save(task.pause(clock=self.clock))
            self.publish_task_event(EventType.TASK_PAUSED, task)
        return task

    def stop_current(self) -> Task:
        """Stop the current task when the transition is allowed."""
        task = self.registry.get(self.task_id)
        if task.can(TaskAction.STOP):
            task = self.registry.save(task.stop(clock=self.clock))
            self.publish_task_event(EventType.TASK_STOPPED, task)
        return task

    def complete_current(self) -> Task:
        """Complete the current task when the transition is allowed."""
        task = self.registry.get(self.task_id)
        if task.can(TaskAction.COMPLETE):
            task = self.registry.save(task.complete(clock=self.clock))
            self.publish_task_event(EventType.TASK_COMPLETED, task)
        return task

    def fail_current(self, reason: str | TaskFailure | BaseException) -> Task:
        """Fail the current task when the transition is allowed."""
        task = self.registry.get(self.task_id)
        if task.can(TaskAction.FAIL):
            task = self.registry.save(task.fail(reason, clock=self.clock))
            failure = task.failure
            self.publish_task_event(
                EventType.TASK_FAILED,
                task,
                metadata=Metadata.of(
                    reason="" if failure is None else failure.message,
                    cause_type="" if failure is None else failure.cause_type,
                    traceback="" if failure is None else failure.traceback,
                ),
            )
        return task

    def publish_task_event(
        self,
        event_type: EventType,
        task: Task,
        *,
        metadata: Metadata | None = None,
    ) -> None:
        """Publish a task lifecycle event."""
        event_metadata = Metadata.of(
            task_status=task.status.value,
            task_type=task.task_type.value,
        )
        if metadata is not None:
            event_metadata = event_metadata.merge(metadata)

        self.event_bus.publish(
            Event(
                type=event_type,
                timestamp=self.clock.now(),
                task_id=task.id,
                source=EventSource.CORE,
                metadata=event_metadata,
            )
        )


type TerminalMode = Literal["complete", "stop"]


@dataclass(frozen=True, slots=True)
class TaskTickStep:
    """Result of processing one task tick."""

    task: Task
    terminal_task: Task | None = None
    finish_terminal: bool = False


class StrategyExecutor:
    """Execute strategy callbacks and consume task-scoped execution responses."""

    def __init__(
        self,
        *,
        task_id: UUID,
        strategy: Strategy,
        publisher: StrategyPublisher,
        event_handler: StrategyEventHandler,
        registry: TaskRegistry,
        observer_notifier: ObserverNotifier,
        event_bus: EventBus,
        lifecycle: TaskLifecycle,
        execution_coordinator: BrokerExecutionCoordinator | None = None,
    ) -> None:
        self.task_id = task_id
        self.strategy = strategy
        self.publisher = publisher
        self.event_handler = event_handler
        self.registry = registry
        self.observer_notifier = observer_notifier
        self.event_bus = event_bus
        self.lifecycle = lifecycle
        self.execution_coordinator = execution_coordinator
        self._subscriptions: tuple[EventSubscription, ...] = ()
        self._lock = RLock()

    def __enter__(self) -> Self:
        """Subscribe task-scoped strategy handlers."""
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Unsubscribe task-scoped strategy handlers."""
        _ = exc_type
        _ = exc
        _ = traceback
        self.close()

    def open(self) -> None:
        """Subscribe task-scoped request execution and response consumption."""
        if self._subscriptions:
            return
        subscriptions: list[EventSubscription] = []
        try:
            subscriptions.append(
                self.event_bus.subscribe(
                    self.event_handler,
                    predicate=self._matches_task,
                    event_class=StrategyEventRequest,
                )
            )
            subscriptions.append(
                self.event_bus.subscribe(
                    self,
                    predicate=self._matches_task,
                    event_class=StrategyExecutionResponse,
                )
            )
        except Exception:
            for subscription in reversed(subscriptions):
                self.event_bus.unsubscribe(subscription)
            raise
        self._subscriptions = tuple(subscriptions)

    def close(self) -> None:
        """Remove task-scoped subscriptions."""
        with self._lock:
            for subscription in reversed(self._subscriptions):
                self.event_bus.unsubscribe(subscription)
            self._subscriptions = ()

    def handle(self, event: Event) -> None:
        """Apply one event-bus response and persist the resulting strategy context."""
        if not isinstance(event, StrategyExecutionResponse):
            return
        with self._lock:
            self.registry.apply_execution_response(event)
            context = self.registry.current_context(event.event.task_id)
            state = self.strategy.on_execution_reports((event,), context)
            if state != context.state:
                context = context.with_state(state)
            self.registry.save_context(context)
            if self.execution_coordinator is not None:
                self.execution_coordinator.response_applied(event)

    def start(self, task: Task, *, recovering: bool = False) -> Task:
        """Run the appropriate strategy activation callback and persist state."""
        with self._lock:
            context = self.registry.initialize_context(task, strategy_name=self.strategy.name)
            if recovering and self.execution_coordinator is not None:
                task, context = self._recover_pending(task, context)
            start_result = (
                self.strategy.on_recover(context) if recovering else self.strategy.on_start(context)
            )
            context = self._publish(
                start_result,
                context,
                task=task,
                phase="recover" if recovering else "start",
            )
            return self.registry.save_context(context)

    def tick(
        self,
        *,
        task: Task,
        tick: Tick,
        control: TaskExecutionControl,
    ) -> TaskTickStep:
        """Run one strategy tick or return a requested terminal transition."""
        with self._lock:
            context = self.registry.current_context(task.id)
            self.event_bus.expire_pending_strategy_requests(
                task_id=task.id,
                timestamp=tick.timestamp,
            )
            if control.pause_requested:
                return TaskTickStep(
                    task=task,
                    terminal_task=self.lifecycle.pause_current(),
                )
            if control.stop_requested:
                return TaskTickStep(
                    task=task,
                    terminal_task=self.lifecycle.stop_current(),
                    finish_terminal=True,
                )

            tick_result = self.strategy.on_tick(tick, context)
            context = self._publish(
                tick_result,
                context,
                task=task,
                phase=f"tick:{tick.timestamp.isoformat()}",
                checkpoint_at=tick.timestamp,
            )
            task = self.registry.save_context(context)
            if task.last_processed_at != tick.timestamp:
                task = self.registry.save(task.with_last_processed_at(tick.timestamp))
            self.observer_notifier.tick(task, tick)
            return TaskTickStep(task=task)

    def stop(
        self,
        *,
        task: Task,
        mode: TerminalMode,
    ) -> Task:
        """Run strategy stop callback and apply the final lifecycle transition."""
        with self._lock:
            context = self.registry.current_context(task.id)
            stop_result = self.strategy.on_stop(context)
            context = self._publish(
                stop_result,
                context,
                task=task,
                phase=f"stop:{mode}",
            )
            self.registry.save_context(context)
            if mode == "complete":
                return self.lifecycle.complete_current()
            return self.lifecycle.stop_current()

    def _publish(
        self,
        result: StrategyResult,
        context: StrategyContext,
        *,
        task: Task,
        phase: str,
        checkpoint_at: datetime | None = None,
    ) -> StrategyContext:
        result = self._identified(result, task=task, phase=phase)
        context = context if result.state is None else context.with_state(result.state)
        self.registry.save_context(context)
        if self.execution_coordinator is not None:
            self.execution_coordinator.prepare(
                result.events,
                checkpoint_at=checkpoint_at,
            )
        self.publisher.publish(result)
        if self.execution_coordinator is not None:
            self.execution_coordinator.complete(result.events)
        if checkpoint_at is not None and self.execution_coordinator is not None:
            latest = self.registry.get(task.id)
            self.registry.save(latest.with_last_processed_at(checkpoint_at))
            self.execution_coordinator.checkpointed(result.events)
        return self.registry.current_context(context.task_id)

    def _recover_pending(
        self,
        task: Task,
        context: StrategyContext,
    ) -> tuple[Task, StrategyContext]:
        if self.execution_coordinator is None:
            return task, context
        for batch in self.execution_coordinator.pending(task.id):
            self.publisher.publish(StrategyResult(events=batch.requests))
            self.execution_coordinator.complete(batch.requests)
            context = self.registry.current_context(task.id)
            task = self.registry.save_context(context)
            if batch.checkpoint_at is not None:
                task = self.registry.save(task.with_last_processed_at(batch.checkpoint_at))
                self.execution_coordinator.checkpointed(batch.requests)
        return task, context

    @staticmethod
    def _identified(
        result: StrategyResult,
        *,
        task: Task,
        phase: str,
    ) -> StrategyResult:
        events = tuple(
            event.evolve(id=uuid5(task.id, f"{task.run_count}:{phase}:{index}"))
            for index, event in enumerate(result.events)
        )
        if events == result.events:
            return result
        return result.evolve(events=events)

    def _matches_task(self, event: Event) -> bool:
        return event.task_id == self.task_id


class TaskRunner(ABC):
    """Base runner shared by backtest and live trading execution."""

    def __init__(
        self,
        *,
        task: Task,
        data_source: DataSource,
        strategy: Strategy,
        event_bus: EventBus,
        registry: TaskRegistry,
        broker: Broker | None = None,
        clock: Clock | None = None,
        profiler: TaskProfiler | None = None,
        observers: Sequence[TaskObserver] = (),
        recovering: bool = False,
    ) -> None:
        self.task = task
        self.data_source = data_source
        self.strategy = strategy
        self.event_bus = event_bus
        self.registry = registry
        self.observers = tuple(observers)
        self.recovering = recovering
        self.clock = clock or SystemClock()
        self.observer_notifier = ObserverNotifier(
            observers=observers,
            event_bus=event_bus,
            clock=self.clock,
            task_id=task.id,
        )
        self.profiler = profiler or TaskProfiler(
            task_id=task.id,
            task_name=task.name,
            task_type=task.task_type.value,
        )
        self.lifecycle = TaskLifecycle(
            task_id=task.id,
            event_bus=event_bus,
            registry=registry,
            clock=self.clock,
        )
        self.publisher = StrategyPublisher(event_bus)
        self.response_handler = StrategyResponseHandler(event_bus)
        self.strategy_executor = StrategyExecutor(
            task_id=task.id,
            strategy=strategy,
            publisher=self.publisher,
            event_handler=StrategyEventHandler(
                response_handler=self.response_handler,
                broker=broker,
                dry_run=TaskExecutionMode.dry_run_for(task, broker=broker),
            ),
            registry=registry,
            observer_notifier=self.observer_notifier,
            event_bus=event_bus,
            lifecycle=self.lifecycle,
            execution_coordinator=(
                broker if isinstance(broker, BrokerExecutionCoordinator) else None
            ),
        )

    @abstractmethod
    def run(self, control: TaskExecutionControl | None = None) -> Task:
        """Run the task until completion, stop, pause, or failure."""

    def _finish(self, task: Task) -> Task:
        self.event_bus.clear_pending_strategy_requests(
            task_id=task.id,
            reason=f"task {task.status.value}",
            timestamp=self.clock.now(),
        )
        return self.observer_notifier.finished(task)


class BacktestRunner(TaskRunner):
    """Run a finite backtest over historical ticks."""

    task: ExecutableTask

    def run(self, control: TaskExecutionControl | None = None) -> ExecutableTask:
        """Run the backtest until all ticks are consumed."""
        execution_control = control or TaskExecutionControl()
        if not isinstance(self.task.definition, BacktestTaskDefinition):
            msg = "backtest runner requires BacktestTaskDefinition"
            raise TypeError(msg)
        resume_at = self.task.last_processed_at or self.task.definition.start_at
        self._ensure_manual_clock(resume_at)
        self._set_clock(resume_at)
        with self.strategy_executor:
            return self._run(execution_control)

    def _run(self, execution_control: TaskExecutionControl) -> ExecutableTask:
        task = self.lifecycle.ensure_running()
        self.task = task
        if not isinstance(task.definition, BacktestTaskDefinition):
            msg = "backtest runner requires BacktestTaskDefinition"
            raise TypeError(msg)
        definition = task.definition

        try:
            task = self.strategy_executor.start(task, recovering=self.recovering)
            self.task = task
            ticks = self.data_source.ticks(
                instrument=task.instrument,
                start_at=task.last_processed_at or definition.start_at,
                end_at=definition.end_at,
            )
            for tick in ticks:
                if task.last_processed_at is not None and tick.timestamp <= task.last_processed_at:
                    continue
                self._set_clock(tick.timestamp)
                step = self.strategy_executor.tick(
                    task=task,
                    tick=tick,
                    control=execution_control,
                )
                if step.terminal_task is not None:
                    if step.finish_terminal:
                        return self._finish(step.terminal_task)
                    return step.terminal_task
                task = step.task
                self.task = task

            self._set_clock(definition.end_at)
            self.event_bus.expire_pending_strategy_requests(
                task_id=task.id,
                timestamp=definition.end_at,
            )
            completed = self.strategy_executor.stop(
                task=task,
                mode="complete",
            )
            return self._finish(completed)
        except Exception as exc:
            failed = self.lifecycle.fail_current(exc)
            try:
                return self._finish(failed)
            except Exception:
                return failed

    def _ensure_manual_clock(self, start_at: datetime) -> None:
        if isinstance(self.clock, SystemClock):
            self.clock = ManualClock(start_at)
            self.lifecycle.clock = self.clock
            self.observer_notifier.clock = self.clock

    def _set_clock(self, timestamp: datetime) -> None:
        if isinstance(self.clock, ManualClock):
            self.clock.set(timestamp)


class TradingRunner(TaskRunner):
    """Run a live trading task until it is stopped or paused."""

    task: ExecutableTask

    def run(self, control: TaskExecutionControl | None = None) -> ExecutableTask:
        """Run the trading task against a live tick stream."""
        execution_control = control or TaskExecutionControl()
        if not isinstance(self.task.definition, TradingTaskDefinition):
            msg = "trading runner requires TradingTaskDefinition"
            raise TypeError(msg)
        with self.strategy_executor:
            return self._run(execution_control)

    def _run(self, execution_control: TaskExecutionControl) -> ExecutableTask:
        task = self.lifecycle.ensure_running()
        self.task = task
        if not isinstance(task.definition, TradingTaskDefinition):
            msg = "trading runner requires TradingTaskDefinition"
            raise TypeError(msg)

        try:
            task = self.strategy_executor.start(task, recovering=self.recovering)
            self.task = task
            recovery_checkpoint = task.last_processed_at
            ticks = self.data_source.stream_prices(instruments=(task.instrument,))
            for tick in ticks:
                if (
                    recovery_checkpoint is not None
                    and tick.timestamp <= recovery_checkpoint
                    and not execution_control.pause_requested
                    and not execution_control.stop_requested
                ):
                    continue
                recovery_checkpoint = None
                step = self.strategy_executor.tick(
                    task=task,
                    tick=tick,
                    control=execution_control,
                )
                if step.terminal_task is not None:
                    if step.finish_terminal:
                        return self._finish(step.terminal_task)
                    return step.terminal_task
                task = step.task
                self.task = task

            stopped = self.strategy_executor.stop(task=task, mode="stop")
            return self._finish(stopped)
        except Exception as exc:
            failed = self.lifecycle.fail_current(exc)
            try:
                return self._finish(failed)
            except Exception:
                return failed
