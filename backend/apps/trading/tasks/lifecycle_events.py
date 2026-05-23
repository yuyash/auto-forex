"""Lifecycle event publishing for task state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from logging import Logger
from typing import Callable, Protocol

from django.utils import timezone

from apps.trading.enums import LogLevel, StopMode, TaskStatus
from apps.trading.models.celery import CeleryTaskStatus
from apps.trading.models import BacktestTask, TaskLog, TradingEvent, TradingTask
from apps.trading.services.execution_lifecycle import (
    sync_terminal_execution_artifacts,
    transition_task_to_stopped,
    transition_task_to_terminal,
)


class TaskLifecycleKind:
    """Canonical lifecycle event kinds."""

    START_REQUESTED = "task_start_requested"
    STOP_REQUESTED = "task_stop_requested"
    DRAIN_REQUESTED = "task_drain_requested"
    PAUSE_REQUESTED = "task_pause_requested"
    RESTART_REQUESTED = "task_restart_requested"
    RESUME_REQUESTED = "task_resume_requested"
    STARTED = "task_started"
    COMPLETED = "task_completed"
    FAILED = "task_failed"
    STOPPED = "task_stopped"
    CANCELLED = "task_cancelled"


@dataclass(frozen=True)
class TaskLifecycleTemplate:
    """Canonical defaults for a lifecycle event kind."""

    default_description: str
    default_log_message: str
    default_log_level: LogLevel


LIFECYCLE_EVENT_TEMPLATES = {
    TaskLifecycleKind.START_REQUESTED: TaskLifecycleTemplate(
        default_description="Task start requested",
        default_log_message="Task start requested",
        default_log_level=LogLevel.INFO,
    ),
    TaskLifecycleKind.STOP_REQUESTED: TaskLifecycleTemplate(
        default_description="Task stop requested",
        default_log_message="Task stop requested",
        default_log_level=LogLevel.INFO,
    ),
    TaskLifecycleKind.DRAIN_REQUESTED: TaskLifecycleTemplate(
        default_description="Task drain requested",
        default_log_message="Task drain requested",
        default_log_level=LogLevel.INFO,
    ),
    TaskLifecycleKind.PAUSE_REQUESTED: TaskLifecycleTemplate(
        default_description="Task pause requested",
        default_log_message="Task pause requested",
        default_log_level=LogLevel.INFO,
    ),
    TaskLifecycleKind.RESTART_REQUESTED: TaskLifecycleTemplate(
        default_description="Task restart requested",
        default_log_message="Task restart requested",
        default_log_level=LogLevel.INFO,
    ),
    TaskLifecycleKind.RESUME_REQUESTED: TaskLifecycleTemplate(
        default_description="Task resume requested",
        default_log_message="Task resume requested",
        default_log_level=LogLevel.INFO,
    ),
    TaskLifecycleKind.STARTED: TaskLifecycleTemplate(
        default_description="Task execution started",
        default_log_message="Task execution started",
        default_log_level=LogLevel.INFO,
    ),
    TaskLifecycleKind.COMPLETED: TaskLifecycleTemplate(
        default_description="Task completed successfully",
        default_log_message="Task completed successfully",
        default_log_level=LogLevel.INFO,
    ),
    TaskLifecycleKind.FAILED: TaskLifecycleTemplate(
        default_description="Task execution failed",
        default_log_message="Task execution failed",
        default_log_level=LogLevel.ERROR,
    ),
    TaskLifecycleKind.STOPPED: TaskLifecycleTemplate(
        default_description="Task stopped",
        default_log_message="Task stopped",
        default_log_level=LogLevel.INFO,
    ),
    TaskLifecycleKind.CANCELLED: TaskLifecycleTemplate(
        default_description="Task cancelled",
        default_log_message="Task cancelled",
        default_log_level=LogLevel.INFO,
    ),
}


@dataclass(frozen=True)
class TaskLifecycleEvent:
    """Lifecycle event payload shared by publishers."""

    task: BacktestTask | TradingTask
    task_type: str
    kind: str
    description: str
    extra_details: dict[str, object] | None = None
    log_level: LogLevel | None = None
    log_message: str | None = None
    log_component: str | None = None

    @property
    def details(self) -> dict[str, object]:
        details = {
            "kind": self.kind,
            "status": str(self.task.status),
            "task_name": str(getattr(self.task, "name", "")),
        }
        if self.extra_details:
            details.update(self.extra_details)
        return details


@dataclass(frozen=True)
class TaskLifecycleEventSpec:
    """Typed event definition used by worker/service callers."""

    kind: str
    description: str
    extra_details: dict[str, object] | None = None
    log_level: LogLevel | None = None
    log_message: str | None = None
    log_component: str | None = None


def build_lifecycle_event_spec(
    *,
    kind: str,
    description: str | None = None,
    extra_details: dict[str, object] | None = None,
    log_level: LogLevel | None = None,
    log_message: str | None = None,
    log_component: str | None = None,
) -> TaskLifecycleEventSpec:
    """Build a typed lifecycle event payload definition."""

    template = LIFECYCLE_EVENT_TEMPLATES.get(kind)
    return TaskLifecycleEventSpec(
        kind=kind,
        description=description or (template.default_description if template else ""),
        extra_details=extra_details,
        log_level=log_level or (template.default_log_level if template else None),
        log_message=log_message or (template.default_log_message if template else None),
        log_component=log_component,
    )


def build_started_event_spec(*, task_label: str, component: str) -> TaskLifecycleEventSpec:
    """Build a canonical task-started lifecycle event."""

    return build_lifecycle_event_spec(
        kind=TaskLifecycleKind.STARTED,
        description=f"{task_label} task execution started",
        log_component=component,
        log_message=f"{task_label} task execution started",
    )


def build_start_requested_event_spec() -> TaskLifecycleEventSpec:
    """Build a canonical start-request lifecycle event."""

    return build_lifecycle_event_spec(kind=TaskLifecycleKind.START_REQUESTED)


def build_stop_requested_event_spec(*, mode: StopMode | str) -> TaskLifecycleEventSpec:
    """Build a canonical stop/drain request lifecycle event."""

    mode_value = str(getattr(mode, "value", mode))
    is_drain = mode_value == StopMode.DRAIN.value
    return build_lifecycle_event_spec(
        kind=TaskLifecycleKind.DRAIN_REQUESTED if is_drain else TaskLifecycleKind.STOP_REQUESTED,
        extra_details={"mode": mode_value},
    )


def build_pause_requested_event_spec() -> TaskLifecycleEventSpec:
    """Build a canonical pause-request lifecycle event."""

    return build_lifecycle_event_spec(kind=TaskLifecycleKind.PAUSE_REQUESTED)


def build_cancelled_event_spec() -> TaskLifecycleEventSpec:
    """Build a canonical cancel lifecycle event."""

    return build_lifecycle_event_spec(kind=TaskLifecycleKind.CANCELLED)


def build_restart_requested_event_spec() -> TaskLifecycleEventSpec:
    """Build a canonical restart-request lifecycle event."""

    return build_lifecycle_event_spec(kind=TaskLifecycleKind.RESTART_REQUESTED)


def build_resume_requested_event_spec(
    *, from_status: object | None = None
) -> TaskLifecycleEventSpec:
    """Build a canonical resume-request lifecycle event."""

    return build_lifecycle_event_spec(
        kind=TaskLifecycleKind.RESUME_REQUESTED,
        description=(
            f"Task resume requested (from {from_status})"
            if from_status is not None
            else "Task resume requested"
        ),
    )


def build_completed_event_spec(*, task_label: str, component: str) -> TaskLifecycleEventSpec:
    """Build a canonical task-completed lifecycle event."""

    return build_lifecycle_event_spec(
        kind=TaskLifecycleKind.COMPLETED,
        description=f"{task_label} task completed successfully",
        log_component=component,
        log_message=f"{task_label} task completed successfully",
    )


def build_failed_event_spec(
    *,
    task_label: str,
    component: str,
    error_type: str,
    error_message: str,
) -> TaskLifecycleEventSpec:
    """Build a canonical task-failed lifecycle event."""

    suffix = f"{error_type}: {error_message}"
    return build_lifecycle_event_spec(
        kind=TaskLifecycleKind.FAILED,
        description=f"{task_label} task failed: {suffix}",
        log_component=component,
        log_message=f"{task_label} task execution failed: {suffix}",
    )


def build_stopped_event_spec(
    *,
    task_label: str,
    component: str,
    description: str | None = None,
    log_message: str | None = None,
) -> TaskLifecycleEventSpec:
    """Build a canonical task-stopped lifecycle event."""

    return build_lifecycle_event_spec(
        kind=TaskLifecycleKind.STOPPED,
        description=description or f"{task_label} task stopped",
        log_component=component,
        log_message=log_message or f"{task_label} task stopped",
    )


class TaskLifecycleEventSink(Protocol):
    """Sink for lifecycle event side effects."""

    def publish(self, event: TaskLifecycleEvent) -> None:
        """Handle a lifecycle event."""


class LoggerLifecycleEventSink:
    """Emit lifecycle events to structured application logs."""

    def __init__(self, *, logger: Logger) -> None:
        self.logger = logger

    def publish(self, event: TaskLifecycleEvent) -> None:
        self.logger.info(
            "[SERVICE:EVENT] Lifecycle event published - task_id=%s, task_type=%s, kind=%s, status=%s",
            event.task.pk,
            event.task_type,
            event.kind,
            event.task.status,
        )


class CallbackLifecycleEventSink:
    """Forward lifecycle events to an injected callback for notifications."""

    def __init__(self, *, callback: Callable[[TaskLifecycleEvent], None]) -> None:
        self.callback = callback

    def publish(self, event: TaskLifecycleEvent) -> None:
        self.callback(event)


class TaskLogLifecycleSink:
    """Persist lifecycle logs through the same event pipeline."""

    def __init__(self, *, logger: Logger) -> None:
        self.logger = logger

    def publish(self, event: TaskLifecycleEvent) -> None:
        if event.task_type == "backtest" and getattr(event.task, "in_memory_mode", False) is True:
            return
        if event.log_level is None or not event.log_message or not event.log_component:
            return
        try:
            TaskLog.objects.create(
                task_type=event.task_type,
                task_id=event.task.pk,
                execution_id=getattr(event.task, "execution_id", None),
                level=event.log_level,
                component=event.log_component,
                message=event.log_message,
            )
        except Exception as exc:  # pragma: no cover - defensive logging path
            self.logger.warning(
                "[SERVICE:EVENT] Failed to persist task lifecycle log - task_id=%s, kind=%s, error=%s",
                event.task.pk,
                event.kind,
                exc,
            )


class TradingEventLifecycleSink:
    """Persist lifecycle events as TradingEvent rows."""

    def __init__(self, *, logger: Logger) -> None:
        self.logger = logger

    def publish(self, event: TaskLifecycleEvent) -> None:
        if event.task_type == "backtest" and getattr(event.task, "in_memory_mode", False) is True:
            return
        try:
            TradingEvent.objects.create(
                event_type="status_changed",
                severity="info",
                description=event.description,
                user=getattr(event.task, "user", None),
                account=getattr(event.task, "oanda_account", None),
                instrument=getattr(event.task, "instrument", None),
                task_type=event.task_type,
                task_id=event.task.pk,
                execution_id=getattr(event.task, "execution_id", None),
                details=event.details,
            )
        except Exception as exc:  # pragma: no cover - defensive logging path
            self.logger.warning(
                "[SERVICE:EVENT] Failed to persist lifecycle event - task_id=%s, kind=%s, error=%s",
                event.task.pk,
                event.kind,
                exc,
            )


class CeleryTaskStatusLifecycleSink:
    """Persist terminal trading task lifecycle status in CeleryTaskStatus."""

    task_name_map = {
        "backtest": "trading.tasks.run_backtest_task",
        "trading": "trading.tasks.run_trading_task",
    }
    terminal_status_map = {
        str(TaskStatus.STOPPED): CeleryTaskStatus.Status.STOPPED,
        str(TaskStatus.COMPLETED): CeleryTaskStatus.Status.COMPLETED,
        str(TaskStatus.FAILED): CeleryTaskStatus.Status.FAILED,
    }

    def __init__(self, *, logger: Logger) -> None:
        self.logger = logger

    def publish(self, event: TaskLifecycleEvent) -> None:
        execution_id = getattr(event.task, "execution_id", None)
        task_name = self.task_name_map.get(str(event.task_type))
        if not execution_id or not task_name:
            return

        status = self.terminal_status_map.get(str(event.task.status))
        if status is None:
            return

        now = timezone.now()
        updates: dict[str, object] = {
            "status": status,
            "stopped_at": now,
            "last_heartbeat_at": now,
        }
        if status == CeleryTaskStatus.Status.FAILED:
            updates["status_message"] = event.description

        try:
            CeleryTaskStatus.objects.filter(
                task_name=task_name,
                instance_key=f"{event.task.pk}:{execution_id}",
            ).update(**updates)
        except Exception as exc:  # pragma: no cover - defensive logging path
            self.logger.warning(
                "[SERVICE:EVENT] Failed to persist CeleryTaskStatus - task_id=%s, kind=%s, error=%s",
                event.task.pk,
                event.kind,
                exc,
            )


class ExecutionArtifactsLifecycleSink:
    """Refresh execution read models for terminal lifecycle events."""

    terminal_kinds = frozenset({TaskLifecycleKind.CANCELLED})

    def __init__(
        self,
        *,
        logger: Logger,
        sync_artifacts: Callable[..., None] = sync_terminal_execution_artifacts,
    ) -> None:
        self.logger = logger
        self.sync_artifacts = sync_artifacts

    def publish(self, event: TaskLifecycleEvent) -> None:
        if event.kind not in self.terminal_kinds:
            return
        try:
            self.sync_artifacts(task=event.task, task_type=event.task_type)
        except Exception as exc:  # pragma: no cover - defensive logging path
            self.logger.warning(
                "[SERVICE:EVENT] Failed to sync execution artifacts - task_id=%s, kind=%s, error=%s",
                event.task.pk,
                event.kind,
                exc,
            )


class TaskLifecycleEventPublisher:
    """Dispatch lifecycle events to configured sinks."""

    def __init__(
        self,
        *,
        logger: Logger,
        sinks: tuple[TaskLifecycleEventSink, ...] | None = None,
    ) -> None:
        self.logger = logger
        self.sinks = sinks or (
            LoggerLifecycleEventSink(logger=logger),
            TaskLogLifecycleSink(logger=logger),
            CeleryTaskStatusLifecycleSink(logger=logger),
            ExecutionArtifactsLifecycleSink(logger=logger),
            TradingEventLifecycleSink(logger=logger),
        )

    def publish(
        self,
        *,
        task: BacktestTask | TradingTask,
        task_type: str,
        kind: str,
        description: str,
        extra_details: dict[str, object] | None = None,
        log_level: LogLevel | None = None,
        log_message: str | None = None,
        log_component: str | None = None,
    ) -> None:
        event = TaskLifecycleEvent(
            task=task,
            task_type=task_type,
            kind=kind,
            description=description,
            extra_details=extra_details,
            log_level=log_level,
            log_message=log_message,
            log_component=log_component,
        )
        for sink in self.sinks:
            sink.publish(event)

    def publish_spec(
        self,
        *,
        task: BacktestTask | TradingTask,
        task_type: str,
        event: TaskLifecycleEventSpec,
    ) -> None:
        """Publish a typed lifecycle event definition."""

        self.publish(
            task=task,
            task_type=task_type,
            kind=event.kind,
            description=event.description,
            extra_details=event.extra_details,
            log_level=event.log_level,
            log_message=event.log_message,
            log_component=event.log_component,
        )


def publish_task_lifecycle_event(
    *,
    logger: Logger,
    task: BacktestTask | TradingTask,
    task_type: str,
    event: TaskLifecycleEventSpec,
) -> None:
    """Publish a lifecycle event through the default sink pipeline."""

    TaskLifecycleEventPublisher(logger=logger).publish_spec(
        task=task,
        task_type=task_type,
        event=event,
    )


def finalize_task_terminal_lifecycle(
    *,
    logger: Logger,
    task: BacktestTask | TradingTask,
    task_type: str,
    status: TaskStatus,
    event: TaskLifecycleEventSpec,
    expected_current_status: TaskStatus | None = None,
    extra_details: dict[str, object] | None = None,
    error_message: str | None = None,
    error_traceback: str | None = None,
    status_reason_code: str | None = None,
    status_reason_message: str | None = None,
) -> int:
    """Persist a terminal task transition and publish its lifecycle event."""

    if status == TaskStatus.STOPPED:
        rows_updated = transition_task_to_stopped(
            task=task,
            task_type=task_type,
            expected_current_status=expected_current_status,
            status_reason_code=status_reason_code,
            status_reason_message=status_reason_message,
        )
    else:
        rows_updated = transition_task_to_terminal(
            task=task,
            task_type=task_type,
            status=status,
            expected_current_status=expected_current_status,
            error_message=error_message,
            error_traceback=error_traceback,
            status_reason_code=status_reason_code,
            status_reason_message=status_reason_message,
        )

    if rows_updated > 0:
        publish_task_lifecycle_event(
            logger=logger,
            task=task,
            task_type=task_type,
            event=build_lifecycle_event_spec(
                kind=event.kind,
                description=event.description,
                extra_details={**(event.extra_details or {}), **(extra_details or {})}
                if extra_details
                else event.extra_details,
                log_level=event.log_level,
                log_message=event.log_message,
                log_component=event.log_component,
            ),
        )
    return rows_updated
