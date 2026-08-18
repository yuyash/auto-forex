"""Task result records and profit metric models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from uuid import UUID

from pydantic import AwareDatetime

from autoforex.core.models.metadata import Metadata
from autoforex.core.models.money import CurrencyPair, Money
from autoforex.core.models.values import Units
from autoforex.core.strategies.execution import StrategyAction, StrategyDecisionCode, TradeSide


@dataclass(frozen=True, slots=True)
class StrategyEventRecord:
    """Flattened strategy event suitable for notebooks and persistence."""

    event_id: UUID
    task_id: UUID
    timestamp: AwareDatetime
    display_id: str
    action: StrategyAction
    instrument: CurrencyPair
    side: TradeSide | None
    units: Units | None
    price: Money | None
    decision: StrategyDecisionCode
    rule: str
    metadata: Metadata = field(default_factory=Metadata)
    snowball_event: str = ""
    cycle_id: int | None = None
    direction: str = ""
    entry_id: str = ""
    entry_type: str = ""
    entry_role: str = ""
    layer_number: int | None = None
    slot_number: int | None = None
    retracement_count: int | None = None
    build_number: int | None = None
    close_reason: str = ""
    is_rebuild: bool = False
    planned_units: Units | None = None
    filled_units: Units | None = None
    planned_entry_price: Money | None = None
    filled_entry_price: Money | None = None
    planned_take_profit_price: Money | None = None
    filled_take_profit_price: Money | None = None
    planned_stop_loss_price: Money | None = None
    filled_stop_loss_price: Money | None = None
    planned_rebuild_price: Money | None = None
    filled_rebuild_price: Money | None = None
    realized_pl: Money | None = None

    @property
    def trade_id(self) -> str:
        """Return the stable logical trade identifier."""
        if self.display_id:
            return self.display_id
        if self.entry_id:
            return self.entry_id
        return str(self.event_id)


@dataclass(frozen=True, slots=True)
class TradeSummary:
    """One logical trade with realized P/L when it has been closed."""

    task_id: UUID
    trade_id: str
    instrument: CurrencyPair
    side: TradeSide | None = None
    direction: str = ""
    display_id: str = ""
    cycle_id: int | None = None
    entry_role: str = ""
    layer_number: int | None = None
    slot_number: int | None = None
    build_number: int | None = None
    opened_at: AwareDatetime | None = None
    closed_at: AwareDatetime | None = None
    open_event_id: UUID | None = None
    close_event_id: UUID | None = None
    close_reason: str = ""
    units: Units | None = None
    planned_entry_price: Money | None = None
    filled_entry_price: Money | None = None
    planned_take_profit_price: Money | None = None
    filled_take_profit_price: Money | None = None
    planned_stop_loss_price: Money | None = None
    filled_stop_loss_price: Money | None = None
    planned_rebuild_price: Money | None = None
    filled_rebuild_price: Money | None = None
    realized_pl: Money | None = None
    metadata: Metadata = field(default_factory=Metadata)

    @property
    def is_closed(self) -> bool:
        """Return whether this trade has a close event."""
        return self.closed_at is not None


@dataclass(frozen=True, slots=True)
class CycleSummary:
    """Aggregated P/L and trade membership for one strategy cycle."""

    task_id: UUID
    cycle_id: int
    instrument: CurrencyPair
    trade_ids: tuple[str, ...]
    opened_at: AwareDatetime | None
    closed_at: AwareDatetime | None
    trade_count: int
    open_trade_count: int
    closed_trade_count: int
    realized_pl: Money
    metadata: Metadata = field(default_factory=Metadata)


@dataclass(frozen=True, slots=True)
class TaskSummary:
    """Aggregated P/L for a task."""

    task_id: UUID
    instrument: CurrencyPair
    task_name: str = ""
    status: str = ""
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    trade_count: int = 0
    open_trade_count: int = 0
    closed_trade_count: int = 0
    realized_pl: Money | None = None
    metadata: Metadata = field(default_factory=Metadata)


@dataclass(frozen=True, slots=True)
class ProfitMetric:
    """Point-in-time realized and unrealized P/L metric."""

    metric_id: UUID
    task_id: UUID
    timestamp: AwareDatetime
    instrument: CurrencyPair
    realized_pl: Money
    unrealized_pl: Money
    total_pl: Money
    open_trade_count: int
    closed_trade_count: int
    interval: timedelta
    metadata: Metadata = field(default_factory=Metadata)

    @property
    def interval_seconds(self) -> int:
        """Return a positive integer number of seconds for the metric interval."""
        seconds = int(self.interval.total_seconds())
        if seconds <= 0:
            msg = "metric interval must be greater than zero"
            raise ValueError(msg)
        return seconds
