"""Unit tests for trading Celery tasks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from apps.trading.enums import TaskStatus, TaskType


class _DoesNotExist(Exception):
    pass


class TestRunTradingTask:
    @patch("apps.trading.tasks.trading.TaskLoggingSession")
    @patch("apps.trading.tasks.trading.execute_trading")
    @patch("apps.trading.tasks.trading.TradingTask")
    def test_task_not_found_raises(self, mock_model, mock_exec, mock_logging):
        from apps.trading.tasks.trading import run_trading_task

        mock_model.DoesNotExist = _DoesNotExist
        mock_model.objects.get.side_effect = _DoesNotExist("not found")

        with pytest.raises(_DoesNotExist):
            run_trading_task.__wrapped__(uuid4())

    @patch("apps.trading.tasks.trading.TaskLoggingSession")
    @patch("apps.trading.tasks.trading.execute_trading")
    @patch("apps.trading.tasks.trading.TradingTask")
    def test_skips_if_not_starting(self, mock_model, mock_exec, mock_logging):
        from apps.trading.tasks.trading import run_trading_task

        task = MagicMock(pk=uuid4(), status=TaskStatus.COMPLETED, instrument="EUR_USD")
        mock_model.objects.get.return_value = task
        mock_model.DoesNotExist = _DoesNotExist

        run_trading_task.__wrapped__(task.pk)
        mock_exec.assert_not_called()

    @patch("apps.trading.tasks.trading.TaskLoggingSession")
    @patch("apps.trading.tasks.trading.execute_trading")
    @patch("apps.trading.tasks.trading.TradingTask")
    def test_skips_stale_redelivery_when_idempotency_key_mismatches(
        self, mock_model, mock_exec, mock_logging
    ):
        from apps.trading.tasks.trading import run_trading_task

        task = MagicMock(
            pk=uuid4(),
            status=TaskStatus.STARTING,
            instrument="EUR_USD",
            dispatch_idempotency_key=uuid4(),
        )
        mock_model.objects.get.return_value = task
        mock_model.DoesNotExist = _DoesNotExist

        run_trading_task.__wrapped__(task.pk, str(uuid4()))
        mock_exec.assert_not_called()

    @patch("apps.trading.tasks.trading.finalize_task_terminal_lifecycle")
    @patch("apps.trading.tasks.trading.publish_task_lifecycle_event")
    @patch("apps.trading.tasks.trading.TaskLoggingSession")
    @patch("apps.trading.tasks.trading.execute_trading")
    @patch("apps.trading.tasks.trading.TradingTask")
    def test_normal_flow(
        self,
        mock_model,
        mock_exec,
        mock_logging,
        mock_publish_event,
        mock_finalize_terminal,
    ):
        from apps.trading.tasks.trading import run_trading_task

        task_id = uuid4()
        task = MagicMock(
            pk=task_id,
            status=TaskStatus.STARTING,
            instrument="EUR_USD",
            celery_task_id="c-123",
            started_at=object(),
        )
        mock_model.objects.get.return_value = task
        mock_model.objects.filter.return_value.update.return_value = 1
        mock_model.DoesNotExist = _DoesNotExist

        count = [0]

        def refresh():
            count[0] += 1
            if count[0] >= 2:
                task.status = TaskStatus.RUNNING

        task.refresh_from_db = refresh
        mock_finalize_terminal.return_value = 1

        run_trading_task.__wrapped__(task_id)
        mock_exec.assert_called_once_with(task)
        mock_finalize_terminal.assert_called_once()

    @patch("apps.trading.tasks.trading.publish_task_lifecycle_event")
    @patch("apps.trading.tasks.trading.TaskLoggingSession")
    @patch("apps.trading.tasks.trading.execute_trading")
    @patch("apps.trading.tasks.trading.TradingTask")
    def test_exception_handling(self, mock_model, mock_exec, mock_logging, mock_publish_event):
        from apps.trading.tasks.trading import run_trading_task

        task = MagicMock(pk=uuid4(), status=TaskStatus.STARTING, instrument="EUR_USD")
        mock_model.objects.get.return_value = task
        mock_model.objects.filter.return_value.update.return_value = 1
        mock_model.DoesNotExist = _DoesNotExist
        mock_exec.side_effect = RuntimeError("boom")

        with patch("apps.trading.tasks.trading.handle_task_exception") as mock_handle:
            with pytest.raises(RuntimeError, match="boom"):
                run_trading_task.__wrapped__(task.pk)
            mock_handle.assert_called_once()


class TestExecuteTrading:
    @patch("apps.trading.tasks.trading.TradingExecutor")
    @patch("apps.trading.tasks.trading.LiveTickDataSource")
    @patch("apps.trading.tasks.trading.TradingEngine")
    @patch("apps.trading.tasks.trading.pip_size_for_instrument")
    def test_normal_flow(self, mock_pip, mock_engine, mock_source, mock_executor):
        from apps.trading.tasks.trading import execute_trading

        task = MagicMock(
            pk=uuid4(),
            instrument="EUR_USD",
            pip_size=None,
            config={},
            tick_granularity="1m",
        )
        task.oanda_account.account_id = "001-001-123"
        task.oanda_account.currency = "USD"
        mock_pip.return_value = 0.0001

        execute_trading(task)

        mock_engine.assert_called_once()
        mock_source.assert_called_once_with(
            channel="live:001-001-123:EUR_USD",
            instrument="EUR_USD",
            tick_granularity="1m",
        )
        mock_executor.return_value.execute.assert_called_once()

    @patch("apps.trading.tasks.trading.TradingExecutor")
    @patch("apps.trading.tasks.trading.LiveTickDataSource")
    @patch("apps.trading.tasks.trading.TradingEngine")
    @patch("apps.trading.tasks.trading.pip_size_for_instrument")
    def test_uses_existing_pip_size(self, mock_pip, mock_engine, mock_source, mock_executor):
        from apps.trading.tasks.trading import execute_trading

        task = MagicMock(pk=uuid4(), instrument="EUR_USD", pip_size=0.0001, config={})
        task.oanda_account.account_id = "001-001-123"
        task.oanda_account.currency = "USD"

        execute_trading(task)
        mock_pip.assert_not_called()
        task.save.assert_not_called()


class TestHandleExceptionTrading:
    def test_with_task_none(self):
        from apps.trading.tasks.task_runner import handle_task_exception

        handle_task_exception(
            task_id=uuid4(),
            task=None,
            error=RuntimeError("test"),
            task_type=TaskType.TRADING,
            task_label="Trading",
            component="test",
        )

    @patch("apps.trading.tasks.task_runner.finalize_task_terminal_lifecycle")
    def test_with_task_updates_status(self, mock_finalize_terminal):
        from apps.trading.tasks.task_runner import handle_task_exception

        task_id = uuid4()
        execution_id = uuid4()
        task = MagicMock(pk=task_id, execution_id=execution_id)
        mock_finalize_terminal.return_value = 1

        handle_task_exception(
            task_id=task_id,
            task=task,
            error=ValueError("bad"),
            task_type=TaskType.TRADING,
            task_label="Trading",
            component="test",
        )

        mock_finalize_terminal.assert_called_once()

    @patch("apps.trading.tasks.task_runner.finalize_task_terminal_lifecycle")
    def test_error_message_stored(self, mock_finalize_terminal):
        from apps.trading.tasks.task_runner import handle_task_exception

        task = MagicMock(pk=uuid4(), execution_id=uuid4())
        mock_finalize_terminal.return_value = 1

        handle_task_exception(
            task_id=task.pk,
            task=task,
            error=RuntimeError("specific error"),
            task_type=TaskType.TRADING,
            task_label="Trading",
            component="test",
        )

        mock_finalize_terminal.assert_called_once()


class TestStopTradingTask:
    @patch("apps.trading.tasks.trading.TradingTask")
    def test_task_not_found_raises(self, mock_model):
        from apps.trading.tasks.trading import stop_trading_task

        mock_model.DoesNotExist = _DoesNotExist
        mock_model.objects.get.side_effect = _DoesNotExist("not found")

        with pytest.raises(_DoesNotExist):
            stop_trading_task.__wrapped__(uuid4())

    @patch("celery.current_app")
    @patch("apps.trading.tasks.trading.finalize_task_terminal_lifecycle")
    @patch("apps.trading.tasks.trading.TradingTask")
    def test_stopping_state(
        self,
        mock_model,
        mock_finalize_terminal,
        mock_app,
    ):
        from apps.trading.tasks.trading import stop_trading_task

        task_id = uuid4()
        task = MagicMock(pk=task_id, status=TaskStatus.STOPPING, celery_task_id="c-123")
        mock_model.objects.get.return_value = task
        mock_model.DoesNotExist = _DoesNotExist
        mock_finalize_terminal.return_value = 1
        mock_finalize_terminal.side_effect = (
            lambda **kwargs: setattr(task, "status", TaskStatus.STOPPED) or 1
        )

        stop_trading_task.__wrapped__(task_id)

        assert task.status == TaskStatus.STOPPED
        mock_app.control.revoke.assert_not_called()
        mock_finalize_terminal.assert_called_once()

    @patch("apps.trading.tasks.trading.TradingTask")
    def test_already_stopped_noop(self, mock_model):
        from apps.trading.tasks.trading import stop_trading_task

        task = MagicMock(pk=uuid4(), status=TaskStatus.STOPPED)
        mock_model.objects.get.return_value = task
        mock_model.DoesNotExist = _DoesNotExist

        stop_trading_task.__wrapped__(task.pk)
        task.save.assert_not_called()

    @patch("apps.trading.tasks.trading._close_open_positions_for_task")
    @patch("celery.current_app")
    @patch("apps.trading.tasks.trading.finalize_task_terminal_lifecycle")
    @patch("apps.trading.tasks.trading.TradingTask")
    def test_stop_graceful_mode(
        self,
        mock_model,
        mock_finalize_terminal,
        mock_app,
        mock_close_positions,
    ):
        from apps.trading.tasks.trading import stop_trading_task

        task_id = uuid4()
        task = MagicMock(pk=task_id, status=TaskStatus.STOPPING, celery_task_id="c-789")
        mock_model.objects.get.return_value = task
        mock_model.DoesNotExist = _DoesNotExist
        mock_finalize_terminal.return_value = 1
        mock_finalize_terminal.side_effect = (
            lambda **kwargs: setattr(task, "status", TaskStatus.STOPPED) or 1
        )

        stop_trading_task.__wrapped__(task_id, "graceful")

        assert task.status == TaskStatus.STOPPED
        mock_app.control.revoke.assert_not_called()
        mock_close_positions.assert_not_called()
        mock_finalize_terminal.assert_called_once()

    @patch("apps.trading.tasks.trading._close_open_positions_for_task")
    @patch("celery.current_app")
    @patch("apps.trading.tasks.trading.finalize_task_terminal_lifecycle")
    @patch("apps.trading.tasks.trading.TradingTask")
    def test_stop_graceful_close_closes_positions(
        self,
        mock_model,
        mock_finalize_terminal,
        mock_app,
        mock_close_positions,
    ):
        from apps.trading.tasks.trading import stop_trading_task

        task_id = uuid4()
        task = MagicMock(pk=task_id, status=TaskStatus.STOPPING, celery_task_id="c-789")
        task.sell_on_stop = False
        mock_model.objects.get.return_value = task
        mock_model.DoesNotExist = _DoesNotExist
        mock_finalize_terminal.return_value = 1
        mock_finalize_terminal.side_effect = (
            lambda **kwargs: setattr(task, "status", TaskStatus.STOPPED) or 1
        )

        stop_trading_task.__wrapped__(task_id, "graceful_close")

        mock_app.control.revoke.assert_not_called()
        mock_close_positions.assert_called_once_with(task)
        mock_finalize_terminal.assert_called_once()

    @patch("celery.current_app")
    @patch("apps.trading.tasks.trading.finalize_task_terminal_lifecycle")
    @patch("apps.trading.tasks.trading.TradingTask")
    def test_stop_immediate_mode_revokes(
        self,
        mock_model,
        mock_finalize_terminal,
        mock_app,
    ):
        from apps.trading.tasks.trading import stop_trading_task

        task_id = uuid4()
        execution_id = uuid4()
        celery_task_id = uuid4()
        task = MagicMock(
            pk=task_id,
            status=TaskStatus.STOPPING,
            execution_id=execution_id,
            celery_task_id=celery_task_id,
        )
        mock_model.objects.get.return_value = task
        mock_model.DoesNotExist = _DoesNotExist
        mock_finalize_terminal.return_value = 1
        mock_finalize_terminal.side_effect = (
            lambda **kwargs: setattr(task, "status", TaskStatus.STOPPED) or 1
        )

        stop_trading_task.__wrapped__(task_id, "immediate")

        mock_app.control.revoke.assert_called_once_with(
            str(celery_task_id), terminate=True, signal="SIGKILL"
        )
        mock_finalize_terminal.assert_called_once()
