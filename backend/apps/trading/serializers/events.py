"""Event serializers for trading app."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, cast

from rest_framework import serializers

from apps.trading.enums import Direction, EventType
from apps.trading.models import StrategyEventRecord, TradingEvent
from apps.trading.serializers.money import CurrencyConversionContextSerializer, MoneySerializer


class TradingEventSerializer(serializers.ModelSerializer):
    """Serializer for TradingEvent model."""

    event_type = serializers.ChoiceField(choices=EventType.choices)
    event_type_display = serializers.SerializerMethodField(
        help_text="Human-readable display name for the event type.",
    )
    event_scope = serializers.SerializerMethodField(
        help_text="Event scope: trading or task.",
    )

    class Meta:
        model = TradingEvent
        fields = [
            "id",
            "event_type",
            "event_type_display",
            "event_scope",
            "severity",
            "description",
            "user",
            "account",
            "instrument",
            "task_type",
            "task_id",
            "execution_id",
            "details",
            "created_at",
        ]
        read_only_fields = ["id", "event_type_display", "created_at"]

    def get_event_type_display(self, obj: TradingEvent) -> str:
        """Return the human-readable label for the event type."""
        try:
            return EventType(obj.event_type).label
        except ValueError:
            return obj.event_type

    def get_event_scope(self, obj: TradingEvent) -> str:
        details = obj.details if isinstance(obj.details, dict) else {}
        return EventType.scope_of(obj.event_type, details=details)


class StrategyEventSerializer(serializers.ModelSerializer):
    """Serializer for strategy-internal events."""

    event_type_display = serializers.SerializerMethodField(
        help_text="Human-readable display name for the event type.",
    )
    event_scope = serializers.CharField(default="strategy", read_only=True)

    class Meta:
        model = StrategyEventRecord
        fields = [
            "id",
            "event_type",
            "event_type_display",
            "event_scope",
            "severity",
            "description",
            "user",
            "account",
            "instrument",
            "task_type",
            "task_id",
            "execution_id",
            "details",
            "created_at",
        ]
        read_only_fields = ["id", "event_type_display", "event_scope", "created_at"]

    def get_event_type_display(self, obj: StrategyEventRecord) -> str:
        try:
            return EventType(obj.event_type).label
        except ValueError:
            return obj.event_type


class TradeSerializer(serializers.Serializer):
    """Serializer for trade data from Trades model."""

    id = serializers.UUIDField(required=False)
    direction = serializers.ChoiceField(choices=Direction.choices, allow_null=True)
    units = serializers.IntegerField()
    instrument = serializers.CharField()
    price = serializers.DecimalField(max_digits=20, decimal_places=10)
    price_currency = serializers.CharField(required=False, allow_blank=True)
    execution_method = serializers.ChoiceField(choices=EventType.choices)
    execution_method_display = serializers.SerializerMethodField(
        help_text="Human-readable display name for the execution method.",
    )
    layer_index = serializers.IntegerField(required=False, allow_null=True)
    retracement_count = serializers.IntegerField(required=False, allow_null=True)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    timestamp = serializers.DateTimeField()
    position_id = serializers.UUIDField(required=False, allow_null=True)
    order_id = serializers.UUIDField(required=False, allow_null=True)
    oanda_trade_id = serializers.CharField(required=False, allow_null=True)
    cycle_id = serializers.UUIDField(required=False, allow_null=True)
    is_rebuild = serializers.BooleanField(required=False, default=False)
    is_initial_position_seed = serializers.BooleanField(required=False, default=False)
    stop_loss_price = serializers.SerializerMethodField()
    replayed_at = serializers.DateTimeField(required=False, allow_null=True)
    updated_at = serializers.DateTimeField(required=False, allow_null=True)
    pnl = serializers.DecimalField(
        max_digits=20,
        decimal_places=10,
        required=False,
        allow_null=True,
    )
    pnl_currency = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    pnl_money = MoneySerializer(required=False, allow_null=True)
    pnl_display_money = MoneySerializer(required=False, allow_null=True)
    display_conversion_context = CurrencyConversionContextSerializer(
        required=False,
        allow_null=True,
    )
    entry_price = serializers.DecimalField(
        max_digits=20,
        decimal_places=10,
        required=False,
        allow_null=True,
        help_text=(
            "Position entry price (or average price for netting strategies). "
            "Present only on close trades."
        ),
    )

    def get_stop_loss_price(self, obj: object) -> str | None:
        """Return stop_loss_price from the related position, if any."""
        position = getattr(obj, "position", None)
        if position is not None:
            sl = getattr(position, "stop_loss_price", None)
            if sl is not None:
                return str(sl)
        if isinstance(obj, dict):
            val = cast(dict[str, Any], obj).get("stop_loss_price")
            return str(val) if val is not None else None
        return None

    def get_execution_method_display(self, obj: object) -> str:
        """Return the human-readable label for the execution method."""
        value = getattr(obj, "execution_method", None)
        if not value and isinstance(obj, dict):
            value = cast(dict[str, Any], obj).get("execution_method")
        if not value:
            return ""
        try:
            return EventType(value).label
        except ValueError:
            return value


class PositionSerializer(serializers.Serializer):
    """Serializer for position data from Position model."""

    id = serializers.UUIDField()
    instrument = serializers.CharField()
    direction = serializers.CharField()
    units = serializers.IntegerField()
    entry_price = serializers.DecimalField(max_digits=20, decimal_places=10)
    entry_time = serializers.DateTimeField()
    exit_price = serializers.DecimalField(
        max_digits=20, decimal_places=10, required=False, allow_null=True
    )
    exit_time = serializers.DateTimeField(required=False, allow_null=True)
    is_open = serializers.BooleanField()
    layer_index = serializers.IntegerField(required=False, allow_null=True)
    retracement_count = serializers.IntegerField(required=False, allow_null=True)
    planned_exit_price = serializers.DecimalField(
        max_digits=20, decimal_places=10, required=False, allow_null=True
    )
    planned_exit_price_formula = serializers.CharField(required=False, allow_null=True)
    adverse_pips = serializers.DecimalField(
        max_digits=12, decimal_places=4, required=False, allow_null=True
    )
    stop_loss_price = serializers.DecimalField(
        max_digits=20, decimal_places=10, required=False, allow_null=True
    )
    is_rebuild = serializers.BooleanField(required=False, default=False)
    is_initial_position_seed = serializers.BooleanField(required=False, default=False)
    unrealized_pnl = serializers.DecimalField(
        max_digits=20,
        decimal_places=10,
        required=False,
    )
    unrealized_pnl_currency = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    unrealized_pnl_money = MoneySerializer(required=False, allow_null=True)
    unrealized_pnl_display_money = MoneySerializer(required=False, allow_null=True)
    unrealized_pnl_display_conversion_context = CurrencyConversionContextSerializer(
        required=False,
        allow_null=True,
    )
    realized_pnl = serializers.SerializerMethodField()
    realized_pnl_currency = serializers.SerializerMethodField()
    realized_pnl_money = MoneySerializer(required=False, allow_null=True)
    realized_pnl_display_money = MoneySerializer(required=False, allow_null=True)
    realized_pnl_display_conversion_context = CurrencyConversionContextSerializer(
        required=False,
        allow_null=True,
    )
    oanda_trade_id = serializers.CharField(required=False, allow_null=True)
    close_reason = serializers.SerializerMethodField()
    trade_ids = serializers.SerializerMethodField()
    replayed_at = serializers.DateTimeField(required=False, allow_null=True)
    updated_at = serializers.DateTimeField(required=False, allow_null=True)

    _PROTECTION_METHODS = frozenset(
        {
            "volatility_lock",
            "margin_protection",
            "shrink",
            "stop_loss",
        }
    )

    def get_close_reason(self, obj: object) -> str | None:
        """Return close reason derived from the closing trade's execution_method.

        Returns ``None`` for open positions, a protection method name for
        protection closes, and ``"normal"`` for regular TP/manual closes.
        """
        if isinstance(obj, dict):
            return cast(dict[str, Any], obj).get("close_reason")
        if not hasattr(obj, "is_open"):
            return None
        if getattr(obj, "is_open", True):
            return None
        annotated_reason = getattr(obj, "_close_reason", None)
        if annotated_reason:
            return annotated_reason
        # Use prefetched trades if available
        if hasattr(obj, "prefetched_close_reason"):
            return obj.prefetched_close_reason  # type: ignore[return-value]
        if hasattr(obj, "trades"):
            # Check execution_method first (new trades written after the fix)
            close_trade = (
                obj.trades.filter(  # type: ignore[union-attr]
                    execution_method__in=self._PROTECTION_METHODS
                )
                .values_list("execution_method", flat=True)
                .first()
            )
            if close_trade:
                return close_trade
            # Fallback: detect protection closes from description for older
            # trades that still have execution_method='close_position'.
            has_protection_desc = obj.trades.filter(  # type: ignore[union-attr]
                description__startswith="[PROTECTION]"
            ).exists()
            return "shrink" if has_protection_desc else "normal"
        return "normal"

    def get_trade_ids(self, obj: object) -> list[str]:
        """Return the IDs of trades linked to this position."""
        if isinstance(obj, dict) and "trade_ids" in obj:
            raw_trade_ids = cast(dict[str, Any], obj).get("trade_ids") or []
            return [str(trade_id) for trade_id in raw_trade_ids]
        if not self.context.get("include_trade_ids", False):
            return []
        if hasattr(obj, "prefetched_trade_ids"):
            return obj.prefetched_trade_ids  # type: ignore[return-value]
        if hasattr(obj, "trades"):
            return list(obj.trades.values_list("id", flat=True))  # type: ignore[union-attr]
        return []

    def get_realized_pnl(self, obj: object) -> str | None:
        """Return realized PnL for closed positions when available."""
        value = None
        if isinstance(obj, dict):
            value = cast(dict[str, Any], obj).get("realized_pnl")
        else:
            value = getattr(obj, "_realized_pnl", None)
        if value is None:
            return None
        try:
            return str(Decimal(str(value)).quantize(Decimal("0.0000000001")))
        except (InvalidOperation, TypeError, ValueError):
            return str(value)

    def get_realized_pnl_currency(self, obj: object) -> str:
        """Return the currency for realized PnL values."""
        if isinstance(obj, dict):
            data = cast(dict[str, Any], obj)
            return str(
                data.get("realized_pnl_currency") or data.get("unrealized_pnl_currency") or ""
            )
        explicit = getattr(obj, "realized_pnl_currency", None)
        if explicit:
            return str(explicit)
        return str(getattr(obj, "unrealized_pnl_currency", "") or "")


class OrderSerializer(serializers.Serializer):
    """Serializer for order data from Order model."""

    id = serializers.UUIDField()
    broker_order_id = serializers.CharField(required=False, allow_null=True)
    oanda_trade_id = serializers.CharField(required=False, allow_null=True)
    position_id = serializers.UUIDField(required=False, allow_null=True)
    instrument = serializers.CharField()
    order_type = serializers.CharField()
    direction = serializers.CharField(required=False, allow_null=True)
    units = serializers.IntegerField()
    requested_price = serializers.DecimalField(
        max_digits=20, decimal_places=10, required=False, allow_null=True
    )
    fill_price = serializers.DecimalField(
        max_digits=20, decimal_places=10, required=False, allow_null=True
    )
    status = serializers.CharField()
    submitted_at = serializers.DateTimeField()
    filled_at = serializers.DateTimeField(required=False, allow_null=True)
    oanda_response_seconds = serializers.DecimalField(
        max_digits=12, decimal_places=6, required=False, allow_null=True
    )
    cancelled_at = serializers.DateTimeField(required=False, allow_null=True)
    stop_loss = serializers.DecimalField(
        max_digits=20, decimal_places=10, required=False, allow_null=True
    )
    error_message = serializers.CharField(required=False, allow_null=True)
    is_dry_run = serializers.BooleanField()
    layer_index = serializers.IntegerField(required=False, allow_null=True)
    retracement_count = serializers.IntegerField(required=False, allow_null=True)
    replayed_at = serializers.DateTimeField(required=False, allow_null=True)
