"""Clock helpers for core library and standalone scripts.

Live runtimes use the system local clock by default; replay and backtest
runtimes can inject a manual clock so lifecycle timestamps follow historical
market time instead of wall-clock time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Protocol


class Clock(Protocol):
    """Source of timezone-aware datetimes for domain timestamps."""

    def now(self) -> datetime:
        """Return the current time for this clock."""


@dataclass(frozen=True, slots=True)
class SystemClock:
    """Clock backed by the system local timezone."""

    def now(self) -> datetime:
        """Return the current wall-clock time as a timezone-aware datetime."""
        return datetime.now().astimezone()


@dataclass(slots=True)
class ManualClock:
    """Clock whose current time is controlled by the caller."""

    current: datetime

    def __post_init__(self) -> None:
        self.set(self.current)

    def now(self) -> datetime:
        """Return the configured current time."""
        return self.current

    def set(self, current: datetime) -> None:
        """Move the clock to ``current``."""
        if current.tzinfo is None or current.utcoffset() is None:
            msg = "manual clock time must be timezone-aware"
            raise ValueError(msg)
        self.current = current


SYSTEM_CLOCK = SystemClock()


def now(clock: Clock | None = None) -> datetime:
    """Return the current time from ``clock`` or the system clock."""
    return (clock or SYSTEM_CLOCK).now()


def local_timezone() -> tzinfo:
    """Return the system local timezone as a concrete ``tzinfo``."""
    local = datetime.now().astimezone().tzinfo
    if local is None:  # pragma: no cover - astimezone always yields a zone
        msg = "could not resolve the system local timezone"
        raise RuntimeError(msg)
    return local
