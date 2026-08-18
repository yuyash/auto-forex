"""Composable data source filters."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from logging import Logger

from pydantic import model_validator

from autoforex.core.logging import get_logger
from autoforex.core.models import CurrencyPair
from autoforex.core.models.base import DomainModel
from autoforex.core.models.values import Pips
from autoforex.core.sources.base import DataSource, DataSourceFilter
from autoforex.core.sources.models import Candle, CandleGranularity, Tick, TickGranularity

_LOGGER: Logger = get_logger(__name__)


class SpreadFilter(DomainModel):
    """Tick-level bid/ask spread filter expressed in pips."""

    enabled: bool = True
    max_spread_pips: Pips | None = None

    @classmethod
    def of(cls, max_spread_pips: Pips) -> SpreadFilter:
        """Create an enabled spread filter for a maximum spread in pips."""
        return cls(max_spread_pips=Pips.of(max_spread_pips))

    @model_validator(mode="after")
    def _validate_configuration(self) -> SpreadFilter:
        if self.enabled and self.max_spread_pips is None:
            _LOGGER.debug("Rejected enabled spread filter without max spread")
            msg = "max_spread_pips is required when spread filter is enabled"
            raise ValueError(msg)
        if self.max_spread_pips is not None:
            self.max_spread_pips.require_positive()
        _LOGGER.debug(
            "Validated spread filter",
            extra={
                "spread_filter_enabled": self.enabled,
                "max_spread_pips": str(self.max_spread_pips or ""),
            },
        )
        return self

    def allows(self, tick: Tick) -> bool:
        """Return whether the tick should pass the spread filter."""
        if not self.enabled:
            return True
        max_spread_pips = self.max_spread_pips
        if max_spread_pips is None:
            msg = "max_spread_pips is required when spread filter is enabled"
            raise ValueError(msg)
        spread_pips = self.spread_pips(tick)
        allowed = spread_pips <= max_spread_pips
        _LOGGER.debug(
            "Evaluated tick spread filter",
            extra={
                "instrument": str(tick.instrument),
                "timestamp": tick.timestamp.isoformat(),
                "spread_pips": str(spread_pips),
                "max_spread_pips": str(max_spread_pips),
                "spread_filter_allowed": allowed,
            },
        )
        return allowed

    @staticmethod
    def spread_pips(tick: Tick) -> Pips:
        """Return a tick's bid/ask spread in instrument pips."""
        return Pips.of(tick.spread.amount / tick.instrument.pip_size)

    def filter_ticks(self, ticks: Iterable[Tick]) -> Iterable[Tick]:
        """Yield ticks allowed by the spread threshold."""
        yielded_count = 0
        skipped_count = 0
        for tick in ticks:
            if self.allows(tick):
                yielded_count += 1
                yield tick
                continue
            skipped_count += 1
            _LOGGER.debug(
                "Skipped tick because spread exceeded filter threshold",
                extra={
                    "instrument": str(tick.instrument),
                    "timestamp": tick.timestamp.isoformat(),
                    "spread_pips": str(self.spread_pips(tick)),
                    "max_spread_pips": str(self.max_spread_pips or ""),
                    "skipped_count": skipped_count,
                },
            )
        _LOGGER.debug(
            "Finished applying spread filter",
            extra={
                "spread_filter_enabled": self.enabled,
                "max_spread_pips": str(self.max_spread_pips or ""),
                "yielded_count": yielded_count,
                "skipped_count": skipped_count,
            },
        )

    def filter_candles(self, candles: Iterable[Candle]) -> Iterable[Candle]:
        """Leave candles unchanged because bid/ask spread is tick-level data."""
        _ = self
        return candles


class FilteredDataSource(DataSource):
    """Data source decorator that applies composable filters."""

    def __init__(
        self,
        source: DataSource,
        *,
        filters: Iterable[DataSourceFilter],
    ) -> None:
        self._source = source
        self._filters = tuple(filters)

    @property
    def source(self) -> DataSource:
        """Return the wrapped data source."""
        return self._source

    @property
    def filters(self) -> tuple[DataSourceFilter, ...]:
        """Return configured filters in execution order."""
        return self._filters

    def _raw_ticks(
        self,
        *,
        instrument: CurrencyPair,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Tick]:
        """Yield full-resolution ticks from the wrapped source."""
        return self._source.ticks(
            instrument=instrument,
            granularity=TickGranularity.TICK,
            start_at=start_at,
            end_at=end_at,
        )

    def _tick_filters(self, *, granularity: TickGranularity) -> tuple[DataSourceFilter, ...]:
        """Apply custom filters before the requested granularity filter."""
        return (*self._filters, *super()._tick_filters(granularity=granularity))

    def candles(
        self,
        *,
        instrument: CurrencyPair,
        granularity: CandleGranularity,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Candle]:
        """Yield candles from the wrapped source after applying candle filters."""
        candles = self._source.candles(
            instrument=instrument,
            granularity=granularity,
            start_at=start_at,
            end_at=end_at,
        )
        filtered = candles
        for data_filter in self._filters:
            filtered = data_filter.filter_candles(filtered)
        return filtered

    def close(self) -> None:
        """Close the wrapped data source."""
        self._source.close()


class SpreadFilteredDataSource(DataSource):
    """Data source decorator that filters ticks by bid/ask spread."""

    def __init__(
        self,
        source: DataSource,
        *,
        spread_filter: SpreadFilter | None = None,
        max_spread_pips: Pips | None = None,
        enabled: bool = True,
    ) -> None:
        if spread_filter is not None and max_spread_pips is not None:
            msg = "provide either spread_filter or max_spread_pips, not both"
            raise ValueError(msg)
        self.spread_filter = spread_filter or SpreadFilter(
            enabled=enabled,
            max_spread_pips=self._optional_decimal(max_spread_pips),
        )
        self._filtered_source = FilteredDataSource(source, filters=(self.spread_filter,))

    @property
    def source(self) -> DataSource:
        """Return the wrapped data source."""
        return self._filtered_source.source

    def _raw_ticks(
        self,
        *,
        instrument: CurrencyPair,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Tick]:
        """Yield raw spread-filtered ticks from the wrapped source."""
        return self._filtered_source.ticks(
            instrument=instrument,
            granularity=TickGranularity.TICK,
            start_at=start_at,
            end_at=end_at,
        )

    def candles(
        self,
        *,
        instrument: CurrencyPair,
        granularity: CandleGranularity,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Candle]:
        """Delegate candles unchanged because bid/ask spread is tick-level data."""
        return self._filtered_source.candles(
            instrument=instrument,
            granularity=granularity,
            start_at=start_at,
            end_at=end_at,
        )

    def close(self) -> None:
        """Close the wrapped data source."""
        self._filtered_source.close()

    @staticmethod
    def _optional_decimal(value: Pips | None) -> Pips | None:
        if value is None:
            return None
        return Pips.of(value)
