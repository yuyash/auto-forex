from django.contrib import admin

from apps.trading.models import (
    BacktestTask,
    CeleryTaskStatus,
    Equity,
    Order,
    Position,
    RecoveryAttempt,
    StrategyConfiguration,
    TaskLog,
    Trade,
    TradingEvent,
    TradingTask,
    StrategyEventRecord,
)
from apps.trading.models.state import ExecutionState


@admin.register(StrategyConfiguration)
class StrategyConfigurationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "name", "strategy_type", "created_at", "updated_at")
    list_filter = ("strategy_type", "created_at")
    search_fields = ("name", "strategy_type", "user__email", "user__username")
    ordering = ("-created_at",)


@admin.register(BacktestTask)
class BacktestTaskAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "name",
        "status",
        "data_source",
        "in_memory_mode",
        "backtest_tick_batch_size",
        "spread_filter_enabled",
        "oanda_candle_filter_enabled",
        "start_time",
        "end_time",
        "created_at",
    )
    list_filter = (
        "status",
        "data_source",
        "in_memory_mode",
        "spread_filter_enabled",
        "oanda_candle_filter_enabled",
        "created_at",
    )
    search_fields = ("name", "user__email", "user__username")
    ordering = ("-created_at",)


@admin.register(TradingTask)
class TradingTaskAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "name",
        "status",
        "oanda_account",
        "tick_granularity",
        "sell_on_stop",
        "created_at",
    )
    list_filter = ("status", "tick_granularity", "sell_on_stop", "created_at")
    search_fields = ("name", "user__email", "user__username", "oanda_account__account_id")
    ordering = ("-created_at",)


@admin.register(CeleryTaskStatus)
class CeleryTaskStatusAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "task_name",
        "instance_key",
        "status",
        "celery_task_id",
        "worker",
        "last_heartbeat_at",
        "updated_at",
    )
    list_filter = ("status", "task_name", "updated_at")
    search_fields = ("task_name", "instance_key", "celery_task_id", "worker")
    ordering = ("-updated_at",)


@admin.register(TradingEvent)
class TradingEventAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "created_at",
        "severity",
        "event_type",
        "task_type",
        "task_id",
        "user",
        "account",
        "instrument",
    )
    list_filter = ("severity", "event_type", "task_type", "created_at")
    search_fields = ("event_type", "description", "instrument", "task_type", "task_id")
    ordering = ("-created_at",)


@admin.register(StrategyEventRecord)
class StrategyEventRecordAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "created_at",
        "severity",
        "event_type",
        "task_type",
        "task_id",
        "user",
        "account",
        "instrument",
    )
    list_filter = ("severity", "event_type", "task_type", "created_at")
    search_fields = ("event_type", "description", "instrument", "task_type", "task_id")
    ordering = ("-created_at",)


@admin.register(TaskLog)
class TaskLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "task_type",
        "task_id",
        "timestamp",
        "level",
        "component",
        "message",
    )
    list_filter = ("task_type", "level", "component", "timestamp")
    search_fields = ("task_id", "component", "message")
    ordering = ("-timestamp",)
    readonly_fields = (
        "task_type",
        "task_id",
        "timestamp",
        "level",
        "component",
        "message",
        "details",
    )


@admin.register(RecoveryAttempt)
class RecoveryAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "created_at",
        "task_type",
        "task_id",
        "source",
        "action",
        "result",
        "reason",
    )
    list_filter = ("task_type", "source", "result", "action", "created_at")
    search_fields = ("task_id", "execution_id", "source", "reason", "detail")
    ordering = ("-created_at",)
    readonly_fields = (
        "id",
        "task_type",
        "task_id",
        "execution_id",
        "source",
        "reason",
        "action",
        "result",
        "detail",
        "metadata",
        "created_at",
    )


@admin.register(ExecutionState)
class ExecutionStateAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "task_type",
        "task_id",
        "created_at",
        "updated_at",
    )
    list_filter = ("task_type", "created_at")
    search_fields = ("task_id",)
    ordering = ("-updated_at",)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "task_type",
        "task_id",
        "broker_order_id",
        "position",
        "instrument",
        "units",
        "direction",
        "order_type",
        "status",
        "submitted_at",
    )
    list_filter = ("task_type", "direction", "order_type", "status", "submitted_at")
    search_fields = ("task_id", "broker_order_id", "instrument")
    raw_id_fields = ("position",)
    ordering = ("-submitted_at",)


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "task_type",
        "task_id",
        "instrument",
        "units",
        "entry_price",
        "entry_time",
        "updated_at",
    )
    list_filter = ("task_type", "is_open", "direction", "entry_time")
    search_fields = ("task_id", "instrument")
    ordering = ("-entry_time",)


@admin.register(Trade)
class TradeAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "task_type",
        "task_id",
        "position",
        "order",
        "instrument",
        "direction",
        "units",
        "price",
        "timestamp",
    )
    list_filter = ("task_type", "direction", "timestamp")
    search_fields = ("task_id", "instrument")
    raw_id_fields = ("position", "order")
    ordering = ("-timestamp",)


@admin.register(Equity)
class EquityAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "task_type",
        "task_id",
        "timestamp",
        "balance",
        "ticks_processed",
    )
    list_filter = ("task_type", "timestamp")
    search_fields = ("task_id",)
    ordering = ("-timestamp",)
