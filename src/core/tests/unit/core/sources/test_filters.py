from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from autoforex.core import Candle, CurrencyPair, Money, Pips, Tick, TickGranularity
from autoforex.core.sources import (
    DataSource,
    FilteredDataSource,
    SpreadFilter,
    SpreadFilteredDataSource,
)


class MemoryDataSource(DataSource):
    def __init__(self, ticks: Iterable[Tick]) -> None:
        self._ticks = tuple(ticks)
        self.closed = False

    def _raw_ticks(
        self,
        *,
        instrument: CurrencyPair,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Tick]:
        _ = start_at
        _ = end_at
        requested_instrument = CurrencyPair.of(instrument)
        return (tick for tick in self._ticks if tick.instrument == requested_instrument)

    def close(self) -> None:
        self.closed = True


class MinimumBidFilter:
    def __init__(self, minimum_bid: Decimal) -> None:
        self.minimum_bid = minimum_bid

    def filter_ticks(self, ticks: Iterable[Tick]) -> Iterable[Tick]:
        return (tick for tick in ticks if tick.bid.amount >= self.minimum_bid)

    def filter_candles(self, candles: Iterable[Candle]) -> Iterable[Candle]:
        _ = self
        return candles


class TestFilters:
    def test_spread_filter_calculates_spread_pips_from_instrument(self) -> None:
        tick = make_tick(bid="150.10", ask="150.13")

        assert SpreadFilter.of(Pips("3")).spread_pips(tick) == Pips("3")

    def test_spread_filtered_data_source_filters_ticks_above_max_spread(self) -> None:
        source = SpreadFilteredDataSource(
            MemoryDataSource(
                [
                    make_tick(bid="150.10", ask="150.11"),
                    make_tick(bid="150.10", ask="150.13"),
                ]
            ),
            max_spread_pips=Pips("1"),
        )

        ticks = tuple(source.ticks(instrument=CurrencyPair.of("USD_JPY")))

        assert len(ticks) == 1
        assert ticks[0].ask.amount == Decimal("150.11")

    def test_spread_filtered_data_source_can_be_disabled_without_threshold(self) -> None:
        source = SpreadFilteredDataSource(
            MemoryDataSource(
                [
                    make_tick(bid="150.10", ask="150.11"),
                    make_tick(bid="150.10", ask="150.13"),
                ]
            ),
            enabled=False,
        )

        ticks = tuple(source.ticks(instrument=CurrencyPair.of("USD_JPY")))

        assert len(ticks) == 2

    def test_filtered_data_source_applies_custom_filters_before_granularity(self) -> None:
        source = FilteredDataSource(
            MemoryDataSource(
                [
                    make_tick(bid="150.00", ask="150.00", offset_seconds=0),
                    make_tick(bid="150.10", ask="150.10", offset_seconds=1),
                    make_tick(bid="150.20", ask="150.20", offset_seconds=60),
                ]
            ),
            filters=(MinimumBidFilter(Decimal("150.10")),),
        )

        ticks = tuple(
            source.ticks(
                instrument=CurrencyPair.of("USD_JPY"),
                granularity=TickGranularity.MINUTE_1,
            )
        )

        assert [tick.bid for tick in ticks] == [
            Money.of("150.10", "JPY"),
            Money.of("150.20", "JPY"),
        ]

    def test_spread_filter_requires_max_spread_when_enabled(self) -> None:
        with pytest.raises(ValueError, match="max_spread_pips is required"):
            SpreadFilter()

    def test_spread_filtered_data_source_delegates_close(self) -> None:
        wrapped = MemoryDataSource(())
        source = SpreadFilteredDataSource(wrapped, enabled=False)

        source.close()

        assert wrapped.closed is True


def make_tick(*, bid: str, ask: str, offset_seconds: int = 0) -> Tick:
    return Tick.model_validate(
        {
            "instrument": CurrencyPair.of("USD_JPY"),
            "timestamp": datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=offset_seconds),
            "bid": bid,
            "ask": ask,
        }
    )
