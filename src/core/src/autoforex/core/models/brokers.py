"""Broker-neutral order, position, and transaction models."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from logging import Logger
from typing import Any, ClassVar, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, computed_field, field_validator, model_validator

from autoforex.core.logging import get_logger
from autoforex.core.models.accounts import AccountId
from autoforex.core.models.base import DomainModel
from autoforex.core.models.identifiers import new_uuid
from autoforex.core.models.metadata import Metadata
from autoforex.core.models.money import Currency, CurrencyPair, Money
from autoforex.core.models.values import Units

_LOGGER: Logger = get_logger(__name__)


class OrderSide(StrEnum):
    """Market direction for an order."""

    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    """Broker-neutral order types Core understands."""

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class OrderStatus(StrEnum):
    """Normalized order lifecycle status."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class PositionSide(StrEnum):
    """Open exposure direction."""

    LONG = "long"
    SHORT = "short"


class _BrokerStringId(DomainModel):
    """Base class for broker-assigned string identifiers."""

    value: str = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, cls):
            return data
        if isinstance(data, _BrokerStringId):
            return {"value": data.value}
        if isinstance(data, str):
            return {"value": data}
        return data

    @field_validator("value")
    @classmethod
    def _strip_value(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            _LOGGER.debug("Rejected blank broker identifier")
            msg = "broker identifier must not be blank"
            raise ValueError(msg)
        if normalized != value:
            _LOGGER.debug(
                "Normalized broker identifier whitespace",
                extra={"broker_identifier": normalized},
            )
        return normalized

    @classmethod
    def of(cls, value: str | _BrokerStringId) -> Self:
        """Create a broker identifier from a non-empty string."""
        return cls.model_validate(value)

    def __str__(self) -> str:
        return self.value


class BrokerOrderId(_BrokerStringId):
    """Broker-assigned order identifier."""


class BrokerPositionId(_BrokerStringId):
    """Broker-assigned position identifier."""


class BrokerTradeId(_BrokerStringId):
    """Broker-assigned trade identifier."""


class BrokerTransactionId(_BrokerStringId):
    """Broker-assigned transaction identifier."""


class OrderId(DomainModel):
    """Core-assigned identifier for an order."""

    value: UUID

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, cls):
            return data
        if isinstance(data, UUID):
            return {"value": data}
        if isinstance(data, str):
            return {"value": UUID(data)}
        return data

    @classmethod
    def new(cls) -> Self:
        """Create a new time-ordered order identifier."""
        return cls(value=new_uuid())

    @classmethod
    def of(cls, value: UUID | str | OrderId) -> Self:
        """Create an order identifier from a UUID or UUID string."""
        return cls.model_validate(value)

    def __str__(self) -> str:
        return str(self.value)


class OrderReasonCode(StrEnum):
    """Stable machine-readable reason codes for order state."""

    NONE = "none"
    ACCEPTED = "accepted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    BROKER_REJECTED = "broker_rejected"
    INSUFFICIENT_MARGIN = "insufficient_margin"
    INVALID_INSTRUMENT = "invalid_instrument"
    INVALID_PRICE = "invalid_price"
    INVALID_UNITS = "invalid_units"
    MARKET_CLOSED = "market_closed"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class OrderMessageKey(StrEnum):
    """Stable i18n message keys for order state."""

    NONE = "broker.order.none"
    ACCEPTED = "broker.order.accepted"
    FILLED = "broker.order.filled"
    PARTIALLY_FILLED = "broker.order.partially_filled"
    REJECTED = "broker.order.rejected"
    CANCELLED = "broker.order.cancelled"
    BROKER_REJECTED = "broker.order.broker_rejected"
    INSUFFICIENT_MARGIN = "broker.order.insufficient_margin"
    INVALID_INSTRUMENT = "broker.order.invalid_instrument"
    INVALID_PRICE = "broker.order.invalid_price"
    INVALID_UNITS = "broker.order.invalid_units"
    MARKET_CLOSED = "broker.order.market_closed"
    RATE_LIMITED = "broker.order.rate_limited"
    TIMEOUT = "broker.order.timeout"
    UNKNOWN = "broker.order.unknown"


