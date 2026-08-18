from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from autoforex.core import Candle, CurrencyPair, Metadata, Money, Tick

USD_JPY = CurrencyPair.of("USD_JPY")
EUR_USD = CurrencyPair.of("EUR_USD")


class TestModels:
    def test_tick_calculates_mid_and_spread(self) -> None:
        tick = Tick(
            instrument=USD_JPY,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            bid=Money.of("150.10", "JPY"),
            ask=Money.of("150.12", "JPY"),
            metadata=Metadata.of(provider="memory"),
        )

        assert tick.effective_mid == Money.of("150.11", "JPY")
        assert tick.spread == Money.of("0.02", "JPY")
        assert tick.metadata == Metadata.of(provider="memory")

    def test_tick_rejects_naive_datetime_and_invalid_prices(self) -> None:
        with pytest.raises(ValidationError):
            Tick(
                instrument=USD_JPY,
                timestamp=datetime(2026, 1, 1),
                bid=Money.of("150.10", "JPY"),
                ask=Money.of("150.12", "JPY"),
            )
        with pytest.raises(ValidationError, match="ask must be greater"):
            Tick(
                instrument=USD_JPY,
                timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                bid=Money.of("150.12", "JPY"),
                ask=Money.of("150.10", "JPY"),
            )

    def test_candle_validates_ohlc_range_and_metadata(self) -> None:
        candle = Candle.model_validate(
            {
                "instrument": EUR_USD,
                "timestamp": datetime(2026, 1, 1, tzinfo=UTC),
                "granularity": "M1",
                "open": Decimal("1.1000"),
                "high": Decimal("1.1010"),
                "low": Decimal("1.0990"),
                "close": Decimal("1.1005"),
                "volume": 120,
                "metadata": {"provider": "memory"},
            }
        )

        assert candle.range == Money.of("0.0020", "USD")
        assert candle.metadata == Metadata.of(provider="memory")
        assert candle.volume == 120
