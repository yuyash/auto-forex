"""
Admin interface for market app.
"""

from django.contrib import admin

from apps.market.models import (
    CeleryTaskStatus,
    MarketEvent,
    OandaAccounts,
    OandaApiHealthStatus,
)
from apps.market.services.accounts import (
    OANDA_ACCOUNT_SNAPSHOT_STATE_CHOICES,
    oanda_account_snapshot_service,
)


class OandaAccountSnapshotStateFilter(admin.SimpleListFilter):
    """Filter OANDA accounts by cached snapshot health."""

    title = "snapshot state"
    parameter_name = "snapshot_state"

    def lookups(self, request, model_admin):
        return tuple((state, state.title()) for state in OANDA_ACCOUNT_SNAPSHOT_STATE_CHOICES)

    def queryset(self, request, queryset):
        value = self.value()
        if value in OANDA_ACCOUNT_SNAPSHOT_STATE_CHOICES:
            return queryset.filter(oanda_account_snapshot_service.build_state_filter(value))
        return queryset


@admin.register(OandaAccounts)
class OandaAccountAdmin(admin.ModelAdmin):
    """Admin interface for OandaAccounts model."""

    list_display = [
        "user",
        "account_id",
        "api_type",
        "jurisdiction",
        "balance",
        "snapshot_refreshed_at",
        "snapshot_refresh_status",
        "snapshot_refresh_status_updated_at",
        "live_max_exposure_guard_enabled",
        "live_max_estimated_exposure_units",
        "live_max_initial_order_guard_enabled",
        "live_max_initial_order_units",
        "live_max_order_guard_enabled",
        "live_max_order_units",
        "live_tick_latency_metric_interval_seconds",
        "is_active",
        "created_at",
    ]
    list_filter = [
        "api_type",
        "jurisdiction",
        "live_max_exposure_guard_enabled",
        "live_max_initial_order_guard_enabled",
        "live_max_order_guard_enabled",
        "is_active",
        "snapshot_refresh_status",
        OandaAccountSnapshotStateFilter,
        "snapshot_refreshed_at",
        "created_at",
    ]
    search_fields = ["user__email", "account_id"]
    readonly_fields = [
        "snapshot_refreshed_at",
        "snapshot_refresh_error",
        "snapshot_refresh_task_id",
        "snapshot_refresh_status",
        "snapshot_refresh_status_updated_at",
        "created_at",
        "updated_at",
    ]
    ordering = ["-created_at"]

    fieldsets = (
        (
            "Account Information",
            {
                "fields": (
                    "user",
                    "account_id",
                    "api_type",
                    "jurisdiction",
                    "currency",
                )
            },
        ),
        (
            "Balance & Margin",
            {
                "fields": (
                    "balance",
                    "margin_used",
                    "margin_available",
                    "unrealized_pnl",
                    "nav",
                    "open_trade_count",
                    "open_position_count",
                    "pending_order_count",
                    "hedging_enabled",
                    "snapshot_refreshed_at",
                    "snapshot_refresh_error",
                    "snapshot_refresh_task_id",
                    "snapshot_refresh_status",
                    "snapshot_refresh_status_updated_at",
                )
            },
        ),
        (
            "Live Trading Risk",
            {
                "fields": (
                    "live_max_exposure_guard_enabled",
                    "live_max_estimated_exposure_units",
                    "live_max_initial_order_guard_enabled",
                    "live_max_initial_order_units",
                    "live_max_order_guard_enabled",
                    "live_max_order_units",
                    "live_tick_latency_metric_interval_seconds",
                )
            },
        ),
        (
            "Status",
            {"fields": ("is_active",)},
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    # Don't show api_token in admin for security
    exclude = ["api_token"]


@admin.register(MarketEvent)
class MarketEventAdmin(admin.ModelAdmin):
    """Admin interface for MarketEvent model."""

    list_display = [
        "id",
        "created_at",
        "category",
        "severity",
        "event_type",
        "instrument",
        "task_type",
        "task_id",
        "execution_id",
        "account",
        "user",
    ]
    list_filter = [
        "category",
        "severity",
        "event_type",
        "instrument",
        "task_type",
        "created_at",
    ]
    search_fields = [
        "event_type",
        "description",
        "instrument",
        "=task_id",
        "=execution_id",
        "account__account_id",
        "user__email",
    ]
    readonly_fields = ["created_at"]
    ordering = ["-created_at"]


@admin.register(CeleryTaskStatus)
class CeleryTaskStatusAdmin(admin.ModelAdmin):
    """Admin interface for CeleryTaskStatus model."""

    list_display = [
        "id",
        "task_name",
        "instance_key",
        "status",
        "celery_task_id",
        "worker",
        "started_at",
        "last_heartbeat_at",
        "stopped_at",
        "updated_at",
    ]
    list_filter = ["task_name", "status", "started_at", "stopped_at"]
    search_fields = ["task_name", "instance_key", "celery_task_id", "worker"]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["-updated_at"]

    fieldsets = (
        (
            "Task Information",
            {
                "fields": (
                    "task_name",
                    "instance_key",
                    "celery_task_id",
                    "worker",
                )
            },
        ),
        (
            "Status",
            {
                "fields": (
                    "status",
                    "status_message",
                )
            },
        ),
        (
            "Metadata",
            {"fields": ("meta",)},
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "started_at",
                    "last_heartbeat_at",
                    "stopped_at",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )


@admin.register(OandaApiHealthStatus)
class OandaApiHealthStatusAdmin(admin.ModelAdmin):
    """Admin interface for OandaApiHealthStatus model."""

    list_display = [
        "id",
        "account",
        "is_available",
        "checked_at",
        "latency_ms",
        "http_status",
        "created_at",
    ]
    list_filter = ["is_available", "http_status", "checked_at", "created_at"]
    search_fields = ["account__account_id", "account__user__email", "error_message"]
    readonly_fields = [
        "account",
        "is_available",
        "checked_at",
        "latency_ms",
        "http_status",
        "error_message",
        "created_at",
    ]
    ordering = ["-checked_at"]
    date_hierarchy = "checked_at"

    fieldsets = (
        (
            "Account",
            {"fields": ("account",)},
        ),
        (
            "Health Status",
            {
                "fields": (
                    "is_available",
                    "http_status",
                    "latency_ms",
                    "checked_at",
                )
            },
        ),
        (
            "Error Details",
            {"fields": ("error_message",)},
        ),
        (
            "Metadata",
            {"fields": ("created_at",)},
        ),
    )

    def has_add_permission(self, request):
        """Disable manual creation of health status records."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Allow deletion for cleanup purposes."""
        return True
