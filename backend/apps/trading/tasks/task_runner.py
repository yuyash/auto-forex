"""Shared Celery task execution wrapper.

Both ``run_backtest_task`` and ``run_trading_task`` follow the same skeleton:
load task → guard STARTING → atomic transition to RUNNING → publish lifecycle
event → execute → finalize terminal state → handle exception → cleanup.

This module extracts that shared logic so each task file only provides the
domain-specific bits (model class, task type, execute callable, terminal
status).
"""

from __future__ import annotations

import logging
import traceback
from typing import Any
from uuid import UUID

from apps.trading.enums import TaskStatus, TaskType
from apps.trading.tasks.lifecycle_events import (
    build_failed_event_spec,
    finalize_task_terminal_lifecycle,
)
from apps.trading.services.status_reasons import failure_reason_for_exception

logger = logging.getLogger(__name__)

# Statuses that indicate the task was stopped externally.
_STOPPED_STATUSES = [TaskStatus.STOPPED, TaskStatus.STOPPING]


def handle_task_exception(
    *,
    task_id: UUID,
    task: Any | None,
    error: Exception,
    task_type: TaskType,
    task_label: str,
    component: str,
) -> None:
    """Shared exception handler for Celery task wrappers."""
    error_message = str(error)
    error_tb = traceback.format_exc()

    logger.error(
        "%s task %s failed: %s",
        task_label,
        task_id,
        error_message,
        exc_info=True,
    )

    if task is not None:
        public_reason = failure_reason_for_exception(error)
        finalize_task_terminal_lifecycle(
            logger=logger,
            task=task,
            task_type=task_type,
            status=TaskStatus.FAILED,
            event=build_failed_event_spec(
                task_label=task_label,
                component=component,
                error_type=type(error).__name__,
                error_message=error_message,
            ),
            error_message=error_message,
            error_traceback=error_tb,
            status_reason_code=public_reason.code,
            status_reason_message=public_reason.message,
        )
