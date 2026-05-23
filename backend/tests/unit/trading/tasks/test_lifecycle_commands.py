"""Unit tests for lifecycle command adapters."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from apps.trading.enums import StopMode, TaskStatus
from apps.trading.tasks.lifecycle_adapters import LifecycleCommandAdapters
from apps.trading.tasks.lifecycle_commands import (
    TaskLifecycleCommands,
)
from apps.trading.tasks.lifecycle_events import TaskLifecycleKind
from apps.trading.services.status_reasons import stop_request_reason


def _make_commands(service: MagicMock) -> tuple[TaskLifecycleCommands, MagicMock]:
    logger = MagicMock()
    events = MagicMock()
    adapters = LifecycleCommandAdapters(
        inspect_workers=MagicMock(return_value={"worker1": {}}),
        signal_stop=MagicMock(),
        signal_pause=MagicMock(),
        revoke_execution=MagicMock(),
        dispatch_stop=MagicMock(),
        sleep=MagicMock(),
    )
    return (
        TaskLifecycleCommands(
            service=service,
            logger=logger,
            events=events,
            adapters=adapters,
        ),
        adapters,
    )


def _track_writer_state(service: MagicMock) -> None:
    def persist_state_if_current(
        *,
        command: str,
        task: Any,
        from_status: TaskStatus | str,
        to_status: TaskStatus,
        extra_updates: dict[str, object] | None = None,
    ) -> None:
        _ = command
        assert task.status == from_status
        for field, value in (extra_updates or {}).items():
            setattr(task, field, value)
        task.status = to_status

    def persist_terminal_state_if_current(
        *,
        command: str,
        task: Any,
        from_status: TaskStatus | str,
        to_status: TaskStatus,
        extra_updates: dict[str, object] | None = None,
    ) -> None:
        persist_state_if_current(
            command=command,
            task=task,
            from_status=from_status,
            to_status=to_status,
            extra_updates={"completed_at": object(), **(extra_updates or {})},
        )

    def update_if_current(
        *,
        command: str,
        task: Any,
        expected_status: TaskStatus | str,
        updates: dict[str, object],
    ) -> None:
        _ = command
        assert task.status == expected_status
        for field, value in updates.items():
            setattr(task, field, value)

    service.writer.persist_state_if_current.side_effect = persist_state_if_current
    service.writer.persist_terminal_state_if_current.side_effect = persist_terminal_state_if_current
    service.writer.update_if_current.side_effect = update_if_current


def _make_lifecycle_task(
    *,
    status: TaskStatus,
    task_id: object | None = None,
    execution_id: object | None = None,
    celery_task_id: object | None = None,
    in_memory_mode: bool = False,
) -> MagicMock:
    return MagicMock(
        pk=task_id or uuid4(),
        status=status,
        execution_id=execution_id or uuid4(),
        celery_task_id=celery_task_id or uuid4(),
        in_memory_mode=in_memory_mode,
    )


@pytest.mark.parametrize(
    (
        "task_type",
        "previous_status",
        "mode",
        "expected_status",
        "expected_mode",
        "expected_event_kind",
        "expected_dispatch",
        "expected_revoke",
        "expected_extra_updates",
    ),
    [
        (
            "backtest",
            TaskStatus.STARTING,
            "graceful",
            TaskStatus.STOPPING,
            StopMode.GRACEFUL,
            TaskLifecycleKind.STOP_REQUESTED,
            True,
            False,
            {},
        ),
        (
            "trading",
            TaskStatus.RUNNING,
            "immediate",
            TaskStatus.STOPPING,
            StopMode.IMMEDIATE,
            TaskLifecycleKind.STOP_REQUESTED,
            True,
            True,
            {},
        ),
        (
            "trading",
            TaskStatus.RUNNING,
            "drain",
            TaskStatus.DRAINING,
            StopMode.DRAIN,
            TaskLifecycleKind.DRAIN_REQUESTED,
            False,
            False,
            {},
        ),
        (
            "trading",
            TaskStatus.RUNNING,
            "graceful_close",
            TaskStatus.STOPPING,
            StopMode.GRACEFUL_CLOSE,
            TaskLifecycleKind.STOP_REQUESTED,
            True,
            False,
            {},
        ),
        (
            "trading",
            TaskStatus.DRAINING,
            "drain",
            TaskStatus.STOPPING,
            StopMode.IMMEDIATE,
            TaskLifecycleKind.STOP_REQUESTED,
            True,
            True,
            {},
        ),
    ],
)
def test_stop_transition_contract(
    task_type: str,
    previous_status: TaskStatus,
    mode: str,
    expected_status: TaskStatus,
    expected_mode: StopMode,
    expected_event_kind: str,
    expected_dispatch: bool,
    expected_revoke: bool,
    expected_extra_updates: dict[str, object],
) -> None:
    task_id = uuid4()
    task = _make_lifecycle_task(status=previous_status, task_id=task_id)
    service = MagicMock()
    service._get_task_and_type.return_value = (task, task_type)
    _track_writer_state(service)
    commands, adapters = _make_commands(service)

    result = commands.stop(task_id, mode)

    assert result is True
    assert task.status == expected_status
    expected_updates = {
        **expected_extra_updates,
        **stop_request_reason(expected_mode).as_update(),
    }
    service.writer.persist_state_if_current.assert_called_once_with(
        command="stop",
        task=task,
        from_status=previous_status,
        to_status=expected_status,
        extra_updates=expected_updates,
    )
    expected_task_name = (
        "trading.tasks.run_backtest_task"
        if task_type == "backtest"
        else "trading.tasks.run_trading_task"
    )
    adapters.signal_stop.assert_called_once_with(
        task_id,
        expected_task_name,
        task.execution_id,
        expected_mode,
    )
    if expected_revoke:
        adapters.revoke_execution.assert_called_once_with(task.celery_task_id)
    else:
        adapters.revoke_execution.assert_not_called()
    if expected_dispatch:
        adapters.dispatch_stop.assert_called_once_with(
            task_id,
            task_type == "backtest",
            expected_mode,
        )
    else:
        adapters.dispatch_stop.assert_not_called()
    event = commands.events.publish_spec.call_args.kwargs["event"]
    assert event.kind == expected_event_kind
    assert event.extra_details == {"mode": expected_mode.value}


@pytest.mark.parametrize("previous_status", [TaskStatus.STARTING, TaskStatus.RUNNING])
def test_pause_transition_contract_for_backtests(previous_status: TaskStatus) -> None:
    task_id = uuid4()
    task = _make_lifecycle_task(status=previous_status, task_id=task_id)
    service = MagicMock()
    service._get_task_and_type.return_value = (task, "backtest")
    _track_writer_state(service)
    commands, adapters = _make_commands(service)

    result = commands.pause(task_id)

    assert result is True
    assert task.status == TaskStatus.PAUSED
    service.writer.persist_state_if_current.assert_called_once_with(
        command="pause",
        task=task,
        from_status=previous_status,
        to_status=TaskStatus.PAUSED,
    )
    adapters.signal_pause.assert_called_once_with(
        task_id,
        "trading.tasks.run_backtest_task",
        task.execution_id,
    )
    event = commands.events.publish_spec.call_args.kwargs["event"]
    assert event.kind == TaskLifecycleKind.PAUSE_REQUESTED


@pytest.mark.parametrize(
    "previous_status",
    [TaskStatus.STARTING, TaskStatus.RUNNING, TaskStatus.PAUSED],
)
def test_cancel_transition_contract(previous_status: TaskStatus) -> None:
    task_id = uuid4()
    task = _make_lifecycle_task(status=previous_status, task_id=task_id)
    celery_result = MagicMock()
    service = MagicMock()
    service._get_task_and_type.return_value = (task, "backtest")
    service.get_celery_result.return_value = celery_result
    _track_writer_state(service)
    commands, adapters = _make_commands(service)

    result = commands.cancel(task_id)

    assert result is True
    assert task.status == TaskStatus.STOPPED
    service.writer.persist_terminal_state_if_current.assert_called_once_with(
        command="cancel",
        task=task,
        from_status=previous_status,
        to_status=TaskStatus.STOPPED,
    )
    service.get_celery_result.assert_called_once_with(str(task.celery_task_id))
    celery_result.revoke.assert_called_once_with(terminate=True)
    adapters.revoke_execution.assert_not_called()
    event = commands.events.publish_spec.call_args.kwargs["event"]
    assert event.kind == TaskLifecycleKind.CANCELLED


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("task_type", "previous_status", "expected_revoke", "expected_market_kick"),
    [
        ("backtest", TaskStatus.PAUSED, False, False),
        ("backtest", TaskStatus.STOPPED, True, False),
        ("trading", TaskStatus.FAILED, True, True),
    ],
)
def test_resume_transition_contract(
    task_type: str,
    previous_status: TaskStatus,
    expected_revoke: bool,
    expected_market_kick: bool,
) -> None:
    task_id = uuid4()
    old_celery_task_id = uuid4()
    task = _make_lifecycle_task(
        status=previous_status,
        task_id=task_id,
        celery_task_id=old_celery_task_id,
    )
    task.save = MagicMock()
    task_model = MagicMock()
    task_model.objects.select_for_update.return_value.get.return_value = task
    service = MagicMock()
    service._get_task_and_type.return_value = (task, task_type)
    service._get_task_model.return_value = task_model
    service.get_celery_result.return_value = None
    service._dispatch_task = MagicMock()
    commands, adapters = _make_commands(service)
    commands.resume_validator = MagicMock()
    commands._kick_market_supervisor = MagicMock()

    result = commands.resume(task_id)

    assert result is task
    assert task.status == TaskStatus.STARTING
    assert task.celery_task_id != old_celery_task_id
    commands.resume_validator.validate.assert_called_once_with(task=task, task_type=task_type)
    task.save.assert_called_once()
    service._dispatch_task.assert_called_once_with(task, task_type)
    if expected_revoke:
        adapters.revoke_execution.assert_called_once_with(old_celery_task_id)
    else:
        adapters.revoke_execution.assert_not_called()
    if expected_market_kick:
        commands._kick_market_supervisor.assert_called_once_with()
    else:
        commands._kick_market_supervisor.assert_not_called()
    event = commands.events.publish_spec.call_args.kwargs["event"]
    assert event.kind == TaskLifecycleKind.RESUME_REQUESTED
    assert event.description == f"Task resume requested (from {previous_status.value})"


def test_stop_uses_injected_adapters() -> None:
    task_id = uuid4()
    execution_id = uuid4()
    celery_task_id = uuid4()
    task = MagicMock(
        pk=task_id,
        status=TaskStatus.RUNNING,
        execution_id=execution_id,
        celery_task_id=celery_task_id,
    )
    service = MagicMock()
    service._get_task_and_type.return_value = (task, "trading")

    commands, adapters = _make_commands(service)

    result = commands.stop(task_id, "immediate")

    assert result is True
    adapters.signal_stop.assert_called_once()
    adapters.revoke_execution.assert_called_once_with(celery_task_id)
    adapters.dispatch_stop.assert_called_once_with(task_id, False, StopMode.IMMEDIATE)
    event = commands.events.publish_spec.call_args.kwargs["event"]
    assert event.kind == TaskLifecycleKind.STOP_REQUESTED
    assert event.extra_details == {"mode": StopMode.IMMEDIATE.value}


def test_restart_uses_injected_sleep() -> None:
    task_id = uuid4()
    execution_id = uuid4()
    celery_task_id = uuid4()
    task_model = type("DummyTaskModel", (), {"objects": MagicMock()})
    task = task_model()
    task.pk = task_id
    task.status = TaskStatus.RUNNING
    task.execution_id = execution_id
    task.celery_task_id = celery_task_id
    task.refresh_from_db = MagicMock(
        side_effect=lambda: setattr(task, "status", TaskStatus.CREATED)
    )
    service = MagicMock()
    service._get_task_and_type.return_value = (task, "backtest")
    service.stop_task = MagicMock(return_value=True)
    service.start_task = MagicMock(return_value=task)
    service.writer.clear_execution_history = MagicMock()
    task_model.objects.filter.return_value.update.return_value = 1

    commands, adapters = _make_commands(service)

    result = commands.restart(task_id)

    assert result is task
    adapters.sleep.assert_called_once_with(1)


def test_stop_continues_when_signal_adapter_fails() -> None:
    task_id = uuid4()
    task = MagicMock(
        pk=task_id,
        status=TaskStatus.RUNNING,
        execution_id=uuid4(),
        celery_task_id=uuid4(),
    )
    service = MagicMock()
    service._get_task_and_type.return_value = (task, "backtest")

    commands, adapters = _make_commands(service)
    adapters.signal_stop.side_effect = RuntimeError("redis unavailable")

    result = commands.stop(task_id, "graceful")

    assert result is True
    adapters.dispatch_stop.assert_called_once()


def test_pause_rejects_trading_tasks() -> None:
    task_id = uuid4()
    execution_id = uuid4()
    task = MagicMock(pk=task_id, status=TaskStatus.RUNNING, execution_id=execution_id)
    service = MagicMock()
    service._get_task_and_type.return_value = (task, "trading")

    commands, adapters = _make_commands(service)

    with pytest.raises(ValueError, match="Pause is not supported for trading tasks"):
        commands.pause(task_id)

    adapters.signal_pause.assert_not_called()


def test_stop_rejects_drain_for_in_memory_backtests() -> None:
    task_id = uuid4()
    task = _make_lifecycle_task(
        status=TaskStatus.RUNNING,
        task_id=task_id,
        in_memory_mode=True,
    )
    service = MagicMock()
    service._get_task_and_type.return_value = (task, "backtest")

    commands, adapters = _make_commands(service)

    with pytest.raises(ValueError, match="Drain stop is not supported"):
        commands.stop(task_id, "drain")

    service.writer.persist_state_if_current.assert_not_called()
    adapters.signal_stop.assert_not_called()
    adapters.dispatch_stop.assert_not_called()


def test_pause_rejects_in_memory_backtests() -> None:
    task_id = uuid4()
    task = _make_lifecycle_task(
        status=TaskStatus.RUNNING,
        task_id=task_id,
        in_memory_mode=True,
    )
    service = MagicMock()
    service._get_task_and_type.return_value = (task, "backtest")

    commands, adapters = _make_commands(service)

    with pytest.raises(ValueError, match="Pause is not supported for in-memory backtests"):
        commands.pause(task_id)

    service.writer.persist_state_if_current.assert_not_called()
    adapters.signal_pause.assert_not_called()


def test_resume_rejects_in_memory_backtests() -> None:
    task_id = uuid4()
    task = _make_lifecycle_task(
        status=TaskStatus.PAUSED,
        task_id=task_id,
        in_memory_mode=True,
    )
    service = MagicMock()
    service._get_task_and_type.return_value = (task, "backtest")
    service._get_task_model = MagicMock()

    commands, adapters = _make_commands(service)

    with pytest.raises(ValueError, match="Resume is not supported for in-memory backtests"):
        commands.resume(task_id)

    service._get_task_model.assert_not_called()
    service._dispatch_task.assert_not_called()
    adapters.revoke_execution.assert_not_called()


def test_pause_uses_injected_adapter_for_backtest() -> None:
    task_id = uuid4()
    execution_id = uuid4()
    task = MagicMock(pk=task_id, status=TaskStatus.RUNNING, execution_id=execution_id)
    service = MagicMock()
    service._get_task_and_type.return_value = (task, "backtest")

    commands, adapters = _make_commands(service)

    result = commands.pause(task_id)

    assert result is True
    service.writer.persist_state_if_current.assert_called_once_with(
        command="pause",
        task=task,
        from_status=TaskStatus.RUNNING,
        to_status=TaskStatus.PAUSED,
    )
    adapters.signal_pause.assert_called_once()


def test_stop_rejects_created_task_state() -> None:
    task_id = uuid4()
    task = MagicMock(
        pk=task_id,
        status=TaskStatus.CREATED,
        execution_id=uuid4(),
        celery_task_id=uuid4(),
    )
    service = MagicMock()
    service._get_task_and_type.return_value = (task, "backtest")

    commands, adapters = _make_commands(service)

    with pytest.raises(ValueError, match="cannot be stopped from"):
        commands.stop(task_id, "graceful")

    adapters.dispatch_stop.assert_not_called()


def test_stop_rejects_stale_transition_before_side_effects() -> None:
    from apps.trading.tasks.service import TaskConflictError

    task_id = uuid4()
    task = MagicMock(
        pk=task_id,
        status=TaskStatus.RUNNING,
        execution_id=uuid4(),
        celery_task_id=uuid4(),
    )
    service = MagicMock()
    service._get_task_and_type.return_value = (task, "trading")
    service.writer.persist_state_if_current.side_effect = TaskConflictError("superseded")
    commands, adapters = _make_commands(service)

    with pytest.raises(TaskConflictError, match="superseded"):
        commands.stop(task_id, "graceful")

    adapters.signal_stop.assert_not_called()
    adapters.dispatch_stop.assert_not_called()
    adapters.revoke_execution.assert_not_called()


def test_pause_rejects_stale_transition_before_signal() -> None:
    from apps.trading.tasks.service import TaskConflictError

    task_id = uuid4()
    task = MagicMock(
        pk=task_id,
        status=TaskStatus.RUNNING,
        execution_id=uuid4(),
        celery_task_id=uuid4(),
    )
    service = MagicMock()
    service._get_task_and_type.return_value = (task, "backtest")
    service.writer.persist_state_if_current.side_effect = TaskConflictError("superseded")
    commands, adapters = _make_commands(service)

    with pytest.raises(TaskConflictError, match="superseded"):
        commands.pause(task_id)

    adapters.signal_pause.assert_not_called()


def test_cancel_rejects_stale_transition_before_revoke() -> None:
    from apps.trading.tasks.service import TaskConflictError

    task_id = uuid4()
    task = MagicMock(
        pk=task_id,
        status=TaskStatus.RUNNING,
        execution_id=uuid4(),
        celery_task_id=uuid4(),
    )
    service = MagicMock()
    service._get_task_and_type.return_value = (task, "backtest")
    service.get_celery_result = MagicMock()
    service.writer.persist_terminal_state_if_current.side_effect = TaskConflictError("superseded")
    commands, _ = _make_commands(service)

    with pytest.raises(TaskConflictError, match="superseded"):
        commands.cancel(task_id)

    service.get_celery_result.assert_not_called()


@pytest.mark.django_db
def test_resume_emits_audit_log_payload() -> None:
    task_id = uuid4()
    execution_id = uuid4()
    old_celery_task_id = uuid4()
    task = MagicMock(
        pk=task_id,
        status=TaskStatus.STOPPED,
        execution_id=execution_id,
        celery_task_id=old_celery_task_id,
    )
    task.save = MagicMock()
    task_model = MagicMock()
    task_model.objects.select_for_update.return_value.get.return_value = task
    service = MagicMock()
    service._get_task_and_type.return_value = (task, "backtest")
    service._get_task_model.return_value = task_model
    service.get_celery_result.return_value = None
    service._dispatch_task = MagicMock()

    commands, _ = _make_commands(service)

    commands.resume(task_id)

    audit_calls = [
        c
        for c in commands.logger.info.call_args_list
        if c.args and isinstance(c.args[0], str) and c.args[0].startswith("[LIFECYCLE:AUDIT]")
    ]
    assert audit_calls
    payload = audit_calls[-1].args[1]
    assert payload["from_status"] == TaskStatus.STOPPED.value
    assert payload["to_status"] == TaskStatus.STARTING.value


@pytest.mark.django_db
def test_resume_allows_stopped_backtest_and_rotates_only_celery_task_id() -> None:
    task_id = uuid4()
    execution_id = uuid4()
    old_celery_task_id = uuid4()
    task = MagicMock(
        pk=task_id,
        status=TaskStatus.STOPPED,
        execution_id=execution_id,
        celery_task_id=old_celery_task_id,
    )
    task.save = MagicMock()
    task_model = MagicMock()
    task_model.objects.select_for_update.return_value.get.return_value = task
    service = MagicMock()
    service._get_task_and_type.return_value = (task, "backtest")
    service._get_task_model.return_value = task_model
    service.get_celery_result.return_value = None
    service._dispatch_task = MagicMock()

    commands, adapters = _make_commands(service)

    result = commands.resume(task_id)

    assert result is task
    assert task.status == TaskStatus.STARTING
    assert task.execution_id == execution_id
    assert task.celery_task_id != old_celery_task_id
    save_fields = task.save.call_args.kwargs["update_fields"]
    assert "error_message" in save_fields
    assert "error_traceback" in save_fields
    assert "completed_at" in save_fields
    adapters.revoke_execution.assert_called_once_with(old_celery_task_id)
    service._dispatch_task.assert_called_once_with(task, "backtest")
    event = commands.events.publish_spec.call_args.kwargs["event"]
    assert event.kind == TaskLifecycleKind.RESUME_REQUESTED
    assert event.description == f"Task resume requested (from {TaskStatus.STOPPED.value})"


@patch("apps.market.tasks.ensure_tick_pubsub_running.apply_async")
@pytest.mark.django_db
def test_start_trading_task_kicks_market_supervisor(mock_apply_async, settings) -> None:
    settings.CELERY_TASK_ALWAYS_EAGER = False
    task = type("TradingTaskStub", (), {})()
    task.pk = uuid4()
    task.status = TaskStatus.CREATED
    task.execution_id = uuid4()
    task.instrument = "USD_JPY"
    service = MagicMock()
    service._dispatch_task = MagicMock()
    commands, _ = _make_commands(service)
    commands._prepare_start = MagicMock(return_value=task)
    commands._log_worker_state = MagicMock()

    result = commands.start(task)

    assert result is task
    mock_apply_async.assert_called_once_with(countdown=0, queue="system")


@patch("apps.market.tasks.ensure_tick_pubsub_running.apply_async")
@pytest.mark.django_db
def test_start_trading_task_skips_market_supervisor_in_eager_mode(
    mock_apply_async, settings
) -> None:
    settings.CELERY_TASK_ALWAYS_EAGER = True
    task = type("TradingTaskStub", (), {})()
    task.pk = uuid4()
    task.status = TaskStatus.CREATED
    task.execution_id = uuid4()
    task.instrument = "USD_JPY"
    service = MagicMock()
    service._dispatch_task = MagicMock()
    commands, _ = _make_commands(service)
    commands._prepare_start = MagicMock(return_value=task)
    commands._log_worker_state = MagicMock()

    result = commands.start(task)

    assert result is task
    mock_apply_async.assert_not_called()
