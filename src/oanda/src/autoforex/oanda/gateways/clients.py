"""Endpoint-specific clients built on the shared OANDA transport."""

from __future__ import annotations

from typing import Any

import autoforex.oanda.models as om
from autoforex.oanda.transport import OandaTransport

_CREATED = (201,)
_ORDER_REJECTED = (400, 404)


class OandaAccountsApi:
    """OANDA account endpoints."""

    def __init__(self, transport: OandaTransport) -> None:
        self._transport = transport

    def list_accounts(self) -> om.OandaResponse[om.AccountsResponse]:
        """List accounts authorized for the token."""
        return self._transport.typed_request("GET", "/v3/accounts", om.AccountsResponse)

    def get_account(self, account_id: str) -> om.OandaResponse[om.AccountResponse]:
        """Get full account details."""
        return self._transport.typed_request(
            "GET", f"/v3/accounts/{account_id}", om.AccountResponse
        )

    def get_account_summary(self, account_id: str) -> om.OandaResponse[om.AccountSummaryResponse]:
        """Get account summary."""
        return self._transport.typed_request(
            "GET", f"/v3/accounts/{account_id}/summary", om.AccountSummaryResponse
        )

    def get_account_instruments(
        self,
        account_id: str,
        request: om.AccountInstrumentsRequest | None = None,
    ) -> om.OandaResponse[om.AccountInstrumentsResponse]:
        """Get account tradable instruments."""
        return self._transport.typed_request(
            "GET",
            f"/v3/accounts/{account_id}/instruments",
            om.AccountInstrumentsResponse,
            query=request,
        )

    def configure_account(
        self,
        account_id: str,
        request: om.ConfigureAccountRequest | None = None,
        *,
        retry: bool = False,
        **kwargs: Any,
    ) -> om.OandaResponse[om.ConfigureAccountResponse]:
        """Configure account alias or margin settings."""
        body = request if request is not None else om.ConfigureAccountRequest.model_validate(kwargs)
        return self._transport.typed_request(
            "PATCH",
            f"/v3/accounts/{account_id}/configuration",
            om.ConfigureAccountResponse,
            body=body,
            return_error_statuses=(400, 403),
            retry=retry,
        )

    def get_account_changes(
        self,
        account_id: str,
        request: om.AccountChangesRequest | None = None,
    ) -> om.OandaResponse[om.AccountChangesResponse]:
        """Get account changes since a transaction ID."""
        return self._transport.typed_request(
            "GET",
            f"/v3/accounts/{account_id}/changes",
            om.AccountChangesResponse,
            query=request,
        )


class OandaOrdersApi:
    """OANDA order endpoints."""

    def __init__(self, transport: OandaTransport) -> None:
        self._transport = transport

    def create_order(
        self,
        account_id: str,
        request: om.CreateOrderRequest | None = None,
        *,
        retry: bool = False,
        **kwargs: Any,
    ) -> om.OandaResponse[om.OrderTransactionResponse]:
        """Create an order."""
        body = request if request is not None else om.CreateOrderRequest.model_validate(kwargs)
        return self._transport.typed_request(
            "POST",
            f"/v3/accounts/{account_id}/orders",
            om.OrderTransactionResponse,
            body=body,
            success_statuses=_CREATED,
            return_error_statuses=_ORDER_REJECTED,
            retry=retry,
        )

    def list_orders(
        self,
        account_id: str,
        request: om.OrdersRequest | None = None,
    ) -> om.OandaResponse[om.OrdersResponse]:
        """List orders."""
        return self._transport.typed_request(
            "GET", f"/v3/accounts/{account_id}/orders", om.OrdersResponse, query=request
        )

    def list_pending_orders(self, account_id: str) -> om.OandaResponse[om.OrdersResponse]:
        """List pending orders."""
        return self._transport.typed_request(
            "GET", f"/v3/accounts/{account_id}/pendingOrders", om.OrdersResponse
        )

    def get_order(
        self, account_id: str, order_specifier: str
    ) -> om.OandaResponse[om.OrderResponse]:
        """Get one order."""
        return self._transport.typed_request(
            "GET",
            f"/v3/accounts/{account_id}/orders/{order_specifier}",
            om.OrderResponse,
        )

    def replace_order(
        self,
        account_id: str,
        order_specifier: str,
        request: om.ReplaceOrderRequest | None = None,
        *,
        retry: bool = False,
        **kwargs: Any,
    ) -> om.OandaResponse[om.OrderTransactionResponse]:
        """Replace one order."""
        body = request if request is not None else om.ReplaceOrderRequest.model_validate(kwargs)
        return self._transport.typed_request(
            "PUT",
            f"/v3/accounts/{account_id}/orders/{order_specifier}",
            om.OrderTransactionResponse,
            body=body,
            success_statuses=_CREATED,
            return_error_statuses=_ORDER_REJECTED,
            retry=retry,
        )

    def cancel_order(
        self,
        account_id: str,
        order_specifier: str,
        *,
        retry: bool = False,
    ) -> om.OandaResponse[om.OrderTransactionResponse]:
        """Cancel one order."""
        return self._transport.typed_request(
            "PUT",
            f"/v3/accounts/{account_id}/orders/{order_specifier}/cancel",
            om.OrderTransactionResponse,
            return_error_statuses=(404,),
            retry=retry,
        )

    def set_order_client_extensions(
        self,
        account_id: str,
        order_specifier: str,
        request: om.SetOrderClientExtensionsRequest | None = None,
        *,
        retry: bool = False,
        **kwargs: Any,
    ) -> om.OandaResponse[om.OrderTransactionResponse]:
        """Set order client extensions."""
        body = (
            request
            if request is not None
            else om.SetOrderClientExtensionsRequest.model_validate(kwargs)
        )
        return self._transport.typed_request(
            "PUT",
            f"/v3/accounts/{account_id}/orders/{order_specifier}/clientExtensions",
            om.OrderTransactionResponse,
            body=body,
            return_error_statuses=(400, 404),
            retry=retry,
        )


