"""In-memory trade ledger used to aggregate strategy event records."""

from __future__ import annotations

from uuid import UUID

from autoforex.core.models.money import Money
from autoforex.core.results.models import (
    CycleSummary,
    StrategyEventRecord,
    TaskSummary,
    TradeSummary,
)
from autoforex.core.results.money_aggregation import DateRange, MoneyAccumulator
from autoforex.core.results.trade_state import TradeState
from autoforex.core.tasks.execution import ExecutableTask

type Task = ExecutableTask


class TradeLedger:
    """Aggregate event records into trade, cycle, and task summaries."""

    def __init__(self) -> None:
        self.trades: dict[tuple[UUID, str], TradeState] = {}

    def record_open(self, record: StrategyEventRecord) -> TradeState:
        """Record an opened logical trade."""
        state = TradeState.from_open(record)
        self.trades[(record.task_id, state.trade_id)] = state
        return state

    def record_close(
        self,
        record: StrategyEventRecord,
    ) -> tuple[TradeSummary, CycleSummary | None]:
        """Record a closed logical trade and return updated summaries."""
        key = (record.task_id, record.trade_id)
        state = self.trades.get(key)
        if state is None:
            state = TradeState.from_close_without_open(record)
            self.trades[key] = state
        else:
            state.apply_close(record)
        summary = state.summary()
        cycle_summary = None
        if summary.cycle_id is not None:
            cycle_summary = self.cycle_summary(summary.task_id, summary.cycle_id)
        return summary, cycle_summary

    def summaries(
        self,
        *,
        memory_summaries: tuple[TradeSummary, ...] = (),
        task_id: UUID | None = None,
    ) -> tuple[TradeSummary, ...]:
        """Return latest trade summaries from memory and active ledger state."""
        summaries_by_key = {
            (summary.task_id, summary.trade_id): summary for summary in memory_summaries
        }
        summaries_by_key.update(
            ((state.task_id, state.trade_id), state.summary()) for state in self.trades.values()
        )
        summaries = tuple(summaries_by_key.values())
        if task_id is None:
            return summaries
        return tuple(summary for summary in summaries if summary.task_id == task_id)

    def cycle_summaries(
        self,
        *,
        memory_summaries: tuple[CycleSummary, ...] = (),
        task_id: UUID | None = None,
    ) -> tuple[CycleSummary, ...]:
        """Return latest cycle summaries from memory and active ledger state."""
        summaries_by_key = {
            (summary.task_id, summary.cycle_id): summary for summary in memory_summaries
        }
        cycle_keys = sorted(
            {
                (state.task_id, state.cycle_id)
                for state in self.trades.values()
                if state.cycle_id is not None
            },
            key=lambda item: (str(item[0]), item[1]),
        )
        for cycle_task_id, cycle_id in cycle_keys:
            if task_id is not None and cycle_task_id != task_id:
                continue
            summary = self.cycle_summary(cycle_task_id, cycle_id)
            if summary is not None:
                summaries_by_key[(cycle_task_id, cycle_id)] = summary
        summaries = tuple(summaries_by_key.values())
        if task_id is None:
            return summaries
        return tuple(summary for summary in summaries if summary.task_id == task_id)

    def cycle_summary(self, task_id: UUID, cycle_id: int) -> CycleSummary | None:
        """Return a cycle summary from active ledger state."""
        trades = tuple(
            state.summary()
            for state in self.trades.values()
            if state.task_id == task_id and state.cycle_id == cycle_id
        )
        if not trades:
            return None
        return CycleSummaryProjector.from_trades(trades)

    def task_summary(self, task: Task, summaries: tuple[TradeSummary, ...]) -> TaskSummary:
        """Return a task-level summary."""
        return TaskSummaryProjector.from_trades(task, summaries)

    def trade_states(self, task_id: UUID) -> tuple[TradeState, ...]:
        """Return active trade states for one task."""
        return tuple(state for state in self.trades.values() if state.task_id == task_id)

    def cleanup_task(self, task_id: UUID) -> None:
        """Remove mutable state for a finished task."""
        self.trades = {key: state for key, state in self.trades.items() if state.task_id != task_id}


class CycleSummaryProjector:
    """Create cycle summaries from trade summaries."""

    @classmethod
    def from_trades(cls, trades: tuple[TradeSummary, ...]) -> CycleSummary:
        """Return one cycle summary from trades in the same task/cycle."""
        first = trades[0]
        instrument = first.instrument
        realized = MoneyAccumulator.sum(
            tuple(trade.realized_pl for trade in trades if trade.realized_pl is not None),
            currency=instrument.quote,
        )
        return CycleSummary(
            task_id=first.task_id,
            cycle_id=first.cycle_id or 0,
            instrument=instrument,
            trade_ids=tuple(trade.trade_id for trade in trades),
            opened_at=DateRange.earliest(tuple(trade.opened_at for trade in trades)),
            closed_at=DateRange.latest(tuple(trade.closed_at for trade in trades)),
            trade_count=len(trades),
            open_trade_count=len(tuple(trade for trade in trades if not trade.is_closed)),
            closed_trade_count=len(tuple(trade for trade in trades if trade.is_closed)),
            realized_pl=realized,
        )


class TaskSummaryProjector:
    """Create task summaries from trade summaries."""

    @classmethod
    def from_trades(cls, task: Task, summaries: tuple[TradeSummary, ...]) -> TaskSummary:
        """Return a task-level summary."""
        if not summaries:
            return TaskSummary(
                task_id=task.id,
                instrument=task.instrument,
                task_name=task.name,
                status=task.status.value,
                started_at=task.started_at,
                finished_at=DateRange.finished_at(task),
                realized_pl=Money.of("0", task.instrument.quote),
            )
        realized = MoneyAccumulator.sum(
            tuple(summary.realized_pl for summary in summaries if summary.realized_pl is not None),
            currency=task.instrument.quote,
        )
        return TaskSummary(
            task_id=task.id,
            instrument=task.instrument,
            task_name=task.name,
            status=task.status.value,
            started_at=task.started_at,
            finished_at=DateRange.finished_at(task),
            trade_count=len(summaries),
            open_trade_count=len(tuple(summary for summary in summaries if not summary.is_closed)),
            closed_trade_count=len(tuple(summary for summary in summaries if summary.is_closed)),
            realized_pl=realized,
        )
