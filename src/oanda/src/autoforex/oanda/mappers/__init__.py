"""Mapping between OANDA v20 objects and Core domain models.

This module keeps the historical public import path while mapper
implementations live in smaller domain-specific modules.
"""

from __future__ import annotations

from autoforex.oanda.mappers.account import OandaAccountMapper
from autoforex.oanda.mappers.instrument import OandaInstrumentMapper
from autoforex.oanda.mappers.market_data import OandaMarketDataMapper
from autoforex.oanda.mappers.order import OandaOrderMapper
from autoforex.oanda.mappers.position import OandaPositionMapper
from autoforex.oanda.mappers.trade import OandaTradeMapper
from autoforex.oanda.mappers.transaction import OandaTransactionMapper

__all__ = [
    "OandaAccountMapper",
    "OandaInstrumentMapper",
    "OandaMarketDataMapper",
    "OandaOrderMapper",
    "OandaPositionMapper",
    "OandaTradeMapper",
    "OandaTransactionMapper",
]
