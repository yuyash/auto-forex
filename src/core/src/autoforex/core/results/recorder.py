"""Record strategy events into task result summaries and P/L metrics."""

from __future__ import annotations

from datetime import timedelta
from threading import RLock
from uuid import UUID

from autoforex.core.events.event import Event
from autoforex.core.results.ledger import TradeLedger
from autoforex.core.results.mapping import StrategyEventRecordMapper
from autoforex.core.results.metrics import ProfitMetricCollector
from autoforex.core.results.models import (
    CycleSummary,
    StrategyEventRecord,
    TaskSummary,
    TradeSummary,
)
from autoforex.core.results.stores import InMemoryResultStore, ProfitMetricStore, ResultStore
from autoforex.core.results.writer import ResultRecorderWriter
from autoforex.core.sources.models import Tick
from autoforex.core.strategies.execution import StrategyAction, StrategyEvent
from autoforex.core.tasks.execution import ExecutableTask

type Task = ExecutableTask


class TaskResultRecorder:
    """Event handler and task observer that materializes task result summaries."""

    def __init__(
        self,
        *,
        stores: tuple[ResultStore, ...] | None = None,
        metric_stores: tuple[ProfitMetricStore, ...] = (),
        metric_interval: timedelta | None = None,
        flush_every: int = 1,
        cleanup_finished_tasks: bool = True,
        mapper: StrategyEventRecordMapper | None = None,
        ledger: TradeLedger | None = None,
    ) -> None:
        self.writer = ResultRecorderWriter(
            stores=stores,
            metric_stores=metric_stores,
            flush_every=flush_every,
        )
        self.cleanup_finished_tasks = cleanup_finished_tasks
        self.mapper = mapper or StrategyEventRecordMapper()
        self.ledger = ledger or TradeLedger()
        self.metrics = ProfitMetricCollector(metric_interval)
        self._task_status: dict[UUID, str] = {}
        self._lock = RLock()

    @property
    def memory(self) -> InMemoryResultStore:
        """Return the in-memory result store."""
        return self.writer.memory

    @property
    def stores(self) -> tuple[ResultStore, ...]:
        """Return all stores receiving result records."""
        return self.writer.stores

    @property
    def external_stores(self) -> tuple[ResultStore, ...]:
        """Return configured external result stores."""
        return self.writer.external_stores

    @property
    def metric_stores(self) -> tuple[ProfitMetricStore, ...]:
        """Return configured metric stores."""
        return self.writer.metric_stores

    @property
    def metric_interval(self) -> timedelta | None:
        """Return the configured metric interval."""
        return self.metrics.interval

    def handle(self, event: Event) -> None:
        """Handle events emitted by the event bus."""
        if not isinstance(event, StrategyEvent):
            return
        record = self.mapper.from_event(event)
        with self._lock:
            self.writer.event(record)
            if not self._filled_strategy_event(event):
                return
            if record.action == StrategyAction.OPEN_TRADE:
                self.ledger.record_open(record)
            elif record.action == StrategyAction.CLOSE_TRADE:
                self._record_close(record)

    def on_tick(self, task: Task, tick: Tick) -> None:
        """Emit interval P/L metrics after a tick has been processed."""
        with self._lock:
            if not self.metrics.due(task.id, tick.timestamp):
                return
            metric = self.metrics.metric(
                task=task,
                tick=tick,
                trade_states=self.ledger.trade_states(task.id),
            )
            self.writer.metric(metric)
            self.metrics.mark_emitted(task.id, tick.timestamp)

    def on_task_finished(self, task: Task) -> None:
        """Persist final trade, cycle, and task summaries."""
        with self._lock:
            self._task_status[task.id] = task.status.value
            for summary in self.trade_summaries(task.id):
                self.writer.trade(summary)
            for summary in self.cycle_summaries(task.id):
                self.writer.cycle(summary)
            self.writer.task(self.task_summary(task))
            self.flush()
            if self.cleanup_finished_tasks:
                self._cleanup_finished_task_state(task.id)

    def flush(self) -> None:
        """Flush buffered result records to external stores."""
        with self._lock:
            self.writer.flush()

    def event_records(self, task_id: UUID | None = None) -> tuple[StrategyEventRecord, ...]:
        """Return event records captured in memory."""
        events = self.memory.events
        if task_id is None:
            return events
        return tuple(event for event in events if event.task_id == task_id)

    def trade_summaries(self, task_id: UUID | None = None) -> tuple[TradeSummary, ...]:
        """Return latest trade summaries."""
        with self._lock:
            return self.ledger.summaries(memory_summaries=self.memory.trades, task_id=task_id)

    def cycle_summaries(self, task_id: UUID | None = None) -> tuple[CycleSummary, ...]:
        """Return latest cycle summaries."""
        with self._lock:
            return self.ledger.cycle_summaries(
                memory_summaries=self.memory.cycles,
                task_id=task_id,
            )

    def task_summary(self, task: Task) -> TaskSummary:
        """Return a task summary for the provided task."""
        with self._lock:
            summaries = self.trade_summaries(task.id)
        return self.ledger.task_summary(task, summaries)

    def _record_close(self, record: StrategyEventRecord) -> None:
        summary, cycle_summary = self.ledger.record_close(record)
        self.writer.trade(summary)
        if cycle_summary is not None:
            self.writer.cycle(cycle_summary)

    def _cleanup_finished_task_state(self, task_id: UUID) -> None:
        self.ledger.cleanup_task(task_id)
        self.metrics.cleanup_task(task_id)
        self._task_status.pop(task_id, None)

    @staticmethod
    def _filled_strategy_event(event: StrategyEvent) -> bool:
        if event.action == StrategyAction.HOLD:
            return False
        if event.response is None:
            return False
        return event.response.filled