class OrderReason(DomainModel):
    """Structured order reason suitable for i18n and diagnostics."""

    MESSAGE_KEY_BY_CODE: ClassVar[dict[OrderReasonCode, OrderMessageKey]] = {
        OrderReasonCode.NONE: OrderMessageKey.NONE,
        OrderReasonCode.ACCEPTED: OrderMessageKey.ACCEPTED,
        OrderReasonCode.FILLED: OrderMessageKey.FILLED,
        OrderReasonCode.PARTIALLY_FILLED: OrderMessageKey.PARTIALLY_FILLED,
        OrderReasonCode.REJECTED: OrderMessageKey.REJECTED,
        OrderReasonCode.CANCELLED: OrderMessageKey.CANCELLED,
        OrderReasonCode.BROKER_REJECTED: OrderMessageKey.BROKER_REJECTED,
        OrderReasonCode.INSUFFICIENT_MARGIN: OrderMessageKey.INSUFFICIENT_MARGIN,
        OrderReasonCode.INVALID_INSTRUMENT: OrderMessageKey.INVALID_INSTRUMENT,
        OrderReasonCode.INVALID_PRICE: OrderMessageKey.INVALID_PRICE,
        OrderReasonCode.INVALID_UNITS: OrderMessageKey.INVALID_UNITS,
        OrderReasonCode.MARKET_CLOSED: OrderMessageKey.MARKET_CLOSED,
        OrderReasonCode.RATE_LIMITED: OrderMessageKey.RATE_LIMITED,
        OrderReasonCode.TIMEOUT: OrderMessageKey.TIMEOUT,
        OrderReasonCode.UNKNOWN: OrderMessageKey.UNKNOWN,
    }

    code: OrderReasonCode = OrderReasonCode.NONE
    message_key: OrderMessageKey = OrderMessageKey.NONE
    details: Metadata = Field(default_factory=Metadata)

    @classmethod
    def message_key_for_code(cls, code: OrderReasonCode) -> OrderMessageKey:
        """Return the default i18n message key for an order reason code."""
        return cls.MESSAGE_KEY_BY_CODE.get(code, OrderMessageKey.UNKNOWN)

    @model_validator(mode="before")
    @classmethod
    def _apply_message_key_default(cls, data: Any) -> Any:
        if isinstance(data, cls):
            return data
        if isinstance(data, str):
            data = {"code": data}
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        if normalized.get("message_key") is None:
            code = OrderReasonCode(normalized.get("code", OrderReasonCode.NONE))
            normalized["message_key"] = cls.message_key_for_code(code)
            _LOGGER.debug(
                "Applied order message key default",
                extra={
                    "order_reason_code": code.value,
                    "message_key": normalized["message_key"].value,
                },
            )
        return normalized


