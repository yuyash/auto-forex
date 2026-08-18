from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from autoforex.core import (
    BrokerMutation,
    BrokerMutationOperation,
    BrokerOrderId,
    BrokerReconciliationOutcome,
    BrokerTradeId,
    BrokerTransactionId,
    Currency,
    CurrencyPair,
    Metadata,
    Money,
    Order,
    OrderSide,
    OrderType,
    Position,
    PositionSide,
    PositionSideState,
    Trade,
    Transaction,
    Units,
    new_uuid,
)

import autoforex.oanda.broker as broker_module
import autoforex.oanda.models as om
from autoforex.oanda.broker import OandaBroker
from autoforex.oanda.errors import OandaNotFoundError
from autoforex.oanda.services.orders import OandaOrderRequestFactory
from tests.support import FakeResponse

USD_JPY = CurrencyPair.of("USD_JPY")


class TestBroker:
    def test_capture_execution_cursor_reads_latest_transaction_id(self) -> None:
        gateway = Mock()
        gateway.transactions.list_transactions.return_value = FakeResponse(
            200,
            {"lastTransactionID": "901", "pages": ()},
        )
        broker = OandaBroker(account_id="001", gateway=gateway)

        assert broker.capture_execution_cursor() == "901"

    def test_reconciles_open_order_by_stable_client_id(self, monkeypatch) -> None:
        gateway = Mock()
        mapper = Mock()
        original = Order(
            instrument=USD_JPY,
            side=OrderSide.BUY,
            units=Units("10"),
            metadata=Metadata.of(event_id="59d2228e-bbb7-4fd1-a842-e67fcbbafddd"),
        )
        reconciled = original.evolve(
            broker_order_id="100",
            status="filled",
            filled_units=original.units,
        )
        mapper.order_from_snapshot.return_value = reconciled
        broker = OandaBroker(account_id="001", gateway=gateway, order_mapper=mapper)
        monkeypatch.setattr(broker, "get_transactions_since", lambda _: ())
        monkeypatch.setattr(
            broker,
            "get_order",
            lambda order_id: {"id": "100", "state": "FILLED", "client_id": order_id},
        )
        mutation = BrokerMutation(
            command_id=new_uuid(),
            task_id=new_uuid(),
            operation=BrokerMutationOperation.PLACE_ORDER,
            order=original,
            provider_cursor="900",
        )

        result = broker.reconcile_execution(mutation)

        assert result.outcome == BrokerReconciliationOutcome.APPLIED
        assert result.order == reconciled
        mapper.order_from_snapshot.assert_called_once()

    def test_reconciles_missing_client_order_as_not_applied(self, monkeypatch) -> None:
        broker = OandaBroker(account_id="001", gateway=Mock())
        order = Order(
            instrument=USD_JPY,
            side=OrderSide.BUY,
            units=Units("10"),
            metadata=Metadata.of(event_id="5ace94ae-26cb-4908-a532-03c6268b699c"),
        )
        monkeypatch.setattr(broker, "get_transactions_since", lambda _: ())

        def missing(_: str):
            raise OandaNotFoundError(status=404)

        monkeypatch.setattr(broker, "get_order", missing)

        result = broker.reconcile_execution(
            BrokerMutation(
                command_id=new_uuid(),
                task_id=new_uuid(),
                operation=BrokerMutationOperation.PLACE_ORDER,
                order=order,
                provider_cursor="900",
            )
        )

        assert result.outcome == BrokerReconciliationOutcome.NOT_APPLIED

    def test_close_trade_requires_one_matching_transaction(self, monkeypatch) -> None:
        broker = OandaBroker(account_id="001", gateway=Mock())
        trade = Trade(
            id=BrokerTradeId.of("200"),
            instrument=USD_JPY,
            side=PositionSide.LONG,
            units=Units("10"),
        )
        transaction = Transaction(
            id=BrokerTransactionId.of("901"),
            type="ORDER_FILL",
            instrument=USD_JPY,
            order_id=BrokerOrderId.of("100"),
            metadata=Metadata.of(
                units="-10",
                price="150.12",
                tradesClosed=({"tradeID": "200"},),
            ),
        )
        monkeypatch.setattr(
            broker,
            "get_transactions_since",
            lambda _: (transaction,),
        )
        mutation = BrokerMutation(
            command_id=new_uuid(),
            task_id=new_uuid(),
            operation=BrokerMutationOperation.CLOSE_TRADE,
            trade=trade,
            provider_cursor="900",
        )

        applied = broker.reconcile_execution(mutation)
        monkeypatch.setattr(broker, "get_transactions_since", lambda _: ())
        indeterminate = broker.reconcile_execution(mutation)

        assert applied.outcome == BrokerReconciliationOutcome.APPLIED
        assert applied.order is not None
        assert applied.order.status == "filled"
        assert indeterminate.outcome == BrokerReconciliationOutcome.INDETERMINATE

    def test_broker_place_order_uses_order_mapper_and_orders_endpoint(self) -> None:
        gateway = Mock()
        order_mapper = Mock()
        order = Order(instrument=USD_JPY, side=OrderSide.BUY, units=Units("1000"))
        result = order.evolve(broker_order_id="100")
        response = FakeResponse(201, {"orderFillTransaction": SimpleNamespace(id="100")})
        order_mapper.order_kwargs.return_value = {"units": "1000", "instrument": "USD_JPY"}
        order_mapper.order_from_order_response.return_value = result
        gateway.orders.create_order.return_value = response
        broker = OandaBroker(account_id="001", gateway=gateway, order_mapper=order_mapper)

        assert broker.place_order(order) == result

        gateway.orders.create_order.assert_called_once_with(
            "001",
            om.CreateOrderRequest(
                order=om.MarketOrderRequest(
                    type=om.OrderType.MARKET,
                    instrument="USD_JPY",
                    units=Decimal("1000"),
                )
            ),
            retry=True,
        )
        order_mapper.order_from_order_response.assert_called_once_with(response, order)

    def test_broker_account_currency_is_cached(self) -> None:
        gateway = Mock()
        account_mapper = Mock()
        account_mapper.account_currency_from_response.return_value = Currency.of("USD")
        gateway.accounts.get_account_summary.return_value = FakeResponse(
            200, {"account": {"currency": "USD"}}
        )
        broker = OandaBroker(account_id="001", gateway=gateway, account_mapper=account_mapper)

        assert broker.account_currency == Currency.of("USD")
        assert broker.account_currency == Currency.of("USD")
        gateway.accounts.get_account_summary.assert_called_once_with("001")

    def test_broker_close_position_builds_oanda_side_request(self) -> None:
        gateway = Mock()
        order_mapper = Mock()
        position = Position(
            instrument=USD_JPY,
            long=PositionSideState(
                side=PositionSide.LONG,
                units=Units("1000"),
                average_entry_price=Money.of("150.10", "JPY"),
            ),
        )
        response = FakeResponse(200, {"longOrderFillTransaction": SimpleNamespace(id="10")})
        gateway.positions.close_position.return_value = response
        close_order = Order(
            instrument=USD_JPY,
            side=OrderSide.SELL,
            units=Units("250"),
        )
        order_mapper.order_from_position_close_response.return_value = close_order
        broker = OandaBroker(account_id="001", gateway=gateway, order_mapper=order_mapper)

        assert (
            broker.close_position(position=position, side=PositionSide.LONG, units=Units("250"))
            == close_order
        )
        gateway.positions.close_position.assert_called_once_with(
            "001",
            "USD_JPY",
            om.ClosePositionRequest(longUnits="250", shortUnits="NONE"),
        )

    def test_broker_positions_uses_position_mapper(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gateway = Mock()
        account_mapper = Mock()
        mapper = Mock()
        position = Position(
            instrument=USD_JPY,
            long=PositionSideState(
                side=PositionSide.LONG,
                units=Units("1000"),
                average_entry_price=Money.of("150.10", "JPY"),
            ),
        )
        account_mapper.account_currency_from_response.return_value = Currency.of("USD")
        gateway.accounts.get_account_summary.return_value = FakeResponse(
            200, {"account": {"currency": "USD"}}
        )
        gateway.positions.list_open_positions.return_value = FakeResponse(200, {"positions": []})
        mapper.positions_from_response.return_value = (position,)
        monkeypatch.setattr(broker_module, "OandaPositionMapper", Mock(return_value=mapper))
        broker = OandaBroker(account_id="001", gateway=gateway, account_mapper=account_mapper)

        assert broker.positions(instrument=USD_JPY) == (position,)
        mapper.positions_from_response.assert_called_once_with(
            gateway.positions.list_open_positions.return_value
        )

    def test_broker_trade_and_transaction_methods_use_gateway_and_mapper(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        gateway = Mock()
        account_mapper = Mock()
        trade_mapper = Mock()
        transaction_mapper = Mock()
        account_mapper.account_currency_from_response.return_value = Currency.of("USD")
        gateway.accounts.get_account_summary.return_value = FakeResponse(
            200, {"account": {"currency": "USD"}}
        )
        gateway.trades.list_open_trades.return_value = FakeResponse(200, {"trades": []})
        gateway.transactions.get_transactions_since.return_value = FakeResponse(
            200, {"transactions": []}
        )
        trade_mapper.trades_from_response.return_value = ("trade",)
        transaction_mapper.transactions_from_response.return_value = ("transaction",)
        monkeypatch.setattr(broker_module, "OandaTradeMapper", Mock(return_value=trade_mapper))
        monkeypatch.setattr(
            broker_module,
            "OandaTransactionMapper",
            Mock(return_value=transaction_mapper),
        )
        broker = OandaBroker(account_id="001", gateway=gateway, account_mapper=account_mapper)

        assert broker.list_open_trades() == ("trade",)
        assert broker.get_transactions_since("10", types=("ORDER_FILL",)) == ("transaction",)

        gateway.trades.list_open_trades.assert_called_once_with("001")
        gateway.transactions.get_transactions_since.assert_called_once_with(
            "001",
            om.TransactionsSinceRequest(id="10", type=(om.TransactionFilter.ORDER_FILL,)),
        )

    def test_broker_order_mutation_results_return_metadata(self) -> None:
        gateway = Mock()
        response = FakeResponse(200, {"lastTransactionID": "10"})
        gateway.orders.cancel_order.return_value = response
        gateway.orders.set_order_client_extensions.return_value = response
        broker = OandaBroker(account_id="001", gateway=gateway)

        assert broker.cancel_order("100")["lastTransactionID"] == "10"
        assert (
            broker.set_order_client_extensions(
                "100", client_id="client", tag="tag", comment="comment"
            )["lastTransactionID"]
            == "10"
        )
        gateway.orders.cancel_order.assert_called_once_with("001", "100", retry=True)
        gateway.orders.set_order_client_extensions.assert_called_once_with(
            "001",
            "100",
            om.SetOrderClientExtensionsRequest.model_validate(
                {
                    "clientExtensions": {
                        "id": "client",
                        "tag": "tag",
                        "comment": "comment",
                    }
                }
            ),
            retry=True,
        )

    def test_order_service_maps_core_order_types(self) -> None:
        assert OandaOrderRequestFactory.order_type(OrderType.MARKET) == "MARKET"
        assert OandaOrderRequestFactory.order_type(OrderType.LIMIT) == "LIMIT"
        assert OandaOrderRequestFactory.order_type(OrderType.STOP) == "STOP"
