"""Result store contracts and batch models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from autoforex.core.results.models import (
    CycleSummary,
    ProfitMetric,
    StrategyEventRecord,
    TaskSummary,
    TradeSummary,
)


@dataclass(frozen=True, slots=True)
class ResultBatch:
    """Batch of result records flushed to an external result store."""

    events: tuple[StrategyEventRecord, ...] = ()
    trades: tuple[TradeSummary, ...] = ()
    cycles: tuple[CycleSummary, ...] = ()
    tasks: tuple[TaskSummary, ...] = ()
    metrics: tuple[ProfitMetric, ...] = ()

    @property
    def is_empty(self) -> bool:
        """Return whether the batch contains no records."""
        return not (self.events or self.trades or self.cycles or self.tasks or self.metrics)


class ProfitMetricStore(Protocol):
    """Persistence boundary for point-in-time P/L metrics."""

    def save_metric(self, metric: ProfitMetric) -> None:
        """Persist one profit metric."""


class ResultStore(ProfitMetricStore, Protocol):
    """Persistence boundary for task result records and summaries."""

    def save_event(self, record: StrategyEventRecord) -> None:
        """Persist one flattened strategy event."""

    def save_trade(self, summary: TradeSummary) -> None:
        """Persist one trade summary."""

    def save_cycle(self, summary: CycleSummary) -> None:
        """Persist one cycle summary."""

    def save_task(self, summary: TaskSummary) -> None:
        """Persist one task summary."""

    def save_batch(self, batch: ResultBatch) -> None:
        """Persist a batch of result records."""


class ResultReader(Protocol):
    """Read boundary for persisted task result records and summaries."""

    def event_records(self, task_id: object | None = None) -> tuple[StrategyEventRecord, ...]:
        """Return strategy event records."""

    def trade_summaries(self, task_id: object | None = None) -> tuple[TradeSummary, ...]:
        """Return trade summaries."""

    def cycle_summaries(self, task_id: object | None = None) -> tuple[CycleSummary, ...]:
        """Return cycle summaries."""

    def task_summaries(self, task_id: object | None = None) -> tuple[TaskSummary, ...]:
        """Return task summaries."""

    def profit_metrics(self, task_id: object | None = None) -> tuple[ProfitMetric, ...]:
        """Return profit metrics."""
