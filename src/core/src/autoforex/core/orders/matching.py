"""Broker trade matching helpers for strategy execution."""

from __future__ import annotations

from collections.abc import Mapping

from autoforex.core.models.brokers import Trade
from autoforex.core.models.metadata import Metadata
from autoforex.core.strategies.execution import StrategyEventRequest


class LogicalTradeIdResolver:
    """Resolve stable strategy trade ids from strategy events and broker trades."""

    @classmethod
    def from_event(cls, event: StrategyEventRequest) -> str:
        """Return the logical trade id requested by a strategy event."""
        candidates = (
            event.display_id,
            event.metadata.get("logical_trade_id"),
            event.metadata.get("entry_id"),
        )
        for candidate in candidates:
            if candidate is None:
                continue
            value = str(candidate).strip()
            if value:
                return value
        return ""

    @classmethod
    def trade_matches(cls, trade: Trade, logical_trade_id: str) -> bool:
        """Return whether a broker trade carries the requested logical id."""
        return logical_trade_id in cls.from_trade(trade)

    @classmethod
    def from_trade(cls, trade: Trade) -> frozenset[str]:
        """Return known logical ids attached to a broker trade."""
        values = {
            str(trade.id),
            cls._metadata_text(trade.metadata, "logical_trade_id"),
            cls._metadata_text(trade.metadata, "client_trade_id"),
            cls._client_extension_id(trade.metadata),
        }
        return frozenset(value for value in values if value)

    @staticmethod
    def _metadata_text(metadata: Metadata, key: str) -> str:
        value = metadata.get(key)
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def _client_extension_id(metadata: Metadata) -> str:
        value = metadata.get("clientExtensions") or metadata.get("client_extensions")
        if not isinstance(value, Mapping):
            return ""
        client_id = value.get("id")
        return "" if client_id is None else str(client_id).strip()
