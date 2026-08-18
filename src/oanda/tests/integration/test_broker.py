from __future__ import annotations

from typing import cast

from autoforex.core import CurrencyPair, Money, Order, OrderSide, OrderStatus, PositionSide, Units

from autoforex.oanda.broker import OandaBroker
from autoforex.oanda.gateway import OandaGateway
from tests.integration.fakes import IntegrationGateway

USD_JPY = CurrencyPair.of("USD_JPY")


class TestBroker:
    def test_broker_integrates_gateway_and_mappers_without_http(self) -> None:
        gateway = IntegrationGateway()
        broker = OandaBroker(account_id="001", gateway=cast(OandaGateway, gateway))

        order = broker.place_order(
            Order(instrument=USD_JPY, side=OrderSide.BUY, units=Units("1000"))
        )
        position = broker.positions(instrument=USD_JPY)[0]
        close_order = broker.close_position(
            position=position,
            side=PositionSide.LONG,
            units=Units("250"),
        )
        trade = broker.list_open_trades()[0]
        transaction = broker.get_transactions_since("299")[0]

        assert order.status == OrderStatus.FILLED
        assert order.average_fill_price == Money.of("150.12", "JPY")
        assert position.long is not None
        assert position.long.unrealized_pl == Money.of("12.50", "USD")
        assert close_order.average_fill_price == Money.of("150.11", "JPY")
        assert trade.unrealized_pl == Money.of("12.50", "USD")
        assert transaction.amount == Money.of("1.25", "USD")
