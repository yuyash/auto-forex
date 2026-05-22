"""Trading task model."""

from decimal import Decimal
from typing import Any

from django.db import models

from apps.market.models import OandaAccounts
from apps.trading.enums import TaskStatus, TradingMode
from apps.trading.models.base import ExecutableTaskModel
from apps.trading.services.task_policy import ACCOUNT_BLOCKING_STATUSES


class TradingTaskManager(models.Manager["TradingTask"]):
    """Custom manager for TradingTask model."""

    def for_user(self, user: Any) -> models.QuerySet["TradingTask"]:
        """Get trading tasks for a specific user."""
        return self.filter(user=user)

    def active(self) -> models.QuerySet["TradingTask"]:
        """Get all active (running) trading tasks."""
        return self.filter(status=TaskStatus.RUNNING)

    def running(self) -> models.QuerySet["TradingTask"]:
        """Get all running trading tasks."""
        return self.filter(status=TaskStatus.RUNNING)

    def for_account(self, account: Any) -> models.QuerySet["TradingTask"]:
        """Get trading tasks for a specific OANDA account."""
        return self.filter(oanda_account=account)

    def by_config(self, config: Any) -> models.QuerySet["TradingTask"]:
        """Get trading tasks using a specific strategy configuration."""
        return self.filter(config=config)


