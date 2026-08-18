"""Analyze OANDA order mutation payloads."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from autoforex.core import (
    BrokerOrderId,
    CurrencyPair,
    Metadata,
    Money,
    Order,
    OrderReasonCode,
    OrderSide,
    OrderStatus,
)

from autoforex.oanda.payload import OandaPayload as payload


class OandaOrderResponseAnalyzer:
    """Extract normalized order details from OANDA payload fragments."""

    @classmethod
    def signed_units(cls, order: Order) -> Decimal:
        """Return signed OANDA units for a Core order."""
        units = order.units.copy_abs()
        return units if order.side == OrderSide.BUY else -units

    @classmethod
    def status_from_transactions(
        cls,
        *,
        response: Any,
        fill: Any,
        cancel: Any,
        reject: Any,
        create: Any,
    ) -> OrderStatus:
        """Infer Core order status from OANDA transaction fragments."""
        if reject is not None or int(getattr(response, "status", 0) or 0) >= 400:
            return OrderStatus.REJECTED
        if fill is not None:
            return OrderStatus.FILLED
        if cancel is not None:
            return OrderStatus.CANCELLED
        if create is not None:
            return OrderStatus.ACCEPTED
        return OrderStatus.REJECTED

    @classmethod
    def broker_order_id(cls, *transactions: Any) -> BrokerOrderId | None:
        """Return the first broker order ID found in transaction fragments."""
        for transaction in transactions:
            if transaction is None:
                continue
            value = payload.get(transaction, "orderID") or payload.get(transaction, "id")
            if value:
                return BrokerOrderId.of(str(value))
        return None

    @classmethod
    def fill_price(cls, fill: Any, instrument: CurrencyPair) -> Money | None:
        """Return the fill price from a transaction fragment."""
        price = payload.get(fill, "price")
        if price is None:
            return None
        return Money.of(price, instrument.quote)

    @classmethod
    def reason_code(cls, *, status: OrderStatus, error_code: str) -> OrderReasonCode:
        """Map OANDA error text and status to a Core order reason code."""
        normalized = error_code.upper()
        if "INSUFFICIENT_MARGIN" in normalized:
            return OrderReasonCode.INSUFFICIENT_MARGIN
        if "INSTRUMENT" in normalized:
            return OrderReasonCode.INVALID_INSTRUMENT
        if "PRICE" in normalized:
            return OrderReasonCode.INVALID_PRICE
        if "UNITS" in normalized:
            return OrderReasonCode.INVALID_UNITS
        if "MARKET_HALTED" in normalized or "MARKET_CLOSED" in normalized:
            return OrderReasonCode.MARKET_CLOSED
        if "RATE" in normalized:
            return OrderReasonCode.RATE_LIMITED
        if "TIMEOUT" in normalized:
            return OrderReasonCode.TIMEOUT
        if status == OrderStatus.FILLED:
            return OrderReasonCode.FILLED
        if status == OrderStatus.ACCEPTED:
            return OrderReasonCode.ACCEPTED
        if status == OrderStatus.CANCELLED:
            return OrderReasonCode.CANCELLED
        if status == OrderStatus.REJECTED:
            return OrderReasonCode.BROKER_REJECTED
        return OrderReasonCode.UNKNOWN

    @classmethod
    def result_details(
        cls,
        response: Any,
        fill: Any,
        cancel: Any,
        reject: Any,
        create: Any,
    ) -> Metadata:
        """Return structured metadata about an OANDA order result."""
        details: dict[str, Any] = {
            "oanda_response_status": getattr(response, "status", None),
            "oanda_response_reason": getattr(response, "reason", None),
        }
        body = payload.body(response)
        for key in ("errorCode", "errorMessage", "lastTransactionID", "relatedTransactionIDs"):
            value = payload.get(body, key)
            if value is not None:
                details[key] = value
        for name, transaction in {
            "fill_transaction_id": fill,
            "cancel_transaction_id": cancel,
            "reject_transaction_id": reject,
            "create_transaction_id": create,
        }.items():
            value = payload.get(transaction, "id")
            if value is not None:
                details[name] = value
        opened_trade_id = cls.opened_trade_id(fill)
        if opened_trade_id:
            details["broker_trade_id"] = opened_trade_id
        closed_trade_ids = cls.closed_trade_ids(fill)
        if closed_trade_ids:
            details["closed_broker_trade_ids"] = closed_trade_ids
        return Metadata.model_validate(details)

    @classmethod
    def opened_trade_id(cls, fill: Any) -> str:
        """Return a trade-opened ID from a fill transaction."""
        trade_opened = payload.get(fill, "tradeOpened")
        value = payload.get(trade_opened, "tradeID") or payload.get(trade_opened, "id")
        return "" if value is None else str(value)

    @classmethod
    def closed_trade_ids(cls, fill: Any) -> tuple[str, ...]:
        """Return trade-closed IDs from a fill transaction."""
        trades_closed = payload.get(fill, "tradesClosed", ()) or ()
        return tuple(
            str(value)
            for item in trades_closed
            if (value := payload.get(item, "tradeID") or payload.get(item, "id")) is not None
        )
