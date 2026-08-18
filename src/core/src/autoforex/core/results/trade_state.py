"""Mutable trade state used while aggregating task results."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from pydantic import AwareDatetime

from autoforex.core.models.metadata import Metadata
from autoforex.core.models.money import CurrencyPair, Money
from autoforex.core.models.values import Units
from autoforex.core.results.models import StrategyEventRecord, TradeSummary
from autoforex.core.sources.models import Tick
from autoforex.core.strategies.execution import TradeSide


@dataclass(slots=True)
class TradeState:
    """Mutable state for one logical trade while a task is running."""

    task_id: UUID
    trade_id: str
    instrument: CurrencyPair
    side: TradeSide | None
    direction: str
    display_id: str
    cycle_id: int | None
    entry_role: str
    layer_number: int | None
    slot_number: int | None
    build_number: int | None
    opened_at: AwareDatetime | None
    open_event_id: UUID | None
    units: Units | None
    planned_entry_price: Money | None
    filled_entry_price: Money | None
    planned_take_profit_price: Money | None
    planned_stop_loss_price: Money | None
    metadata: Metadata = field(default_factory=Metadata)
    closed_at: AwareDatetime | None = None
    close_event_id: UUID | None = None
    close_reason: str = ""
    filled_take_profit_price: Money | None = None
    filled_stop_loss_price: Money | None = None
    planned_rebuild_price: Money | None = None
    filled_rebuild_price: Money | None = None
    realized_pl: Money | None = None

    @classmethod
    def from_open(cls, record: StrategyEventRecord) -> TradeState:
        """Create trade state from an open event record."""
        return cls(
            task_id=record.task_id,
            trade_id=record.trade_id,
            instrument=record.instrument,
            side=record.side,
            direction=record.direction,
            display_id=record.display_id,
            cycle_id=record.cycle_id,
            entry_role=record.entry_role,
            layer_number=record.layer_number,
            slot_number=record.slot_number,
            build_number=record.build_number,
            opened_at=record.timestamp,
            open_event_id=record.event_id,
            units=record.filled_units or record.units,
            planned_entry_price=record.planned_entry_price,
            filled_entry_price=record.filled_entry_price or record.price,
            planned_take_profit_price=record.planned_take_profit_price,
            planned_stop_loss_price=record.planned_stop_loss_price,
            planned_rebuild_price=record.planned_rebuild_price,
            filled_rebuild_price=record.filled_rebuild_price,
            metadata=record.metadata,
        )

    @classmethod
    def from_close_without_open(cls, record: StrategyEventRecord) -> TradeState:
        """Create partial trade state when the recorder did not see the open event."""
        state = cls(
            task_id=record.task_id,
            trade_id=record.trade_id,
            instrument=record.instrument,
            side=None,
            direction=record.direction,
            display_id=record.display_id,
            cycle_id=record.cycle_id,
            entry_role=record.entry_role,
            layer_number=record.layer_number,
            slot_number=record.slot_number,
            build_number=record.build_number,
            opened_at=None,
            open_event_id=None,
            units=record.filled_units or record.units,
            planned_entry_price=record.planned_entry_price,
            filled_entry_price=record.filled_entry_price,
            planned_take_profit_price=record.planned_take_profit_price,
            planned_stop_loss_price=record.planned_stop_loss_price,
            metadata=record.metadata,
        )
        state.apply_close(record)
        return state

    def apply_close(self, record: StrategyEventRecord) -> None:
        """Apply a close event record."""
        self.closed_at = record.timestamp
        self.close_event_id = record.event_id
        self.close_reason = record.close_reason
        self.filled_take_profit_price = record.filled_take_profit_price
        self.filled_stop_loss_price = record.filled_stop_loss_price
        self.planned_rebuild_price = record.planned_rebuild_price or self.planned_rebuild_price
        self.filled_rebuild_price = record.filled_rebuild_price or self.filled_rebuild_price
        self.realized_pl = record.realized_pl or TradeProfitCalculator.realized_from_close(
            self,
            record,
        )
        self.metadata = self.metadata.merge(record.metadata)
        if self.units is None:
            self.units = record.filled_units or record.units

    def unrealized_pl(self, tick: Tick) -> Money:
        """Calculate unrealized P/L at a tick."""
        return TradeProfitCalculator.unrealized(self, tick)

    def summary(self) -> TradeSummary:
        """Return an immutable trade summary."""
        return TradeSummaryProjector.from_state(self)


class TradeProfitCalculator:
    """Calculate realized and unrealized profit/loss for trade state."""

    @classmethod
    def realized_from_close(
        cls,
        state: TradeState,
        close_record: StrategyEventRecord,
    ) -> Money | None:
        """Calculate realized P/L from prices when metadata omits it."""
        if state.side is None or state.units is None or state.filled_entry_price is None:
            return None
        close_price = (
            close_record.filled_take_profit_price
            or close_record.filled_stop_loss_price
            or close_record.filled_rebuild_price
            or close_record.price
        )
        if close_price is None:
            return None
        if state.side == TradeSide.BUY:
            amount = (close_price.amount - state.filled_entry_price.amount) * state.units
        else:
            amount = (state.filled_entry_price.amount - close_price.amount) * state.units
        return Money.of(amount, close_price.currency)

    @classmethod
    def unrealized(cls, state: TradeState, tick: Tick) -> Money:
        """Calculate unrealized P/L at a tick."""
        if state.side is None or state.units is None or state.filled_entry_price is None:
            return Money.of("0", tick.instrument.quote)
        if state.side == TradeSide.BUY:
            amount = (tick.bid.amount - state.filled_entry_price.amount) * state.units
        else:
            amount = (state.filled_entry_price.amount - tick.ask.amount) * state.units
        return Money.of(amount, tick.instrument.quote)


class TradeSummaryProjector:
    """Create immutable trade summaries from mutable trade state."""

    @classmethod
    def from_state(cls, state: TradeState) -> TradeSummary:
        """Return an immutable trade summary."""
        return TradeSummary(
            task_id=state.task_id,
            trade_id=state.trade_id,
            instrument=state.instrument,
            side=state.side,
            direction=state.direction,
            display_id=state.display_id,
            cycle_id=state.cycle_id,
            entry_role=state.entry_role,
            layer_number=state.layer_number,
            slot_number=state.slot_number,
            build_number=state.build_number,
            opened_at=state.opened_at,
            closed_at=state.closed_at,
            open_event_id=state.open_event_id,
            close_event_id=state.close_event_id,
            close_reason=state.close_reason,
            units=state.units,
            planned_entry_price=state.planned_entry_price,
            filled_entry_price=state.filled_entry_price,
            planned_take_profit_price=state.planned_take_profit_price,
            filled_take_profit_price=state.filled_take_profit_price,
            planned_stop_loss_price=state.planned_stop_loss_price,
            filled_stop_loss_price=state.filled_stop_loss_price,
            planned_rebuild_price=state.planned_rebuild_price,
            filled_rebuild_price=state.filled_rebuild_price,
            realized_pl=state.realized_pl,
            metadata=state.metadata,
        )
