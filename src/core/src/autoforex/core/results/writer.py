"""Write recorder outputs to memory, batch stores, and metric stores."""

from __future__ import annotations

from autoforex.core.results.buffering import ResultFlushCoordinator
from autoforex.core.results.models import (
    CycleSummary,
    ProfitMetric,
    StrategyEventRecord,
    TaskSummary,
    TradeSummary,
)
from autoforex.core.results.stores import InMemoryResultStore, ProfitMetricStore, ResultStore


class ResultRecorderWriter:
    """Persist result records to in-memory and external stores."""

    def __init__(
        self,
        *,
        stores: tuple[ResultStore, ...] | None,
        metric_stores: tuple[ProfitMetricStore, ...],
        flush_every: int,
    ) -> None:
        self.memory = InMemoryResultStore()
        self.external_stores = tuple(stores or ())
        self.stores = (self.memory, *self.external_stores)
        self.metric_stores = metric_stores
        self.flusher = ResultFlushCoordinator(self.external_stores, flush_every=flush_every)

    def event(self, record: StrategyEventRecord) -> None:
        """Save one strategy event record."""
        self.memory.save_event(record)
        self.flusher.queue_event(record)

    def trade(self, summary: TradeSummary) -> None:
        """Save one trade summary."""
        self.memory.save_trade(summary)
        self.flusher.queue_trade(summary)

    def cycle(self, summary: CycleSummary) -> None:
        """Save one cycle summary."""
        self.memory.save_cycle(summary)
        self.flusher.queue_cycle(summary)

    def task(self, summary: TaskSummary) -> None:
        """Save one task summary."""
        self.memory.save_task(summary)
        self.flusher.queue_task(summary)

    def metric(self, metric: ProfitMetric) -> None:
        """Save one metric sample."""
        self.memory.save_metric(metric)
        self.flusher.queue_metric(metric)
        for store in self.metric_stores:
            store.save_metric(metric)

    def flush(self) -> None:
        """Flush buffered result records to external stores."""
        self.flusher.flush()
