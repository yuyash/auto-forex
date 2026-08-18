from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from autoforex.core import (
    AccountId,
    CurrencyPair,
    Money,
    Order,
    OrderReasonCode,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    Units,
)

from autoforex.oanda import OandaApiError, OandaProvider, OandaSettings
from tests.e2e.coverage import covers_endpoints


class TestMutatingLivePractice:
    @covers_endpoints("accounts.configure_account")
    def test_practice_account_configuration_endpoint(
        self,
        mutating_oanda_provider: OandaProvider,
        oanda_settings: OandaSettings,
    ) -> None:
        account_id = AccountId.of(oanda_settings.account_id)
        summary = mutating_oanda_provider.accounts.get_account_summary(account_id)
        assert summary.margin_rate is not None

        configured = mutating_oanda_provider.accounts.configure_account(
            account_id,
            margin_rate=summary.margin_rate,
        )

        assert configured.metadata["lastTransactionID"]

    @covers_endpoints(
        "orders.create_order",
        "orders.get_order",
        "orders.set_order_client_extensions",
        "orders.replace_order",
        "orders.cancel_order",
    )
    def test_practice_pending_order_can_be_created_modified_and_cancelled(
        self,
        mutating_oanda_provider: OandaProvider,
        e2e_instrument: CurrencyPair,
        mutating_units: Units,
    ) -> None:
        order_id: str | None = None
        replacement_id: str | None = None
        try:
            order = _far_buy_limit_order(mutating_oanda_provider, e2e_instrument, mutating_units)
            placed = mutating_oanda_provider.broker.place_order(order)
            _skip_if_market_rejected(placed)
            assert placed.broker_order_id is not None
            order_id = placed.broker_order_id.value

            fetched_order = mutating_oanda_provider.broker.get_order(order_id)
            assert fetched_order.get("order")

            metadata = mutating_oanda_provider.broker.set_order_client_extensions(
                order_id,
                client_id=f"af-e2e-{uuid4().hex[:16]}",
                tag="auto-forex-e2e",
                comment="mutating e2e pending order",
            )
            assert metadata

            assert order.price is not None
            replacement = order.evolve(
                price=Money.of(
                    _lower_price(order.price.require_currency(e2e_instrument.quote).amount),
                    e2e_instrument.quote,
                )
            )
            replaced = mutating_oanda_provider.broker.replace_order(order_id, replacement)
            _skip_if_market_rejected(replaced)
            assert replaced.broker_order_id is not None
            replacement_id = replaced.broker_order_id.value
            order_id = None

            cancelled = mutating_oanda_provider.broker.cancel_order(replacement_id)
            assert cancelled
            replacement_id = None
        finally:
            _cancel_order_if_present(mutating_oanda_provider, replacement_id)
            _cancel_order_if_present(mutating_oanda_provider, order_id)

    @covers_endpoints(
        "trades.get_trade",
        "trades.set_trade_client_extensions",
        "trades.set_trade_dependent_orders",
        "trades.close_trade",
    )
    def test_practice_market_order_can_be_closed_by_trade(
        self,
        mutating_oanda_provider: OandaProvider,
        e2e_instrument: CurrencyPair,
        mutating_units: Units,
    ) -> None:
        _skip_if_existing_trade_or_position(mutating_oanda_provider, e2e_instrument)
        trade_id: str | None = None
        try:
            placed = mutating_oanda_provider.broker.place_order(
                Order(
                    instrument=e2e_instrument,
                    side=OrderSide.BUY,
                    units=mutating_units,
                    order_type=OrderType.MARKET,
                )
            )
            _skip_if_market_rejected(placed)
            assert placed.status == OrderStatus.FILLED

            trades = tuple(
                trade
                for trade in mutating_oanda_provider.broker.list_open_trades()
                if trade.instrument == e2e_instrument
            )
            assert len(trades) == 1
            trade_id = trades[0].id.value

            fetched_trade = mutating_oanda_provider.broker.get_trade(trade_id)
            assert fetched_trade.id.value == trade_id

            client_extensions = mutating_oanda_provider.broker.set_trade_client_extensions(
                trade_id,
                client_id=f"af-e2e-{uuid4().hex[:16]}",
                tag="auto-forex-e2e",
                comment="mutating e2e trade",
            )
            assert client_extensions

            assert fetched_trade.price is not None
            price = fetched_trade.price.require_currency(e2e_instrument.quote).amount
            dependent_orders = mutating_oanda_provider.broker.set_trade_dependent_orders(
                trade_id,
                takeProfit={"timeInForce": "GTC", "price": str(_higher_price(price))},
            )
            assert dependent_orders

            closed = mutating_oanda_provider.broker.close_trade(fetched_trade)
            assert closed
            trade_id = None
        finally:
            _close_trade_if_present(mutating_oanda_provider, trade_id)

    @covers_endpoints(
        "positions.get_position",
        "positions.close_position",
    )
    def test_practice_market_order_can_be_closed_by_position(
        self,
        mutating_oanda_provider: OandaProvider,
        e2e_instrument: CurrencyPair,
        mutating_units: Units,
    ) -> None:
        _skip_if_existing_trade_or_position(mutating_oanda_provider, e2e_instrument)
        opened = False
        try:
            placed = mutating_oanda_provider.broker.place_order(
                Order(
                    instrument=e2e_instrument,
                    side=OrderSide.BUY,
                    units=mutating_units,
                    order_type=OrderType.MARKET,
                )
            )
            _skip_if_market_rejected(placed)
            assert placed.status == OrderStatus.FILLED
            opened = True

            position = mutating_oanda_provider.broker.get_position(e2e_instrument)
            close_order = mutating_oanda_provider.broker.close_position(
                position=position,
                side=PositionSide.LONG,
                units=mutating_units,
            )
            _skip_if_market_rejected(close_order)
            assert close_order.status == OrderStatus.FILLED
            opened = False
        finally:
            if opened:
                _close_position_if_present(mutating_oanda_provider, e2e_instrument, mutating_units)