class OandaPositionsApi:
    """OANDA position endpoints."""

    def __init__(self, transport: OandaTransport) -> None:
        self._transport = transport

    def list_positions(self, account_id: str) -> om.OandaResponse[om.PositionsResponse]:
        """List positions."""
        return self._transport.typed_request(
            "GET", f"/v3/accounts/{account_id}/positions", om.PositionsResponse
        )

    def list_open_positions(self, account_id: str) -> om.OandaResponse[om.PositionsResponse]:
        """List open positions."""
        return self._transport.typed_request(
            "GET", f"/v3/accounts/{account_id}/openPositions", om.PositionsResponse
        )

    def get_position(
        self, account_id: str, instrument: str
    ) -> om.OandaResponse[om.PositionResponse]:
        """Get one position."""
        return self._transport.typed_request(
            "GET",
            f"/v3/accounts/{account_id}/positions/{instrument}",
            om.PositionResponse,
        )

    def close_position(
        self,
        account_id: str,
        instrument: str,
        request: om.ClosePositionRequest | None = None,
        *,
        retry: bool = False,
        **kwargs: Any,
    ) -> om.OandaResponse[om.PositionCloseResponse]:
        """Close one position."""
        body = request if request is not None else om.ClosePositionRequest.model_validate(kwargs)
        return self._transport.typed_request(
            "PUT",
            f"/v3/accounts/{account_id}/positions/{instrument}/close",
            om.PositionCloseResponse,
            body=body,
            return_error_statuses=_ORDER_REJECTED,
            retry=retry,
        )


class OandaPricingApi:
    """OANDA pricing and candle endpoints."""

    def __init__(self, transport: OandaTransport) -> None:
        self._transport = transport

    def get_account_prices(
        self,
        account_id: str,
        request: om.PricingRequest | None = None,
        **kwargs: Any,
    ) -> om.OandaResponse[om.PricingResponse]:
        """Get account prices."""
        query = (
            request
            if request is not None
            else om.PricingRequest.model_validate(self._tuple_field(kwargs, "instruments"))
        )
        return self._transport.typed_request(
            "GET", f"/v3/accounts/{account_id}/pricing", om.PricingResponse, query=query
        )

    def stream_account_prices(
        self,
        account_id: str,
        request: om.PricingStreamRequest | None = None,
        **kwargs: Any,
    ) -> om.OandaResponse[None]:
        """Stream account prices."""
        query = (
            request
            if request is not None
            else om.PricingStreamRequest.model_validate(self._tuple_field(kwargs, "instruments"))
        )
        return self._transport.stream(
            "GET",
            f"/v3/accounts/{account_id}/pricing/stream",
            query=query,
            stream_kind="pricing",
        )

    def get_account_candles(
        self,
        account_id: str,
        instrument: str,
        request: om.AccountCandlesRequest | None = None,
        **kwargs: Any,
    ) -> om.OandaResponse[om.CandlestickResponse]:
        """Fetch account-specific candles."""
        query = request if request is not None else om.AccountCandlesRequest.model_validate(kwargs)
        return self._transport.typed_request(
            "GET",
            f"/v3/accounts/{account_id}/instruments/{instrument}/candles",
            om.CandlestickResponse,
            query=query,
        )

    @staticmethod
    def _tuple_field(values: dict[str, Any], key: str) -> dict[str, Any]:
        value = values.get(key)
        if isinstance(value, str):
            return {**values, key: (value,)}
        return values

    def get_instrument_candles(
        self,
        instrument: str,
        **kwargs: Any,
    ) -> om.OandaResponse[om.CandlestickResponse]:
        """Fetch public instrument candles."""
        return self._transport.typed_request(
            "GET",
            f"/v3/instruments/{instrument}/candles",
            om.CandlestickResponse,
            query=kwargs,
        )


