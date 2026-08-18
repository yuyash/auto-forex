from __future__ import annotations

from autoforex.oanda.gateway import OandaGateway
from autoforex.oanda.models import AccountsResponse, PricingResponse
from tests.support import FakeHTTPResponse, FakeOpener


class TestGateway:
    def test_gateway_endpoint_methods_parse_generated_models_without_http(self) -> None:
        opener = FakeOpener(
            [
                FakeHTTPResponse(200, {"accounts": [{"id": "001"}]}),
                FakeHTTPResponse(
                    200,
                    {
                        "prices": [
                            {
                                "type": "PRICE",
                                "instrument": "USD_JPY",
                                "bids": [{"price": "150.10"}],
                                "asks": [{"price": "150.12"}],
                            }
                        ]
                    },
                ),
            ]
        )
        gateway = OandaGateway(
            access_token="token",
            hostname="api.example.test",
            stream_hostname="stream.example.test",
            opener=opener,
        )

        accounts = gateway.accounts.list_accounts()
        prices = gateway.pricing.get_account_prices("001", instruments="USD_JPY")

        assert isinstance(accounts.body, AccountsResponse)
        assert accounts.body.accounts[0].id == "001"
        assert isinstance(prices.body, PricingResponse)
        assert prices.body.prices[0].instrument == "USD_JPY"
        assert opener.requests[1].full_url.endswith("/v3/accounts/001/pricing?instruments=USD_JPY")
