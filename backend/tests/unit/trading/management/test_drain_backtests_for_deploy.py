"""Unit tests for the drain_backtests_for_deploy management command."""

from __future__ import annotations

from io import StringIO
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.trading.management.commands.drain_backtests_for_deploy import Command


def _make_task(*, status: str = "running", in_memory_mode: bool = False) -> MagicMock:
    task = MagicMock()
    task.pk = uuid4()
    task.name = "Backtest task"
    task.instrument = "USD_JPY"
    task.status = status
    task.in_memory_mode = in_memory_mode
    task.config.strategy_type = "snowball"
    return task


@patch("apps.trading.management.commands.drain_backtests_for_deploy.TaskService")
@patch("apps.trading.management.commands.drain_backtests_for_deploy.BacktestTask")
@patch.object(Command, "_get_remaining_tasks", return_value=[])
def test_drain_backtests_for_deploy_pauses_and_waits(
    _mock_remaining,
    mock_task_model,
    mock_service_cls,
):
    task = _make_task()
    mock_qs = mock_task_model.objects.select_related.return_value.filter.return_value
    mock_qs.order_by.return_value = [task]

    out = StringIO()
    call_command("drain_backtests_for_deploy", stdout=out)

    mock_service_cls.return_value.pause_task.assert_called_once_with(task.pk)
    output = out.getvalue()
    assert "Draining 1 active backtest task" in output
    assert "mode=pause" in output
    assert "All active backtest tasks drained." in output


@patch("apps.trading.management.commands.drain_backtests_for_deploy.TaskService")
@patch("apps.trading.management.commands.drain_backtests_for_deploy.BacktestTask")
@patch.object(Command, "_get_remaining_tasks", return_value=[])
def test_drain_backtests_for_deploy_emits_drained_task_ids(
    _mock_remaining,
    mock_task_model,
    mock_service_cls,
):
    task = _make_task()
    mock_qs = mock_task_model.objects.select_related.return_value.filter.return_value
    mock_qs.order_by.return_value = [task]

    out = StringIO()
    call_command("drain_backtests_for_deploy", emit_task_ids=True, stdout=out)

    mock_service_cls.return_value.pause_task.assert_called_once_with(task.pk)
    assert f"DRAINED_BACKTEST_TASK_IDS={task.pk}" in out.getvalue()
    assert "RESTART_BACKTEST_TASK_IDS=" in out.getvalue()


@patch("apps.trading.management.commands.drain_backtests_for_deploy.TaskService")
@patch("apps.trading.management.commands.drain_backtests_for_deploy.BacktestTask")
@patch.object(Command, "_get_remaining_tasks", return_value=[])
def test_drain_backtests_for_deploy_stops_in_memory_backtests_for_restart(
    _mock_remaining,
    mock_task_model,
    mock_service_cls,
):
    task = _make_task(in_memory_mode=True)
    mock_qs = mock_task_model.objects.select_related.return_value.filter.return_value
    mock_qs.order_by.return_value = [task]

    out = StringIO()
    call_command("drain_backtests_for_deploy", emit_task_ids=True, stdout=out)

    mock_service_cls.return_value.stop_task.assert_called_once_with(task.pk, mode="graceful")
    mock_service_cls.return_value.pause_task.assert_not_called()
    output = out.getvalue()
    assert "DRAINED_BACKTEST_TASK_IDS=" in output
    assert f"RESTART_BACKTEST_TASK_IDS={task.pk}" in output
    assert "in_memory=True" in output


@patch("apps.trading.management.commands.drain_backtests_for_deploy.TaskService")
@patch("apps.trading.management.commands.drain_backtests_for_deploy.BacktestTask")
@patch.object(Command, "_get_remaining_tasks", return_value=[])
def test_drain_backtests_for_deploy_can_use_stop_mode(
    _mock_remaining,
    mock_task_model,
    mock_service_cls,
):
    task = _make_task()
    mock_qs = mock_task_model.objects.select_related.return_value.filter.return_value
    mock_qs.order_by.return_value = [task]

    out = StringIO()
    call_command("drain_backtests_for_deploy", mode="graceful", stdout=out)

    mock_service_cls.return_value.stop_task.assert_called_once_with(task.pk, mode="graceful")
    mock_service_cls.return_value.pause_task.assert_not_called()


