"""Event builder service for Snowball strategy entries."""

from __future__ import annotations

from decimal import Decimal

from apps.trading.dataclasses.tick import Tick
from apps.trading.enums import EventType
from apps.trading.events import (
    ClosePositionEvent,
    OpenPositionEvent,
    RebuildPositionEvent,
    StrategyEvent,
)
from apps.trading.money import AccountCurrency
from apps.trading.strategies.snowball.entries import Entry
from apps.trading.utils import Instrument


class SnowballEventFactory:
    """Build Snowball strategy events from entry state."""

    def apply_entry_metadata(
        self,
        entry: Entry,
        event: StrategyEvent,
        *,
        close_reason: str = "",
        actual_tp_pips: Decimal | None = None,
        actual_exit_price: Decimal | None = None,
    ) -> None:
        event.strategy_type = "snowball"
        event.basket = entry.role
        event.root_entry_id = entry.root_entry_id
        event.parent_entry_id = entry.parent_entry_id
        event.visual_group_id = str(entry.root_entry_id) if entry.root_entry_id is not None else ""
        event.step = entry.step
        event.close_reason = close_reason
        event.validation_status = entry.validation_status
        event.expected_interval_pips = entry.expected_interval_pips
        event.actual_interval_pips = entry.actual_interval_pips
        event.expected_tp_pips = entry.expected_tp_pips
        event.actual_tp_pips = actual_tp_pips
        event.expected_exit_price = entry.close_price
        event.actual_exit_price = actual_exit_price

    def entry_open_event(
        self,
        entry: Entry,
        *,
        timestamp,
        execution_price: Decimal | None = None,
        planned_exit_price_formula: str | None = None,
        description: str = "",
    ) -> OpenPositionEvent:
        event_price = execution_price if execution_price is not None else entry.entry_price
        event = OpenPositionEvent(
            event_type=EventType.OPEN_POSITION,
            timestamp=timestamp,
            layer_number=entry.layer_number,
            direction=entry.direction.value,
            price=event_price,
            planned_entry_price=entry.entry_price if execution_price is not None else None,
            units=entry.units,
            entry_id=entry.entry_id,
            retracement_count=entry.retracement_count,
            strategy_event_type=f"snowball_{entry.role}",
            planned_exit_price=entry.close_price,
            planned_exit_price_formula=planned_exit_price_formula,
            stop_loss_price=entry.stop_loss_price,
            description=description,
        )
        self.apply_entry_metadata(entry, event)
        return event

    def entry_rebuild_event(
        self,
        entry: Entry,
        *,
        timestamp,
        execution_price: Decimal | None = None,
        original_position_id: str | None = None,
        description: str = "",
    ) -> RebuildPositionEvent:
        event_price = execution_price if execution_price is not None else entry.entry_price
        event = RebuildPositionEvent(
            event_type=EventType.REBUILD_POSITION,
            timestamp=timestamp,
            layer_number=entry.layer_number,
            direction=entry.direction.value,
            price=event_price,
            planned_entry_price=entry.entry_price if execution_price is not None else None,
            units=entry.units,
            entry_id=entry.entry_id,
            retracement_count=entry.retracement_count,
            strategy_event_type=f"snowball_{entry.role}",
            planned_exit_price=entry.close_price,
            stop_loss_price=entry.stop_loss_price,
            description=description,
            original_position_id=original_position_id,
        )
        self.apply_entry_metadata(entry, event)
        return event

    def entry_close_event(
        self,
        entry: Entry,
        tick: Tick,
        *,
        instrument: str,
        pip_size: Decimal,
        account_currency: str,
        description: str = "",
        close_reason: str = "",
        actual_tp_pips: Decimal | None = None,
        validation_status: str = "",
    ) -> ClosePositionEvent:
        exit_px = entry.exit_price(tick)
        conv = Instrument(instrument).quote_to_account_rate(
            tick.mid,
            AccountCurrency(account_currency),
        )
        pnl = (exit_px - entry.entry_price) * Decimal(str(entry.units)) * conv
        if entry.is_short:
            pnl = -pnl

        event = ClosePositionEvent(
            event_type=EventType.CLOSE_POSITION,
            timestamp=tick.timestamp,
            layer_number=entry.layer_number,
            direction=entry.direction.value,
            entry_price=entry.entry_price,
            exit_price=exit_px,
            units=entry.units,
            pnl=pnl,
            pips=abs(exit_px - entry.entry_price) / pip_size,
            entry_id=entry.entry_id,
            position_id=entry.position_id,
            retracement_count=entry.retracement_count,
            description=description,
        )
        original_status = entry.validation_status
        if validation_status:
            entry.validation_status = validation_status
        self.apply_entry_metadata(
            entry,
            event,
            close_reason=close_reason,
            actual_tp_pips=actual_tp_pips,
            actual_exit_price=exit_px,
        )
        entry.validation_status = original_status
        return event


SNOWBALL_EVENTS = SnowballEventFactory()
