from __future__ import annotations

from autoforex.core import CurrencyPair, Money

from autoforex.oanda.mappers import OandaAccountMapper, OandaMarketDataMapper
from autoforex.oanda.models import (
    AccountSummaryResponse,
    OandaHttpResponse,
    OandaResponse,
    PricingResponse,
)


class TestMappers:
    def test_mappers_integrate_with_generated_oanda_models(self) -> None:
        summary_response = OandaResponse(
            raw=OandaHttpResponse(
                status=200,
                reason="OK",
                headers={},
                body={},
                raw_body=b"",
                url="https://api.example.test",
            ),
            body=AccountSummaryResponse.model_validate(
                {
                    "account": {
                        "id": "001",
                        "currency": "USD",
                        "balance": "1000.00",
                        "NAV": "1001.00",
                        "marginUsed": "10.00",
                        "marginAvailable": "991.00",
                    },
                    "lastTransactionID": "10",
                }
            ),
        )
        price_response = OandaResponse(
            raw=summary_response.raw,
            body=PricingResponse.model_validate(
                {
                    "prices": [
                        {
                            "type": "PRICE",
                            "instrument": "USD_JPY",
                            "time": "2026-01-01T00:00:00Z",
                            "bids": [{"price": "150.10"}],
                            "asks": [{"price": "150.12"}],
                        }
                    ]
                }
            ),
        )

        summary = OandaAccountMapper.summary_from_response(summary_response)
        tick = OandaMarketDataMapper().ticks_from_prices(price_response.body.prices)[0]

        assert summary.balance == Money.of("1000.00", "USD")
        assert tick.instrument == CurrencyPair.of("USD_JPY")
        assert tick.ask == Money.of("150.12", "JPY")
