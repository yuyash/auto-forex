"""Buffered result-store flushing."""

from __future__ import annotations

from dataclasses import dataclass, field

from autoforex.core.results.models import (
    CycleSummary,
    ProfitMetric,
    StrategyEventRecord,
    TaskSummary,
    TradeSummary,
)
from autoforex.core.results.stores import ResultBatch, ResultStore


@dataclass(slots=True)
class ResultBatchBuffer:
    """Mutable per-store buffer for result records waiting to be flushed."""

    events: list[StrategyEventRecord] = field(default_factory=list)
    trades: list[TradeSummary] = field(default_factory=list)
    cycles: list[CycleSummary] = field(default_factory=list)
    tasks: list[TaskSummary] = field(default_factory=list)
    metrics: list[ProfitMetric] = field(default_factory=list)

    def add_event(self, record: StrategyEventRecord) -> None:
        """Queue one event record."""
        self.events.append(record)

    def add_trade(self, summary: TradeSummary) -> None:
        """Queue one trade summary."""
        self.trades.append(summary)

    def add_cycle(self, summary: CycleSummary) -> None:
        """Queue one cycle summary."""
        self.cycles.append(summary)

    def add_task(self, summary: TaskSummary) -> None:
        """Queue one task summary."""
        self.tasks.append(summary)

    def add_metric(self, metric: ProfitMetric) -> None:
        """Queue one metric."""
        self.metrics.append(metric)

    def batch(self) -> ResultBatch:
        """Return an immutable snapshot of queued records."""
        return ResultBatch(
            events=tuple(self.events),
            trades=tuple(self.trades),
            cycles=tuple(self.cycles),
            tasks=tuple(self.tasks),
            metrics=tuple(self.metrics),
        )

    @property
    def is_empty(self) -> bool:
        """Return whether this buffer contains no records."""
        return self.batch().is_empty

    def clear(self) -> None:
        """Clear queued records after a successful store flush."""
        self.events.clear()
        self.trades.clear()
        self.cycles.clear()
        self.tasks.clear()
        self.metrics.clear()


class ResultFlushCoordinator:
    """Coordinate batched writes to external result stores."""

    def __init__(self, stores: tuple[ResultStore, ...], *, flush_every: int) -> None:
        self.stores = stores
        self.flush_every = self._validated_flush_every(flush_every)
        self.buffers = tuple(ResultBatchBuffer() for _ in stores)
        self.pending_count = 0

    def queue_event(self, record: StrategyEventRecord) -> None:
        """Queue an event record."""
        for buffer in self.buffers:
            buffer.add_event(record)
        self.flush_if_due()

    def queue_trade(self, summary: TradeSummary) -> None:
        """Queue a trade summary."""
        for buffer in self.buffers:
            buffer.add_trade(summary)
        self.flush_if_due()

    def queue_cycle(self, summary: CycleSummary) -> None:
        """Queue a cycle summary."""
        for buffer in self.buffers:
            buffer.add_cycle(summary)
        self.flush_if_due()

    def queue_task(self, summary: TaskSummary) -> None:
        """Queue a task summary."""
        for buffer in self.buffers:
            buffer.add_task(summary)
        self.flush_if_due()

    def queue_metric(self, metric: ProfitMetric) -> None:
        """Queue a profit metric."""
        for buffer in self.buffers:
            buffer.add_metric(metric)
        self.flush_if_due()

    def flush_if_due(self) -> None:
        """Flush queued batches once the configured threshold is reached."""
        if not self.buffers:
            return
        self.pending_count += 1
        if self.pending_count >= self.flush_every:
            self.flush()

    def flush(self) -> None:
        """Flush buffered result records to external stores."""
        if not self.buffers:
            self.pending_count = 0
            return
        for store, buffer in zip(self.stores, self.buffers, strict=True):
            batch = buffer.batch()
            if batch.is_empty:
                continue
            store.save_batch(batch)
            buffer.clear()
        if all(buffer.is_empty for buffer in self.buffers):
            self.pending_count = 0

    @staticmethod
    def _validated_flush_every(value: int) -> int:
        if value <= 0:
            msg = "flush_every must be greater than zero"
            raise ValueError(msg)
        return value
