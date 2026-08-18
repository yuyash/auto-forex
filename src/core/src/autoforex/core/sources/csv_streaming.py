"""CSV stream filtering and diagnostics."""

from __future__ import annotations

from datetime import datetime
from logging import Logger
from pathlib import Path

from autoforex.core.models import CurrencyPair
from autoforex.core.sources.models import CandleGranularity


class CSVTimestampRange:
    """Inclusive timestamp range filter for CSV market data."""

    def __init__(
        self,
        *,
        start_at: datetime | None,
        end_at: datetime | None,
    ) -> None:
        self.start_at = start_at
        self.end_at = end_at

    def includes(self, timestamp: datetime) -> bool:
        """Return whether a timestamp is inside this range."""
        if self.start_at is not None and timestamp < self.start_at:
            return False
        if self.end_at is not None and timestamp > self.end_at:
            return False
        return True


class CSVLoadLogger:
    """Log CSV loading diagnostics."""

    def __init__(self, logger: Logger) -> None:
        self.logger = logger

    def start(
        self,
        kind: str,
        instrument: CurrencyPair,
        paths: tuple[Path, ...],
        granularity: CandleGranularity | None = None,
    ) -> None:
        """Log the beginning of a CSV load."""
        extra = {
            "csv_path": self.paths_log(paths),
            "instrument": str(instrument),
            "data_kind": kind,
        }
        if granularity is not None:
            extra["granularity"] = granularity.value
        self.logger.info("Loading %ss from %d CSV file(s)", kind, len(paths), extra=extra)

    def finish(
        self,
        kind: str,
        instrument: CurrencyPair,
        paths: tuple[Path, ...],
        yielded_count: int,
    ) -> None:
        """Log the end of a CSV load."""
        self.logger.info(
            "Finished loading %ss from %d CSV file(s)",
            kind,
            len(paths),
            extra={
                "csv_path": self.paths_log(paths),
                "instrument": str(instrument),
                "data_kind": kind,
                "yielded_count": yielded_count,
            },
        )

    @classmethod
    def paths_log(cls, paths: tuple[Path, ...]) -> str:
        """Return a compact path list for structured logs."""
        return ",".join(str(path) for path in paths)
