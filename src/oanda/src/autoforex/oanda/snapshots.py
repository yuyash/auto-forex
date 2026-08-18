"""OANDA-specific immutable snapshots composed from Core domain models."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Self, cast

from autoforex.core import (
    Account,
    AccountId,
    AccountProvider,
    AccountSummary,
    Currency,
    DomainModel,
    Metadata,
    Money,
    Order,
    OrderId,
    OrderReason,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    PositionSide,
    PositionSideState,
    Trade,
    Transaction,
    Units,
)
from pydantic import Field, model_validator

from autoforex.oanda.constants import OANDA_PROVIDER


class OandaAccount(DomainModel):
    """OANDA account snapshot with a composed Core account reference."""

    account: Account
    mt4_account_id: int | None = None
    tags: tuple[str, ...] = ()
    last_transaction_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, cls):
            return data
        if isinstance(data, Account):
            return {"account": data}
        if not isinstance(data, dict) or "account" in data:
            return data

        return {
            "account": {
                "id": data.get("id"),
                "provider": OANDA_PROVIDER,
                "alias": data.get("alias"),
                "metadata": data.get("metadata", Metadata()),
            },
            "mt4_account_id": data.get("mt4_account_id"),
            "tags": data.get("tags", ()),
            "last_transaction_id": data.get("last_transaction_id"),
        }

    @model_validator(mode="after")
    def _force_provider(self) -> Self:
        if self.account.provider != OANDA_PROVIDER:
            object.__setattr__(self, "account", self.account.evolve(provider=OANDA_PROVIDER))
        return self

    @property
    def id(self) -> AccountId:
        """Return the Core account id."""
        return self.account.id

    @property
    def provider(self) -> AccountProvider:
        """Return the forced OANDA provider id."""
        provider = self.account.provider
        if provider is None:
            return OANDA_PROVIDER
        return provider

    @property
    def alias(self) -> str | None:
        """Return the account alias."""
        return self.account.alias

    @property
    def metadata(self) -> Metadata:
        """Return Core account metadata."""
        return self.account.metadata


class OandaAccountSummary(DomainModel):
    """OANDA account-state snapshot with a composed Core account summary."""

    summary: AccountSummary
    financing_mode: str | None = None
    hedging_enabled: bool | None = None
    position_aggregation_mode: str | None = None
    guaranteed_stop_loss_order_mode: str | None = None
    withdrawal_limit: Money | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, cls):
            return data
        if isinstance(data, AccountSummary):
            return {"summary": data}
        if not isinstance(data, dict):
            return data
        if "summary" in data:
            normalized = dict(data)
            summary = AccountSummary.model_validate(normalized["summary"])
            normalized["summary"] = summary
            normalized["withdrawal_limit"] = cls._money(
                normalized.get("withdrawal_limit"),
                summary.currency,
            )
            return normalized

        return {
            "summary": {
                "account_id": data.get("account_id"),
                "currency": data.get("currency"),
                "alias": data.get("alias"),
                "balance": data.get("balance"),
                "nav": data.get("nav"),
                "margin_used": data.get("margin_used"),
                "margin_available": data.get("margin_available"),
                "margin_rate": data.get("margin_rate"),
                "open_trade_count": data.get("open_trade_count"),
                "open_position_count": data.get("open_position_count"),
                "pending_order_count": data.get("pending_order_count"),
                "last_transaction_id": data.get("last_transaction_id"),
                "created_at": data.get("created_at"),
                "metadata": data.get("metadata", Metadata()),
            },
            "financing_mode": data.get("financing_mode"),
            "hedging_enabled": data.get("hedging_enabled"),
            "position_aggregation_mode": data.get("position_aggregation_mode"),
            "guaranteed_stop_loss_order_mode": data.get("guaranteed_stop_loss_order_mode"),
            "withdrawal_limit": cls._money(
                data.get("withdrawal_limit"),
                data.get("currency"),
            ),
        }

    @staticmethod
    def _money(value: object, currency: object) -> Money | None:
        if value is None or isinstance(value, Money):
            return value
        return Money.coerce(
            cast(Money | Decimal | str | Mapping[str, Any], value),
            Currency.of(cast(Currency | str, currency)),
        )

    @property
    def account_id(self) -> AccountId:
        """Return the account id."""
        return self.summary.account_id

    @property
    def currency(self) -> Currency:
        """Return the account currency."""
        return self.summary.currency

    @property
    def alias(self) -> str | None:
        """Return the account alias."""
        return self.summary.alias

    @property
    def balance(self) -> Money | None:
        """Return the account balance."""
        return self.summary.balance

    @property
    def nav(self) -> Money | None:
        """Return the account NAV."""
        return self.summary.nav

    @property
    def margin_used(self) -> Money | None:
        """Return used margin."""
        return self.summary.margin_used

    @property
    def margin_available(self) -> Money | None:
        """Return available margin."""
        return self.summary.margin_available

    @property
    def last_transaction_id(self) -> str | None:
        """Return the last OANDA transaction id."""
        return self.summary.last_transaction_id

    @property
    def metadata(self) -> Metadata:
        """Return Core summary metadata."""
        return self.summary.metadata


class OandaOrder(DomainModel):
    """OANDA order snapshot with a composed Core order."""

    order: Order
    client_order_id: str | None = None
    client_order_tag: str | None = None
    time_in_force: str | None = None
    position_fill: str | None = None
    trigger_condition: str | None = None
    related_transaction_ids: tuple[str, ...] = ()
    last_transaction_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, cls):
            return data
        if isinstance(data, Order):
            return {"order": data}
        if not isinstance(data, dict) or "order" in data:
            return data

        return {
            "order": {
                "id": data.get("id", OrderId.new()),
                "broker_order_id": data.get("broker_order_id"),
                "instrument": data.get("instrument"),
                "side": data.get("side"),
                "units": data.get("units"),
                "order_type": data.get("order_type", OrderType.MARKET),
                "price": data.get("price"),
                "status": data.get("status", OrderStatus.PENDING),
                "filled_units": data.get("filled_units", Decimal("0")),
                "average_fill_price": data.get("average_fill_price"),
                "reason": data.get("reason", OrderReason()),
                "metadata": data.get("metadata", Metadata()),
            },
            "client_order_id": data.get("client_order_id"),
            "client_order_tag": data.get("client_order_tag"),
            "time_in_force": data.get("time_in_force"),
            "position_fill": data.get("position_fill"),
            "trigger_condition": data.get("trigger_condition"),
            "related_transaction_ids": data.get("related_transaction_ids", ()),
            "last_transaction_id": data.get("last_transaction_id"),
        }

    @property
    def id(self) -> OrderId:
        """Return the Core order id."""
        return self.order.id

    @property
    def status(self) -> OrderStatus:
        """Return the Core order status."""
        return self.order.status

    @property
    def side(self) -> OrderSide:
        """Return the Core order side."""
        return self.order.side

    @property
    def filled_units(self) -> Units:
        """Return filled order units."""
        return self.order.filled_units

    @property
    def average_fill_price(self) -> Money | None:
        """Return the average fill price."""
        return self.order.average_fill_price

    @property
    def metadata(self) -> Metadata:
        """Return Core order metadata."""
        return self.order.metadata


class OandaPosition(DomainModel):
    """OANDA position snapshot with a composed Core position."""

    position: Position
    pl: Money | None = None
    resettable_pl: Money | None = None
    financing: Money | None = None
    margin_used: Money | None = None
    long_trade_ids: tuple[str, ...] = ()
    short_trade_ids: tuple[str, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, cls):
            return data
        if isinstance(data, Position):
            return {"position": data}
        if not isinstance(data, dict):
            return data
        if "position" in data:
            normalized = dict(data)
            normalized["pl"] = cls._quote_money(normalized.get("pl"), normalized)
            normalized["resettable_pl"] = cls._quote_money(
                normalized.get("resettable_pl"),
                normalized,
            )
            normalized["financing"] = cls._quote_money(normalized.get("financing"), normalized)
            normalized["margin_used"] = cls._quote_money(normalized.get("margin_used"), normalized)
            return normalized

        return {
            "position": {
                "instrument": data.get("instrument"),
                "long": data.get("long"),
                "short": data.get("short"),
                "unrealized_pl": data.get("unrealized_pl"),
                "metadata": data.get("metadata", Metadata()),
            },
            "pl": cls._quote_money(data.get("pl"), data),
            "resettable_pl": cls._quote_money(data.get("resettable_pl"), data),
            "financing": cls._quote_money(data.get("financing"), data),
            "margin_used": cls._quote_money(data.get("margin_used"), data),
            "long_trade_ids": data.get("long_trade_ids", ()),
            "short_trade_ids": data.get("short_trade_ids", ()),
        }

    @staticmethod
    def _quote_money(value: object, data: dict[str, Any]) -> Money | None:
        if value is None or isinstance(value, Money):
            return value
        position = data.get("position")
        if isinstance(position, Position):
            currency = position.instrument.quote
        elif isinstance(position, dict):
            currency = Position.model_validate(position).instrument.quote
        else:
            currency = Position.model_validate(
                {"instrument": data.get("instrument")}
            ).instrument.quote
        return Money.coerce(cast(Money | Decimal | str | Mapping[str, Any], value), currency)

    @property
    def long(self) -> PositionSideState | None:
        """Return the long side state."""
        return self.position.long

    @property
    def short(self) -> PositionSideState | None:
        """Return the short side state."""
        return self.position.short

    @property
    def open_sides(self) -> tuple[PositionSide, ...]:
        """Return open position sides."""
        return self.position.open_sides

    @property
    def metadata(self) -> Metadata:
        """Return Core position metadata."""
        return self.position.metadata


class OandaTrade(DomainModel):
    """OANDA trade snapshot with a composed Core trade."""

    trade: Trade
    client_trade_id: str | None = None
    initial_units: Units | None = None
    initial_margin_required: Money | None = None
    realized_pl_value: Money | None = None
    financing: Money | None = None
    dividend_adjustment: Money | None = None
    close_transaction_ids: tuple[str, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, cls):
            return data
        if isinstance(data, Trade):
            return {"trade": data}
        if not isinstance(data, dict):
            return data
        if "trade" in data:
            normalized = dict(data)
            normalized["initial_units"] = cls._units(normalized.get("initial_units"))
            normalized["initial_margin_required"] = cls._quote_money(
                normalized.get("initial_margin_required"),
                normalized,
            )
            normalized["realized_pl_value"] = cls._quote_money(
                normalized.get("realized_pl_value"),
                normalized,
            )
            normalized["financing"] = cls._quote_money(normalized.get("financing"), normalized)
            normalized["dividend_adjustment"] = cls._quote_money(
                normalized.get("dividend_adjustment"),
                normalized,
            )
            return normalized

        return {
            "trade": {
                "id": data.get("id"),
                "instrument": data.get("instrument"),
                "side": data.get("side"),
                "units": data.get("units"),
                "price": data.get("price"),
                "open_time": data.get("open_time"),
                "close_time": data.get("close_time"),
                "state": data.get("state", "open"),
                "realized_pl": data.get("realized_pl"),
                "unrealized_pl": data.get("unrealized_pl"),
                "metadata": data.get("metadata", Metadata()),
            },
            "client_trade_id": data.get("client_trade_id"),
            "initial_units": cls._units(data.get("initial_units")),
            "initial_margin_required": cls._quote_money(
                data.get("initial_margin_required"),
                data,
            ),
            "realized_pl_value": cls._quote_money(data.get("realized_pl_value"), data),
            "financing": cls._quote_money(data.get("financing"), data),
            "dividend_adjustment": cls._quote_money(data.get("dividend_adjustment"), data),
            "close_transaction_ids": data.get("close_transaction_ids", ()),
        }

    @staticmethod
    def _units(value: object) -> Units | None:
        if value is None or isinstance(value, Units):
            return value
        return Units.of(cast(Decimal | str, value))

    @staticmethod
    def _quote_money(value: object, data: dict[str, Any]) -> Money | None:
        if value is None or isinstance(value, Money):
            return value
        trade = data.get("trade")
        if isinstance(trade, Trade):
            currency = trade.instrument.quote
        elif isinstance(trade, dict):
            currency = Trade.model_validate(trade).instrument.quote
        else:
            currency = Trade.model_validate(
                {
                    "id": data.get("id"),
                    "instrument": data.get("instrument"),
                    "side": data.get("side"),
                    "units": data.get("units") or "1",
                }
            ).instrument.quote
        return Money.coerce(cast(Money | Decimal | str | Mapping[str, Any], value), currency)

    @property
    def id(self) -> object:
        """Return the Core trade id."""
        return self.trade.id

    @property
    def unrealized_pl(self) -> Money | None:
        """Return unrealized P/L."""
        return self.trade.unrealized_pl

    @property
    def metadata(self) -> Metadata:
        """Return Core trade metadata."""
        return self.trade.metadata


class OandaTransaction(DomainModel):
    """OANDA transaction snapshot with a composed Core transaction."""

    transaction: Transaction
    user_id: int | None = None
    batch_id: str | None = None
    request_id: str | None = None
    reason: str | None = None
    reject_reason: str | None = None
    related_transaction_ids: tuple[str, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, cls):
            return data
        if isinstance(data, Transaction):
            return {"transaction": data}
        if not isinstance(data, dict) or "transaction" in data:
            return data

        return {
            "transaction": {
                "id": data.get("id"),
                "account_id": data.get("account_id"),
                "time": data.get("time"),
                "type": data.get("type"),
                "instrument": data.get("instrument"),
                "order_id": data.get("order_id"),
                "amount": data.get("amount"),
                "metadata": data.get("metadata", Metadata()),
            },
            "user_id": data.get("user_id"),
            "batch_id": data.get("batch_id"),
            "request_id": data.get("request_id"),
            "reason": data.get("reason"),
            "reject_reason": data.get("reject_reason"),
            "related_transaction_ids": data.get("related_transaction_ids", ()),
        }

    @property
    def id(self) -> object:
        """Return the Core transaction id."""
        return self.transaction.id

    @property
    def amount(self) -> Money | None:
        """Return the transaction amount."""
        return self.transaction.amount

    @property
    def metadata(self) -> Metadata:
        """Return Core transaction metadata."""
        return self.transaction.metadata
