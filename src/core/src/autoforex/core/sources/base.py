"""Market data source abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from datetime import datetime
from typing import Protocol

from autoforex.core.logging import get_logger
from autoforex.core.models import CurrencyPair
from autoforex.core.models.base import DomainModel
from autoforex.core.sources.models import Candle, CandleGranularity, Tick, TickGranularity

_LOGGER = get_logger(__name__)


class DataSourceFilter(Protocol):
    """Composable filter for data source streams."""

    def filter_ticks(self, ticks: Iterable[Tick]) -> Iterable[Tick]:
        """Return a filtered tick stream."""
        ...

    def filter_candles(self, candles: Iterable[Candle]) -> Iterable[Candle]:
        """Return a filtered candle stream."""
        ...


class TickGranularityFilter(DomainModel):
    """Tick filter that emits one tick per requested granularity bucket."""

    granularity: TickGranularity = TickGranularity.TICK

    @classmethod
    def of(cls, granularity: TickGranularity) -> TickGranularityFilter:
        """Create a granularity filter from a tick granularity value."""
        return cls(granularity=TickGranularity(granularity))

    def filter_ticks(self, ticks: Iterable[Tick]) -> Iterable[Tick]:
        """Downsample ticks to one per interval bucket."""
        interval = self.granularity.interval
        if interval is None:
            yield from ticks
            return
        interval_seconds = interval.total_seconds()
        current_bucket: int | None = None
        for tick in ticks:
            bucket = int(tick.timestamp.timestamp() // interval_seconds)
            if bucket != current_bucket:
                current_bucket = bucket
                yield tick

    def filter_candles(self, candles: Iterable[Candle]) -> Iterable[Candle]:
        """Leave candles unchanged."""
        _ = self
        return candles


class DataSource(ABC):
    """Abstract provider of historical or live market data."""

    @abstractmethod
    def _raw_ticks(
        self,
        *,
        instrument: CurrencyPair,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Tick]:
        """Yield every available tick for the instrument and optional range.

        Implemented by concrete sources. Callers use :meth:`ticks`, which
        applies the requested sampling granularity on top of these raw ticks.
        """

    def ticks(
        self,
        *,
        instrument: CurrencyPair,
        granularity: TickGranularity = TickGranularity.TICK,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Tick]:
        """Yield ticks for the instrument sampled at ``granularity``.

        ``granularity`` mirrors the ``granularity`` argument of :meth:`candles`.
        With :attr:`TickGranularity.TICK` every raw tick is yielded; otherwise
        the first tick of each fixed interval bucket is yielded.
        """
        raw = self._raw_ticks(instrument=instrument, start_at=start_at, end_at=end_at)
        return self._apply_tick_filters(raw, filters=self._tick_filters(granularity=granularity))

    def with_filters(self, *filters: DataSourceFilter) -> DataSource:
        """Return a data source decorator that applies additional filters."""
        from autoforex.core.sources.filters import FilteredDataSource

        return FilteredDataSource(self, filters=filters)

    def prices(
        self,
        *,
        instruments: Iterable[CurrencyPair],
        since: datetime | None = None,
        include_units_available: bool = False,
        include_home_conversions: bool = False,
    ) -> Iterable[Tick]:
        """Return the latest known prices for one or more instruments."""
        _ = include_units_available
        _ = include_home_conversions
        return (
            tick
            for instrument in instruments
            for tick in self.ticks(instrument=instrument, start_at=since)
        )

    def stream_prices(
        self,
        *,
        instruments: Iterable[CurrencyPair],
        snapshot: bool = True,
    ) -> Iterable[Tick]:
        """Yield live prices for one or more instruments."""
        _ = snapshot
        return (tick for instrument in instruments for tick in self.ticks(instrument=instrument))

    def candles(
        self,
        *,
        instrument: CurrencyPair,
        granularity: CandleGranularity,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Candle]:
        """Yield candles when the data source supports candle data."""
        _ = instrument
        _ = granularity
        _ = start_at
        _ = end_at
        return ()

    def close(self) -> None:
        """Release resources held by the data source."""
        return None

    def _tick_filters(self, *, granularity: TickGranularity) -> tuple[DataSourceFilter, ...]:
        """Return filters applied by :meth:`ticks` in execution order."""
        return (TickGranularityFilter.of(granularity),)

    @staticmethod
    def _apply_tick_filters(
        ticks: Iterable[Tick],
        *,
        filters: Iterable[DataSourceFilter],
    ) -> Iterable[Tick]:
        filtered = ticks
        for data_filter in filters:
            filtered = data_filter.filter_ticks(filtered)
        return filtered

    @staticmethod
    def _sample_ticks(
        ticks: Iterable[Tick],
        *,
        granularity: TickGranularity,
    ) -> Iterator[Tick]:
        """Downsample ticks to one per interval bucket (passthrough for TICK)."""
        yield from TickGranularityFilter.of(granularity).filter_ticks(ticks)
