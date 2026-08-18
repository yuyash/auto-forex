from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from autoforex.core import CandleGranularity, CurrencyPair, Money, Tick

import autoforex.oanda.models as om
from autoforex.oanda.source import OandaDataSource
from tests.support import FakeResponse

USD_JPY = CurrencyPair.of("USD_JPY")


class StreamResponseFake:
    def parts(self) -> tuple[tuple[str, object], ...]:
        return (
            ("PricingHeartbeat", SimpleNamespace()),
            ("ClientPrice", SimpleNamespace(instrument="USD_JPY")),
        )


class TestSource:
    def test_data_source_ticks_with_since_uses_account_pricing_endpoint(self) -> None:
        pricing = Mock()
        mapper = Mock()
        tick = Tick(
            instrument=USD_JPY,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            bid=Money.of("150.10", "JPY"),
            ask=Money.of("150.12", "JPY"),
        )
        pricing.get_account_prices.return_value = FakeResponse(200, {"prices": ["price"]})
        mapper.ticks_from_prices.return_value = (tick,)
        source = OandaDataSource(
            account_id="001",
            pricing=pricing,
            time_formatter=Mock(datetime_to_str=Mock(return_value="2026-01-01T00:00:00Z")),
            mapper=mapper,
        )

        result = tuple(
            source.ticks(
                instrument=USD_JPY,
                start_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert result == (tick,)
        pricing.get_account_prices.assert_called_once_with(
            "001",
            om.PricingRequest.model_validate(
                {
                    "instruments": ("USD_JPY",),
                    "since": "2026-01-01T00:00:00Z",
                    "includeUnitsAvailable": False,
                    "includeHomeConversions": False,
                }
            ),
        )

    def test_data_source_ticks_rejects_historical_end_time(self) -> None:
        source = OandaDataSource(
            account_id="001",
            pricing=Mock(),
            time_formatter=Mock(),
        )

        with pytest.raises(NotImplementedError, match="historical tick ranges"):
            source.ticks(
                instrument=USD_JPY,
                end_at=datetime(2026, 1, 1, tzinfo=UTC),
            )

    def test_data_source_prices_uses_account_pricing_endpoint(self) -> None:
        pricing = Mock()
        time_formatter = Mock()
        mapper = Mock()
        tick = Tick(
            instrument=USD_JPY,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            bid=Money.of("150.10", "JPY"),
            ask=Money.of("150.12", "JPY"),
        )
        pricing.get_account_prices.return_value = FakeResponse(200, {"prices": ["price"]})
        time_formatter.datetime_to_str.return_value = "2026-01-01T00:00:00Z"
        mapper.ticks_from_prices.return_value = (tick,)
        source = OandaDataSource(
            account_id="001",
            pricing=pricing,
            time_formatter=time_formatter,
            mapper=mapper,
        )

        result = tuple(
            source.prices(
                instruments=(USD_JPY,),
                since=datetime(2026, 1, 1, tzinfo=UTC),
                include_units_available=True,
                include_home_conversions=True,
            )
        )

        assert result == (tick,)
        pricing.get_account_prices.assert_called_once_with(
            "001",
            om.PricingRequest.model_validate(
                {
                    "instruments": ("USD_JPY",),
                    "since": "2026-01-01T00:00:00Z",
                    "includeUnitsAvailable": True,
                    "includeHomeConversions": True,
                }
            ),
        )
        mapper.ticks_from_prices.assert_called_once_with(["price"])

    def test_data_source_candles_uses_account_candles_endpoint(self) -> None:
        pricing = Mock()
        mapper = Mock()
        pricing.get_account_candles.return_value = FakeResponse(200, {"candles": ["candle"]})
        mapper.candles_from_response.return_value = ("mapped-candle",)
        source = OandaDataSource(
            account_id="001",
            pricing=pricing,
            time_formatter=Mock(),
            mapper=mapper,
        )

        assert tuple(
            source.candles(instrument=USD_JPY, granularity=CandleGranularity.MINUTE_1)
        ) == ("mapped-candle",)
        pricing.get_account_candles.assert_called_once_with(
            "001",
            "USD_JPY",
            om.AccountCandlesRequest.model_validate(
                {"price": "M", "granularity": "M1", "from": None, "to": None}
            ),
        )

    def test_data_source_stream_prices_yields_mapped_non_heartbeat_parts(self) -> None:
        pricing = Mock()
        mapper = Mock()
        tick = Tick(
            instrument=USD_JPY,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            bid=Money.of("150.10", "JPY"),
            ask=Money.of("150.12", "JPY"),
        )
        pricing.stream_account_prices.return_value = StreamResponseFake()
        mapper.tick_from_price.return_value = tick
        source = OandaDataSource(
            account_id="001",
            pricing=pricing,
            time_formatter=Mock(),
            mapper=mapper,
        )

        assert tuple(source.stream_prices(instruments=(USD_JPY,), snapshot=False)) == (tick,)
        pricing.stream_account_prices.assert_called_once_with(
            "001",
            instruments="USD_JPY",
            snapshot=False,
        )

    def test_data_source_close_closes_gateway_opener(self) -> None:
        opener = Mock()
        session = Mock()
        session.opener = opener
        source = OandaDataSource(
            account_id="001",
            pricing=Mock(),
            time_formatter=Mock(),
            session=session,
            mapper=Mock(),
        )

        source.close()

        opener.close.assert_called_once_with()
