"""Task summary serializer."""

from rest_framework import serializers

from apps.trading.serializers.money import CurrencyConversionContextSerializer, MoneySerializer


class TickInfoSerializer(serializers.Serializer):
    """Serializer for tick information."""

    timestamp = serializers.CharField(allow_null=True)
    bid = serializers.DecimalField(max_digits=20, decimal_places=10, allow_null=True)
    ask = serializers.DecimalField(max_digits=20, decimal_places=10, allow_null=True)
    mid = serializers.DecimalField(max_digits=20, decimal_places=10, allow_null=True)


class TickDeliveryInfoSerializer(serializers.Serializer):
    """Serializer for live tick delivery diagnostics."""

    status = serializers.CharField(allow_null=True)
    tick_timestamp = serializers.CharField(allow_null=True)
    observed_at = serializers.CharField(allow_null=True)
    age_seconds = serializers.FloatField(allow_null=True)
    max_age_seconds = serializers.IntegerField(allow_null=True)
    message = serializers.CharField(allow_null=True)


class PnlInfoSerializer(serializers.Serializer):
    """Serializer for PnL information."""

    realized = serializers.DecimalField(max_digits=20, decimal_places=10)
    unrealized = serializers.DecimalField(max_digits=20, decimal_places=10)
    currency = serializers.CharField(allow_null=True, required=False)
    realized_money = MoneySerializer(allow_null=True, required=False)
    unrealized_money = MoneySerializer(allow_null=True, required=False)
    total_money = MoneySerializer(allow_null=True, required=False)
    realized_display_money = MoneySerializer(allow_null=True, required=False)
    unrealized_display_money = MoneySerializer(allow_null=True, required=False)
    total_display_money = MoneySerializer(allow_null=True, required=False)
    display_conversion_context = CurrencyConversionContextSerializer(
        allow_null=True,
        required=False,
    )


class CountsInfoSerializer(serializers.Serializer):
    """Serializer for trade/position counts."""

    total_trades = serializers.IntegerField()
    open_positions = serializers.IntegerField()
    closed_positions = serializers.IntegerField()
    open_long_units = serializers.IntegerField()
    open_short_units = serializers.IntegerField()
    winning_trades = serializers.IntegerField()
    losing_trades = serializers.IntegerField()


class ExecutionInfoSerializer(serializers.Serializer):
    """Serializer for execution state."""

    current_balance = serializers.DecimalField(max_digits=20, decimal_places=10, allow_null=True)
    ticks_processed = serializers.IntegerField()
    account_currency = serializers.CharField(allow_null=True)
    current_balance_currency = serializers.CharField(allow_null=True, required=False)
    current_balance_money = MoneySerializer(allow_null=True, required=False)
    current_balance_display = serializers.DecimalField(
        max_digits=20, decimal_places=2, allow_null=True
    )
    display_currency = serializers.CharField(allow_null=True)
    current_balance_display_money = MoneySerializer(allow_null=True, required=False)
    current_balance_display_conversion_context = CurrencyConversionContextSerializer(
        allow_null=True,
        required=False,
    )
    resume_cursor_timestamp = serializers.CharField(allow_null=True)
    margin_ratio = serializers.DecimalField(max_digits=20, decimal_places=10, allow_null=True)
    current_atr = serializers.DecimalField(max_digits=20, decimal_places=10, allow_null=True)
    recovery_status = serializers.CharField(allow_null=True)
    recovery_warnings = serializers.ListField(
        child=serializers.CharField(), required=False, allow_empty=True
    )
    recovery_blockers = serializers.ListField(
        child=serializers.CharField(), required=False, allow_empty=True
    )
    reconciled_at = serializers.CharField(allow_null=True, required=False)
    tick_delivery = TickDeliveryInfoSerializer(allow_null=True, required=False)


class TaskInfoSerializer(serializers.Serializer):
    """Serializer for task status information."""

    status = serializers.CharField()
    started_at = serializers.CharField(allow_null=True)
    completed_at = serializers.CharField(allow_null=True)
    error_message = serializers.CharField(allow_null=True)
    error_code = serializers.CharField(allow_null=True)
    status_reason_code = serializers.CharField(allow_null=True, required=False)
    status_reason_message = serializers.CharField(allow_null=True, required=False)
    stop_reason = serializers.CharField(allow_null=True)
    progress = serializers.IntegerField()


class WatermarkInfoSerializer(serializers.Serializer):
    """Serializer for one execution watermark."""

    value = serializers.DecimalField(
        max_digits=24,
        decimal_places=10,
        allow_null=True,
    )
    timestamp = serializers.CharField(allow_null=True)
    source_metric = serializers.CharField(allow_null=True, required=False)


class ExecutionWatermarksSerializer(serializers.Serializer):
    """Serializer for execution extrema displayed on the overview tab."""

    margin_ratio_max = WatermarkInfoSerializer()
    base_units_max = WatermarkInfoSerializer()
    open_long_units_max = WatermarkInfoSerializer()
    open_short_units_max = WatermarkInfoSerializer()
    realized_pnl_max = WatermarkInfoSerializer()
    unrealized_pnl_min = WatermarkInfoSerializer()
    open_positions_max = WatermarkInfoSerializer()
    active_cycles_max = WatermarkInfoSerializer()


class TaskSummarySerializer(serializers.Serializer):
    """Serializer for structured task summary response.

    Returns comprehensive task summary grouped into logical sections:
    - timestamp: Common timestamp from the last tick
    - pnl: Realized and unrealized PnL
    - counts: Trade and position counts
    - execution: Balance and ticks processed
    - tick: Last tick prices (bid, ask, mid)
    - task: Status, timing, and progress
    """

    timestamp = serializers.CharField(allow_null=True)
    pnl = PnlInfoSerializer()
    counts = CountsInfoSerializer()
    execution = ExecutionInfoSerializer()
    tick = TickInfoSerializer()
    task = TaskInfoSerializer()
    watermarks = ExecutionWatermarksSerializer()