def _far_buy_limit_order(
    provider: OandaProvider,
    instrument: CurrencyPair,
    units: Units,
) -> Order:
    tick = next(iter(provider.data.prices(instruments=(instrument,))))
    bid = tick.bid.require_currency(instrument.quote).amount
    return Order(
        instrument=instrument,
        side=OrderSide.BUY,
        units=units,
        order_type=OrderType.LIMIT,
        price=Money.of(_lower_price(bid), instrument.quote),
    )


def _lower_price(price: Decimal) -> Decimal:
    return (price * Decimal("0.50")).quantize(price)


def _higher_price(price: Decimal) -> Decimal:
    return (price * Decimal("1.50")).quantize(price)


def _skip_if_market_rejected(order: Order) -> None:
    if order.status not in {OrderStatus.REJECTED, OrderStatus.CANCELLED}:
        return
    if order.reason.code == OrderReasonCode.MARKET_CLOSED:
        pytest.skip("OANDA market is closed")
    if order.status == OrderStatus.CANCELLED:
        pytest.skip("OANDA cancelled mutating e2e order before fill")
    pytest.fail(f"OANDA rejected mutating e2e order: {order.reason.code}")


def _skip_if_existing_trade_or_position(provider: OandaProvider, instrument: CurrencyPair) -> None:
    if any(trade.instrument == instrument for trade in provider.broker.list_open_trades()):
        pytest.skip(f"Open trade already exists for {instrument}; refusing to mutate it")
    if any(position.instrument == instrument for position in provider.broker.list_open_positions()):
        pytest.skip(f"Open position already exists for {instrument}; refusing to mutate it")


def _cancel_order_if_present(provider: OandaProvider, order_id: str | None) -> None:
    if order_id is None:
        return
    try:
        provider.broker.cancel_order(order_id)
    except OandaApiError:
        return


def _close_trade_if_present(provider: OandaProvider, trade_id: str | None) -> None:
    if trade_id is None:
        return
    try:
        provider.broker.close_trade(provider.broker.get_trade(trade_id))
    except OandaApiError:
        return


def _close_position_if_present(
    provider: OandaProvider,
    instrument: CurrencyPair,
    units: Units,
) -> None:
    try:
        position = provider.broker.get_position(instrument)
        provider.broker.close_position(position=position, side=PositionSide.LONG, units=units)
    except LookupError, OandaApiError:
        return
