"""Execution feedback dataclasses for event processing."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from apps.trading.money import Money


@dataclass(frozen=True, slots=True)
class EntryExecutionBinding:
    """Binding between strategy entry ID and persisted position ID."""

    entry_id: int | None
    position_id: str
    cycle_id: str | None = None
    fill_price: Decimal | None = None


@dataclass(frozen=True, slots=True)
class EventExecutionResult:
    """Result of executing a single persisted trading event."""

    realized_pnl_delta: Decimal = Decimal("0")
    realized_pnl_delta_quote: Decimal = Decimal("0")
    realized_pnl_delta_currency: str = ""
    realized_pnl_delta_quote_currency: str = ""
    execution_price: Decimal | None = None
    executed_units: int = 0
    entry_binding: EntryExecutionBinding | None = None
    position_ids: tuple[str, ...] = ()
    order_ids: tuple[str, ...] = ()
    trade_ids: tuple[str, ...] = ()
    broker_order_ids: tuple[str, ...] = ()
    oanda_trade_ids: tuple[str, ...] = ()
    oanda_response_seconds: tuple[Decimal, ...] = ()

    @property
    def realized_pnl_delta_money(self) -> Money:
        """Return realized account PnL as an amount/currency pair."""
        return Money.coerce(self.realized_pnl_delta, self.realized_pnl_delta_currency)

    @property
    def realized_pnl_delta_quote_money(self) -> Money:
        """Return realized quote PnL as an amount/currency pair."""
        return Money.coerce(
            self.realized_pnl_delta_quote,
            self.realized_pnl_delta_quote_currency,
        )
