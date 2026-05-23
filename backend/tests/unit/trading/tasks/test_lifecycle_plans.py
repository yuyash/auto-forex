"""Unit tests for lifecycle command planning."""

from __future__ import annotations

from uuid import uuid4

from apps.trading.enums import StopMode, TaskStatus
from apps.trading.tasks.lifecycle_plans import (
    build_resume_command_plan,
    build_stop_command_plan,
)


def test_stop_plan_escalates_draining_drain_to_immediate() -> None:
    plan = build_stop_command_plan(
        current_status=TaskStatus.DRAINING,
        requested_mode=StopMode.DRAIN,
    )

    assert plan.effective_mode == StopMode.IMMEDIATE
    assert plan.next_status == TaskStatus.STOPPING
    assert plan.should_revoke_execution is True
    assert plan.should_dispatch_stop_task is True
    assert plan.escalation_log_message is not None


def test_stop_plan_keeps_drain_worker_running() -> None:
    plan = build_stop_command_plan(
        current_status=TaskStatus.RUNNING,
        requested_mode=StopMode.DRAIN,
    )

    assert plan.effective_mode == StopMode.DRAIN
    assert plan.next_status == TaskStatus.DRAINING
    assert plan.should_revoke_execution is False
    assert plan.should_dispatch_stop_task is False


def test_stop_plan_keeps_graceful_close_as_per_request_mode() -> None:
    plan = build_stop_command_plan(
        current_status=TaskStatus.RUNNING,
        requested_mode=StopMode.GRACEFUL_CLOSE,
    )

    assert plan.effective_mode == StopMode.GRACEFUL_CLOSE
    assert plan.next_status == TaskStatus.STOPPING
    assert plan.extra_updates == {}


def test_resume_plan_rotates_and_clears_failed_task() -> None:
    old_celery_task_id = uuid4()
    new_celery_task_id = uuid4()

    plan = build_resume_command_plan(
        previous_status=TaskStatus.FAILED,
        previous_celery_task_id=old_celery_task_id,
        new_celery_task_id=new_celery_task_id,
    )

    assert plan.next_status == TaskStatus.STARTING
    assert plan.new_celery_task_id == new_celery_task_id
    assert plan.should_revoke_previous_execution is True
    assert plan.should_clear_terminal_fields is True
    assert plan.update_fields == (
        "status",
        "updated_at",
        "error_message",
        "error_traceback",
        "completed_at",
        "status_reason_code",
        "status_reason_message",
        "celery_task_id",
    )
    assert plan.transition.dispatch_task is True
    assert plan.transition.event.description == f"Task resume requested (from {TaskStatus.FAILED})"


def test_resume_plan_keeps_paused_task_state_fields() -> None:
    plan = build_resume_command_plan(
        previous_status=TaskStatus.PAUSED,
        previous_celery_task_id=uuid4(),
        new_celery_task_id=uuid4(),
    )

    assert plan.next_status == TaskStatus.STARTING
    assert plan.should_revoke_previous_execution is False
    assert plan.should_clear_terminal_fields is False
    assert plan.update_fields == ("status", "updated_at", "celery_task_id")
