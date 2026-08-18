from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from autoforex.core import Candle, CandleGranularity, CurrencyPair, Money, Tick, TickGranularity
from autoforex.core.sources import DataSource

USD_JPY = CurrencyPair.of("USD_JPY")


class EmptyDataSource(DataSource):
    def _raw_ticks(
        self,
        *,
        instrument: CurrencyPair,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Tick]:
        _ = instrument
        _ = start_at
        _ = end_at
        return ()


class SequenceDataSource(DataSource):
    """Yield a fixed sequence of ticks for sampling tests."""

    def __init__(self, ticks: Iterable[Tick]) -> None:
        self._ticks = tuple(ticks)

    def _raw_ticks(
        self,
        *,
        instrument: CurrencyPair,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Tick]:
        _ = instrument
        _ = start_at
        _ = end_at
        return self._ticks


def _tick(offset_seconds: int, bid: str) -> Tick:
    return Tick(
        instrument=USD_JPY,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=offset_seconds),
        bid=Money.of(bid, "JPY"),
        ask=Money.of(bid, "JPY"),
    )


class TestBase:
    def test_data_source_default_candles_and_close_are_noops(self) -> None:
        source = EmptyDataSource()

        candles: Iterable[Candle] = source.candles(
            instrument=CurrencyPair.of("USD_JPY"),
            granularity=CandleGranularity.MINUTE_1,
        )

        assert tuple(candles) == ()
        assert source.close() is None

    def test_ticks_default_granularity_yields_every_tick(self) -> None:
        ticks = [_tick(0, "150.00"), _tick(1, "150.01"), _tick(2, "150.02")]
        source = SequenceDataSource(ticks)

        result = tuple(source.ticks(instrument=USD_JPY))

        assert result == tuple(ticks)

    def test_ticks_downsamples_to_one_per_interval_bucket(self) -> None:
        # Three ticks within the first minute and two in the second minute.
        ticks = [
            _tick(0, "150.00"),
            _tick(20, "150.01"),
            _tick(40, "150.02"),
            _tick(60, "150.03"),
            _tick(90, "150.04"),
        ]
        source = SequenceDataSource(ticks)

        result = tuple(source.ticks(instrument=USD_JPY, granularity=TickGranularity.MINUTE_1))

        # One tick per minute bucket: the first of each bucket.
        assert [tick.bid for tick in result] == [
            Money.of("150.00", "JPY"),
            Money.of("150.03", "JPY"),
        ]

    def test_ticks_explicit_tick_granularity_is_passthrough(self) -> None:
        ticks = [_tick(0, "150.00"), _tick(1, "150.01")]
        source = SequenceDataSource(ticks)

        result = tuple(source.ticks(instrument=USD_JPY, granularity=TickGranularity.TICK))

        assert result == tuple(ticks)
