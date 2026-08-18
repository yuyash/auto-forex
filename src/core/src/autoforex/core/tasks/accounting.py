"""Runtime account-balance tracking for task execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from uuid import UUID

from autoforex.core.models.brokers import Order
from autoforex.core.models.metadata import Metadata
from autoforex.core.models.money import Currency, Money
from autoforex.core.models.values import Units
from autoforex.core.orders.matching import LogicalTradeIdResolver
from autoforex.core.strategies.execution import (
    StrategyAction,
    StrategyExecutionResponse,
    TradeSide,
)
from autoforex.core.strategies.models import StrategyParameters
from autoforex.core.tasks.execution import ExecutableTask

type Task = ExecutableTask


@dataclass(slots=True)
class AccountOpenTrade:
    """Open trade state needed for realized balance updates."""

    task_id: UUID
    trade_id: str
    side: TradeSide
    units: Units
    entry_price: Money

    def realized_pl(self, *, close_price: Money, units: Units) -> Money:
        """Return realized P/L for a close fill."""
        close_price.require_currency(self.entry_price.currency)
        closed_units = Units.of(min(units, self.units))
        if self.side == TradeSide.BUY:
            amount = (close_price.amount - self.entry_price.amount) * closed_units
        else:
            amount = (self.entry_price.amount - close_price.amount) * closed_units
        return Money.of(amount, close_price.currency)

    def apply_close(self, units: Units) -> None:
        """Reduce remaining units after a close fill."""
        self.units = Units.of(max(self.units - units, Decimal("0")))

    @property
    def closed(self) -> bool:
        """Return whether the trade has no remaining tracked units."""
        return self.units <= 0


class StrategyParameterInitialBalanceResolver:
    """Resolve task initial balance from canonical strategy account parameters."""

    @classmethod
    def initial_balance(cls, task: Task) -> Money:
        """Return initial account balance for a task."""
        parameter_balance = cls.from_parameters(task.parameters)
        if parameter_balance is not None:
            return parameter_balance
        return Money.of("10000", "USD")

    @classmethod
    def from_parameters(cls, parameters: StrategyParameters) -> Money | None:
        """Return ``account.initial_balance`` when strategy parameters define it."""
        values = parameters.to_plain()
        account = values.get("account")
        if not isinstance(account, Mapping) or "initial_balance" not in account:
            return None
        return cls.money(account["initial_balance"])

    @staticmethod
    def money(value: object) -> Money:
        """Parse a currency-tagged Money value from strategy parameters."""
        if isinstance(value, Money):
            return value.require_positive()
        if not isinstance(value, Mapping):
            raise TypeError("account.initial_balance must be a Money object")
        return Money.model_validate(value).require_positive()


class AccountBalance:
    """Apply execution responses to account balance state owned by a context store."""

    def __init__(self) -> None:
        self._open_trades: dict[tuple[UUID, str], AccountOpenTrade] = {}

    def initial(self, task: Task) -> Money:
        """Return the initial balance for a task."""
        return StrategyParameterInitialBalanceResolver.initial_balance(task)

    def reset(self, task_id: UUID) -> None:
        """Discard open-trade accounting state for a new task run."""
        self._open_trades = {
            key: trade for key, trade in self._open_trades.items() if key[0] != task_id
        }

    def apply(self, balance: Money, report: StrategyExecutionResponse) -> Money:
        """Return the balance after applying one execution response."""
        if not report.filled:
            return balance
        if report.event.action == StrategyAction.OPEN_TRADE:
            self._record_open(report)
            return balance
        if report.event.action != StrategyAction.CLOSE_TRADE:
            return balance
        realized = self._realized_close_pl(report, currency=balance.currency)
        if realized is None or realized.currency != balance.currency:
            return balance
        return balance + realized

    def _record_open(self, report: StrategyExecutionResponse) -> None:
        event = report.event
        order = report.order
        trade_id = LogicalTradeIdResolver.from_event(event)
        if not trade_id or event.side is None or order is None:
            return
        units = self._filled_units(order)
        price = self._fill_price(order)
        if units is None or price is None:
            return
        self._open_trades[(event.task_id, trade_id)] = AccountOpenTrade(
            task_id=event.task_id,
            trade_id=trade_id,
            side=event.side,
            units=units,
            entry_price=price,
        )

    def _realized_close_pl(
        self,
        report: StrategyExecutionResponse,
        *,
        currency: Currency,
    ) -> Money | None:
        event = report.event
        order = report.order
        trade_id = LogicalTradeIdResolver.from_event(event)
        if not trade_id or order is None:
            return self._metadata_money(report.metadata, "realized_pl", currency=currency)
        state = self._open_trades.get((event.task_id, trade_id))
        units = self._filled_units(order)
        close_price = self._fill_price(order)
        if state is None or units is None or close_price is None:
            return self._metadata_money(report.metadata, "realized_pl", currency=currency)
        realized = state.realized_pl(close_price=close_price, units=units)
        state.apply_close(units)
        if state.closed:
            self._open_trades.pop((event.task_id, trade_id), None)
        return realized

    @staticmethod
    def _filled_units(order: Order) -> Units | None:
        if order.filled_units <= 0:
            return None
        return order.filled_units

    @staticmethod
    def _fill_price(order: Order) -> Money | None:
        return order.average_fill_price or order.price

    @staticmethod
    def _metadata_money(metadata: Metadata, key: str, *, currency: Currency) -> Money | None:
        value = metadata.get(key)
        if value is None or value == "":
            return None
        if isinstance(value, Money):
            return value.require_currency(currency)
        if isinstance(value, Mapping):
            return Money.model_validate(value).require_currency(currency)
        text = str(value).strip()
        if not text:
            return None
        parts = text.split()
        if len(parts) == 2:
            amount_text, currency_text = parts
            try:
                return Money.of(Decimal(amount_text), currency_text).require_currency(currency)
            except InvalidOperation as exc:
                msg = f"invalid money amount in metadata {key}: {amount_text}"
                raise ValueError(msg) from exc
        return Money.of(text, currency)
