"""Profit metric collection from active trade ledger state."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from pydantic import AwareDatetime

from autoforex.core.models.identifiers import new_uuid
from autoforex.core.results.models import ProfitMetric
from autoforex.core.results.money_aggregation import MoneyAccumulator
from autoforex.core.results.trade_state import TradeState
from autoforex.core.sources.models import Tick
from autoforex.core.tasks.execution import ExecutableTask

type Task = ExecutableTask


class ProfitMetricCollector:
    """Collect interval P/L metrics for running tasks."""

    def __init__(self, interval: timedelta | None) -> None:
        self.interval = interval
        self.last_metric_at: dict[UUID, AwareDatetime] = {}
        if interval is not None:
            self._interval_seconds(interval)

    def due(self, task_id: UUID, timestamp: AwareDatetime) -> bool:
        """Return whether a task should emit a metric at a timestamp."""
        if self.interval is None:
            return False
        previous = self.last_metric_at.get(task_id)
        if previous is None:
            return True
        return timestamp - previous >= self.interval

    def mark_emitted(self, task_id: UUID, timestamp: AwareDatetime) -> None:
        """Remember the latest metric timestamp for a task."""
        self.last_metric_at[task_id] = timestamp

    def metric(
        self,
        *,
        task: Task,
        tick: Tick,
        trade_states: tuple[TradeState, ...],
    ) -> ProfitMetric:
        """Return a point-in-time profit metric."""
        if self.interval is None:
            msg = "metric interval is not configured"
            raise ValueError(msg)
        closed = tuple(state for state in trade_states if state.closed_at is not None)
        open_states = tuple(state for state in trade_states if state.closed_at is None)
        realized = MoneyAccumulator.sum(
            tuple(state.realized_pl for state in closed if state.realized_pl is not None),
            currency=tick.instrument.quote,
        )
        unrealized = MoneyAccumulator.sum(
            tuple(state.unrealized_pl(tick) for state in open_states),
            currency=tick.instrument.quote,
        )
        return ProfitMetric(
            metric_id=new_uuid(),
            task_id=task.id,
            timestamp=tick.timestamp,
            instrument=tick.instrument,
            realized_pl=realized,
            unrealized_pl=unrealized,
            total_pl=realized + unrealized,
            open_trade_count=len(open_states),
            closed_trade_count=len(closed),
            interval=self.interval,
        )

    def cleanup_task(self, task_id: UUID) -> None:
        """Remove metric state for a finished task."""
        self.last_metric_at.pop(task_id, None)

    @staticmethod
    def _interval_seconds(interval: timedelta) -> int:
        seconds = int(interval.total_seconds())
        if seconds <= 0:
            msg = "metric interval must be greater than zero"
            raise ValueError(msg)
        return seconds
