from autoforex.core import (
    BrokerOrderId,
    BrokerPositionId,
    BrokerTransactionId,
    CurrencyPair,
    Metadata,
    Money,
    Order,
    OrderId,
    OrderMessageKey,
    OrderReason,
    OrderReasonCode,
    OrderSide,
    OrderStatus,
    Position,
    PositionSide,
    Transaction,
    Units,
)

USD_JPY = CurrencyPair.of("USD_JPY")


class TestModels:
    def test_order_id_is_uuidv7_value_object(self) -> None:
        order_id = OrderId.new()

        assert order_id.value.version == 7
        assert OrderId.of(str(order_id)) == order_id
        assert OrderId.of(order_id.value) == order_id

    def test_broker_ids_order_reason_and_transaction_are_value_objects(self) -> None:
        broker_order_id = BrokerOrderId.of(" order-1 ")
        broker_position_id = BrokerPositionId.of("position-1")
        reason = OrderReason(
            code=OrderReasonCode.REJECTED,
            details=Metadata.of(raw_reason="INSUFFICIENT_MARGIN"),
        )

        order = Order(
            status=OrderStatus.REJECTED,
            broker_order_id=broker_order_id,
            instrument=USD_JPY,
            side=OrderSide.BUY,
            units=Units("1000"),
            reason=reason,
        )
        position = Position.model_validate(
            {
                "instrument": USD_JPY,
                "long": {
                    "broker_position_id": broker_position_id,
                    "units": Units("1000"),
                    "average_entry_price": Money.of("150.10", "JPY"),
                },
            }
        )
        transaction = Transaction(
            id=BrokerTransactionId.of("tx-1"),
            type="ORDER_FILL",
            instrument=USD_JPY,
            order_id=broker_order_id,
        )

        assert str(broker_order_id) == "order-1"
        assert order.reason.message_key == OrderMessageKey.REJECTED
        assert position.long is not None
        assert position.long.side == PositionSide.LONG
        assert position.open_sides == (PositionSide.LONG,)
        assert position.evolve(unrealized_pl=Money.of("12.50", "USD")).unrealized_pl == Money.of(
            "12.50",
            "USD",
        )
        assert str(transaction.id) == "tx-1"

    def test_order_normalizes_price_currency(self) -> None:
        order = Order(
            instrument=USD_JPY,
            side=OrderSide.BUY,
            units=Units("1000"),
            price=Money.of("150.12", "JPY"),
        )

        assert order.status == OrderStatus.PENDING
        assert order.price == Money.of("150.12", "JPY")