class Order(DomainModel):
    """Broker-neutral order before or after broker execution."""

    id: OrderId = Field(default_factory=OrderId.new)
    broker_order_id: BrokerOrderId | None = None
    instrument: CurrencyPair
    side: OrderSide
    units: Units
    order_type: OrderType = OrderType.MARKET
    price: Money | None = None
    status: OrderStatus = OrderStatus.PENDING
    filled_units: Units = Units("0")
    average_fill_price: Money | None = None
    reason: OrderReason = Field(default_factory=OrderReason)
    metadata: Metadata = Field(default_factory=Metadata)

    @model_validator(mode="before")
    @classmethod
    def _normalize_prices(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        instrument = CurrencyPair.of(data["instrument"])
        normalized = dict(data)
        normalized["instrument"] = instrument
        if data.get("price") is not None:
            normalized["price"] = Money.coerce(
                data["price"],
                instrument.quote,
            ).require_positive()
        if data.get("average_fill_price") is not None:
            normalized["average_fill_price"] = Money.coerce(
                data["average_fill_price"],
                instrument.quote,
            ).require_positive()
        return normalized

    @model_validator(mode="after")
    def _validate_order(self) -> Self:
        self.units.require_positive()
        if self.filled_units > self.units:
            msg = "filled units must be less than or equal to order units"
            raise ValueError(msg)
        _LOGGER.debug(
            "Validated order",
            extra={
                "order_id": str(self.id),
                "broker_order_id": str(self.broker_order_id or ""),
                "instrument": str(self.instrument),
                "order_side": self.side.value,
                "order_type": self.order_type.value,
                "order_units": str(self.units),
                "order_status": self.status.value,
                "filled_units": str(self.filled_units),
            },
        )
        return self

    @computed_field
    @property
    def remaining_units(self) -> Units:
        """Return unfilled units."""
        return Units.of(self.units - self.filled_units)


class PositionSideState(DomainModel):
    """State for one side of a broker-neutral instrument position."""

    side: PositionSide
    units: Units = Units("0")
    average_entry_price: Money | None = None
    broker_position_id: BrokerPositionId | None = None
    unrealized_pl: Money | None = None
    opened_at: AwareDatetime | None = None
    metadata: Metadata = Field(default_factory=Metadata)

    @model_validator(mode="after")
    def _validate_side_state(self) -> Self:
        if self.units > 0 and self.average_entry_price is None:
            msg = "average entry price is required when position units are open"
            raise ValueError(msg)
        return self

    @computed_field
    @property
    def is_open(self) -> bool:
        """Return whether this side has open exposure."""
        return self.units > 0


class Position(DomainModel):
    """Broker-neutral instrument position that can hold long and short sides."""

    instrument: CurrencyPair
    long: PositionSideState | None = None
    short: PositionSideState | None = None
    unrealized_pl: Money | None = None
    metadata: Metadata = Field(default_factory=Metadata)

    @model_validator(mode="before")
    @classmethod
    def _normalize_sides(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        instrument = CurrencyPair.of(data["instrument"])
        normalized = dict(data)
        normalized["instrument"] = instrument
        normalized["long"] = cls._normalize_side(
            data.get("long"),
            side=PositionSide.LONG,
            quote_currency=instrument.quote,
        )
        normalized["short"] = cls._normalize_side(
            data.get("short"),
            side=PositionSide.SHORT,
            quote_currency=instrument.quote,
        )
        return normalized

    @model_validator(mode="after")
    def _validate_position(self) -> Self:
        if self.long is not None and self.long.side != PositionSide.LONG:
            msg = "long side state must have side=long"
            raise ValueError(msg)
        if self.short is not None and self.short.side != PositionSide.SHORT:
            msg = "short side state must have side=short"
            raise ValueError(msg)
        _LOGGER.debug(
            "Validated broker-neutral position",
            extra={
                "instrument": str(self.instrument),
                "long_units": str(self.long.units if self.long else ""),
                "short_units": str(self.short.units if self.short else ""),
                "has_unrealized_pl": self.unrealized_pl is not None,
            },
        )
        return self

    @computed_field
    @property
    def open_sides(self) -> tuple[PositionSide, ...]:
        """Return sides with open exposure."""
        sides: list[PositionSide] = []
        if self.long is not None and self.long.is_open:
            sides.append(PositionSide.LONG)
        if self.short is not None and self.short.is_open:
            sides.append(PositionSide.SHORT)
        return tuple(sides)

    @computed_field
    @property
    def net_units(self) -> Decimal:
        """Return long units minus short units."""
        long_units = self.long.units if self.long is not None else Decimal("0")
        short_units = self.short.units if self.short is not None else Decimal("0")
        return long_units - short_units

    def side_state(self, side: PositionSide) -> PositionSideState | None:
        """Return the side state for ``side``."""
        return self.long if side == PositionSide.LONG else self.short

    def require_side(self, side: PositionSide) -> PositionSideState:
        """Return an open side state or raise a clear error."""
        state = self.side_state(side)
        if state is None or not state.is_open:
            msg = f"position has no open {side.value} side"
            raise ValueError(msg)
        return state

    @classmethod
    def _normalize_side(
        cls,
        value: Any,
        *,
        side: PositionSide,
        quote_currency: Currency,
    ) -> Any:
        if value is None or isinstance(value, PositionSideState):
            return value
        if not isinstance(value, dict):
            return value

        normalized = dict(value)
        normalized.setdefault("side", side)
        if normalized.get("average_entry_price") is not None:
            normalized["average_entry_price"] = Money.coerce(
                normalized["average_entry_price"],
                quote_currency,
            ).require_positive()
        if normalized.get("unrealized_pl") is not None and not isinstance(
            normalized["unrealized_pl"],
            Money,
        ):
            if isinstance(normalized["unrealized_pl"], dict):
                normalized["unrealized_pl"] = Money.model_validate(normalized["unrealized_pl"])
            else:
                normalized["unrealized_pl"] = Money.coerce(
                    normalized["unrealized_pl"],
                    quote_currency,
                )
        return normalized


class Trade(DomainModel):
    """Broker-neutral trade snapshot."""

    id: BrokerTradeId
    instrument: CurrencyPair
    side: PositionSide
    units: Units
    price: Money | None = None
    open_time: AwareDatetime | None = None
    close_time: AwareDatetime | None = None
    state: str = Field(default="open", min_length=1)
    realized_pl: Money | None = None
    unrealized_pl: Money | None = None
    metadata: Metadata = Field(default_factory=Metadata)

    @model_validator(mode="before")
    @classmethod
    def _normalize_trade(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        instrument = CurrencyPair.of(data["instrument"])
        normalized = dict(data)
        normalized["instrument"] = instrument
        if normalized.get("price") is not None:
            normalized["price"] = Money.coerce(normalized["price"], instrument.quote)
        for field_name in ("realized_pl", "unrealized_pl"):
            if normalized.get(field_name) is not None and not isinstance(
                normalized[field_name],
                Money,
            ):
                normalized[field_name] = Money.coerce(
                    normalized[field_name],
                    instrument.quote,
                )
        if normalized.get("state") is not None:
            normalized["state"] = str(normalized["state"]).strip().lower()
        return normalized

    @model_validator(mode="after")
    def _validate_trade(self) -> Self:
        self.units.require_positive()
        return self


class Transaction(DomainModel):
    """Broker-neutral account transaction."""

    id: BrokerTransactionId
    account_id: AccountId | None = None
    time: AwareDatetime | None = None
    type: str = Field(min_length=1)
    instrument: CurrencyPair | None = None
    order_id: BrokerOrderId | None = None
    amount: Money | None = None
    metadata: Metadata = Field(default_factory=Metadata)

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        if normalized.get("type") is not None:
            normalized["type"] = str(normalized["type"]).strip()
        if normalized.get("instrument") is not None:
            normalized["instrument"] = CurrencyPair.of(normalized["instrument"])
        return normalized
