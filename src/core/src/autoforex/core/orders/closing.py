"""Close-trade target resolution and dry-run order construction."""

from __future__ import annotations

from autoforex.core.models.brokers import Order, OrderSide, Position, PositionSide, Trade
from autoforex.core.models.metadata import Metadata
from autoforex.core.models.values import Units
from autoforex.core.orders.matching import LogicalTradeIdResolver
from autoforex.core.ports.brokers import Broker
from autoforex.core.strategies.execution import StrategyEventRequest, TradeSide


class CloseTradeSideMapper:
    """Map strategy close sides to Core order and position sides."""

    @classmethod
    def order_side(cls, side: TradeSide) -> OrderSide:
        """Return the order side that closes a strategy trade side."""
        return OrderSide.BUY if side == TradeSide.BUY else OrderSide.SELL

    @classmethod
    def position_side_closed_by(cls, side: TradeSide) -> PositionSide:
        """Return the broker position side closed by a strategy trade side."""
        return PositionSide.SHORT if side == TradeSide.BUY else PositionSide.LONG


class CloseTradeDryRunOrderFactory:
    """Create synthetic close orders for dry-run execution."""

    def order(
        self,
        event: StrategyEventRequest,
        *,
        side: TradeSide,
        units: Units,
    ) -> Order:
        """Return a close order for a dry-run strategy request."""
        return Order(
            instrument=event.instrument,
            side=CloseTradeSideMapper.order_side(side),
            units=units,
            price=event.price,
            metadata=self.metadata(event),
        )

    @classmethod
    def metadata(cls, event: StrategyEventRequest) -> Metadata:
        """Build close-order metadata from a strategy request."""
        return Metadata.of(
            event_id=str(event.id),
            task_id=str(event.task_id),
            logical_trade_id=LogicalTradeIdResolver.from_event(event),
            reason_code=event.reason.code.value,
            reason_rule_id=event.reason.rule_id,
            reason_evidence=event.reason.evidence.to_dict(),
        ).merge(event.metadata)


class BrokerCloseTradeTargetResolver:
    """Resolve broker trades and positions affected by close requests."""

    def __init__(
        self,
        *,
        broker: Broker,
        matcher: type[LogicalTradeIdResolver] = LogicalTradeIdResolver,
    ) -> None:
        self.broker = broker
        self.matcher = matcher

    def trades(
        self,
        event: StrategyEventRequest,
        *,
        side: TradeSide,
        logical_trade_id: str,
    ) -> tuple[Trade, ...]:
        """Return open broker trades matching the requested logical trade ID."""
        target_side = CloseTradeSideMapper.position_side_closed_by(side)
        return tuple(
            trade
            for trade in self.broker.open_trades(instrument=event.instrument)
            if trade.side == target_side and self.matcher.trade_matches(trade, logical_trade_id)
        )

    def position_sides(
        self,
        event: StrategyEventRequest,
    ) -> tuple[tuple[Position, PositionSide], ...]:
        """Return open broker position sides matching the close request."""
        positions = tuple(self.broker.positions(instrument=event.instrument))
        if event.side is None:
            return tuple((position, side) for position in positions for side in position.open_sides)

        target_side = CloseTradeSideMapper.position_side_closed_by(event.side)
        return tuple(
            (position, target_side)
            for position in positions
            if (state := position.side_state(target_side)) is not None and state.is_open
        )
