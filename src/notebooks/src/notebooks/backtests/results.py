"""Reusable result DataFrame builders for backtest notebooks."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import tzinfo
from typing import Any

import pandas as pd
from autoforex.core import TaskResultRecorder
from autoforex.core.results.models import (
    CycleSummary,
    ProfitMetric,
    StrategyEventRecord,
    TaskSummary,
    TradeSummary,
)
from autoforex.core.tasks.execution import ExecutableTask


@dataclass(frozen=True, slots=True)
class NotebookValueFormatter:
    """Format Core result values for notebook tables and charts."""

    timezone: tzinfo

    def datetime(self, value: Any) -> Any:
        """Return a local-time datetime when a value is present."""
        return value.astimezone(self.timezone) if value is not None else None

    def text(self, value: Any) -> str | None:
        """Return a display string while preserving missing values."""
        return str(value) if value is not None else None

    def money_amount(self, value: Any) -> float | None:
        """Return a numeric amount for charting Money values."""
        return None if value is None else float(value.amount)


@dataclass(frozen=True, slots=True)
class TaskResultFrames:
    """Notebook DataFrames built from a task result recorder."""

    events: pd.DataFrame
    trades: pd.DataFrame
    cycles: pd.DataFrame
    task: pd.DataFrame
    metrics: pd.DataFrame

    @property
    def signals(self) -> pd.DataFrame:
        """Return strategy event records under the notebook's historical name."""
        return self.events