class TradingTask(ExecutableTaskModel):
    """
    Persistent live trading task with reusable configuration.

    A TradingTask represents a live trading operation with specific configuration
    and account. Tasks can be started, stopped, paused, and resumed multiple times,
    with each execution tracked separately.

    Only one task can be running per account at a time.

    Inherits UUID primary key and timestamps from UUIDModel.
    """

    class TickGranularity(models.TextChoices):
        """Live tick sampling granularity."""

        TICK = "tick", "All Ticks"
        SECOND_1 = "1s", "1 Second"
        SECOND_10 = "10s", "10 Seconds"
        SECOND_15 = "15s", "15 Seconds"
        SECOND_30 = "30s", "30 Seconds"
        MINUTE_1 = "1m", "1 Minute"
        MINUTE_5 = "5m", "5 Minutes"
        MINUTE_15 = "15m", "15 Minutes"
        MINUTE_30 = "30m", "30 Minutes"
        HOUR_1 = "1h", "1 Hour"

    objects = TradingTaskManager()

    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="trading_tasks",
        help_text="User who created this trading task",
    )
    config = models.ForeignKey(
        "trading.StrategyConfiguration",
        on_delete=models.PROTECT,
        related_name="trading_tasks",
        help_text="Strategy configuration used by this task",
    )
    oanda_account = models.ForeignKey(
        OandaAccounts,
        on_delete=models.PROTECT,
        related_name="trading_tasks",
        help_text="OANDA account used for trading",
    )
    dry_run = models.BooleanField(
        default=False,
        help_text="Simulate order execution without placing real orders on OANDA",
    )
    instrument = models.CharField(
        max_length=20,
        default="USD_JPY",
        help_text="Trading instrument (e.g., EUR_USD, USD_JPY)",
    )
    display_currency = models.CharField(
        max_length=3,
        blank=True,
        default="",
        help_text="Preferred currency for displaying balances and PnL.",
    )
    pip_size = models.DecimalField(
        max_digits=10,
        decimal_places=5,
        null=True,
        blank=True,
        default=None,
        help_text="Pip size for the instrument (e.g., 0.0001 for EUR_USD, 0.01 for USD_JPY). If not provided, will be fetched from OANDA account.",
    )
    trading_mode = models.CharField(
        max_length=20,
        choices=TradingMode.choices,
        default=TradingMode.NETTING,
        help_text="Trading mode: netting (aggregated positions) or hedging (independent trades).",
    )
    hedging_enabled = models.BooleanField(
        default=True,
        help_text="Allow simultaneous long and short positions (hedging). Requires a hedging-enabled OANDA account.",
    )
    tick_granularity = models.CharField(
        max_length=8,
        choices=TickGranularity.choices,
        default=TickGranularity.TICK,
        help_text=(
            "Live tick sampling granularity. Use 'tick' for every tick, "
            "or a time bucket such as '1s' or '1m' to use the first tick in each bucket."
        ),
    )
    initial_positions_enabled = models.BooleanField(
        default=False,
        help_text="Create Snowball initial cycles/positions before starting the trading task.",
    )
    initial_position_cycles = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Requested Snowball initial cycle/position structure. "
            "Positions, trades, orders, and strategy state are generated from this data."
        ),
    )
    strategy_state = models.JSONField(
        default=dict,
        blank=True,
        help_text="Strategy-specific state for persistence across restarts",
    )

    # OANDA API retry/backoff settings.  The reconciliation service uses these
    # to recover from transient network errors when fetching account/position
    # state.  With exponential backoff a single transient outage typically
    # resolves within the first few retries; higher caps protect the task
    # from failing during longer broker-side incidents.
    api_retry_max_attempts = models.PositiveIntegerField(
        default=50,
        help_text=(
            "Maximum number of retry attempts for OANDA API calls before the task fails. "
            "Uses exponential backoff between attempts."
        ),
    )
    api_retry_backoff_base_seconds = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal("1.0"),
        help_text="Initial delay between OANDA API retries (seconds). Doubled on each attempt.",
    )
    api_retry_backoff_max_seconds = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        default=Decimal("60.0"),
        help_text="Cap on the backoff delay between retries (seconds).",
    )

    live_tick_stale_guard_enabled = models.BooleanField(
        default=True,
        help_text=(
            "Fail the task before strategy/order processing when a live tick is older than "
            "live_tick_max_age_seconds."
        ),
    )
    live_tick_max_age_seconds = models.PositiveIntegerField(
        default=30,
        help_text="Maximum accepted age in seconds for a live tick before the task fails.",
    )
    live_tick_status_log_interval_seconds = models.PositiveIntegerField(
        default=60,
        help_text=(
            "Interval in seconds for periodic live tick delivery status logs. "
            "Set to 0 to disable periodic OK logs."
        ),
    )
    broker_drift_check_interval_seconds = models.PositiveIntegerField(
        default=60,
        help_text=(
            "Interval in seconds for runtime OANDA/local broker drift checks. "
            "Set to 0 to disable runtime drift checks after startup reconciliation."
        ),
    )

    class Meta:
        db_table = "trading_tasks"
        verbose_name = "Trading Task"
        verbose_name_plural = "Trading Tasks"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"],
                name="unique_user_trading_task_name",
            ),
            models.UniqueConstraint(
                fields=["oanda_account"],
                condition=models.Q(status__in=ACCOUNT_BLOCKING_STATUSES),
                name="uniq_active_trading_task_per_account",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=[
                        TaskStatus.CREATED,
                        TaskStatus.STARTING,
                        TaskStatus.RUNNING,
                        TaskStatus.PAUSED,
                        TaskStatus.IDLE,
                        TaskStatus.DRAINING,
                        TaskStatus.STOPPING,
                        TaskStatus.STOPPED,
                        TaskStatus.COMPLETED,
                        TaskStatus.FAILED,
                    ]
                ),
                name="valid_trading_task_status",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["user", "config"]),
            models.Index(fields=["oanda_account", "status"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["execution_id"]),
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["user", "-created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.config.strategy_type}) - {self.oanda_account.account_id}"

    @property
    def account_currency(self) -> str:
        """Return the account base currency supplied by the linked OANDA account."""
        return str(getattr(self.oanda_account, "currency", "") or "").strip().upper()

    @property
    def effective_display_currency(self) -> str:
        """Return the configured display currency, falling back to account currency."""
        return str(self.display_currency or self.account_currency or "").strip().upper()

    def copy(self, new_name: str) -> "TradingTask":
        """
        Create a copy of this task with a new name.

        All task properties are duplicated except name and ID.

        Args:
            new_name: Name for the new task

        Returns:
            TradingTask: The newly created task

        Raises:
            ValueError: If new_name is the same as current name or already exists
        """
        if new_name == self.name:
            raise ValueError("New name must be different from current name")

        # Check if name already exists for this user
        if TradingTask.objects.filter(user=self.user, name=new_name).exists():
            raise ValueError(f"A trading task with name '{new_name}' already exists")

        copy_values = self.copy_values()
        copy_values.update(name=new_name, status=TaskStatus.CREATED)
        new_task = TradingTask.objects.create(**copy_values)

        return new_task

    def validate_configuration(self) -> tuple[bool, str | None]:
        """
        Validate task configuration before execution.

        Validates:
        - Strategy configuration parameters
        - Account ownership
        - Account is active

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Validate account ownership
        if self.oanda_account.user != self.user:
            return False, "Account does not belong to the user"

        # Validate account is active
        if not self.oanda_account.is_active:
            return False, "Account is not active"

        # Validate strategy configuration
        is_valid, error_message = self.config.validate_parameters()
        if not is_valid:
            return False, f"Configuration validation failed: {error_message}"

        return True, None

    def has_strategy_state(self) -> bool:
        """Check if task has saved strategy state."""
        return bool(self.strategy_state)

    def can_resume(self) -> bool:
        """Whether the current execution can resume from persisted state."""
        return (
            self.status in (TaskStatus.PAUSED, TaskStatus.STOPPED, TaskStatus.FAILED)
            and self.execution_id is not None
        )

    @property
    def account_id(self) -> int:
        """Get the OANDA account ID.

        Returns:
            int: The primary key of the associated OANDA account
        """
        return self.oanda_account_id  # type: ignore[return-value]
