"""Market event model for logging."""

from django.db import models


class MarketEvent(models.Model):
    """Persistent event log for the market app.

    This is intentionally independent from any trading/accounts event mechanisms.
    """

    event_type = models.CharField(max_length=64, db_index=True)
    category = models.CharField(max_length=32, default="market", db_index=True)
    severity = models.CharField(max_length=16, default="info", db_index=True)
    description = models.TextField()

    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="market_events",
    )
    account = models.ForeignKey(
        "market.OandaAccounts",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="market_events",
    )
    instrument = models.CharField(max_length=32, default="", blank=True, db_index=True)
    task_type = models.CharField(max_length=32, default="", blank=True, db_index=True)
    task_id = models.UUIDField(null=True, blank=True, db_index=True)
    execution_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Execution run UUID when this event is associated with a task.",
    )
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "market_events"
        verbose_name = "Market Event"
        verbose_name_plural = "Market Events"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["task_type", "task_id", "-created_at"]),
            models.Index(fields=["task_type", "task_id", "execution_id", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.created_at.isoformat()} [{self.category}/{self.severity}] {self.event_type}"
