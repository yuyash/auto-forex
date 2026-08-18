"""CSV row value parsing."""

from __future__ import annotations

from datetime import UTC, datetime, tzinfo
from enum import StrEnum
from logging import Logger

from autoforex.core.models import CurrencyPair, Metadata
from autoforex.core.sources.csv_errors import CSVDataSourceError
from autoforex.core.sources.csv_rows import CSVInstrumentNormalizer, CSVRow


class CSVTimestampFormat(StrEnum):
    """Timestamp formats supported by CSVDataSource."""

    ISO = "iso"
    UNIX_SECONDS = "unix_seconds"
    UNIX_MILLISECONDS = "unix_milliseconds"
    UNIX_MICROSECONDS = "unix_microseconds"
    UNIX_NANOSECONDS = "unix_nanoseconds"


class CSVRowValues:
    """Access and validate raw row values."""

    @staticmethod
    def require(row: CSVRow, column: str, *, logger: Logger) -> str:
        """Return a non-empty column value or raise."""
        value = CSVRowValues.optional(row, column)
        if value is None:
            logger.warning(
                "Missing required CSV column value %s",
                column,
                extra=CSVRowDiagnostics.log_extra(row, csv_column=column),
            )
            msg = CSVRowDiagnostics.error(row, f"missing required column value: {column}")
            raise CSVDataSourceError(msg)
        return value

    @staticmethod
    def optional(row: CSVRow, column: str) -> str | None:
        """Return a stripped optional column value."""
        value = row.values.get(column)
        if value is None:
            return None
        text = str(value).strip()
        if text == "":
            return None
        return text


class CSVTimestampParser:
    """Parse timestamp columns into aware datetimes."""

    def __init__(self, *, assume_timezone: tzinfo, logger: Logger) -> None:
        self.assume_timezone = assume_timezone
        self.logger = logger

    def parse(
        self,
        value: str,
        row: CSVRow,
        *,
        timestamp_format: CSVTimestampFormat,
    ) -> datetime:
        """Parse a timestamp value."""
        raw = value.strip()
        if timestamp_format != CSVTimestampFormat.ISO:
            return self._parse_epoch(raw, row, timestamp_format=timestamp_format)
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            self.logger.warning(
                "Invalid CSV datetime %s",
                raw,
                extra=CSVRowDiagnostics.log_extra(row, csv_value=raw),
            )
            msg = CSVRowDiagnostics.error(row, f"invalid datetime: {raw}")
            raise CSVDataSourceError(msg) from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return parsed.replace(tzinfo=self.assume_timezone)
        return parsed

    def _parse_epoch(
        self,
        value: str,
        row: CSVRow,
        *,
        timestamp_format: CSVTimestampFormat,
    ) -> datetime:
        try:
            raw_epoch = int(value)
        except ValueError as exc:
            self.logger.warning(
                "Invalid CSV epoch timestamp %s",
                value,
                extra=CSVRowDiagnostics.log_extra(row, csv_value=value),
            )
            msg = CSVRowDiagnostics.error(row, f"invalid epoch timestamp: {value}")
            raise CSVDataSourceError(msg) from exc

        if timestamp_format == CSVTimestampFormat.UNIX_SECONDS:
            seconds = raw_epoch
            microseconds = 0
        elif timestamp_format == CSVTimestampFormat.UNIX_MILLISECONDS:
            seconds, milliseconds = divmod(raw_epoch, 1_000)
            microseconds = milliseconds * 1_000
        elif timestamp_format == CSVTimestampFormat.UNIX_MICROSECONDS:
            seconds, microseconds = divmod(raw_epoch, 1_000_000)
        elif timestamp_format == CSVTimestampFormat.UNIX_NANOSECONDS:
            seconds, nanoseconds = divmod(raw_epoch, 1_000_000_000)
            microseconds = nanoseconds // 1_000
        else:
            msg = CSVRowDiagnostics.error(row, f"unsupported timestamp format: {timestamp_format}")
            raise CSVDataSourceError(msg)
        return datetime.fromtimestamp(seconds, tz=UTC).replace(microsecond=microseconds)


class CSVModelValueParser:
    """Parse non-timestamp CSV model values."""

    def __init__(self, *, logger: Logger) -> None:
        self.logger = logger

    @staticmethod
    def instrument(
        value: str | None,
        *,
        fallback: CurrencyPair,
        prefix_separator: str | None,
    ) -> CurrencyPair:
        """Parse an instrument value with fallback."""
        if value is None:
            return fallback
        normalized = value
        if prefix_separator and prefix_separator in normalized:
            normalized = normalized.rsplit(prefix_separator, maxsplit=1)[-1]
        return CurrencyPair.of(normalized)

    def metadata(
        self,
        row: CSVRow,
        prefix: str,
        metadata_columns: tuple[str, ...],
    ) -> Metadata:
        """Parse metadata columns."""
        metadata = {
            key.removeprefix(prefix): value
            for key, value in row.values.items()
            if prefix and key.startswith(prefix) and value not in (None, "")
        }
        for column in metadata_columns:
            value = CSVRowValues.optional(row, column)
            if value is not None:
                metadata[column] = value
        return Metadata.model_validate(metadata)

    def boolean(self, value: str, row: CSVRow) -> bool:
        """Parse a boolean value."""
        normalized = value.strip().lower()
        if normalized in {"1", "true", "t", "yes", "y"}:
            return True
        if normalized in {"0", "false", "f", "no", "n"}:
            return False
        self.logger.warning(
            "Invalid CSV boolean %s",
            value,
            extra=CSVRowDiagnostics.log_extra(row, csv_value=value),
        )
        msg = CSVRowDiagnostics.error(row, f"invalid boolean: {value}")
        raise CSVDataSourceError(msg)


class CSVRowDiagnostics:
    """Build CSV row diagnostics."""

    @staticmethod
    def error(row: CSVRow, message: str) -> str:
        """Return an error string with row location."""
        return f"{row.path}:{row.number}: {message}"

    @staticmethod
    def log_extra(
        row: CSVRow,
        *,
        csv_column: str = "",
        csv_value: str = "",
    ) -> dict[str, str | int]:
        """Return structured logging context for a row."""
        return {
            "csv_path": str(row.path),
            "csv_row": row.number,
            "csv_column": csv_column,
            "csv_value": csv_value,
        }


class CSVSymbol:
    """Symbol formatting helpers."""

    @staticmethod
    def compact(instrument: CurrencyPair) -> str:
        """Return the separator-free symbol, e.g. ``EURUSD``."""
        return CSVInstrumentNormalizer.strip_separators(f"{instrument.base}{instrument.quote}")
