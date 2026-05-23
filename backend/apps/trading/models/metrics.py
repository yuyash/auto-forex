"""Metrics model for time-series strategy metrics."""

from uuid import uuid4

from django.db import models


class Metrics(models.Model):
    """
    Time-series metric recorded during strategy execution.

    Stores strategy-specific metrics as a JSON field, aggregated at
    minute-level granularity by MetricsAggregator.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    task_type = models.CharField(max_length=32)
    task_id = models.UUIDField()
    execution_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="Execution run UUID (shared with Celery task_id)",
    )
    timestamp = models.DateTimeField()
    metrics = models.JSONField(
        default=dict,
        blank=True,
        help_text="Strategy-specific metrics as JSON",
    )

    class Meta:
        db_table = "metrics"
        ordering = ["timestamp"]
        indexes = [
            models.Index(fields=["task_type", "task_id", "execution_id", "timestamp"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["task_type", "task_id", "execution_id", "timestamp"],
                name="unique_metric_timestamp_per_run",
            ),
        ]

    def __str__(self) -> str:
        return f"Metrics({self.timestamp})"


class ExecutionMetricAggregate(models.Model):
    """Incremental roll-up for one execution's latest metrics and continuity checks."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    task_type = models.CharField(max_length=32)
    task_id = models.UUIDField()
    execution_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="Execution run UUID (shared with Celery task_id)",
    )
    latest_timestamp = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Latest metric timestamp persisted for this execution",
    )
    latest_metrics = models.JSONField(
        default=dict,
        blank=True,
        help_text="Latest metric snapshot for this execution",
    )
    sample_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of metric rows ingested into this aggregate",
    )
    balance_min = models.DecimalField(
        max_digits=20,
        decimal_places=10,
        null=True,
        blank=True,
        help_text="Minimum observed current_balance in the aggregate window",
    )
    balance_max = models.DecimalField(
        max_digits=20,
        decimal_places=10,
        null=True,
        blank=True,
        help_text="Maximum observed current_balance in the aggregate window",
    )
    margin_ratio_min = models.DecimalField(
        max_digits=20,
        decimal_places=10,
        null=True,
        blank=True,
        help_text="Minimum observed margin_ratio in the aggregate window",
    )
    margin_ratio_max = models.DecimalField(
        max_digits=20,
        decimal_places=10,
        null=True,
        blank=True,
        help_text="Maximum observed margin_ratio in the aggregate window",
    )
    watermarks = models.JSONField(
        default=dict,
        blank=True,
        help_text="Execution watermark values and timestamps keyed by summary metric",
    )
    continuity_warnings = models.JSONField(
        default=list,
        blank=True,
        help_text="Validation warnings detected during resume/aggregation continuity checks",
    )
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "execution_metric_aggregates"
        indexes = [
            models.Index(fields=["task_type", "task_id", "execution_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["task_type", "task_id", "execution_id"],
                name="uniq_execution_metric_aggregate",
            )
        ]

    def __str__(self) -> str:
        return (
            "ExecutionMetricAggregate("
            f"{self.task_type}:{self.task_id}:exec={self.execution_id}, samples={self.sample_count})"
        )


class MetricsRollup(models.Model):
    """Pre-aggregated latest metric snapshot for one chart bucket."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    task_type = models.CharField(max_length=32)
    task_id = models.UUIDField()
    execution_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="Execution run UUID (shared with Celery task_id)",
    )
    granularity = models.CharField(
        max_length=8,
        help_text="Bucket granularity token such as M5, M15, H1, H4, or D.",
    )
    bucket = models.DateTimeField(help_text="Start timestamp of the rollup bucket")
    source_timestamp = models.DateTimeField(
        help_text="Timestamp of the source metrics row represented by this bucket"
    )
    metrics = models.JSONField(
        default=dict,
        blank=True,
        help_text="Latest strategy metrics snapshot for this bucket",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "metrics_rollups"
        ordering = ["bucket"]
        indexes = [
            models.Index(
                fields=["task_type", "task_id", "execution_id", "granularity", "bucket"],
                name="metrics_roll_scope_bucket_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["task_type", "task_id", "execution_id", "granularity", "bucket"],
                name="uniq_metrics_rollup_bucket",
                nulls_distinct=False,
            )
        ]

    def __str__(self) -> str:
        return (
            "MetricsRollup("
            f"{self.task_type}:{self.task_id}:exec={self.execution_id}, "
            f"{self.granularity}@{self.bucket})"
        )