@dataclass(frozen=True, slots=True)
class TaskResultFrameBuilder:
    """Build display-oriented DataFrames from Core result records."""

    timezone: tzinfo
    formatter: NotebookValueFormatter = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "formatter", NotebookValueFormatter(self.timezone))

    def from_recorder(
        self,
        *,
        recorder: TaskResultRecorder,
        task: ExecutableTask,
    ) -> TaskResultFrames:
        """Build all standard result frames for a completed task."""
        task_id = task.id
        task_summary = recorder.task_summary(task)
        return TaskResultFrames(
            events=self.events(recorder.event_records(task_id)),
            trades=self.trades(recorder.trade_summaries(task_id)),
            cycles=self.cycles(recorder.cycle_summaries(task_id)),
            task=self.task(task_summary),
            metrics=self.metrics(
                metric for metric in recorder.memory.metrics if metric.task_id == task_id
            ),
        )

    def events(self, events: Any) -> pd.DataFrame:
        """Build the strategy event frame."""
        return pd.DataFrame(self._event_row(event) for event in events)

    def trades(self, trades: Any) -> pd.DataFrame:
        """Build the trade summary frame sorted by open time."""
        frame = pd.DataFrame(self._trade_row(trade) for trade in trades)
        return self._sort(frame, by="opened_at")

    def cycles(self, cycles: Any) -> pd.DataFrame:
        """Build the cycle summary frame sorted by cycle id."""
        frame = pd.DataFrame(self._cycle_row(cycle) for cycle in cycles)
        return self._sort(frame, by="cycle_id")

    def task(self, summary: TaskSummary | None) -> pd.DataFrame:
        """Build the task summary frame."""
        if summary is None:
            return pd.DataFrame()
        return pd.DataFrame([self._task_row(summary)])

    def metrics(self, metrics: Any) -> pd.DataFrame:
        """Build the profit metric frame for charting."""
        return pd.DataFrame(self._metric_row(metric) for metric in metrics)

    def _event_row(self, event: StrategyEventRecord) -> dict[str, Any]:
        formatter = self.formatter
        return {
            "timestamp": formatter.datetime(event.timestamp),
            "action": event.action.value,
            "display_id": event.display_id,
            "units": formatter.text(event.units),
            "price": formatter.text(event.price),
            "rule": event.rule,
            "cycle_id": event.cycle_id,
            "direction": event.direction,
            "entry_role": event.entry_role,
            "layer_number": event.layer_number,
            "slot_number": event.slot_number,
            "build_number": event.build_number,
            "close_reason": event.close_reason,
            "is_rebuild": event.is_rebuild,
            "planned_entry_price": formatter.text(event.planned_entry_price),
            "filled_entry_price": formatter.text(event.filled_entry_price),
            "planned_take_profit_price": formatter.text(event.planned_take_profit_price),
            "filled_take_profit_price": formatter.text(event.filled_take_profit_price),
            "planned_stop_loss_price": formatter.text(event.planned_stop_loss_price),
            "filled_stop_loss_price": formatter.text(event.filled_stop_loss_price),
            "planned_rebuild_price": formatter.text(event.planned_rebuild_price),
            "filled_rebuild_price": formatter.text(event.filled_rebuild_price),
            "realized_pl": formatter.text(event.realized_pl),
        }

    def _trade_row(self, trade: TradeSummary) -> dict[str, Any]:
        formatter = self.formatter
        return {
            "trade_id": trade.trade_id,
            "instrument": trade.instrument,
            "side": None if trade.side is None else trade.side.value,
            "direction": trade.direction,
            "display_id": trade.display_id,
            "cycle_id": trade.cycle_id,
            "entry_role": trade.entry_role,
            "layer_number": trade.layer_number,
            "slot_number": trade.slot_number,
            "build_number": trade.build_number,
            "opened_at": formatter.datetime(trade.opened_at),
            "closed_at": formatter.datetime(trade.closed_at),
            "close_reason": trade.close_reason,
            "units": formatter.text(trade.units),
            "planned_entry_price": formatter.text(trade.planned_entry_price),
            "filled_entry_price": formatter.text(trade.filled_entry_price),
            "planned_take_profit_price": formatter.text(trade.planned_take_profit_price),
            "filled_take_profit_price": formatter.text(trade.filled_take_profit_price),
            "planned_stop_loss_price": formatter.text(trade.planned_stop_loss_price),
            "filled_stop_loss_price": formatter.text(trade.filled_stop_loss_price),
            "planned_rebuild_price": formatter.text(trade.planned_rebuild_price),
            "filled_rebuild_price": formatter.text(trade.filled_rebuild_price),
            "realized_pl": formatter.text(trade.realized_pl),
        }

    def _cycle_row(self, cycle: CycleSummary) -> dict[str, Any]:
        formatter = self.formatter
        return {
            "cycle_id": cycle.cycle_id,
            "instrument": cycle.instrument,
            "trade_ids": list(cycle.trade_ids),
            "opened_at": formatter.datetime(cycle.opened_at),
            "closed_at": formatter.datetime(cycle.closed_at),
            "trade_count": cycle.trade_count,
            "open_trade_count": cycle.open_trade_count,
            "closed_trade_count": cycle.closed_trade_count,
            "realized_pl": formatter.text(cycle.realized_pl),
        }

    def _task_row(self, summary: TaskSummary) -> dict[str, Any]:
        formatter = self.formatter
        return {
            "task_id": summary.task_id,
            "instrument": summary.instrument,
            "task_name": summary.task_name,
            "status": summary.status,
            "started_at": formatter.datetime(summary.started_at),
            "finished_at": formatter.datetime(summary.finished_at),
            "trade_count": summary.trade_count,
            "open_trade_count": summary.open_trade_count,
            "closed_trade_count": summary.closed_trade_count,
            "realized_pl": formatter.text(summary.realized_pl),
        }

    def _metric_row(self, metric: ProfitMetric) -> dict[str, Any]:
        formatter = self.formatter
        return {
            "timestamp": formatter.datetime(metric.timestamp),
            "realized_pl": formatter.money_amount(metric.realized_pl),
            "unrealized_pl": formatter.money_amount(metric.unrealized_pl),
            "total_pl": formatter.money_amount(metric.total_pl),
            "currency": metric.total_pl.currency.code,
            "open_trade_count": metric.open_trade_count,
            "closed_trade_count": metric.closed_trade_count,
        }

    @staticmethod
    def _sort(frame: pd.DataFrame, *, by: str) -> pd.DataFrame:
        if frame.empty or by not in frame.columns:
            return frame
        return frame.sort_values(by, kind="stable", na_position="last").reset_index(drop=True)
