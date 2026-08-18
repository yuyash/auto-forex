from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import autoforex.oanda.models as om
from tests.support import FakeResponse, candle_namespace, price_namespace


class IntegrationGateway:
    def __init__(self) -> None:
        self.order_requests: list[om.CreateOrderRequest] = []
        self.close_position_calls: list[tuple[str, om.ClosePositionRequest]] = []
        self.configure_account_calls: list[om.ConfigureAccountRequest] = []
        self.opener = SimpleNamespace(close=lambda: None)
        self.accounts = self
        self.orders = self
        self.positions = self
        self.pricing = self
        self.trades = self
        self.transactions = self
        self.transport = self

    def list_accounts(self) -> FakeResponse:
        return FakeResponse(
            200,
            {
                "accounts": [
                    SimpleNamespace(id="001", alias="primary", mt4AccountID=123, tags=("demo",))
                ]
            },
        )

    def get_account(self, account_id: str) -> FakeResponse:
        return FakeResponse(
            200,
            {"account": SimpleNamespace(id=account_id, alias="primary", tags=("demo",))},
        )

    def get_account_summary(self, account_id: str) -> FakeResponse:
        return FakeResponse(
            200,
            {
                "account": {
                    "id": account_id,
                    "currency": "USD",
                    "balance": "1000.00",
                    "NAV": "1001.00",
                    "marginUsed": "10.00",
                    "marginAvailable": "991.00",
                    "marginRate": "0.02",
                    "openTradeCount": 1,
                    "openPositionCount": 1,
                    "pendingOrderCount": 0,
                },
                "lastTransactionID": "10",
            },
        )

    def get_account_instruments(
        self,
        account_id: str,
        request: om.AccountInstrumentsRequest | None = None,
    ) -> FakeResponse:
        _ = account_id
        _ = request
        return FakeResponse(200, {"instruments": [SimpleNamespace(name="USD_JPY")]})

    def configure_account(
        self,
        account_id: str,
        request: om.ConfigureAccountRequest | None = None,
        **kwargs: Any,
    ) -> FakeResponse:
        _ = account_id
        _ = kwargs
        self.configure_account_calls.append(request or om.ConfigureAccountRequest())
        return FakeResponse(200, {"lastTransactionID": "11"})

    def get_account_changes(
        self,
        account_id: str,
        request: om.AccountChangesRequest | None = None,
    ) -> FakeResponse:
        _ = account_id
        _ = request
        return FakeResponse(200, {"lastTransactionID": "12", "state": {"NAV": "1001.00"}})

    def create_order(
        self,
        account_id: str,
        request: om.CreateOrderRequest,
        **kwargs: Any,
    ) -> FakeResponse:
        _ = account_id
        _ = kwargs
        self.order_requests.append(request)
        order = request.order
        if not isinstance(order, om.MarketOrderRequest) or order.units is None:
            msg = "integration fake supports market order requests with units"
            raise ValueError(msg)
        return FakeResponse(
            201,
            {
                "orderCreateTransaction": SimpleNamespace(id="100"),
                "orderFillTransaction": SimpleNamespace(
                    id="101",
                    orderID="100",
                    units=str(order.units),
                    price="150.12",
                ),
                "lastTransactionID": "101",
                "relatedTransactionIDs": ("100", "101"),
            },
        )

    def list_open_positions(self, account_id: str) -> FakeResponse:
        _ = account_id
        return FakeResponse(
            200,
            {
                "positions": [
                    SimpleNamespace(
                        instrument="USD_JPY",
                        long=SimpleNamespace(
                            units="1000",
                            averagePrice="150.10",
                            unrealizedPL="12.50",
                            tradeIDs=("200",),
                        ),
                        short=SimpleNamespace(units="0"),
                    )
                ]
            },
        )

    def close_position(
        self,
        account_id: str,
        instrument: str,
        request: om.ClosePositionRequest,
        **kwargs: Any,
    ) -> FakeResponse:
        _ = account_id
        _ = kwargs
        self.close_position_calls.append((instrument, request))
        return FakeResponse(
            200,
            {
                "longOrderCreateTransaction": SimpleNamespace(id="102"),
                "longOrderFillTransaction": SimpleNamespace(
                    id="103",
                    orderID="102",
                    units="-250",
                    price="150.11",
                ),
            },
        )

    def list_open_trades(self, account_id: str) -> FakeResponse:
        _ = account_id
        return FakeResponse(200, {"trades": [self._trade()]})

    def get_transactions_since(
        self,
        account_id: str,
        request: om.TransactionsSinceRequest | None = None,
    ) -> FakeResponse:
        _ = request
        return FakeResponse(200, {"transactions": [self._transaction(account_id)]})

    def get_account_prices(
        self,
        account_id: str,
        request: om.PricingRequest | None = None,
        **kwargs: Any,
    ) -> FakeResponse:
        _ = account_id
        _ = request
        _ = kwargs
        return FakeResponse(200, {"prices": [price_namespace()]})

    def get_account_candles(
        self,
        account_id: str,
        instrument: str,
        request: om.AccountCandlesRequest | None = None,
        **kwargs: Any,
    ) -> FakeResponse:
        _ = account_id
        _ = instrument
        _ = request
        _ = kwargs
        return FakeResponse(200, {"candles": [candle_namespace()]})

    def stream_account_prices(
        self,
        account_id: str,
        request: om.PricingStreamRequest | None = None,
        **kwargs: Any,
    ) -> Any:
        _ = account_id
        _ = request
        _ = kwargs
        return SimpleNamespace(parts=lambda: (("ClientPrice", price_namespace()),))

    def datetime_to_str(self, value: object) -> str:
        if isinstance(value, datetime):
            return value.isoformat().replace("+00:00", "Z")
        return str(value)

    @staticmethod
    def _trade() -> SimpleNamespace:
        return SimpleNamespace(
            id="200",
            instrument="USD_JPY",
            currentUnits="1000",
            initialUnits="1000",
            price="150.10",
            state="OPEN",
            unrealizedPL="12.50",
            realizedPL="0.00",
        )

    @staticmethod
    def _transaction(account_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            id="300",
            accountID=account_id,
            type="ORDER_FILL",
            instrument="USD_JPY",
            orderID="100",
            pl="1.25",
        )
