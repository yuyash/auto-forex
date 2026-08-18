"""CSV row to Core market-data model mappers."""

from __future__ import annotations

from logging import Logger
from typing import Any

from autoforex.core.models import CurrencyPair
from autoforex.core.sources.csv_parsing import (
    CSVModelValueParser,
    CSVRowDiagnostics,
    CSVRowValues,
    CSVTimestampParser,
)
from autoforex.core.sources.csv_rows import CSVRow
from autoforex.core.sources.models import Candle, CandleGranularity, Tick


class CSVTickMapper:
    """Map CSV rows into Tick models."""

    def __init__(
        self,
        *,
        schema: Any,
        timestamps: CSVTimestampParser,
        values: CSVModelValueParser,
        logger: Logger,
    ) -> None:
        self.schema = schema
        self.timestamps = timestamps
        self.values = values
        self.logger = logger

    def from_row(self, row: CSVRow, instrument: CurrencyPair) -> Tick:
        """Return one Tick from a CSV row."""
        schema = self.schema
        row_instrument = CSVRowValues.optional(row, schema.instrument)
        model_values: dict[str, Any] = {
            "instrument": self.values.instrument(
                row_instrument,
                fallback=instrument,
                prefix_separator=schema.instrument_prefix_separator,
            ),
            "timestamp": self.timestamps.parse(
                CSVRowValues.require(row, schema.timestamp, logger=self.logger),
                row,
                timestamp_format=schema.timestamp_format,
            ),
            "bid": CSVRowValues.require(row, schema.bid, logger=self.logger),
            "ask": CSVRowValues.require(row, schema.ask, logger=self.logger),
            "metadata": self.values.metadata(
                row,
                schema.metadata_prefix,
                schema.metadata_columns,
            ),
        }
        if schema.mid is not None:
            mid = CSVRowValues.optional(row, schema.mid)
            if mid is not None:
                model_values["mid"] = mid
        tick = Tick.model_validate(model_values)
        self.logger.debug(
            "Parsed CSV tick row",
            extra={
                **CSVRowDiagnostics.log_extra(row),
                "instrument": str(tick.instrument),
                "timestamp": tick.timestamp.isoformat(),
                "data_kind": "tick",
            },
        )
        return tick


class CSVCandleMapper:
    """Map CSV rows into Candle models."""

    def __init__(
        self,
        *,
        schema: Any,
        timestamps: CSVTimestampParser,
        values: CSVModelValueParser,
        logger: Logger,
    ) -> None:
        self.schema = schema
        self.timestamps = timestamps
        self.values = values
        self.logger = logger

    def from_row(
        self,
        row: CSVRow,
        instrument: CurrencyPair,
        granularity: CandleGranularity,
    ) -> Candle:
        """Return one Candle from a CSV row."""
        schema = self.schema
        row_instrument = CSVRowValues.optional(row, schema.instrument)
        row_granularity = CSVRowValues.optional(row, schema.granularity)
        model_values: dict[str, Any] = {
            "instrument": self.values.instrument(
                row_instrument,
                fallback=instrument,
                prefix_separator=schema.instrument_prefix_separator,
            ),
            "timestamp": self.timestamps.parse(
                CSVRowValues.require(row, schema.timestamp, logger=self.logger),
                row,
                timestamp_format=schema.timestamp_format,
            ),
            "granularity": CandleGranularity(row_granularity or granularity.value),
            "open": CSVRowValues.require(row, schema.open, logger=self.logger),
            "high": CSVRowValues.require(row, schema.high, logger=self.logger),
            "low": CSVRowValues.require(row, schema.low, logger=self.logger),
            "close": CSVRowValues.require(row, schema.close, logger=self.logger),
            "metadata": self.values.metadata(
                row,
                schema.metadata_prefix,
                schema.metadata_columns,
            ),
        }
        if schema.volume is not None:
            volume = CSVRowValues.optional(row, schema.volume)
            if volume is not None:
                model_values["volume"] = int(volume)
        if schema.complete is not None:
            complete = CSVRowValues.optional(row, schema.complete)
            if complete is not None:
                model_values["complete"] = self.values.boolean(complete, row)
        candle = Candle.model_validate(model_values)
        self.logger.debug(
            "Parsed CSV candle row",
            extra={
                **CSVRowDiagnostics.log_extra(row),
                "instrument": str(candle.instrument),
                "timestamp": candle.timestamp.isoformat(),
                "granularity": str(candle.granularity),
                "data_kind": "candle",
            },
        )
        return candle
