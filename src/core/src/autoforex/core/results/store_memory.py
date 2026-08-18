"""In-memory result store."""

from __future__ import annotations

from threading import RLock
from uuid import UUID

from autoforex.core.results.models import (
    CycleSummary,
    ProfitMetric,
    StrategyEventRecord,
    TaskSummary,
    TradeSummary,
)
from autoforex.core.results.store_contracts import ResultBatch

type ResultRecord = StrategyEventRecord | TradeSummary | CycleSummary | TaskSummary | ProfitMetric


class InMemoryResultStore:
    """Thread-safe in-memory result store for notebooks and tests."""

    def __init__(self) -> None:
        self._events: dict[UUID, StrategyEventRecord] = {}
        self._trades: dict[tuple[UUID, str], TradeSummary] = {}
        self._cycles: dict[tuple[UUID, int], CycleSummary] = {}
        self._tasks: dict[UUID, TaskSummary] = {}
        self._metrics: dict[UUID, ProfitMetric] = {}
        self._lock = RLock()

    def save_event(self, record: StrategyEventRecord) -> None:
        """Persist one flattened strategy event."""
        with self._lock:
            self._events[record.event_id] = record

    def save_trade(self, summary: TradeSummary) -> None:
        """Persist one trade summary."""
        with self._lock:
            self._trades[(summary.task_id, summary.trade_id)] = summary

    def save_cycle(self, summary: CycleSummary) -> None:
        """Persist one cycle summary."""
        with self._lock:
            self._cycles[(summary.task_id, summary.cycle_id)] = summary

    def save_task(self, summary: TaskSummary) -> None:
        """Persist one task summary."""
        with self._lock:
            self._tasks[summary.task_id] = summary

    def save_metric(self, metric: ProfitMetric) -> None:
        """Persist one profit metric."""
        with self._lock:
            self._metrics[metric.metric_id] = metric

    def save_batch(self, batch: ResultBatch) -> None:
        """Persist a batch of result records."""
        with self._lock:
            for record in batch.events:
                self._events[record.event_id] = record
            for summary in batch.trades:
                self._trades[(summary.task_id, summary.trade_id)] = summary
            for summary in batch.cycles:
                self._cycles[(summary.task_id, summary.cycle_id)] = summary
            for summary in batch.tasks:
                self._tasks[summary.task_id] = summary
            for metric in batch.metrics:
                self._metrics[metric.metric_id] = metric

    @property
    def events(self) -> tuple[StrategyEventRecord, ...]:
        """Return event records."""
        with self._lock:
            return tuple(self._events.values())

    @property
    def trades(self) -> tuple[TradeSummary, ...]:
        """Return latest trade summaries."""
        with self._lock:
            return tuple(self._trades.values())

    @property
    def cycles(self) -> tuple[CycleSummary, ...]:
        """Return latest cycle summaries."""
        with self._lock:
            return tuple(self._cycles.values())

    @property
    def tasks(self) -> tuple[TaskSummary, ...]:
        """Return latest task summaries."""
        with self._lock:
            return tuple(self._tasks.values())

    @property
    def metrics(self) -> tuple[ProfitMetric, ...]:
        """Return profit metrics."""
        with self._lock:
            return tuple(self._metrics.values())

    def event_records(self, task_id: object | None = None) -> tuple[StrategyEventRecord, ...]:
        """Return event records, optionally filtered by task."""
        return self._filter_task(self.events, task_id=task_id)

    def trade_summaries(self, task_id: object | None = None) -> tuple[TradeSummary, ...]:
        """Return trade summaries, optionally filtered by task."""
        return self._filter_task(self.trades, task_id=task_id)

    def cycle_summaries(self, task_id: object | None = None) -> tuple[CycleSummary, ...]:
        """Return cycle summaries, optionally filtered by task."""
        return self._filter_task(self.cycles, task_id=task_id)

    def task_summaries(self, task_id: object | None = None) -> tuple[TaskSummary, ...]:
        """Return task summaries, optionally filtered by task."""
        return self._filter_task(self.tasks, task_id=task_id)

    def profit_metrics(self, task_id: object | None = None) -> tuple[ProfitMetric, ...]:
        """Return profit metrics, optionally filtered by task."""
        return self._filter_task(self.metrics, task_id=task_id)

    @staticmethod
    def _filter_task[RecordT: ResultRecord](
        records: tuple[RecordT, ...],
        *,
        task_id: object | None,
    ) -> tuple[RecordT, ...]:
        if task_id is None:
            return records
        return tuple(record for record in records if str(record.task_id) == str(task_id))
