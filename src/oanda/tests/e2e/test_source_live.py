from __future__ import annotations

from autoforex.core import CandleGranularity, CurrencyPair, Tick

from autoforex.oanda import OandaProvider
from autoforex.oanda.mappers import OandaInstrumentMapper
from tests.e2e.coverage import covers_endpoints


class TestSourceLive:
    @covers_endpoints("pricing.get_account_prices")
    def test_live_get_account_prices(
        self,
        oanda_provider: OandaProvider,
        e2e_instrument: CurrencyPair,
    ) -> None:
        prices = tuple(oanda_provider.data.prices(instruments=(e2e_instrument,)))

        assert prices
        assert prices[0].instrument == e2e_instrument

    @covers_endpoints("pricing.get_account_candles")
    def test_live_get_account_candles(
        self,
        oanda_provider: OandaProvider,
        e2e_instrument: CurrencyPair,
    ) -> None:
        candles = tuple(
            oanda_provider.data.candles(
                instrument=e2e_instrument,
                granularity=CandleGranularity.MINUTE_1,
            )
        )

        assert candles
        assert candles[0].instrument == e2e_instrument

    @covers_endpoints("pricing.get_instrument_candles")
    def test_live_get_instrument_candles(
        self,
        oanda_provider: OandaProvider,
        e2e_instrument: CurrencyPair,
    ) -> None:
        response = oanda_provider.gateway.pricing.get_instrument_candles(
            OandaInstrumentMapper.to_oanda(e2e_instrument),
            price="M",
            granularity="M1",
            count=1,
        )

        assert response.status == 200
        assert response.body is not None
        assert response.body.candles

    @covers_endpoints("pricing.stream_account_prices")
    def test_live_data_source_pricing_stream_snapshot(
        self,
        oanda_provider: OandaProvider,
        e2e_instrument: CurrencyPair,
    ) -> None:
        stream = oanda_provider.data.stream_prices(
            instruments=(e2e_instrument,),
            snapshot=True,
        )
        tick = next(iter(stream))

        assert isinstance(tick, Tick)
        assert tick.instrument == e2e_instrument
