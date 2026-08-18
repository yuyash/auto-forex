from autoforex.core import (
    BrokerOrderId,
    CurrencyPair,
    Money,
    Order,
    OrderSide,
    OrderStatus,
    Position,
    PositionSide,
    Trade,
    Units,
)
from autoforex.core.ports import Broker


class MemoryBroker(Broker):
    def __init__(self) -> None:
        self.orders: list[Order] = []

    def place_order(self, order: Order) -> Order:
        self.orders.append(order)
        return order.evolve(
            status=OrderStatus.FILLED,
            broker_order_id=BrokerOrderId.of("order-1"),
            filled_units=order.units,
            average_fill_price=order.price,
        )

    def close_position(
        self,
        *,
        position: Position,
        side: PositionSide,
        units: Units | None = None,
    ) -> Order:
        state = position.require_side(side)
        amount = units or state.units
        return Order(
            status=OrderStatus.FILLED,
            broker_order_id=BrokerOrderId.of("close-order-1"),
            instrument=position.instrument,
            side=OrderSide.SELL if side == PositionSide.LONG else OrderSide.BUY,
            units=amount,
            filled_units=amount,
            average_fill_price=state.average_entry_price,
        )

    def positions(self, *, instrument: CurrencyPair | None = None) -> tuple[Position, ...]:
        _ = instrument
        return ()

    def trades(self, *, instrument: CurrencyPair | None = None) -> tuple[Trade, ...]:
        _ = instrument
        return ()

    def close_trade(self, trade: Trade, *, units: Units | None = None) -> Order:
        amount = units or trade.units
        return Order(
            status=OrderStatus.FILLED,
            broker_order_id=BrokerOrderId.of("close-order-1"),
            instrument=trade.instrument,
            side=OrderSide.SELL if trade.side == PositionSide.LONG else OrderSide.BUY,
            units=amount,
            filled_units=amount,
            average_fill_price=trade.price,
        )


class TestBase:
    def test_broker_port_can_be_implemented(self) -> None:
        broker = MemoryBroker()
        order = Order(
            instrument=CurrencyPair.of("USD_JPY"),
            side=OrderSide.BUY,
            units=Units("1000"),
            price=Money.of("150.12", "JPY"),
        )

        result = broker.place_order(order)

        assert result.status == OrderStatus.FILLED
        assert broker.orders == [order]
