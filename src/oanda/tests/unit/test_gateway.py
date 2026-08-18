from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import SecretStr

import autoforex.oanda.models as om
from autoforex.oanda.config import OandaEnvironment, OandaSettings
from autoforex.oanda.errors import OandaAuthenticationError
from autoforex.oanda.gateway import OandaGateway, OandaRetryPolicy
from autoforex.oanda.models import AccountsResponse, OandaResponse, OandaStreamResponse
from tests.support import FakeHTTPResponse, FakeOpener


class EndpointOpener:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.requests: list[Any] = []

    def open(self, request: Any, timeout: int) -> Any:
        _ = timeout
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class FakeStreamingHTTPResponse:
    def __init__(self) -> None:
        self.status = 200
        self.code = 200
        self.reason = "OK"
        self.headers = {"Content-Type": "application/json"}

    def __iter__(self) -> Any:
        return iter(())


class TestGateway:
    def test_retry_policy_validates_values(self) -> None:
        with pytest.raises(ValueError, match="retry attempts"):
            OandaRetryPolicy(attempts=0)
        with pytest.raises(ValueError, match="retry initial delay"):
            OandaRetryPolicy(initial_delay=timedelta(seconds=-1))

    def test_gateway_from_settings_uses_settings_values(self) -> None:
        settings = OandaSettings(
            account_id="001",
            access_token=SecretStr("token"),
            environment=OandaEnvironment.LIVE,
            application="UnitTest",
        )

        gateway = OandaGateway.from_settings(settings)

        assert gateway.access_token == "token"
        assert gateway.hostname == "api-fxtrade.oanda.com"
        assert gateway.stream_hostname == "stream-fxtrade.oanda.com"
        assert gateway.application == "UnitTest"

    def test_gateway_request_uses_fake_opener_and_parses_typed_response(self) -> None:
        opener = FakeOpener([FakeHTTPResponse(200, {"accounts": [{"id": "001"}]})])
        gateway = OandaGateway(
            access_token="token",
            hostname="api.example.test",
            stream_hostname="stream.example.test",
            opener=opener,
        )

        response = gateway.accounts.list_accounts()

        assert isinstance(response.body, AccountsResponse)
        assert response.body.accounts[0].id == "001"
        request = opener.requests[0]
        assert request.full_url == "https://api.example.test/v3/accounts"
        assert request.headers["Authorization"] == "Bearer token"

    def test_gateway_builds_json_body_and_query_values(self) -> None:
        opener = FakeOpener([FakeHTTPResponse(201, {"orderCreateTransaction": {"id": "10"}})])
        gateway = OandaGateway(
            access_token="token",
            hostname="api.example.test",
            stream_hostname="stream.example.test",
            opener=opener,
        )

        gateway.orders.create_order(
            "001",
            om.CreateOrderRequest(
                order=om.MarketOrderRequest(
                    type=om.OrderType.MARKET,
                    instrument="USD_JPY",
                    units=Decimal("1000"),
                )
            ),
        )

        request = opener.requests[0]
        body = json.loads(request.data.decode())
        assert body["order"]["type"] == "MARKET"
        assert request.full_url == "https://api.example.test/v3/accounts/001/orders"

    @pytest.mark.parametrize(
        ("call", "status", "method", "path", "query", "body"),
        [
            (
                lambda gateway: gateway.transport.request(
                    "PATCH", "/v3/accounts/001/custom", query={"a": 1}, body={"b": 2}
                ),
                200,
                "PATCH",
                "/v3/accounts/001/custom",
                {"a": "1"},
                {"b": 2},
            ),
            (
                lambda gateway: gateway.accounts.list_accounts(),
                200,
                "GET",
                "/v3/accounts",
                {},
                None,
            ),
            (
                lambda gateway: gateway.accounts.get_account("001"),
                200,
                "GET",
                "/v3/accounts/001",
                {},
                None,
            ),
            (
                lambda gateway: gateway.accounts.get_account_summary("001"),
                200,
                "GET",
                "/v3/accounts/001/summary",
                {},
                None,
            ),
            (
                lambda gateway: gateway.accounts.get_account_instruments(
                    "001", om.AccountInstrumentsRequest(instruments=("USD_JPY", "EUR_USD"))
                ),
                200,
                "GET",
                "/v3/accounts/001/instruments",
                {"instruments": "USD_JPY,EUR_USD"},
                None,
            ),
            (
                lambda gateway: gateway.accounts.configure_account(
                    "001", om.ConfigureAccountRequest(alias="primary")
                ),
                200,
                "PATCH",
                "/v3/accounts/001/configuration",
                {},
                {"alias": "primary"},
            ),
            (
                lambda gateway: gateway.accounts.get_account_changes(
                    "001",
                    om.AccountChangesRequest.model_validate({"sinceTransactionID": "10"}),
                ),
                200,
                "GET",
                "/v3/accounts/001/changes",
                {"sinceTransactionID": "10"},
                None,
            ),
            (
                lambda gateway: gateway.orders.create_order(
                    "001",
                    om.CreateOrderRequest(order=om.MarketOrderRequest(type=om.OrderType.MARKET)),
                ),
                201,
                "POST",
                "/v3/accounts/001/orders",
                {},
                {"order": {"type": "MARKET"}},
            ),
            (
                lambda gateway: gateway.orders.list_orders(
                    "001", om.OrdersRequest(count=10, state=om.OrderStateFilter.PENDING)
                ),
                200,
                "GET",
                "/v3/accounts/001/orders",
                {"count": "10", "state": "PENDING"},
                None,
            ),
            (
                lambda gateway: gateway.orders.list_pending_orders("001"),
                200,
                "GET",
                "/v3/accounts/001/pendingOrders",
                {},
                None,
            ),
            (
                lambda gateway: gateway.orders.get_order("001", "100"),
                200,
                "GET",
                "/v3/accounts/001/orders/100",
                {},
                None,
            ),
            (
                lambda gateway: gateway.orders.replace_order(
                    "001",
                    "100",
                    om.ReplaceOrderRequest(order=om.LimitOrderRequest(type=om.OrderType.LIMIT)),
                ),
                201,
                "PUT",
                "/v3/accounts/001/orders/100",
                {},
                {"order": {"type": "LIMIT"}},
            ),
            (
                lambda gateway: gateway.orders.cancel_order("001", "100"),
                200,
                "PUT",
                "/v3/accounts/001/orders/100/cancel",
                {},
                None,
            ),
            (
                lambda gateway: gateway.orders.set_order_client_extensions(
                    "001",
                    "100",
                    om.SetOrderClientExtensionsRequest.model_validate(
                        {"clientExtensions": om.ClientExtensions(id="client-100")}
                    ),
                ),
                200,
                "PUT",
                "/v3/accounts/001/orders/100/clientExtensions",
                {},
                {"clientExtensions": {"id": "client-100"}},
            ),
            (
                lambda gateway: gateway.positions.list_positions("001"),
                200,
                "GET",
                "/v3/accounts/001/positions",
                {},
                None,
            ),
            (
                lambda gateway: gateway.positions.list_open_positions("001"),
                200,
                "GET",
                "/v3/accounts/001/openPositions",
                {},
                None,
            ),
            (
                lambda gateway: gateway.positions.get_position("001", "USD_JPY"),
                200,
                "GET",
                "/v3/accounts/001/positions/USD_JPY",
                {},
                None,
            ),
            (
                lambda gateway: gateway.positions.close_position(
                    "001",
                    "USD_JPY",
                    om.ClosePositionRequest.model_validate({"longUnits": "ALL"}),
                ),
                200,
                "PUT",
                "/v3/accounts/001/positions/USD_JPY/close",
                {},
                {"longUnits": "ALL"},
            ),
            (
                lambda gateway: gateway.pricing.get_account_prices(
                    "001", instruments="USD_JPY", includeHomeConversions=True
                ),
                200,
                "GET",
                "/v3/accounts/001/pricing",
                {"instruments": "USD_JPY", "includeHomeConversions": "true"},
                None,
            ),
            (
                lambda gateway: gateway.pricing.get_account_candles(
                    "001", "USD_JPY", granularity="M1", count=1
                ),
                200,
                "GET",
                "/v3/accounts/001/instruments/USD_JPY/candles",
                {"granularity": "M1", "count": "1"},
                None,
            ),
            (
                lambda gateway: gateway.pricing.get_instrument_candles(
                    "USD_JPY", granularity="M1", count=1
                ),
                200,
                "GET",
                "/v3/instruments/USD_JPY/candles",
                {"granularity": "M1", "count": "1"},
                None,
            ),
            (
                lambda gateway: gateway.trades.list_trades(
                    "001", om.TradesRequest(count=10, state=om.TradeStateFilter.OPEN)
                ),
                200,
                "GET",
                "/v3/accounts/001/trades",
                {"count": "10", "state": "OPEN"},
                None,
            ),
            (
                lambda gateway: gateway.trades.list_open_trades("001"),
                200,
                "GET",
                "/v3/accounts/001/openTrades",
                {},
                None,
            ),
            (
                lambda gateway: gateway.trades.get_trade("001", "200"),
                200,
                "GET",
                "/v3/accounts/001/trades/200",
                {},
                None,
            ),
            (
                lambda gateway: gateway.trades.close_trade(
                    "001", "200", om.CloseTradeRequest(units="ALL")
                ),
                200,
                "PUT",
                "/v3/accounts/001/trades/200/close",
                {},
                {"units": "ALL"},
            ),
            (
                lambda gateway: gateway.trades.set_trade_client_extensions(
                    "001",
                    "200",
                    om.SetTradeClientExtensionsRequest.model_validate(
                        {"clientExtensions": om.ClientExtensions(id="trade-200")}
                    ),
                ),
                200,
                "PUT",
                "/v3/accounts/001/trades/200/clientExtensions",
                {},
                {"clientExtensions": {"id": "trade-200"}},
            ),
            (
                lambda gateway: gateway.trades.set_trade_dependent_orders(
                    "001",
                    "200",
                    om.SetTradeDependentOrdersRequest.model_validate(
                        {"takeProfit": om.TakeProfitDetails(price=Decimal("151.00"))}
                    ),
                ),
                200,
                "PUT",
                "/v3/accounts/001/trades/200/orders",
                {},
                {"takeProfit": {"price": "151.00"}},
            ),
            (
                lambda gateway: gateway.transactions.list_transactions(
                    "001", om.TransactionsRequest.model_validate({"pageSize": 100})
                ),
                200,
                "GET",
                "/v3/accounts/001/transactions",
                {"pageSize": "100"},
                None,
            ),
            (
                lambda gateway: gateway.transactions.get_transaction("001", "300"),
                200,
                "GET",
                "/v3/accounts/001/transactions/300",
                {},
                None,
            ),
            (
                lambda gateway: gateway.transactions.get_transaction_range(
                    "001", from_id="300", to_id="301"
                ),
                200,
                "GET",
                "/v3/accounts/001/transactions/idrange",
                {"from": "300", "to": "301"},
                None,
            ),
            (
                lambda gateway: gateway.transactions.get_transactions_since("001", id="300"),
                200,
                "GET",
                "/v3/accounts/001/transactions/sinceid",
                {"id": "300"},
                None,
            ),
        ],
    )
    def test_gateway_endpoint_methods_build_expected_requests(
        self,
        call: Callable[[OandaGateway], object],
        status: int,
        method: str,
        path: str,
        query: dict[str, str],
        body: dict[str, Any] | None,
    ) -> None:
        opener = EndpointOpener([FakeHTTPResponse(status, {})])
        gateway = OandaGateway(
            access_token="token",
            hostname="api.example.test",
            stream_hostname="stream.example.test",
            opener=opener,
        )

        call(gateway)

        request = opener.requests[0]
        parsed = urlparse(request.full_url)
        assert request.get_method() == method
        assert parsed.scheme == "https"
        assert parsed.netloc == "api.example.test"
        assert parsed.path == path
        assert {key: values[0] for key, values in parse_qs(parsed.query).items()} == query
        if body is None:
            assert request.data is None
        else:
            assert json.loads(request.data.decode()) == body

    @pytest.mark.parametrize(
        ("call", "path", "query", "stream_kind"),
        [
            (
                lambda gateway: gateway.pricing.stream_account_prices(
                    "001", instruments="USD_JPY", snapshot=True
                ),
                "/v3/accounts/001/pricing/stream",
                {"instruments": "USD_JPY", "snapshot": "true"},
                "pricing",
            ),
            (
                lambda gateway: gateway.transactions.stream_transactions("001"),
                "/v3/accounts/001/transactions/stream",
                {},
                "transactions",
            ),
        ],
    )
    def test_gateway_stream_endpoint_methods_build_expected_requests(
        self,
        call: Callable[[OandaGateway], OandaResponse[None]],
        path: str,
        query: dict[str, str],
        stream_kind: str,
    ) -> None:
        opener = EndpointOpener([FakeStreamingHTTPResponse()])
        gateway = OandaGateway(
            access_token="token",
            hostname="api.example.test",
            stream_hostname="stream.example.test",
            opener=opener,
        )

        response = call(gateway)

        request = opener.requests[0]
        parsed = urlparse(request.full_url)
        assert request.get_method() == "GET"
        assert parsed.scheme == "https"
        assert parsed.netloc == "stream.example.test"
        assert parsed.path == path
        assert {key: values[0] for key, values in parse_qs(parsed.query).items()} == query
        assert isinstance(response.raw, OandaStreamResponse)
        assert response.raw.stream_kind == stream_kind

    def test_gateway_retries_stream_timeout_without_real_network(self) -> None:
        opener = EndpointOpener(
            [
                TimeoutError("temporary stream timeout"),
                FakeStreamingHTTPResponse(),
            ]
        )
        gateway = OandaGateway(
            access_token="token",
            hostname="api.example.test",
            stream_hostname="stream.example.test",
            opener=opener,
            retry_policy=OandaRetryPolicy(
                attempts=2,
                initial_delay=timedelta(seconds=0),
                max_delay=timedelta(seconds=0),
            ),
        )

        response = gateway.transactions.stream_transactions("001")

        assert response.status == 200
        assert len(opener.requests) == 2

    def test_gateway_datetime_to_str_formats_rfc3339(self) -> None:
        gateway = OandaGateway(
            access_token="token",
            hostname="api.example.test",
            stream_hostname="stream.example.test",
            opener=FakeOpener([]),
        )

        assert (
            gateway.transport.datetime_to_str(datetime(2026, 1, 1, tzinfo=UTC))
            == "2026-01-01T00:00:00Z"
        )

    def test_gateway_maps_http_error_without_real_network(self) -> None:
        class ErrorOpener:
            def __init__(self) -> None:
                self.requests: list[Any] = []

            def open(self, request: Any, timeout: int) -> Any:
                from urllib.error import HTTPError

                _ = timeout
                self.requests.append(request)
                response = FakeHTTPResponse(
                    401,
                    {"errorCode": "UNAUTHORIZED", "errorMessage": "bad token"},
                    reason="Unauthorized",
                )
                raise HTTPError(
                    url="https://api.example.test/v3/accounts",
                    code=401,
                    msg="Unauthorized",
                    hdrs=cast(Any, response.headers),
                    fp=cast(Any, response),
                )

        gateway = OandaGateway(
            access_token="token",
            hostname="api.example.test",
            stream_hostname="stream.example.test",
            opener=ErrorOpener(),
        )

        with pytest.raises(OandaAuthenticationError):
            gateway.accounts.list_accounts()

    def test_gateway_retries_retryable_api_errors_without_real_network(self) -> None:
        opener = FakeOpener(
            [
                FakeHTTPResponse(
                    500,
                    {"errorCode": "INTERNAL_SERVER_ERROR", "errorMessage": "temporary failure"},
                    reason="Server Error",
                ),
                FakeHTTPResponse(200, {"accounts": []}),
            ]
        )
        gateway = OandaGateway(
            access_token="token",
            hostname="api.example.test",
            stream_hostname="stream.example.test",
            opener=opener,
            retry_policy=OandaRetryPolicy(
                attempts=2,
                initial_delay=timedelta(seconds=0),
                max_delay=timedelta(seconds=0),
            ),
        )

        response = gateway.accounts.list_accounts()

        assert response.status == 200
        assert opener.calls == 2

    def test_gateway_does_not_retry_non_retryable_api_errors_without_real_network(self) -> None:
        opener = FakeOpener(
            [
                FakeHTTPResponse(
                    401,
                    {"errorCode": "UNAUTHORIZED", "errorMessage": "invalid token"},
                    reason="Unauthorized",
                )
            ]
        )
        gateway = OandaGateway(
            access_token="token",
            hostname="api.example.test",
            stream_hostname="stream.example.test",
            opener=opener,
            retry_policy=OandaRetryPolicy(
                attempts=3,
                initial_delay=timedelta(seconds=0),
                max_delay=timedelta(seconds=0),
            ),
        )

        with pytest.raises(OandaAuthenticationError):
            gateway.accounts.list_accounts()

        assert opener.calls == 1
