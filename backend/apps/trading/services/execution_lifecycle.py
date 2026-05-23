"""Execution lifecycle state transitions and side effects."""

from __future__ import annotations

from django.utils import timezone

from apps.trading.enums import TaskStatus
from apps.trading.services.execution_snapshots import sync_execution_snapshot


def sync_terminal_execution_artifacts(*, task, task_type: str):
    """Persist terminal execution artifacts for a task run."""
    return sync_execution_snapshot(task=task, task_type=task_type)


def transition_task_to_running(*, task_model, task_id) -> int:
    """Atomically transition a task from STARTING to RUNNING."""
    return task_model.objects.filter(
        pk=task_id,
        status=TaskStatus.STARTING,
    ).update(
        status=TaskStatus.RUNNING,
        started_at=timezone.now(),
    )


def transition_task_to_terminal(
    *,
    task,
    task_type: str,
    status: TaskStatus,
    expected_current_status: TaskStatus | None = None,
    error_message: str | None = None,
    error_traceback: str | None = None,
    status_reason_code: str | None = None,
    status_reason_message: str | None = None,
) -> int:
    """Persist a terminal task transition and sync snapshots.

    ``expected_current_status`` may be a single status or ``None`` to skip
    the guard entirely.  It is also expanded internally to accept IDLE
    wherever RUNNING is expected: an IDLE task has the same semantics as
    a RUNNING task for terminal transitions (the strategy loop pauses
    entries during an idle window but the run itself is still active).
    """
    queryset = type(task).objects.filter(pk=task.pk)
    if expected_current_status is not None:
        allowed = {expected_current_status}
        if expected_current_status == TaskStatus.RUNNING:
            allowed.add(TaskStatus.IDLE)
        queryset = queryset.filter(status__in=allowed)

    update_fields: dict[str, object] = {
        "status": status,
        "completed_at": timezone.now(),
    }
    if error_message is not None:
        update_fields["error_message"] = error_message
    if error_traceback is not None:
        update_fields["error_traceback"] = error_traceback
    if status_reason_code is not None:
        update_fields["status_reason_code"] = status_reason_code
    if status_reason_message is not None:
        update_fields["status_reason_message"] = status_reason_message

    rows_updated = queryset.update(**update_fields)
    if rows_updated > 0:
        task.refresh_from_db()
        sync_terminal_execution_artifacts(task=task, task_type=task_type)
    return rows_updated


def transition_task_to_stopped(
    *,
    task,
    task_type: str,
    expected_current_status: TaskStatus | None = None,
    status_reason_code: str | None = None,
    status_reason_message: str | None = None,
) -> int:
    """Persist a STOPPED transition without a completion timestamp.

    As with :func:`transition_task_to_terminal`, IDLE is accepted wherever
    the caller expects RUNNING so a task that drained through a market
    close still finalises cleanly.
    """
    queryset = type(task).objects.filter(pk=task.pk)
    if expected_current_status is not None:
        allowed = {expected_current_status}
        if expected_current_status == TaskStatus.RUNNING:
            allowed.add(TaskStatus.IDLE)
        queryset = queryset.filter(status__in=allowed)

    update_fields: dict[str, object] = {
        "status": TaskStatus.STOPPED,
        "completed_at": None,
    }
    if status_reason_code is not None:
        update_fields["status_reason_code"] = status_reason_code
    if status_reason_message is not None:
        update_fields["status_reason_message"] = status_reason_message

    rows_updated = queryset.update(**update_fields)
    if rows_updated > 0:
        task.refresh_from_db()
        sync_terminal_execution_artifacts(task=task, task_type=task_type)
    return rows_updated
