"""Orphaned task recovery for crash recovery and periodic health checks.

When the system crashes (e.g., worker killed, server power loss), tasks may
remain in active database states with no Celery worker actually processing
them.  These "orphaned" tasks need to be detected and re-queued so they can
resume execution.

This module provides:
- ``recover_orphaned_tasks``: core recovery logic (shared by startup & beat)
- ``recover_orphaned_tasks_beat``: Celery task for periodic invocation
- ``on_worker_ready``: signal handler for startup-time recovery
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from celery import shared_task
from celery import current_app
from django.core.cache import cache
from django.utils import timezone as dj_timezone

from apps.trading.enums import TaskStatus, TaskType
from apps.trading.models import BacktestTask, RecoveryAttempt, TaskLog, TradingTask
from apps.trading.models.celery import CeleryTaskStatus
from apps.trading.services.public_errors import (
    TASK_FAILED_ERROR_CODE,
    TASK_FAILED_PUBLIC_MESSAGE,
)

logger = logging.getLogger(__name__)

# A task whose last heartbeat is older than its threshold is considered
# orphaned. Backtests tolerate a longer gap because they can spend longer
# between executor heartbeats while waiting for their publisher/data-source
# path to come online, especially around restart/recovery windows.
TRADING_ORPHAN_HEARTBEAT_THRESHOLD = timedelta(minutes=1)
BACKTEST_ORPHAN_HEARTBEAT_THRESHOLD = timedelta(minutes=5)

# Statuses that indicate a task *should* be actively running. Trading IDLE is
# worker-owned: the task loop is still alive and periodically re-evaluates the
# market clock, so it must also be recovered after a deploy/crash.
_ACTIVE_STATUSES = [TaskStatus.RUNNING, TaskStatus.STARTING]
_ACTIVE_TRADING_STATUSES = [TaskStatus.RUNNING, TaskStatus.STARTING, TaskStatus.IDLE]

# Maximum number of orphaned tasks to process per recovery run to avoid
# unbounded memory usage if many tasks are stuck.
_MAX_RECOVERY_BATCH = 100
_RECOVERY_RUN_LOCK_SECONDS = 45
_TASK_RECOVERY_COOLDOWN_SECONDS = 120


@dataclass(frozen=True, slots=True)
class OrphanDecision:
    """Decision produced by orphan detection for auditability and tests."""

    is_orphaned: bool
    reason: str
    detail: str = ""


def _instance_key(task: BacktestTask | TradingTask) -> str:
    return f"{task.pk}:{task.execution_id}"


def _cache_safe_task_execution_id(task: BacktestTask | TradingTask) -> str:
    execution_id = getattr(task, "execution_id", None)
    if execution_id is None:
        return "none"
    return str(execution_id).replace(" ", "_").replace(":", "_")


def recover_orphaned_tasks(*, source: str = "manual") -> dict[str, int]:
    """Detect and re-queue orphaned backtest and trading tasks.

    A task is considered orphaned when:
    1. Its DB status is RUNNING or STARTING (or IDLE for trading), **and**
    2. Its ``CeleryTaskStatus.last_heartbeat_at`` is older than
       ``ORPHAN_HEARTBEAT_THRESHOLD``, **or** no ``CeleryTaskStatus`` row
       exists at all.

    Backtest tasks are reset to CREATED and re-submitted via
    ``TaskService.start_task``.
    Trading tasks are resumed in the same execution run via
    ``TaskService.recover_trading_task``.

    Args:
        source: Label for log messages (e.g. "worker_ready", "celery_beat").

    Returns:
        Dict with counts: ``{"backtest": N, "trading": N}``
    """
    from apps.trading.tasks.service import TaskService

    lock_key = f"trading:orphan-recovery:lock:{source}"
    if not cache.add(lock_key, dj_timezone.now().isoformat(), timeout=_RECOVERY_RUN_LOCK_SECONDS):
        logger.info(
            "[RECOVERY:%s] Recovery run already in progress; skipping duplicate trigger",
            source,
        )
        return {"backtest": 0, "trading": 0}

    service = TaskService()
    counts: dict[str, int] = {"backtest": 0, "trading": 0}
    try:
        # --- Backtest tasks (bounded queryset) ---
        orphaned_backtest = list(
            BacktestTask.objects.filter(
                status__in=_ACTIVE_STATUSES,
            ).order_by("started_at")[:_MAX_RECOVERY_BATCH]
        )
        active_task_ids = _active_celery_task_ids()
        backtest_heartbeats = _prefetch_heartbeats(
            orphaned_backtest, "trading.tasks.run_backtest_task"
        )
        for task in orphaned_backtest:
            if not _is_orphaned_prefetched(
                task,
                backtest_heartbeats,
                dj_timezone.now() - BACKTEST_ORPHAN_HEARTBEAT_THRESHOLD,
                source=source,
                active_task_ids=active_task_ids,
            ):
                continue
            if _recover_task(task, TaskType.BACKTEST, service, source):
                counts["backtest"] += 1

        # --- Trading tasks (bounded queryset) ---
        orphaned_trading = list(
            TradingTask.objects.filter(
                status__in=_ACTIVE_TRADING_STATUSES,
            ).order_by("started_at")[:_MAX_RECOVERY_BATCH]
        )
        trading_heartbeats = _prefetch_heartbeats(
            orphaned_trading, "trading.tasks.run_trading_task"
        )
        for task in orphaned_trading:
            if not _is_orphaned_prefetched(
                task,
                trading_heartbeats,
                dj_timezone.now() - TRADING_ORPHAN_HEARTBEAT_THRESHOLD,
                source=source,
                active_task_ids=active_task_ids,
            ):
                continue
            if _recover_task(task, TaskType.TRADING, service, source):
                counts["trading"] += 1
    finally:
        cache.delete(lock_key)

    total = counts["backtest"] + counts["trading"]
    if total:
        logger.warning(
            "[RECOVERY:%s] Recovered %d orphaned task(s) (backtest=%d, trading=%d)",
            source,
            total,
            counts["backtest"],
            counts["trading"],
        )
    else:
        logger.info("[RECOVERY:%s] No orphaned tasks found", source)

    return counts


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _prefetch_heartbeats(
    tasks: list[BacktestTask | TradingTask],
    celery_task_name: str,
) -> dict[str, CeleryTaskStatus]:
    """Fetch all CeleryTaskStatus rows for a batch of tasks in one query."""
    if not tasks:
        return {}
    keys = [_instance_key(t) for t in tasks]
    return {
        cts.instance_key: cts
        for cts in CeleryTaskStatus.objects.filter(
            task_name=celery_task_name,
            instance_key__in=keys,
        )
    }


def _is_orphaned_prefetched(
    task: BacktestTask | TradingTask,
    heartbeats: dict[str, CeleryTaskStatus],
    cutoff: datetime,
    *,
    source: str,
    active_task_ids: set[str],
) -> bool:
    """Return True if the task has no recent heartbeat (using prefetched data)."""
    decision = _orphan_decision_prefetched(
        task,
        heartbeats,
        cutoff,
        source=source,
        active_task_ids=active_task_ids,
    )
    if decision.is_orphaned:
        logger.info(
            "[RECOVERY] Task considered orphaned - task_id=%s, reason=%s%s",
            task.pk,
            decision.reason,
            f", detail={decision.detail}" if decision.detail else "",
        )
    return decision.is_orphaned


def _orphan_decision_prefetched(
    task: BacktestTask | TradingTask,
    heartbeats: dict[str, CeleryTaskStatus],
    cutoff: datetime,
    *,
    source: str,
    active_task_ids: set[str],
) -> OrphanDecision:
    """Return an explainable orphan decision using prefetched heartbeat data."""
    # Fall back to execution_id for older rows that pre-date the
    # celery_task_id field and may still have it set to NULL.
    celery_task_id = str(task.celery_task_id or task.execution_id or "")
    if celery_task_id and celery_task_id in active_task_ids:
        return OrphanDecision(False, "active_celery_task", celery_task_id)

    if source == "worker_ready":
        return OrphanDecision(
            True,
            "startup_no_active_celery_task",
            f"celery_task_id={task.celery_task_id}",
        )

    cts = heartbeats.get(_instance_key(task))

    if cts is None:
        return OrphanDecision(True, "missing_heartbeat_row")

    if cts.last_heartbeat_at is None or cts.last_heartbeat_at < cutoff:
        return OrphanDecision(
            True,
            "stale_heartbeat",
            f"last_heartbeat={cts.last_heartbeat_at}, cutoff={cutoff}",
        )

    return OrphanDecision(False, "recent_heartbeat", str(cts.last_heartbeat_at))


def _active_celery_task_ids() -> set[str]:
    """Return the task ids currently reported as active by Celery workers."""
    try:
        active = current_app.control.inspect(timeout=3.0).active() or {}
    except Exception:
        logger.exception("[RECOVERY] Failed to inspect active Celery tasks")
        return set()

    task_ids: set[str] = set()
    for worker_tasks in active.values():
        if not isinstance(worker_tasks, list):
            continue
        for task in worker_tasks:
            if not isinstance(task, dict):
                continue
            task_id = str(task.get("id") or "").strip()
            if task_id:
                task_ids.add(task_id)
    return task_ids


def _is_orphaned(
    task: BacktestTask | TradingTask,
    celery_task_name: str,
    cutoff: datetime,
) -> bool:
    """Return True if the task has no recent heartbeat."""
    cts = CeleryTaskStatus.objects.filter(
        task_name=celery_task_name,
        instance_key=_instance_key(task),
    ).first()

    if cts is None:
        logger.info(
            "[RECOVERY] No CeleryTaskStatus row for task_id=%s (%s) — treating as orphaned",
            task.pk,
            celery_task_name,
        )
        return True

    if cts.last_heartbeat_at is None or cts.last_heartbeat_at < cutoff:
        logger.info(
            "[RECOVERY] Stale heartbeat for task_id=%s (%s) — last_heartbeat=%s, cutoff=%s",
            task.pk,
            celery_task_name,
            cts.last_heartbeat_at,
            cutoff,
        )
        return True

    return False


def _recover_task(
    task: BacktestTask | TradingTask,
    task_type: TaskType,
    service: Any,
    source: str,
) -> bool:
    """Handle an orphaned task according to its task type."""
    action = "resume_same_execution" if task_type == TaskType.TRADING else "mark_stopped"
    task_cooldown_key = (
        "trading:orphan-recovery:task:"
        f"{task_type.value}:{task.pk}:{_cache_safe_task_execution_id(task)}"
    )
    if not cache.add(
        task_cooldown_key,
        dj_timezone.now().isoformat(),
        timeout=_TASK_RECOVERY_COOLDOWN_SECONDS,
    ):
        logger.info(
            "[RECOVERY:%s] Task recovery cooldown active - task_id=%s, type=%s",
            source,
            task.pk,
            task_type,
        )
        _record_recovery_attempt(
            task=task,
            task_type=task_type,
            source=source,
            action=action,
            result="skipped",
            reason="cooldown",
        )
        return False

    logger.warning(
        "[RECOVERY:%s] Recovering orphaned task - task_id=%s, type=%s, "
        "old_status=%s, execution_id=%s",
        source,
        task.pk,
        task_type,
        task.status,
        task.execution_id,
    )

    model_class = type(task)

    if task_type == TaskType.TRADING:
        return _recover_trading_task(task=task, service=service, source=source)

    # Backtests are not resumable and restarting them automatically from the
    # beginning can create duplicate executions after a false orphan signal.
    # Prefer stopping the interrupted run and requiring an explicit restart.
    now = dj_timezone.now()
    rows = model_class.objects.filter(
        pk=task.pk,
        status__in=_ACTIVE_STATUSES,
    ).update(
        status=TaskStatus.STOPPED,
        completed_at=now,
        error_message=(
            "Backtest execution was interrupted and marked stopped during recovery. "
            "Restart manually to rerun it from the beginning."
        ),
    )

    if rows == 0:
        logger.info("[RECOVERY:%s] Task already transitioned - task_id=%s", source, task.pk)
        _record_recovery_attempt(
            task=task,
            task_type=task_type,
            source=source,
            action=action,
            result="skipped",
            reason="already_transitioned",
        )
        return False

    heartbeat_qs = CeleryTaskStatus.objects.filter(
        task_name="trading.tasks.run_backtest_task",
        instance_key=_instance_key(task),
    )
    heartbeat_qs.update(
        status=CeleryTaskStatus.Status.STOPPED,
        status_message="recovery_marked_stopped",
        stopped_at=now,
        last_heartbeat_at=now,
    )

    TaskLog.objects.create(
        task_type=task_type,
        task_id=task.pk,
        execution_id=task.execution_id,
        level="WARNING",
        component=__name__,
        message=(
            f"Backtest task recovered from orphaned {task.status} state "
            f"(source={source}). The interrupted run was marked stopped to avoid "
            "restarting the backtest from the beginning automatically."
        ),
    )

    logger.info(
        "[RECOVERY:%s] Backtest marked STOPPED instead of auto-restart - task_id=%s",
        source,
        task.pk,
    )
    _record_recovery_attempt(
        task=task,
        task_type=task_type,
        source=source,
        action=action,
        result="success",
        reason="orphaned_backtest",
    )
    return True


def _recover_trading_task(*, task: BacktestTask | TradingTask, service: Any, source: str) -> bool:
    """Resume an orphaned trading task in the same execution run."""
    from apps.trading.tasks.service import TaskConflictError

    CeleryTaskStatus.objects.filter(
        task_name="trading.tasks.run_trading_task",
        instance_key=_instance_key(task),
    ).delete()

    TaskLog.objects.create(
        task_type=TaskType.TRADING,
        task_id=task.pk,
        execution_id=task.execution_id,
        level="WARNING",
        component=__name__,
        message=(
            f"Trading task recovered from orphaned {task.status} state "
            f"(source={source}). Resuming the same execution run with the "
            "persisted strategy and grid state."
        ),
    )

    try:
        service.recover_trading_task(
            task,
            expected_celery_task_id=getattr(task, "celery_task_id", None),
        )
        logger.info(
            "[RECOVERY:%s] Trading task resumed in same run - task_id=%s, execution_id=%s",
            source,
            task.pk,
            task.execution_id,
        )
        _record_recovery_attempt(
            task=task,
            task_type=TaskType.TRADING,
            source=source,
            action="resume_same_execution",
            result="success",
            reason="orphaned_trading",
        )
        return True
    except TaskConflictError:
        logger.info(
            "[RECOVERY:%s] Trading task recovery already claimed - task_id=%s",
            source,
            task.pk,
        )
        _record_recovery_attempt(
            task=task,
            task_type=TaskType.TRADING,
            source=source,
            action="resume_same_execution",
            result="skipped",
            reason="already_claimed",
        )
        return False
    except Exception:
        logger.exception(
            "[RECOVERY:%s] Failed to resume trading task - task_id=%s",
            source,
            task.pk,
        )
        TradingTask.objects.filter(pk=task.pk).update(
            status=TaskStatus.FAILED,
            error_message=f"Recovery failed after crash (source={source})",
            status_reason_code=TASK_FAILED_ERROR_CODE,
            status_reason_message=TASK_FAILED_PUBLIC_MESSAGE,
        )
        _record_recovery_attempt(
            task=task,
            task_type=TaskType.TRADING,
            source=source,
            action="resume_same_execution",
            result="failed",
            reason="resume_failed",
        )
        return False


def _record_recovery_attempt(
    *,
    task: BacktestTask | TradingTask,
    task_type: TaskType,
    source: str,
    action: str,
    result: str,
    reason: str,
    detail: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    """Persist a structured recovery audit record without affecting recovery."""
    try:
        RecoveryAttempt.objects.create(
            task_type=task_type,
            task_id=task.pk,
            execution_id=task.execution_id,
            source=source,
            action=action,
            result=result,
            reason=reason,
            detail=detail,
            metadata=metadata or {"status": str(task.status)},
        )
    except Exception:  # pragma: no cover - audit write should never block recovery
        logger.debug("[RECOVERY:%s] Failed to persist recovery attempt", source, exc_info=True)


# ---------------------------------------------------------------------------
# Celery Beat task
# ---------------------------------------------------------------------------


@shared_task(name="trading.tasks.recover_orphaned_tasks")
def recover_orphaned_tasks_beat() -> dict[str, int]:
    """Periodic Celery Beat task to detect and recover orphaned tasks."""
    return recover_orphaned_tasks(source="celery_beat")


@shared_task(name="trading.tasks.recover_orphaned_tasks_startup")
def recover_orphaned_tasks_startup() -> dict[str, int]:
    """Startup recovery task that prefers immediate orphan detection."""
    return recover_orphaned_tasks(source="worker_ready")
