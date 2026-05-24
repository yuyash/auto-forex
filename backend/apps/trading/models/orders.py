"""Order execution model."""

from decimal import Decimal
from uuid import uuid4

from django.db import models

from apps.trading.enums import Direction, TaskType


class OrderType(models.TextChoices):
    """Order types supported by the system."""

    MARKET = "market", "Market Order"
    LIMIT = "limit", "Limit Order"
    STOP = "stop", "Stop Order"
    OCO = "oco", "OCO Order"


class OrderStatus(models.TextChoices):
    """Order execution status."""

    PENDING = "pending", "Pending"
    FILLED = "filled", "Filled"
    CANCELLED = "cancelled", "Cancelled"
    REJECTED = "rejected", "Rejected"
    TRIGGERED = "triggered", "Triggered"


class Order(models.Model):
    """
    Order execution record from task execution.

    Stores order details including submission, fill, and cancellation information.
    Orders are created when trades are submitted to the broker.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid4,
        editable=False,
        help_text="Unique identifier for this order",
    )
    task_type = models.CharField(
        max_length=32,
        choices=TaskType.choices,
        db_index=True,
        help_text="Type of task (backtest or trading)",
    )
    task_id = models.UUIDField(
        db_index=True,
        help_text="UUID of the task this order belongs to",
    )
    execution_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Execution run UUID (shared with Celery task_id)",
    )
    broker_order_id = models.TextField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Order ID from the broker (OANDA)",
    )
    oanda_trade_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        db_index=True,
        help_text="OANDA trade ID associated with this order",
    )
    instrument = models.CharField(
        max_length=32,
        db_index=True,
        help_text="Trading instrument (e.g., EUR_USD)",
    )
    order_type = models.CharField(
        max_length=20,
        choices=OrderType.choices,
        help_text="Type of order (market, limit, stop, oco)",
    )
    direction = models.CharField(
        max_length=10,
        choices=Direction.choices,
        null=True,
        blank=True,
        help_text="Order direction (LONG/SHORT). Matches the original position direction for close orders.",
    )
    units = models.IntegerField(
        help_text="Number of units to trade (positive for long, negative for short)",
    )
    requested_price = models.DecimalField(
        max_digits=20,
        decimal_places=10,
        null=True,
        blank=True,
        help_text="Requested price for limit/stop orders (null for market orders)",
    )
    fill_price = models.DecimalField(
        max_digits=20,
        decimal_places=10,
        null=True,
        blank=True,
        help_text="Actual fill price (null if not filled)",
    )
    status = models.CharField(
        max_length=20,
        choices=OrderStatus.choices,
        default=OrderStatus.PENDING,
        db_index=True,
        help_text="Current order status",
    )
    submitted_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="When the order was submitted",
    )
    filled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the order was filled (null if not filled)",
    )
    oanda_response_seconds = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Elapsed wall-clock seconds from submitting the OANDA order request until the response/error returned.",
    )
    cancelled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the order was cancelled (null if not cancelled)",
    )
    stop_loss = models.DecimalField(
        max_digits=20,
        decimal_places=10,
        null=True,
        blank=True,
        help_text="Stop loss price (optional)",
    )
    error_message = models.TextField(
        null=True,
        blank=True,
        help_text="Error message if order was rejected",
    )
    position = models.ForeignKey(
        "trading.Position",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
        help_text="Position this order belongs to",
    )
    layer_index = models.IntegerField(
        null=True,
        blank=True,
        help_text="Layer index (cycle number for Snowball, layer number for Floor)",
    )
    retracement_count = models.IntegerField(
        null=True,
        blank=True,
        help_text="Retracement count (add count for Snowball, retracement count for Floor)",
    )
    is_dry_run = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Whether this was a dry-run order (backtest/simulation)",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="Timestamp when this record was created",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp when this record was last updated",
    )
    replayed_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="When this order was created or updated by resumed event replay.",
    )

    class Meta:
        db_table = "orders"
        verbose_name = "Order"
        verbose_name_plural = "Orders"
        ordering = ["-submitted_at"]
        indexes = [
            models.Index(fields=["task_type", "task_id", "-submitted_at"]),
            models.Index(fields=["task_type", "task_id", "execution_id", "-submitted_at"]),
            models.Index(fields=["task_type", "task_id", "instrument", "status"]),
            models.Index(fields=["status", "-submitted_at"]),
            models.Index(fields=["broker_order_id"]),
            models.Index(fields=["is_dry_run", "status"]),
        ]

    def __str__(self) -> str:
        direction_str = self.direction or "CLOSE"
        return (
            f"{self.status} {self.order_type} {direction_str} "
            f"{self.units} {self.instrument} @ {self.fill_price or self.requested_price or 'market'}"
        )

    def mark_filled(self, fill_price: Decimal, filled_at: models.DateTimeField) -> None:
        """
        Mark the order as filled.

        Args:
            fill_price: Price at which order was filled
            filled_at: Timestamp when order was filled
        """
        self.fill_price = fill_price
        self.filled_at = filled_at
        self.status = OrderStatus.FILLED

    def mark_cancelled(self, cancelled_at: models.DateTimeField) -> None:
        """
        Mark the order as cancelled.

        Args:
            cancelled_at: Timestamp when order was cancelled
        """
        self.cancelled_at = cancelled_at
        self.status = OrderStatus.CANCELLED

    def mark_rejected(self, error_message: str) -> None:
        """
        Mark the order as rejected.

        Args:
            error_message: Reason for rejection
        """
        self.error_message = error_message
        self.status = OrderStatus.REJECTED
