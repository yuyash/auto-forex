"""CSV-backed market data source."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, tzinfo
from logging import Logger
from os import PathLike
from pathlib import Path
from typing import Any

from autoforex.core.clock import local_timezone
from autoforex.core.logging import get_logger
from autoforex.core.models import CurrencyPair
from autoforex.core.sources.base import DataSource
from autoforex.core.sources.csv_errors import CSVDataSourceError
from autoforex.core.sources.csv_mapping import CSVCandleMapper, CSVTickMapper
from autoforex.core.sources.csv_parsing import (
    CSVModelValueParser,
    CSVRowDiagnostics,
    CSVSymbol,
    CSVTimestampFormat,
    CSVTimestampParser,
)
from autoforex.core.sources.csv_paths import CSVSourcePaths
from autoforex.core.sources.csv_rows import CSVFileRowReader
from autoforex.core.sources.csv_streaming import CSVLoadLogger, CSVTimestampRange
from autoforex.core.sources.models import Candle, CandleGranularity, Tick

_LOGGER: Logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CSVTickSchema:
    """Column names used to parse tick CSV rows."""

    timestamp: str = "timestamp"
    instrument: str = "instrument"
    bid: str = "bid"
    ask: str = "ask"
    mid: str | None = "mid"
    metadata_prefix: str = "metadata."
    metadata_columns: tuple[str, ...] = ()
    timestamp_format: CSVTimestampFormat = CSVTimestampFormat.ISO
    instrument_prefix_separator: str | None = ":"

    @classmethod
    def polygon_forex_quotes(cls, *, ticker_column: str = "ticker") -> CSVTickSchema:
        """Return a schema for Polygon-style forex quote CSV files."""
        return cls(
            timestamp="participant_timestamp",
            instrument=ticker_column,
            bid="bid_price",
            ask="ask_price",
            mid=None,
            metadata_columns=("ask_exchange", "bid_exchange"),
            timestamp_format=CSVTimestampFormat.UNIX_NANOSECONDS,
        )


@dataclass(frozen=True, slots=True)
class CSVCandleSchema:
    """Column names used to parse candle CSV rows."""

    timestamp: str = "timestamp"
    instrument: str = "instrument"
    granularity: str = "granularity"
    open: str = "open"
    high: str = "high"
    low: str = "low"
    close: str = "close"
    volume: str | None = "volume"
    complete: str | None = "complete"
    metadata_prefix: str = "metadata."
    metadata_columns: tuple[str, ...] = ()
    timestamp_format: CSVTimestampFormat = CSVTimestampFormat.ISO
    instrument_prefix_separator: str | None = ":"

    @classmethod
    def polygon_forex_minute_aggs(cls, *, ticker_column: str = "ticker") -> CSVCandleSchema:
        """Return a schema for Polygon-style forex one-minute aggregate CSV files."""
        return cls(
            timestamp="window_start",
            instrument=ticker_column,
            granularity="granularity",
            open="open",
            high="high",
            low="low",
            close="close",
            volume="volume",
            complete=None,
            metadata_columns=("transactions",),
            timestamp_format=CSVTimestampFormat.UNIX_NANOSECONDS,
        )


class CSVDataSource(DataSource):
    """Data source that yields ticks and candles from one or more CSV files."""

    def __init__(
        self,
        *,
        tick_path: str | PathLike[str] | None = None,
        candle_path: str | PathLike[str] | None = None,
        tick_paths: Sequence[str | PathLike[str]] | None = None,
        candle_paths: Sequence[str | PathLike[str]] | None = None,
        tick_schema: CSVTickSchema | None = None,
        candle_schema: CSVCandleSchema | None = None,
        encoding: str = "utf-8",
        assume_timezone: tzinfo | None = None,
    ) -> None:
        self.tick_paths = CSVSourcePaths.resolve(
            single=tick_path,
            multiple=tick_paths,
            label="tick",
        )
        self.candle_paths = CSVSourcePaths.resolve(
            single=candle_path,
            multiple=candle_paths,
            label="candle",
        )
        self.tick_schema = tick_schema or CSVTickSchema()
        self.candle_schema = candle_schema or CSVCandleSchema()
        self.encoding = encoding
        self.assume_timezone = assume_timezone or local_timezone()
        self.load_logger = CSVLoadLogger(_LOGGER)
        self.reader = CSVFileRowReader(encoding=encoding, logger=_LOGGER)
        self.timestamps = CSVTimestampParser(
            assume_timezone=self.assume_timezone,
            logger=_LOGGER,
        )
        self.values = CSVModelValueParser(logger=_LOGGER)
        self.tick_mapper = CSVTickMapper(
            schema=self.tick_schema,
            timestamps=self.timestamps,
            values=self.values,
            logger=_LOGGER,
        )
        self.candle_mapper = CSVCandleMapper(
            schema=self.candle_schema,
            timestamps=self.timestamps,
            values=self.values,
            logger=_LOGGER,
        )

    @classmethod
    def from_directory(
        cls,
        directory: str | PathLike[str],
        *,
        tick_pattern: str | None = None,
        candle_pattern: str | None = None,
        **kwargs: Any,
    ) -> CSVDataSource:
        """Create a source from files matching glob patterns in ``directory``."""
        base = Path(directory)
        if tick_pattern is None and candle_pattern is None:
            msg = "provide tick_pattern and/or candle_pattern"
            raise ValueError(msg)
        if tick_pattern is not None:
            kwargs["tick_paths"] = CSVSourcePaths.glob_sorted(base, tick_pattern)
        if candle_pattern is not None:
            kwargs["candle_paths"] = CSVSourcePaths.glob_sorted(base, candle_pattern)
        return cls(**kwargs)

    def _raw_ticks(
        self,
        *,
        instrument: CurrencyPair,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Tick]:
        """Yield every tick from the configured tick CSV file(s)."""
        if not self.tick_paths:
            _LOGGER.debug(
                "CSV tick path is not configured",
                extra={"instrument": str(instrument), "data_kind": "tick"},
            )
            return
        requested_instrument = CurrencyPair.of(instrument)
        self.load_logger.start("tick", requested_instrument, self.tick_paths)
        target = CSVSymbol.compact(requested_instrument)
        requested_range = CSVTimestampRange(start_at=start_at, end_at=end_at)
        yielded_count = 0
        for path in self.tick_paths:
            for row in self.reader.rows(
                path,
                instrument_column=self.tick_schema.instrument,
                target=target,
                prefix_separator=self.tick_schema.instrument_prefix_separator,
            ):
                tick = self.tick_mapper.from_row(row, requested_instrument)
                if tick.instrument != requested_instrument:
                    _LOGGER.debug(
                        "Skipped CSV tick row for different instrument",
                        extra={
                            **CSVRowDiagnostics.log_extra(row),
                            "instrument": str(tick.instrument),
                            "requested_instrument": str(requested_instrument),
                            "data_kind": "tick",
                        },
                    )
                    continue
                if not requested_range.includes(tick.timestamp):
                    continue
                yielded_count += 1
                yield tick
        self.load_logger.finish("tick", requested_instrument, self.tick_paths, yielded_count)

    def candles(
        self,
        *,
        instrument: CurrencyPair,
        granularity: CandleGranularity,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Candle]:
        """Yield candles from the configured candle CSV file(s)."""
        if not self.candle_paths:
            _LOGGER.debug(
                "CSV candle path is not configured",
                extra={
                    "instrument": str(instrument),
                    "granularity": granularity.value,
                    "data_kind": "candle",
                },
            )
            return
        requested_instrument = CurrencyPair.of(instrument)
        self.load_logger.start("candle", requested_instrument, self.candle_paths, granularity)
        target = CSVSymbol.compact(requested_instrument)
        requested_range = CSVTimestampRange(start_at=start_at, end_at=end_at)
        yielded_count = 0
        for path in self.candle_paths:
            for row in self.reader.rows(
                path,
                instrument_column=self.candle_schema.instrument,
                target=target,
                prefix_separator=self.candle_schema.instrument_prefix_separator,
            ):
                candle = self.candle_mapper.from_row(row, requested_instrument, granularity)
                if candle.instrument != requested_instrument:
                    _LOGGER.debug(
                        "Skipped CSV candle row for different instrument",
                        extra={
                            **CSVRowDiagnostics.log_extra(row),
                            "instrument": str(candle.instrument),
                            "requested_instrument": str(requested_instrument),
                            "granularity": str(candle.granularity),
                            "data_kind": "candle",
                        },
                    )
                    continue
                if candle.granularity != granularity:
                    continue
                if not requested_range.includes(candle.timestamp):
                    continue
                yielded_count += 1
                yield candle
        self.load_logger.finish("candle", requested_instrument, self.candle_paths, yielded_count)


__all__ = [
    "CSVCandleSchema",
    "CSVDataSource",
    "CSVDataSourceError",
    "CSVTickSchema",
    "CSVTimestampFormat",
]
