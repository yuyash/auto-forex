"""Mapping from strategy events to durable result records."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from autoforex.core.models.metadata import Metadata
from autoforex.core.models.money import Currency, Money
from autoforex.core.models.values import Units
from autoforex.core.results.models import StrategyEventRecord
from autoforex.core.strategies.execution import StrategyEvent


class StrategyEventRecordMapper:
    """Convert aggregated strategy events into flattened result records."""

    def from_event(self, event: StrategyEvent) -> StrategyEventRecord:
        """Return a durable record for one aggregated strategy event."""
        reader = StrategyEventMetadataReader(event.metadata, currency=event.instrument.quote)
        return StrategyEventRecord(
            event_id=event.id,
            task_id=event.task_id,
            timestamp=event.timestamp,
            display_id=event.display_id,
            action=event.action,
            instrument=event.instrument,
            side=event.side,
            units=event.units,
            price=event.price,
            decision=event.reason.code,
            rule=event.reason.rule_id,
            metadata=event.metadata,
            snowball_event=reader.text("snowball_event"),
            cycle_id=reader.integer("cycle_id"),
            direction=reader.text("direction"),
            entry_id=reader.text("entry_id"),
            entry_type=reader.text("entry_type"),
            entry_role=reader.text("entry_role"),
            layer_number=reader.integer("layer_number"),
            slot_number=reader.integer("slot_number"),
            retracement_count=reader.integer("retracement_count"),
            build_number=reader.integer("build_number"),
            close_reason=reader.text("close_reason"),
            is_rebuild=reader.boolean("is_rebuild"),
            planned_units=reader.units("planned_units"),
            filled_units=reader.units("filled_units"),
            planned_entry_price=reader.money("planned_entry_price"),
            filled_entry_price=reader.money("filled_entry_price"),
            planned_take_profit_price=reader.money("planned_take_profit_price"),
            filled_take_profit_price=reader.money("filled_take_profit_price"),
            planned_stop_loss_price=reader.money("planned_stop_loss_price"),
            filled_stop_loss_price=reader.money("filled_stop_loss_price"),
            planned_rebuild_price=reader.money("planned_rebuild_price"),
            filled_rebuild_price=reader.money("filled_rebuild_price"),
            realized_pl=reader.money("realized_pl"),
        )


class StrategyEventMetadataReader:
    """Read typed values from strategy event metadata."""

    def __init__(self, metadata: Metadata, *, currency: Currency) -> None:
        self.metadata = metadata
        self.currency = currency

    def text(self, key: str) -> str:
        """Return a metadata value as a string, or an empty string when absent."""
        value = self.metadata.get(key)
        if value is None:
            return ""
        return str(value)

    def integer(self, key: str) -> int | None:
        """Return a metadata value as an integer."""
        value = self.metadata.get(key)
        if value is None or value == "":
            return None
        return int(value)

    def boolean(self, key: str) -> bool:
        """Return a metadata value as a boolean."""
        value = self.metadata.get(key)
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).lower() in {"1", "true", "yes"}

    def units(self, key: str) -> Units | None:
        """Return a metadata value as units."""
        value = self.metadata.get(key)
        if value is None or value == "":
            return None
        return Units.of(str(value))

    def money(self, key: str) -> Money | None:
        """Return a metadata value as money in the event instrument quote currency."""
        value = self.metadata.get(key)
        if value is None or value == "":
            return None
        if isinstance(value, Money):
            return value.require_currency(self.currency)
        if isinstance(value, dict):
            return Money.model_validate(value).require_currency(self.currency)
        text = str(value).strip()
        if not text:
            return None
        parts = text.split()
        if len(parts) == 2:
            amount_text, currency_text = parts
            try:
                return Money.of(Decimal(amount_text), currency_text).require_currency(self.currency)
            except InvalidOperation as exc:
                msg = f"invalid money amount in metadata {key}: {amount_text}"
                raise ValueError(msg) from exc
        return Money.of(text, self.currency)