@patch("apps.trading.management.commands.drain_backtests_for_deploy.TaskService")
@patch("apps.trading.management.commands.drain_backtests_for_deploy.BacktestTask")
def test_drain_backtests_for_deploy_emits_empty_ids_when_no_tasks(
    mock_task_model, _mock_service_cls
):
    mock_qs = mock_task_model.objects.select_related.return_value.filter.return_value
    mock_qs.order_by.return_value = []

    out = StringIO()
    call_command("drain_backtests_for_deploy", emit_task_ids=True, stdout=out)

    assert "No active backtest tasks to drain." in out.getvalue()
    assert "DRAINED_BACKTEST_TASK_IDS=" in out.getvalue()
    assert "RESTART_BACKTEST_TASK_IDS=" in out.getvalue()


@patch("apps.trading.management.commands.drain_backtests_for_deploy.time.sleep", return_value=None)
@patch("apps.trading.management.commands.drain_backtests_for_deploy.TaskService")
@patch("apps.trading.management.commands.drain_backtests_for_deploy.BacktestTask")
@patch.object(Command, "_get_remaining_tasks")
def test_drain_backtests_for_deploy_raises_on_timeout(
    mock_remaining,
    mock_task_model,
    _mock_service_cls,
    _mock_sleep,
):
    task = _make_task(status="stopping")
    mock_qs = mock_task_model.objects.select_related.return_value.filter.return_value
    mock_qs.order_by.return_value = [task]
    mock_remaining.return_value = [task]

    with pytest.raises(CommandError, match="Timed out draining active backtest tasks"):
        call_command("drain_backtests_for_deploy", timeout=1, poll_interval=0.1)


@patch("apps.trading.management.commands.drain_backtests_for_deploy.TaskService")
@patch("apps.trading.management.commands.drain_backtests_for_deploy.BacktestTask")
@patch.object(Command, "_get_remaining_tasks", return_value=[])
def test_drain_backtests_for_deploy_only_resumes_starting_or_running_tasks(
    _mock_remaining,
    mock_task_model,
    mock_service_cls,
):
    running_task = _make_task(status="running")
    stopping_task = _make_task(status="stopping")
    mock_qs = mock_task_model.objects.select_related.return_value.filter.return_value
    mock_qs.order_by.return_value = [running_task, stopping_task]

    out = StringIO()
    call_command("drain_backtests_for_deploy", emit_task_ids=True, stdout=out)

    mock_service_cls.return_value.pause_task.assert_called_once_with(running_task.pk)
    assert f"DRAINED_BACKTEST_TASK_IDS={running_task.pk}" in out.getvalue()
    assert str(stopping_task.pk) not in out.getvalue().split("DRAINED_BACKTEST_TASK_IDS=")[-1]


@patch("apps.trading.management.commands.drain_backtests_for_deploy.TaskService")
@patch("apps.trading.management.commands.drain_backtests_for_deploy.BacktestTask")
@patch.object(Command, "_get_remaining_tasks", return_value=[])
def test_drain_backtests_for_deploy_does_not_restart_stopping_in_memory_tasks(
    _mock_remaining,
    mock_task_model,
    mock_service_cls,
):
    task = _make_task(status="stopping", in_memory_mode=True)
    mock_qs = mock_task_model.objects.select_related.return_value.filter.return_value
    mock_qs.order_by.return_value = [task]

    out = StringIO()
    call_command("drain_backtests_for_deploy", emit_task_ids=True, stdout=out)

    mock_service_cls.return_value.stop_task.assert_not_called()
    mock_service_cls.return_value.pause_task.assert_not_called()
    assert "RESTART_BACKTEST_TASK_IDS=" in out.getvalue()
    assert str(task.pk) not in out.getvalue().split("RESTART_BACKTEST_TASK_IDS=")[-1]
