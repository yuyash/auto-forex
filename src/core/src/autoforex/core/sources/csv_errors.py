"""CSV market-data source errors."""

from __future__ import annotations


class CSVDataSourceError(ValueError):
    """Raised when CSV market data cannot be parsed."""
