"""Market data models."""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum
from logging import Logger
from typing import Any

from pydantic import AwareDatetime, Field, computed_field, model_validator

from autoforex.core.logging import get_logger
from autoforex.core.models.base import DomainModel
from autoforex.core.models.metadata import Metadata
from autoforex.core.models.money import CurrencyPair, Money

_LOGGER: Logger = get_logger(__name__)


class TickGranularity(StrEnum):
    """Tick replay or sampling granularity.

    ``TICK`` means every tick (no downsampling). The other members describe a
    fixed sampling interval; :attr:`interval` returns it as a ``timedelta``.
    """

    TICK = "tick"
    SECOND_1 = "1s"
    SECOND_10 = "10s"
    SECOND_15 = "15s"
    SECOND_30 = "30s"
    MINUTE_1 = "1m"
    MINUTE_5 = "5m"
    MINUTE_15 = "15m"
    MINUTE_30 = "30m"
    HOUR_1 = "1h"

    @property
    def interval(self) -> timedelta | None:
        """Return the sampling interval, or ``None`` for per-tick granularity."""
        return _TICK_GRANULARITY_INTERVALS[self]


_TICK_GRANULARITY_INTERVALS: dict[TickGranularity, timedelta | None] = {
    TickGranularity.TICK: None,
    TickGranularity.SECOND_1: timedelta(seconds=1),
    TickGranularity.SECOND_10: timedelta(seconds=10),
    TickGranularity.SECOND_15: timedelta(seconds=15),
    TickGranularity.SECOND_30: timedelta(seconds=30),
    TickGranularity.MINUTE_1: timedelta(minutes=1),
    TickGranularity.MINUTE_5: timedelta(minutes=5),
    TickGranularity.MINUTE_15: timedelta(minutes=15),
    TickGranularity.MINUTE_30: timedelta(minutes=30),
    TickGranularity.HOUR_1: timedelta(hours=1),
}


class CandleGranularity(StrEnum):
    """Common candle granularities independent from a specific broker."""

    SECOND_5 = "S5"
    SECOND_10 = "S10"
    SECOND_15 = "S15"
    SECOND_30 = "S30"
    MINUTE_1 = "M1"
    MINUTE_5 = "M5"
    MINUTE_15 = "M15"
    MINUTE_30 = "M30"
    HOUR_1 = "H1"
    HOUR_4 = "H4"
    DAY = "D"


class Tick(DomainModel):
    """Single bid/ask market quote for an instrument."""

    instrument: CurrencyPair
    timestamp: AwareDatetime
    bid: Money
    ask: Money
    mid: Money | None = None
    metadata: Metadata = Field(default_factory=Metadata)

    @model_validator(mode="before")
    @classmethod
    def _normalize_prices(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if data.get("instrument") is None or data.get("bid") is None or data.get("ask") is None:
            return data

        instrument = CurrencyPair.of(data["instrument"])
        normalized = dict(data)
        normalized["instrument"] = instrument
        normalized["bid"] = Money.coerce(data["bid"], instrument.quote).require_positive()
        normalized["ask"] = Money.coerce(data["ask"], instrument.quote).require_positive()
        if data.get("mid") is None:
            normalized["mid"] = (normalized["bid"] + normalized["ask"]) / 2
        else:
            normalized["mid"] = Money.coerce(data["mid"], instrument.quote).require_positive()
        return normalized

    @model_validator(mode="after")
    def _validate_prices(self) -> Tick:
        if self.ask < self.bid:
            _LOGGER.debug(
                "Rejected tick with ask below bid",
                extra=self._log_extra(),
            )
            msg = "ask must be greater than or equal to bid"
            raise ValueError(msg)
        if self.mid is None:
            _LOGGER.debug(
                "Rejected tick without mid price",
                extra=self._log_extra(),
            )
            msg = "mid is required"
            raise ValueError(msg)
        if not self.bid <= self.mid <= self.ask:
            _LOGGER.debug(
                "Rejected tick with mid outside bid/ask range",
                extra=self._log_extra(),
            )
            msg = "mid must be between bid and ask"
            raise ValueError(msg)
        _LOGGER.debug("Validated tick", extra=self._log_extra())
        return self

    @computed_field
    @property
    def effective_mid(self) -> Money:
        """Return the provided mid price or calculate it from bid/ask."""
        if self.mid is None:
            msg = "mid is required"
            raise ValueError(msg)
        return self.mid

    @computed_field
    @property
    def spread(self) -> Money:
        """Return the absolute bid/ask spread."""
        return self.ask - self.bid

    def _log_extra(self) -> dict[str, str]:
        return {
            "instrument": str(self.instrument),
            "timestamp": self.timestamp.isoformat(),
            "bid": str(self.bid.amount),
            "ask": str(self.ask.amount),
            "mid": str(self.mid.amount if self.mid is not None else ""),
            "currency": str(self.bid.currency),
        }


class Candle(DomainModel):
    """OHLC candle for an instrument and time bucket."""

    instrument: CurrencyPair
    timestamp: AwareDatetime
    granularity: CandleGranularity
    open: Money
    high: Money
    low: Money
    close: Money
    volume: int | None = Field(default=None, ge=0)
    complete: bool = True
    metadata: Metadata = Field(default_factory=Metadata)

    @model_validator(mode="before")
    @classmethod
    def _normalize_prices(cls, data: Any) -> Any:
        if not isinstance(data, dict) or data.get("instrument") is None:
            return data

        instrument = CurrencyPair.of(data["instrument"])
        normalized = dict(data)
        normalized["instrument"] = instrument
        for field_name in ("open", "high", "low", "close"):
            if data.get(field_name) is not None:
                normalized[field_name] = Money.coerce(
                    data[field_name],
                    instrument.quote,
                ).require_positive()
        return normalized

    @model_validator(mode="after")
    def _validate_ohlc(self) -> Candle:
        max_price = max(self.open, self.high, self.low, self.close)
        min_price = min(self.open, self.high, self.low, self.close)
        if self.high != max_price:
            _LOGGER.debug(
                "Rejected candle with invalid high price",
                extra=self._log_extra(),
            )
            msg = "high must be greater than or equal to open, low, and close"
            raise ValueError(msg)
        if self.low != min_price:
            _LOGGER.debug(
                "Rejected candle with invalid low price",
                extra=self._log_extra(),
            )
            msg = "low must be less than or equal to open, high, and close"
            raise ValueError(msg)
        _LOGGER.debug("Validated candle", extra=self._log_extra())
        return self

    @computed_field
    @property
    def range(self) -> Money:
        """Return the candle high/low range."""
        return self.high - self.low

    def _log_extra(self) -> dict[str, str | int]:
        return {
            "instrument": str(self.instrument),
            "timestamp": self.timestamp.isoformat(),
            "granularity": str(self.granularity),
            "open": str(self.open.amount),
            "high": str(self.high.amount),
            "low": str(self.low.amount),
            "close": str(self.close.amount),
            "currency": str(self.close.currency),
            "volume": self.volume or 0,
        }
