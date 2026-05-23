"""Decision plans for task lifecycle commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from apps.trading.enums import StopMode, TaskStatus
from apps.trading.tasks.lifecycle_events import (
    TaskLifecycleEventSpec,
    build_resume_requested_event_spec,
)


@dataclass(frozen=True)
class LifecycleCommandResult:
    """Transition metadata produced by a lifecycle command."""

    command: str
    previous_status: TaskStatus | str
    current_status: TaskStatus | str
    event: TaskLifecycleEventSpec
    dispatch_task: bool = False
    audit_details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class StopCommandPlan:
    """Decision plan for a stop command before side effects run."""

    effective_mode: StopMode
    next_status: TaskStatus
    extra_updates: dict[str, object] = field(default_factory=dict)
    escalation_log_message: str | None = None

    @property
    def should_revoke_execution(self) -> bool:
        return self.effective_mode == StopMode.IMMEDIATE

    @property
    def should_dispatch_stop_task(self) -> bool:
        return self.effective_mode != StopMode.DRAIN


def build_stop_command_plan(
    *,
    current_status: TaskStatus,
    requested_mode: StopMode,
) -> StopCommandPlan:
    """Resolve stop command mode, target state, and follow-up side effects."""

    effective_mode = requested_mode
    escalation_log_message = None

    if current_status == TaskStatus.DRAINING and requested_mode == StopMode.DRAIN:
        effective_mode = StopMode.IMMEDIATE
        escalation_log_message = (
            "[SERVICE:STOP] DRAINING task received another drain stop, "
            "escalating to IMMEDIATE - task_id=%s"
        )
    elif current_status == TaskStatus.DRAINING and requested_mode == StopMode.GRACEFUL:
        effective_mode = StopMode.IMMEDIATE
        escalation_log_message = (
            "[SERVICE:STOP] DRAINING task received graceful stop, "
            "escalating to IMMEDIATE - task_id=%s"
        )

    if effective_mode == StopMode.DRAIN:
        next_status = TaskStatus.DRAINING
    else:
        next_status = TaskStatus.STOPPING

    return StopCommandPlan(
        effective_mode=effective_mode,
        next_status=next_status,
        extra_updates={},
        escalation_log_message=escalation_log_message,
    )


@dataclass(frozen=True)
class ResumeCommandPlan:
    """Decision plan for a resume command after validation passes."""

    previous_status: TaskStatus
    next_status: TaskStatus
    previous_celery_task_id: object
    new_celery_task_id: UUID
    update_fields: tuple[str, ...]
    transition: LifecycleCommandResult

    @property
    def should_revoke_previous_execution(self) -> bool:
        return self.should_clear_terminal_fields and bool(self.previous_celery_task_id)

    @property
    def should_clear_terminal_fields(self) -> bool:
        return self.previous_status in (TaskStatus.STOPPED, TaskStatus.FAILED)


def build_resume_command_plan(
    *,
    previous_status: TaskStatus,
    previous_celery_task_id: object,
    new_celery_task_id: UUID,
) -> ResumeCommandPlan:
    """Resolve resume mutation fields, Celery id rotation, and transition metadata."""

    next_status = TaskStatus.STARTING
    update_fields = ["status", "updated_at"]
    if previous_status in (TaskStatus.STOPPED, TaskStatus.FAILED):
        update_fields += [
            "error_message",
            "error_traceback",
            "completed_at",
            "status_reason_code",
            "status_reason_message",
        ]
    update_fields.append("celery_task_id")

    transition = LifecycleCommandResult(
        command="resume",
        previous_status=previous_status,
        current_status=next_status,
        event=build_resume_requested_event_spec(from_status=previous_status),
        dispatch_task=True,
    )
    return ResumeCommandPlan(
        previous_status=previous_status,
        next_status=next_status,
        previous_celery_task_id=previous_celery_task_id,
        new_celery_task_id=new_celery_task_id,
        update_fields=tuple(update_fields),
        transition=transition,
    )
