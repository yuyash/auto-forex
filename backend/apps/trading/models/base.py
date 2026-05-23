"""Base models for trading app with UUID support."""

import uuid
from datetime import timedelta
from typing import List
from uuid import uuid4

from django.db import models

from apps.trading.enums import TaskStatus


class UUIDModel(models.Model):
    """Abstract base model with UUID primary key and timestamps.

    This model provides:
    - UUID primary key for better distribution and security
    - Automatic created_at timestamp
    - Automatic updated_at timestamp

    All models that need UUID primary keys should inherit from this class.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier for this record",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="Timestamp when this record was created",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        db_index=True,
        help_text="Timestamp when this record was last updated",
    )

    class Meta:
        abstract = True
        ordering: List[str] = ["-created_at"]


class ExecutableTaskModel(UUIDModel):
    """Abstract base model for executable task lifecycle fields."""

    name = models.CharField(
        max_length=255,
        help_text="Human-readable name for this task",
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text="Optional description of this task",
    )
    status = models.CharField(
        max_length=20,
        default=TaskStatus.CREATED,
        choices=TaskStatus.choices,
        db_index=True,
        help_text="Current task status",
    )
    execution_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text="UUID identifying the current execution run",
    )
    celery_task_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Celery task_id for the current worker invocation",
    )
    dispatch_idempotency_key = models.UUIDField(
        default=uuid4,
        db_index=True,
        help_text=(
            "Idempotency key rotated for each dispatch. "
            "Workers skip stale redeliveries with mismatched keys."
        ),
    )
    started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the task execution started",
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the task execution completed",
    )
    error_message = models.TextField(
        null=True,
        blank=True,
        help_text="Internal failure message if task failed",
    )
    error_traceback = models.TextField(
        null=True,
        blank=True,
        help_text="Internal traceback if task failed",
    )
    status_reason_code = models.CharField(
        max_length=80,
        blank=True,
        default="",
        help_text="Stable public reason code for the latest stop/failure trigger",
    )
    status_reason_message = models.TextField(
        blank=True,
        default="",
        help_text="Public message explaining the latest stop/failure trigger",
    )
    debug_options = models.JSONField(
        default=dict,
        blank=True,
        help_text='Debug settings. Supported: {"tracemalloc": true}',
    )
    sell_on_stop = models.BooleanField(
        default=False,
        help_text="Close all positions when the task is stopped",
    )
    drain_duration_hours = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Maximum duration in hours for drain-on-stop before forcing a stop. "
            "Set to 0 to wait indefinitely for positions to reach breakeven."
        ),
    )
    market_idle_pre_close_minutes = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Switch to IDLE this many minutes before the market closes. "
            "0 disables pre-close idling."
        ),
    )
    market_idle_resume_delay_minutes = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Wait this many minutes after the market reopens before resuming trading. "
            "0 disables the resume delay."
        ),
    )

    COPY_EXCLUDE_FIELDS = frozenset(
        {
            "id",
            "created_at",
            "updated_at",
            "name",
            "status",
            "execution_id",
            "celery_task_id",
            "dispatch_idempotency_key",
            "started_at",
            "completed_at",
            "error_message",
            "error_traceback",
            "status_reason_code",
            "status_reason_message",
            "strategy_state",
        }
    )

    class Meta(UUIDModel.Meta):
        abstract = True

    @property
    def duration(self) -> timedelta | None:
        """Calculate task execution duration when start and completion are known."""
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at  # type: ignore[operator]
        return None

    def _revoke_stopping_celery_task(self) -> None:
        celery_id = self.celery_task_id or self.execution_id
        if self.status == TaskStatus.STOPPING and celery_id:
            from celery import current_app

            current_app.control.revoke(str(celery_id), terminate=True, signal="SIGKILL")

    def delete(self, *args, **kwargs) -> tuple[int, dict[str, int]]:
        """Delete the task if it is not actively running."""
        if self.status in [TaskStatus.STARTING, TaskStatus.RUNNING]:
            raise ValueError(
                f"Cannot delete task in {self.status} state. Stop the task first before deleting."
            )

        self._revoke_stopping_celery_task()
        return super().delete(*args, **kwargs)  # type: ignore[misc]

    def copy_values(self) -> dict[str, object]:
        """Return concrete model field values safe to duplicate into a new task."""
        values: dict[str, object] = {}
        for field in self._meta.concrete_fields:
            if field.name in self.COPY_EXCLUDE_FIELDS:
                continue
            values[field.name] = getattr(self, field.name)
        return values


ExecutableTaskBehaviorMixin = ExecutableTaskModel