class OandaTradesApi:
    """OANDA trade endpoints."""

    def __init__(self, transport: OandaTransport) -> None:
        self._transport = transport

    def list_trades(
        self,
        account_id: str,
        request: om.TradesRequest | None = None,
    ) -> om.OandaResponse[om.TradesResponse]:
        """List trades."""
        return self._transport.typed_request(
            "GET", f"/v3/accounts/{account_id}/trades", om.TradesResponse, query=request
        )

    def list_open_trades(self, account_id: str) -> om.OandaResponse[om.TradesResponse]:
        """List open trades."""
        return self._transport.typed_request(
            "GET", f"/v3/accounts/{account_id}/openTrades", om.TradesResponse
        )

    def get_trade(
        self, account_id: str, trade_specifier: str
    ) -> om.OandaResponse[om.TradeResponse]:
        """Get one trade."""
        return self._transport.typed_request(
            "GET",
            f"/v3/accounts/{account_id}/trades/{trade_specifier}",
            om.TradeResponse,
        )

    def close_trade(
        self,
        account_id: str,
        trade_specifier: str,
        request: om.CloseTradeRequest | None = None,
        *,
        retry: bool = False,
        **kwargs: Any,
    ) -> om.OandaResponse[om.TradeTransactionResponse]:
        """Close one trade."""
        body = request if request is not None else om.CloseTradeRequest.model_validate(kwargs)
        return self._transport.typed_request(
            "PUT",
            f"/v3/accounts/{account_id}/trades/{trade_specifier}/close",
            om.TradeTransactionResponse,
            body=body,
            return_error_statuses=_ORDER_REJECTED,
            retry=retry,
        )

    def set_trade_client_extensions(
        self,
        account_id: str,
        trade_specifier: str,
        request: om.SetTradeClientExtensionsRequest | None = None,
        *,
        retry: bool = False,
        **kwargs: Any,
    ) -> om.OandaResponse[om.TradeTransactionResponse]:
        """Set trade client extensions."""
        body = (
            request
            if request is not None
            else om.SetTradeClientExtensionsRequest.model_validate(kwargs)
        )
        return self._transport.typed_request(
            "PUT",
            f"/v3/accounts/{account_id}/trades/{trade_specifier}/clientExtensions",
            om.TradeTransactionResponse,
            body=body,
            return_error_statuses=(400, 404),
            retry=retry,
        )

    def set_trade_dependent_orders(
        self,
        account_id: str,
        trade_specifier: str,
        request: om.SetTradeDependentOrdersRequest | None = None,
        *,
        retry: bool = False,
        **kwargs: Any,
    ) -> om.OandaResponse[om.TradeTransactionResponse]:
        """Set trade dependent orders."""
        body = (
            request
            if request is not None
            else om.SetTradeDependentOrdersRequest.model_validate(kwargs)
        )
        return self._transport.typed_request(
            "PUT",
            f"/v3/accounts/{account_id}/trades/{trade_specifier}/orders",
            om.TradeTransactionResponse,
            body=body,
            return_error_statuses=_ORDER_REJECTED,
            retry=retry,
        )


class OandaTransactionsApi:
    """OANDA transaction endpoints."""

    def __init__(self, transport: OandaTransport) -> None:
        self._transport = transport

    def list_transactions(
        self,
        account_id: str,
        request: om.TransactionsRequest | None = None,
    ) -> om.OandaResponse[om.TransactionPagesResponse]:
        """List transaction pages."""
        return self._transport.typed_request(
            "GET",
            f"/v3/accounts/{account_id}/transactions",
            om.TransactionPagesResponse,
            query=request,
        )

    def get_transaction(
        self,
        account_id: str,
        transaction_id: str,
    ) -> om.OandaResponse[om.TransactionResponse]:
        """Get one transaction."""
        return self._transport.typed_request(
            "GET",
            f"/v3/accounts/{account_id}/transactions/{transaction_id}",
            om.TransactionResponse,
        )

    def get_transaction_range(
        self,
        account_id: str,
        request: om.TransactionRangeRequest | None = None,
        **kwargs: Any,
    ) -> om.OandaResponse[om.TransactionsResponse]:
        """Get a transaction ID range."""
        query = (
            request if request is not None else om.TransactionRangeRequest.model_validate(kwargs)
        )
        return self._transport.typed_request(
            "GET",
            f"/v3/accounts/{account_id}/transactions/idrange",
            om.TransactionsResponse,
            query=query,
        )

    def get_transactions_since(
        self,
        account_id: str,
        request: om.TransactionsSinceRequest | None = None,
        **kwargs: Any,
    ) -> om.OandaResponse[om.TransactionsResponse]:
        """Get transactions since an ID."""
        query = (
            request if request is not None else om.TransactionsSinceRequest.model_validate(kwargs)
        )
        return self._transport.typed_request(
            "GET",
            f"/v3/accounts/{account_id}/transactions/sinceid",
            om.TransactionsResponse,
            query=query,
        )

    def stream_transactions(self, account_id: str) -> om.OandaResponse[None]:
        """Stream transactions."""
        return self._transport.stream(
            "GET",
            f"/v3/accounts/{account_id}/transactions/stream",
            stream_kind="transactions",
        )
