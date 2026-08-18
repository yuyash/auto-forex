"""Factories for broker-neutral orders."""

from __future__ import annotations

from autoforex.core.models.brokers import Order, OrderSide
from autoforex.core.models.metadata import Metadata
from autoforex.core.models.values import Units
from autoforex.core.strategies.execution import StrategyEventRequest, TradeSide


class OrderFactory:
    """Create broker-neutral orders from strategy events."""

    def open_trade_order(
        self,
        *,
        event: StrategyEventRequest,
        side: TradeSide,
        units: Units,
    ) -> Order:
        """Create a broker-neutral order for an open-trade strategy event."""
        logical_trade_id = event.display_id or str(event.metadata.get("entry_id", ""))
        return Order(
            instrument=event.instrument,
            side=self._order_side(side),
            units=units,
            price=event.price,
            metadata=Metadata.of(
                event_id=str(event.id),
                task_id=str(event.task_id),
                logical_trade_id=logical_trade_id,
                reason_code=event.reason.code.value,
                reason_rule_id=event.reason.rule_id,
                reason_evidence=event.reason.evidence.to_dict(),
            ).merge(event.metadata),
        )

    @staticmethod
    def _order_side(side: TradeSide) -> OrderSide:
        return OrderSide.BUY if side == TradeSide.BUY else OrderSide.SELL
