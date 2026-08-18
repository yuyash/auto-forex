from __future__ import annotations

from typing import cast

from autoforex.core import CandleGranularity, CurrencyPair, Money

from autoforex.oanda.source import (
    OandaDataSource,
    OandaPricingClient,
    OandaSession,
    OandaTimeFormatter,
)
from tests.integration.fakes import IntegrationGateway


class TestSource:
    def test_data_source_integrates_gateway_and_market_data_mapper_without_http(self) -> None:
        gateway = IntegrationGateway()
        source = OandaDataSource(
            account_id="001",
            pricing=cast(OandaPricingClient, gateway.pricing),
            time_formatter=cast(OandaTimeFormatter, gateway.transport),
            session=cast(OandaSession, gateway.transport),
        )

        prices = tuple(source.prices(instruments=(CurrencyPair.of("USD_JPY"),)))
        candles = tuple(
            source.candles(
                instrument=CurrencyPair.of("USD_JPY"),
                granularity=CandleGranularity.MINUTE_1,
            )
        )

        assert prices[0].bid == Money.of("150.10", "JPY")
        assert candles[0].close == Money.of("150.10", "JPY")
