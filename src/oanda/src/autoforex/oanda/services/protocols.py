"""Protocols shared by OANDA broker services."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from autoforex.core import Currency

import autoforex.oanda.models as om

AccountCurrencyProvider = Callable[[], Currency]
MapperFactory = Callable[..., object]


class OandaOrderClient(Protocol):
    """OANDA order endpoint methods required by order services."""

    def create_order(
        self,
        account_id: str,
        request: om.CreateOrderRequest,
        *,
        retry: bool = False,
    ) -> om.OandaResponse[om.OrderTransactionResponse]: ...
    def list_orders(
        self,
        account_id: str,
        request: om.OrdersRequest | None = None,
    ) -> om.OandaResponse[om.OrdersResponse]: ...
    def list_pending_orders(self, account_id: str) -> om.OandaResponse[om.OrdersResponse]: ...
    def get_order(
        self,
        account_id: str,
        order_specifier: str,
    ) -> om.OandaResponse[om.OrderResponse]: ...
    def replace_order(
        self,
        account_id: str,
        order_specifier: str,
        request: om.ReplaceOrderRequest,
        *,
        retry: bool = False,
    ) -> om.OandaResponse[om.OrderTransactionResponse]: ...
    def cancel_order(
        self,
        account_id: str,
        order_specifier: str,
        *,
        retry: bool = False,
    ) -> om.OandaResponse[om.OrderTransactionResponse]: ...
    def set_order_client_extensions(
        self,
        account_id: str,
        order_specifier: str,
        request: om.SetOrderClientExtensionsRequest,
        *,
        retry: bool = False,
    ) -> om.OandaResponse[om.OrderTransactionResponse]: ...


class OandaPositionClient(Protocol):
    """OANDA position endpoint methods required by position services."""

    def list_open_positions(self, account_id: str) -> om.OandaResponse[om.PositionsResponse]: ...
    def list_positions(self, account_id: str) -> om.OandaResponse[om.PositionsResponse]: ...
    def get_position(
        self,
        account_id: str,
        instrument: str,
    ) -> om.OandaResponse[om.PositionResponse]: ...
    def close_position(
        self,
        account_id: str,
        instrument: str,
        request: om.ClosePositionRequest,
        *,
        retry: bool = False,
    ) -> om.OandaResponse[om.PositionCloseResponse]: ...


class OandaTradeClient(Protocol):
    """OANDA trade endpoint methods required by trade services."""

    def list_trades(
        self,
        account_id: str,
        request: om.TradesRequest | None = None,
    ) -> om.OandaResponse[om.TradesResponse]: ...
    def list_open_trades(self, account_id: str) -> om.OandaResponse[om.TradesResponse]: ...
    def get_trade(
        self,
        account_id: str,
        trade_specifier: str,
    ) -> om.OandaResponse[om.TradeResponse]: ...
    def close_trade(
        self,
        account_id: str,
        trade_specifier: str,
        request: om.CloseTradeRequest | None = None,
        *,
        retry: bool = False,
    ) -> om.OandaResponse[om.TradeTransactionResponse]: ...
    def set_trade_client_extensions(
        self,
        account_id: str,
        trade_specifier: str,
        request: om.SetTradeClientExtensionsRequest,
        *,
        retry: bool = False,
    ) -> om.OandaResponse[om.TradeTransactionResponse]: ...
    def set_trade_dependent_orders(
        self,
        account_id: str,
        trade_specifier: str,
        request: om.SetTradeDependentOrdersRequest,
        *,
        retry: bool = False,
    ) -> om.OandaResponse[om.TradeTransactionResponse]: ...


class OandaTransactionClient(Protocol):
    """OANDA transaction endpoint methods required by transaction services."""

    def list_transactions(
        self,
        account_id: str,
        request: om.TransactionsRequest | None = None,
    ) -> om.OandaResponse[om.TransactionPagesResponse]: ...
    def get_transaction(
        self,
        account_id: str,
        transaction_id: str,
    ) -> om.OandaResponse[om.TransactionResponse]: ...
    def get_transaction_range(
        self,
        account_id: str,
        request: om.TransactionRangeRequest | None = None,
    ) -> om.OandaResponse[om.TransactionsResponse]: ...
    def get_transactions_since(
        self,
        account_id: str,
        request: om.TransactionsSinceRequest | None = None,
    ) -> om.OandaResponse[om.TransactionsResponse]: ...
    def stream_transactions(self, account_id: str) -> om.OandaResponse[None]: ...


class OandaTimeFormatter(Protocol):
    """Formats datetimes for OANDA query parameters."""

    def datetime_to_str(self, value: datetime) -> str: ...
