"""CSV file row reading and raw instrument filtering."""

from __future__ import annotations

import csv
import gzip
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from logging import Logger
from pathlib import Path
from typing import IO, Any

from autoforex.core.sources.csv_errors import CSVDataSourceError


@dataclass(frozen=True, slots=True)
class CSVRow:
    """One CSV row with source location information."""

    path: Path
    number: int
    values: Mapping[str, Any]


class CSVInstrumentNormalizer:
    """Normalize instrument text for raw row filtering."""

    @classmethod
    def compact_ticker(cls, raw_ticker: str, prefix_separator: str | None) -> str:
        """Reduce a raw instrument field, e.g. ``C:EUR-USD``, to ``EURUSD``."""
        value = raw_ticker.strip()
        if prefix_separator and prefix_separator in value:
            value = value.rsplit(prefix_separator, maxsplit=1)[-1]
        return cls.strip_separators(value)

    @staticmethod
    def strip_separators(value: str) -> str:
        """Return upper-case text without common instrument separators."""
        return value.upper().replace("-", "").replace("_", "").replace("/", "").strip()


class CSVFileRowReader:
    """Read CSV rows from plain or gzip-compressed files."""

    def __init__(self, *, encoding: str, logger: Logger) -> None:
        self.encoding = encoding
        self.logger = logger

    def rows(
        self,
        path: Path,
        *,
        instrument_column: str | None = None,
        target: str | None = None,
        prefix_separator: str | None = None,
    ) -> Iterable[CSVRow]:
        """Yield rows from ``path``, optionally filtering by raw instrument text."""
        try:
            file = self.open_csv(path)
        except OSError as exc:
            self.logger.exception(
                "Failed to open CSV file %s",
                path,
                extra={"csv_path": str(path)},
            )
            msg = f"failed to open CSV file: {path}"
            raise CSVDataSourceError(msg) from exc
        with file:
            reader = csv.reader(file)
            try:
                fieldnames = next(reader)
            except StopIteration:
                return
            self.logger.debug(
                "Opened CSV file %s",
                path,
                extra={"csv_path": str(path), "csv_columns": ",".join(fieldnames)},
            )
            filter_index = (
                fieldnames.index(instrument_column)
                if instrument_column is not None and instrument_column in fieldnames
                else None
            )
            for row_number, values in enumerate(reader, start=2):
                if filter_index is not None and target is not None and filter_index < len(values):
                    raw_instrument = values[filter_index].strip()
                    compact = CSVInstrumentNormalizer.compact_ticker(
                        raw_instrument,
                        prefix_separator,
                    )
                    if raw_instrument and compact != target:
                        continue
                yield CSVRow(
                    path=path,
                    number=row_number,
                    values=dict(zip(fieldnames, values, strict=False)),
                )

    def open_csv(self, path: Path) -> IO[str]:
        """Open one CSV file."""
        if path.suffix.lower() == ".gz":
            self.logger.debug(
                "Opening gzip-compressed CSV file %s",
                path,
                extra={"csv_path": str(path), "compression": "gzip"},
            )
            return gzip.open(path, "rt", encoding=self.encoding, newline="")
        self.logger.debug(
            "Opening CSV file %s",
            path,
            extra={"csv_path": str(path), "compression": ""},
        )
        return path.open("r", encoding=self.encoding, newline="")
