"""Instrument mapping helpers."""

from __future__ import annotations

from autoforex.core import CurrencyPair


class OandaInstrumentMapper:
    """Convert between Core and OANDA instrument representations."""

    @staticmethod
    def to_oanda(instrument: CurrencyPair) -> str:
        """Return the OANDA instrument name."""
        return instrument.symbol

    @staticmethod
    def to_core(instrument: str) -> CurrencyPair:
        """Return the Core currency pair."""
        return CurrencyPair.of(instrument)

    @classmethod
    def to_core_or_none(cls, instrument: object) -> CurrencyPair | None:
        """Return a Core currency pair or ``None`` when the value is not valid."""
        if instrument is None:
            return None
        try:
            return cls.to_core(str(instrument))
        except ValueError:
            return None
