"""Unit tests for order service module."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from apps.trading.enums import TaskType
from apps.trading.order import OrderService, OrderServiceError


class TestOrderServiceError:
    """Tests for OrderServiceError exception."""

    def test_is_exception(self):
        assert issubclass(OrderServiceError, Exception)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(OrderServiceError, match="test error"):
            raise OrderServiceError("test error")

    def test_stores_message(self):
        error = OrderServiceError("something went wrong")
        assert str(error) == "something went wrong"


class TestOrderServiceInit:
    """Tests for OrderService.__init__."""

    @patch("apps.trading.order.OandaService")
    def test_init_with_account(self, mock_oanda_svc):
        account = MagicMock()
        account.account_id = "001-001-123"
        task = MagicMock()
        task.id = uuid4()
        task.__class__.__name__ = "TradingTask"

        service = OrderService(account=account, task=task, dry_run=False)

        assert service.account is account
        assert service.task is task
        assert service.dry_run is False
        assert service.task_type == TaskType.TRADING
        mock_oanda_svc.assert_called_once()
        assert mock_oanda_svc.call_args.kwargs["account"] is account
        assert mock_oanda_svc.call_args.kwargs["dry_run"] is False
        assert mock_oanda_svc.call_args.kwargs["retry_policy"] is not None

    @patch("apps.trading.order.OandaService")
    def test_init_dry_run(self, mock_oanda_svc):
        task = MagicMock()
        task.id = uuid4()
        task.__class__.__name__ = "BacktestTask"
        task.execution_id = uuid4()

        service = OrderService(account=None, task=task, dry_run=True)

        assert service.account is None
        assert service.dry_run is True
        assert service.task_type == TaskType.BACKTEST
        mock_oanda_svc.assert_called_once()
        assert mock_oanda_svc.call_args.kwargs["account"] is None
        assert mock_oanda_svc.call_args.kwargs["dry_run"] is True
        assert mock_oanda_svc.call_args.kwargs["retry_policy"] is not None

    @patch("apps.trading.order.OandaService")
    def test_task_type_detection_backtest(self, mock_oanda_svc):
        task = MagicMock()
        task.id = uuid4()
        task.__class__.__name__ = "BacktestTask"

        service = OrderService(account=None, task=task)

        assert service.task_type == TaskType.BACKTEST

    @patch("apps.trading.order.OandaService")
    def test_task_type_detection_trading(self, mock_oanda_svc):
        account = MagicMock()
        account.account_id = "001-001-123"
        task = MagicMock()
        task.id = uuid4()
        task.__class__.__name__ = "TradingTask"

        service = OrderService(account=account, task=task)

        assert service.task_type == TaskType.TRADING

    @patch("apps.trading.order.OandaService")
    def test_task_type_defaults_to_trading(self, mock_oanda_svc):
        task = MagicMock()
        task.id = uuid4()
        task.__class__.__name__ = "SomeOtherTask"

        service = OrderService(account=None, task=task)

        assert service.task_type == TaskType.TRADING


class TestGetOpenPositions:
    """Tests for OrderService.get_open_positions."""

    @patch("apps.trading.order.OandaService")
    @patch("apps.trading.order.Position")
    def test_get_open_positions_no_filter(self, mock_position, mock_oanda_svc):
        task = MagicMock()
        task.id = uuid4()
        task.__class__.__name__ = "BacktestTask"
        task.execution_id = uuid4()

        service = OrderService(account=None, task=task, dry_run=True)

        mock_qs = MagicMock()
        mock_position.objects.filter.return_value = mock_qs
        mock_qs.order_by.return_value = [MagicMock(), MagicMock()]

        result = service.get_open_positions()

        mock_position.objects.filter.assert_called_once_with(
            task_type=TaskType.BACKTEST,
            task_id=task.id,
            execution_id=task.execution_id,
            is_open=True,
        )
        assert len(result) == 2

    @patch("apps.trading.order.OandaService")
    @patch("apps.trading.order.Position")
    def test_get_open_positions_with_instrument_filter(self, mock_position, mock_oanda_svc):
        task = MagicMock()
        task.id = uuid4()
        task.__class__.__name__ = "BacktestTask"
        task.execution_id = uuid4()

        service = OrderService(account=None, task=task, dry_run=True)

        mock_qs = MagicMock()
        mock_position.objects.filter.return_value = mock_qs
        mock_filtered_qs = MagicMock()
        mock_qs.filter.return_value = mock_filtered_qs
        mock_filtered_qs.order_by.return_value = [MagicMock()]

        result = service.get_open_positions(instrument="EUR_USD")

        mock_qs.filter.assert_called_once_with(instrument="EUR_USD")
        assert len(result) == 1


class TestGetOrderHistory:
    """Tests for OrderService.get_order_history."""

    @patch("apps.trading.order.OandaService")
    @patch("apps.trading.order.Order")
    def test_get_order_history_no_filter(self, mock_order, mock_oanda_svc):
        task = MagicMock()
        task.id = uuid4()
        task.__class__.__name__ = "TradingTask"
        task.execution_id = uuid4()

        account = MagicMock()
        account.account_id = "001-001-123"

        service = OrderService(account=account, task=task, dry_run=False)

        mock_qs = MagicMock()
        mock_order.objects.filter.return_value = mock_qs
        mock_ordered_qs = MagicMock()
        mock_qs.order_by.return_value = mock_ordered_qs
        mock_ordered_qs.__getitem__ = MagicMock(return_value=[MagicMock()])

        service.get_order_history()

        mock_order.objects.filter.assert_called_once_with(
            task_type=TaskType.TRADING,
            task_id=task.id,
            execution_id=task.execution_id,
        )

    @patch("apps.trading.order.OandaService")
    @patch("apps.trading.order.Order")
    def test_get_order_history_with_instrument_filter(self, mock_order, mock_oanda_svc):
        task = MagicMock()
        task.id = uuid4()
        task.__class__.__name__ = "TradingTask"

        account = MagicMock()
        account.account_id = "001-001-123"

        service = OrderService(account=account, task=task, dry_run=False)

        mock_qs = MagicMock()
        mock_order.objects.filter.return_value = mock_qs
        mock_filtered_qs = MagicMock()
        mock_qs.filter.return_value = mock_filtered_qs
        mock_ordered_qs = MagicMock()
        mock_filtered_qs.order_by.return_value = mock_ordered_qs
        mock_ordered_qs.__getitem__ = MagicMock(return_value=[MagicMock()])

        service.get_order_history(instrument="EUR_USD", limit=50)

        mock_qs.filter.assert_called_once_with(instrument="EUR_USD")

    @patch("apps.trading.order.OandaService")
    @patch("apps.trading.order.Order")
    def test_get_order_history_custom_limit(self, mock_order, mock_oanda_svc):
        task = MagicMock()
        task.id = uuid4()
        task.__class__.__name__ = "TradingTask"

        account = MagicMock()
        account.account_id = "001-001-123"

        service = OrderService(account=account, task=task, dry_run=False)

        mock_qs = MagicMock()
        mock_order.objects.filter.return_value = mock_qs
        mock_ordered_qs = MagicMock()
        mock_qs.order_by.return_value = mock_ordered_qs
        mock_ordered_qs.__getitem__ = MagicMock(return_value=[])

        service.get_order_history(limit=25)

        mock_ordered_qs.__getitem__.assert_called_once_with(slice(None, 25))


class TestOrderExecutionTime:
    """Tests for persisted order execution timestamps."""

    @patch("apps.trading.order.OandaService")
    def test_live_order_uses_broker_fill_time_over_tick_timestamp(self, mock_oanda_svc):
        account = MagicMock()
        account.account_id = "001-001-123"
        task = MagicMock()
        task.id = uuid4()
        task.execution_id = uuid4()
        task.__class__.__name__ = "TradingTask"
        service = OrderService(account=account, task=task, dry_run=False)

        tick_timestamp = datetime(2026, 5, 6, 4, 43, 40, tzinfo=UTC)
        broker_fill_time = datetime(2026, 5, 6, 4, 57, 38, tzinfo=UTC)
        oanda_order = MagicMock(fill_time=broker_fill_time, create_time=None)

        assert (
            service._order_execution_time(
                oanda_order=oanda_order,
                tick_timestamp=tick_timestamp,
            )
            == broker_fill_time
        )

    @patch("apps.trading.order.OandaService")
    def test_dry_run_order_keeps_strategy_tick_timestamp(self, mock_oanda_svc):
        task = MagicMock()
        task.id = uuid4()
        task.execution_id = uuid4()
        task.__class__.__name__ = "BacktestTask"
        service = OrderService(account=None, task=task, dry_run=True)

        tick_timestamp = datetime(2026, 5, 6, 4, 43, 40, tzinfo=UTC)
        simulator_fill_time = datetime(2026, 5, 6, 4, 57, 38, tzinfo=UTC)
        oanda_order = MagicMock(fill_time=simulator_fill_time, create_time=None)

        assert (
            service._order_execution_time(
                oanda_order=oanda_order,
                tick_timestamp=tick_timestamp,
            )
            == tick_timestamp
        )

    @patch("apps.trading.order.monotonic", side_effect=[10.0, 10.1234567])
    def test_broker_response_seconds_quantizes_elapsed_time(self, _mock_monotonic):
        started_at = OrderService._broker_request_started_at(MagicMock(dry_run=False))

        assert OrderService._broker_response_seconds(started_at) == Decimal("0.123457")

    def test_broker_request_started_at_skips_dry_run(self):
        assert OrderService._broker_request_started_at(MagicMock(dry_run=True)) is None
