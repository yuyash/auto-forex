from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import cast

from autoforex.core import (
    CandleGranularity,
    Currency,
    CurrencyPair,
    Metadata,
    Money,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    Units,
)

import autoforex.oanda.models as om
from autoforex.oanda.mappers import (
    OandaAccountMapper,
    OandaInstrumentMapper,
    OandaMarketDataMapper,
    OandaOrderMapper,
    OandaPositionMapper,
    OandaTradeMapper,
    OandaTransactionMapper,
)
from tests.support import FakeResponse, candle_namespace, price_namespace

USD_JPY = CurrencyPair.of("USD_JPY")


class TestMappers:
    def test_instrument_mapper_converts_between_core_and_oanda_symbols(self) -> None:
        assert OandaInstrumentMapper.to_oanda(USD_JPY) == "USD_JPY"
        assert OandaInstrumentMapper.to_core("USD_JPY") == USD_JPY

    def test_account_mapper_maps_properties_summary_and_currency(self) -> None:
        account = OandaAccountMapper.account_from_properties(
            SimpleNamespace(id="001", alias="primary", mt4AccountID=123, tags=("demo",))
        )
        response = cast(
            om.OandaResponse[om.AccountSummaryResponse],
            FakeResponse(
                200,
                {
                    "account": {
                        "id": "001",
                        "currency": "USD",
                        "alias": "primary",
                        "balance": "1000.00",
                        "NAV": "1001.00",
                        "marginUsed": "10.00",
                        "marginAvailable": "991.00",
                        "marginRate": "0.02",
                        "createdTime": "2026-01-01T00:00:00.000000000Z",
                    },
                    "lastTransactionID": "10",
                },
            ),
        )
        summary = OandaAccountMapper.summary_from_response(response)

        assert account.id.value == "001"
        assert account.provider is not None
        assert summary.balance == Money.of("1000.00", "USD")
        assert OandaAccountMapper.account_currency_from_response(response).code == "USD"

    def test_order_mapper_builds_request_and_maps_fill_response(self) -> None:
        order = Order(
            instrument=USD_JPY,
            side=OrderSide.SELL,
            units=Units("1000"),
            order_type=OrderType.MARKET,
        )
        response = cast(
            om.OandaResponse[om.OrderTransactionResponse],
            FakeResponse(
                201,
                {
                    "orderCreateTransaction": SimpleNamespace(id="100"),
                    "orderFillTransaction": SimpleNamespace(
                        id="101",
                        orderID="100",
                        units="-1000",
                        price="150.12",
                    ),
                    "lastTransactionID": "101",
                    "relatedTransactionIDs": ("100", "101"),
                },
            ),
        )
        mapper = OandaOrderMapper()

        kwargs = mapper.order_kwargs(order)
        mapped = mapper.order_from_order_response(response, order)

        assert kwargs["units"] == "-1000"
        assert kwargs["clientExtensions"]["id"] == str(order.id)
        assert kwargs["tradeClientExtensions"]["id"] == str(order.id)
        assert mapped.status == OrderStatus.FILLED
        assert mapped.filled_units == Units("1000")
        assert mapped.average_fill_price == Money.of("150.12", "JPY")

    def test_order_mapper_writes_logical_trade_id_to_trade_client_extensions(self) -> None:
        order = Order(
            instrument=USD_JPY,
            side=OrderSide.BUY,
            units=Units("1000"),
            price=Money.of("150.12", "JPY"),
            metadata=Metadata.of(logical_trade_id="C1L1R0B1"),
        )
        mapper = OandaOrderMapper()

        kwargs = mapper.order_kwargs(order)

        assert kwargs["clientExtensions"]["id"] == str(order.id)
        assert kwargs["tradeClientExtensions"]["id"] == "C1L1R0B1"

    def test_order_mapper_records_opened_and_closed_broker_trade_ids(self) -> None:
        order = Order(
            instrument=USD_JPY,
            side=OrderSide.BUY,
            units=Units("1000"),
            order_type=OrderType.MARKET,
        )
        response = cast(
            om.OandaResponse[om.OrderTransactionResponse],
            FakeResponse(
                201,
                {
                    "orderCreateTransaction": SimpleNamespace(id="100"),
                    "orderFillTransaction": SimpleNamespace(
                        id="101",
                        orderID="100",
                        units="1000",
                        price="150.12",
                        tradeOpened=SimpleNamespace(tradeID="200"),
                        tradesClosed=(
                            SimpleNamespace(tradeID="201"),
                            SimpleNamespace(id="202"),
                        ),
                    ),
                    "lastTransactionID": "101",
                    "relatedTransactionIDs": ("100", "101"),
                },
            ),
        )
        mapper = OandaOrderMapper()

        mapped = mapper.order_from_order_response(response, order)

        assert mapped.metadata["broker_trade_id"] == "200"
        assert mapped.metadata["closed_broker_trade_ids"] == ("201", "202")

    def test_position_trade_transaction_and_market_data_mappers(self) -> None:
        position_response = cast(
            om.OandaResponse[om.PositionsResponse],
            FakeResponse(
                200,
                {
                    "positions": [
                        SimpleNamespace(
                            instrument="USD_JPY",
                            long=SimpleNamespace(
                                units="1000",
                                averagePrice="150.10",
                                unrealizedPL="12.50",
                            ),
                            short=SimpleNamespace(units="0"),
                        )
                    ]
                },
            ),
        )
        trade_response = cast(
            om.OandaResponse[om.TradesResponse],
            FakeResponse(
                200,
                {
                    "trades": [
                        SimpleNamespace(
                            id="200",
                            instrument="USD_JPY",
                            currentUnits="1000",
                            initialUnits="1000",
                            price="150.10",
                            openTime="2026-01-01T00:00:00.000000000Z",
                            state="OPEN",
                            unrealizedPL="12.50",
                            realizedPL="0.00",
                        )
                    ]
                },
            ),
        )
        transaction_response = cast(
            om.OandaResponse[om.TransactionsResponse],
            FakeResponse(
                200,
                {
                    "transactions": [
                        SimpleNamespace(
                            id="300",
                            accountID="001",
                            type="ORDER_FILL",
                            instrument="USD_JPY",
                            orderID="100",
                            pl="1.25",
                        )
                    ]
                },
            ),
        )
        price_response = FakeResponse(200, {"prices": [price_namespace()]})
        candle_response = FakeResponse(200, {"candles": [candle_namespace()]})

        account_currency = Currency.of("USD")
        positions = OandaPositionMapper(account_currency=account_currency).positions_from_response(
            position_response
        )
        trades = OandaTradeMapper(account_currency=account_currency).trades_from_response(
            trade_response
        )
        transactions = OandaTransactionMapper(
            account_currency=account_currency
        ).transactions_from_response(transaction_response)
        market_data = OandaMarketDataMapper()
        ticks = market_data.ticks_from_prices(price_response.body["prices"])
        candles = market_data.candles_from_response(
            candle_response,
            instrument=USD_JPY,
            granularity=CandleGranularity.MINUTE_1,
        )

        assert positions[0].long is not None
        assert positions[0].long.side == PositionSide.LONG
        assert positions[0].long.unrealized_pl == Money.of("12.50", "USD")
        assert trades[0].id.value == "200"
        assert trades[0].unrealized_pl == Money.of("12.50", "USD")
        assert transactions[0].amount == Money.of("1.25", "USD")
        assert ticks[0].bid == Money.of("150.10", "JPY")
        assert candles[0].close == Money.of("150.10", "JPY")

    def test_position_mapper_keeps_oanda_long_and_short_sides(self) -> None:
        response = cast(
            om.OandaResponse[om.PositionsResponse],
            FakeResponse(
                200,
                {
                    "positions": [
                        SimpleNamespace(
                            instrument="USD_JPY",
                            long=SimpleNamespace(
                                units="1000",
                                averagePrice="150.10",
                                unrealizedPL="12.50",
                            ),
                            short=SimpleNamespace(
                                units="-500",
                                averagePrice="150.20",
                                unrealizedPL="-3.25",
                            ),
                        )
                    ]
                },
            ),
        )

        positions = OandaPositionMapper(
            account_currency=Currency.of("USD")
        ).positions_from_response(response)

        assert positions[0].long is not None
        assert positions[0].short is not None
        assert positions[0].open_sides == (PositionSide.LONG, PositionSide.SHORT)
        assert positions[0].long.units == Decimal("1000")
        assert positions[0].short.units == Decimal("500")
