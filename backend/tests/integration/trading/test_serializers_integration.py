"""Integration tests for trading serializers with real DB.

Tests BacktestTaskSerializer, BacktestTaskCreateSerializer,
TradingTaskSerializer, TradingTaskCreateSerializer, and
serializer method fields (get_progress).
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from rest_framework.test import APIRequestFactory

from apps.market.models import TickData
from apps.trading.enums import TaskStatus, TaskType
from apps.trading.money import Money
from apps.trading.models import ExecutionState
from apps.trading.serializers.backtest import (
    BacktestTaskCreateSerializer,
    BacktestTaskSerializer,
)
from apps.trading.serializers.trading import (
    TradingTaskCreateSerializer,
    TradingTaskSerializer,
)
from tests.integration.factories import (
    BacktestTaskFactory,
    OandaAccountFactory,
    StrategyConfigurationFactory,
    TradingTaskFactory,
    UserFactory,
)

factory = APIRequestFactory()


def _fake_request(user):
    """Create a fake DRF request with an authenticated user."""
    request = factory.get("/fake/")
    request.user = user
    return request


@pytest.mark.django_db
class TestBacktestTaskSerializer:
    """Tests for BacktestTaskSerializer with real BacktestTask."""

    def test_serializes_all_fields(self):
        task = BacktestTaskFactory()
        serializer = BacktestTaskSerializer(task)
        data = serializer.data

        assert data["id"] == str(task.pk)
        assert data["user_id"] == task.user.pk
        assert data["config_id"] == str(task.config.pk)
        assert data["config_name"] == task.config.name
        assert data["strategy_type"] == task.config.strategy_type
        assert data["name"] == task.name
        assert data["instrument"] == task.instrument
        assert data["status"] == task.status
        assert data["max_tick_gap_hours"] == task.max_tick_gap_hours
        assert data["backtest_tick_batch_size"] == task.backtest_tick_batch_size
        assert data["spread_filter_enabled"] == task.spread_filter_enabled
        assert Decimal(data["max_spread_pips"]) == task.max_spread_pips
        assert data["oanda_candle_filter_enabled"] == task.oanda_candle_filter_enabled
        assert data["oanda_candle_filter_granularity"] == task.oanda_candle_filter_granularity
        assert (
            Decimal(data["oanda_candle_filter_tolerance_pips"])
            == task.oanda_candle_filter_tolerance_pips
        )
        assert "initial_balance" in data
        assert (
            data["initial_balance_money"]
            == Money.coerce(task.initial_balance, task.account_currency).as_dict()
        )
        assert (
            data["commission_per_trade_money"]
            == Money.coerce(task.commission_per_trade, task.account_currency).as_dict()
        )
        assert data["instrument_context"]["instrument"] == task.instrument
        assert data["instrument_context"]["effective_pip_size"] == "0.01"
        assert data["instrument_context"]["pip_size_matches_instrument"] is True
        assert data["money_context"]["account_currency"] == task.account_currency
        assert data["money_context"]["display_currency"] == task.effective_display_currency
        assert data["money_context"]["initial_balance_money"] == data["initial_balance_money"]
        assert data["money_context"]["display_uses_account_currency"] is True
        assert "start_time" in data
        assert "end_time" in data
        assert "created_at" in data
        # progress and current_tick are now served via /summary/ endpoint
        assert "progress" not in data
        assert "current_tick" not in data
        assert "account_currency" in data
        assert "display_currency" in data


@pytest.mark.django_db
class TestBacktestTaskCreateSerializer:
    """Tests for BacktestTaskCreateSerializer."""

    def test_create_with_valid_data(self):
        user = UserFactory()
        config = StrategyConfigurationFactory(user=user)
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=30)
        end = now - timedelta(days=1)

        # Create tick data so validation passes
        TickData.objects.create(
            instrument="USD_JPY",
            timestamp=start - timedelta(hours=1),
            bid=Decimal("150.000"),
            ask=Decimal("150.005"),
            mid=Decimal("150.0025"),
        )
        TickData.objects.create(
            instrument="USD_JPY",
            timestamp=end + timedelta(hours=1),
            bid=Decimal("151.000"),
            ask=Decimal("151.005"),
            mid=Decimal("151.0025"),
        )

        request = _fake_request(user)
        data = {
            "config": str(config.pk),
            "name": "Test Backtest",
            "data_source": "postgresql",
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "initial_balance": "50000.00",
            "instrument": "USD_JPY",
        }

        serializer = BacktestTaskCreateSerializer(data=data, context={"request": request})
        assert serializer.is_valid(), serializer.errors
        task = serializer.save()
        assert task.user == user
        assert task.config == config
        assert task.name == "Test Backtest"
        assert task.account_currency == "USD"
        assert task.display_currency == "USD"
        assert task.max_tick_gap_hours == 120
        assert task.backtest_tick_batch_size == 1000
        assert task.spread_filter_enabled is False
        assert task.oanda_candle_filter_enabled is False

    def test_create_persists_execution_replay_controls(self):
        user = UserFactory()
        config = StrategyConfigurationFactory(user=user)
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=30)
        end = now - timedelta(days=1)

        TickData.objects.create(
            instrument="USD_JPY",
            timestamp=start - timedelta(hours=1),
            bid=Decimal("150.000"),
            ask=Decimal("150.005"),
            mid=Decimal("150.0025"),
        )
        TickData.objects.create(
            instrument="USD_JPY",
            timestamp=end + timedelta(hours=1),
            bid=Decimal("151.000"),
            ask=Decimal("151.005"),
            mid=Decimal("151.0025"),
        )

        request = _fake_request(user)
        serializer = BacktestTaskCreateSerializer(
            data={
                "config": str(config.pk),
                "name": "Custom Replay Controls",
                "data_source": "postgresql",
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "initial_balance": "50000.00",
                "instrument": "USD_JPY",
                "max_tick_gap_hours": 168,
                "backtest_tick_batch_size": 5000,
            },
            context={"request": request},
        )

        assert serializer.is_valid(), serializer.errors
        task = serializer.save()

        assert task.max_tick_gap_hours == 168
        assert task.backtest_tick_batch_size == 5000

    def test_create_persists_tick_quality_filters(self):
        user = UserFactory()
        config = StrategyConfigurationFactory(user=user)
        account = OandaAccountFactory(user=user)
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=30)
        end = now - timedelta(days=1)

        TickData.objects.create(
            instrument="USD_JPY",
            timestamp=start - timedelta(hours=1),
            bid=Decimal("150.000"),
            ask=Decimal("150.005"),
            mid=Decimal("150.0025"),
        )
        TickData.objects.create(
            instrument="USD_JPY",
            timestamp=end + timedelta(hours=1),
            bid=Decimal("151.000"),
            ask=Decimal("151.005"),
            mid=Decimal("151.0025"),
        )

        request = _fake_request(user)
        serializer = BacktestTaskCreateSerializer(
            data={
                "config": str(config.pk),
                "name": "Quality Filter Backtest",
                "data_source": "postgresql",
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "initial_balance": "50000.00",
                "instrument": "USD_JPY",
                "spread_filter_enabled": True,
                "max_spread_pips": "12.5",
                "oanda_candle_filter_enabled": True,
                "oanda_candle_filter_account": account.pk,
                "oanda_candle_filter_granularity": "M1",
                "oanda_candle_filter_tolerance_pips": "5",
            },
            context={"request": request},
        )

        assert serializer.is_valid(), serializer.errors
        task = serializer.save()

        assert task.spread_filter_enabled is True
        assert task.max_spread_pips == Decimal("12.5")
        assert task.oanda_candle_filter_enabled is True
        assert task.oanda_candle_filter_account == account
        assert task.oanda_candle_filter_granularity == "M1"
        assert task.oanda_candle_filter_tolerance_pips == Decimal("5")

    def test_validation_error_wrong_user_config(self):
        user1 = UserFactory()
        user2 = UserFactory()
        config = StrategyConfigurationFactory(user=user2)
        now = datetime.now(timezone.utc)

        request = _fake_request(user1)
        data = {
            "config": str(config.pk),
            "name": "Bad Backtest",
            "start_time": (now - timedelta(days=30)).isoformat(),
            "end_time": (now - timedelta(days=1)).isoformat(),
            "initial_balance": "10000.00",
            "instrument": "USD_JPY",
        }

        serializer = BacktestTaskCreateSerializer(data=data, context={"request": request})
        assert not serializer.is_valid()
        assert "config" in serializer.errors

    def test_validation_error_negative_balance(self):
        user = UserFactory()
        config = StrategyConfigurationFactory(user=user)
        now = datetime.now(timezone.utc)

        request = _fake_request(user)
        data = {
            "config": str(config.pk),
            "name": "Negative Balance",
            "start_time": (now - timedelta(days=30)).isoformat(),
            "end_time": (now - timedelta(days=1)).isoformat(),
            "initial_balance": "-100.00",
            "instrument": "USD_JPY",
        }

        serializer = BacktestTaskCreateSerializer(data=data, context={"request": request})
        assert not serializer.is_valid()
        assert "initial_balance" in serializer.errors

    def test_update_rejects_aggregated_tick_granularity_before_first_run(self):
        user = UserFactory()
        now = datetime.now(timezone.utc)
        TickData.objects.create(
            instrument="USD_JPY",
            timestamp=now - timedelta(days=11),
            bid=Decimal("150.000"),
            ask=Decimal("150.005"),
            mid=Decimal("150.0025"),
        )
        TickData.objects.create(
            instrument="USD_JPY",
            timestamp=now - timedelta(hours=12),
            bid=Decimal("151.000"),
            ask=Decimal("151.005"),
            mid=Decimal("151.0025"),
        )
        task = BacktestTaskFactory(
            user=user,
            config=StrategyConfigurationFactory(user=user),
            status=TaskStatus.CREATED,
            execution_id=None,
            start_time=now - timedelta(days=10),
            end_time=now - timedelta(days=1),
            tick_granularity="tick",
            tick_window_value_mode="last",
        )

        request = _fake_request(user)
        serializer = BacktestTaskCreateSerializer(
            task,
            data={"tick_granularity": "1m"},
            context={"request": request},
            partial=True,
        )

        assert not serializer.is_valid()
        assert "tick_granularity" in serializer.errors

    def test_update_rejects_aggregated_tick_granularity_after_execution(self):
        user = UserFactory()
        now = datetime.now(timezone.utc)
        TickData.objects.create(
            instrument="USD_JPY",
            timestamp=now - timedelta(days=11),
            bid=Decimal("150.000"),
            ask=Decimal("150.005"),
            mid=Decimal("150.0025"),
        )
        TickData.objects.create(
            instrument="USD_JPY",
            timestamp=now - timedelta(hours=12),
            bid=Decimal("151.000"),
            ask=Decimal("151.005"),
            mid=Decimal("151.0025"),
        )
        task = BacktestTaskFactory(
            user=user,
            config=StrategyConfigurationFactory(user=user),
            status=TaskStatus.PAUSED,
            execution_id="a5dd2e8d-9dc2-49f2-944a-07083d2d47ab",
            start_time=now - timedelta(days=10),
            end_time=now - timedelta(days=1),
            tick_granularity="tick",
            tick_window_value_mode="last",
        )

        request = _fake_request(user)
        serializer = BacktestTaskCreateSerializer(
            task,
            data={"tick_granularity": "1m", "tick_window_value_mode": "average"},
            context={"request": request},
            partial=True,
        )

        assert not serializer.is_valid()
        assert "tick_granularity" in serializer.errors


@pytest.mark.django_db
class TestTradingTaskSerializer:
    """Tests for TradingTaskSerializer with real TradingTask."""

    def test_serializes_all_fields(self):
        task = TradingTaskFactory()
        serializer = TradingTaskSerializer(task)
        data = serializer.data

        assert data["id"] == str(task.pk)
        assert data["user_id"] == task.user.pk
        assert data["config_id"] == str(task.config.pk)
        assert data["config_name"] == task.config.name
        assert data["strategy_type"] == task.config.strategy_type
        assert data["account_id"] == task.oanda_account.pk
        assert data["account_name"] == task.oanda_account.account_id
        assert data["account_currency"] == task.oanda_account.currency
        assert data["display_currency"] == task.oanda_account.currency
        assert data["name"] == task.name
        assert data["status"] == task.status
        assert data["instrument_context"]["instrument"] == task.instrument
        assert data["instrument_context"]["effective_pip_size"] == "0.01"
        assert data["money_context"]["account_currency"] == task.oanda_account.currency
        assert data["money_context"]["display_currency"] == task.oanda_account.currency
        assert data["money_context"]["account_currency_source"] == "oanda_account"
        assert "has_strategy_state" in data
        assert "can_resume" in data
        # current_tick is now served via /summary/ endpoint only
        assert "current_tick" not in data

    def test_instrument_from_config(self):
        user = UserFactory()
        config = StrategyConfigurationFactory(
            user=user,
            parameters={
                "instrument": "EUR_USD",
                "base_lot_size": 1.0,
                "retracement_pips": 30.0,
                "take_profit_pips": 25.0,
                "max_layers": 3,
                "max_retracements_per_layer": 10,
            },
        )
        account = OandaAccountFactory(user=user)
        task = TradingTaskFactory(
            user=user,
            config=config,
            oanda_account=account,
            instrument="EUR_USD",
        )
        serializer = TradingTaskSerializer(task)
        assert serializer.data["instrument"] == "EUR_USD"


@pytest.mark.django_db
class TestTradingTaskCreateSerializer:
    """Tests for TradingTaskCreateSerializer."""

    def test_create_with_valid_data(self):
        user = UserFactory()
        config = StrategyConfigurationFactory(user=user)
        account = OandaAccountFactory(user=user)

        request = _fake_request(user)
        data = {
            "config_id": str(config.pk),
            "account_id": account.pk,
            "name": "Live Trading Task",
        }

        serializer = TradingTaskCreateSerializer(data=data, context={"request": request})
        assert serializer.is_valid(), serializer.errors
        task = serializer.save()
        assert task.user == user
        assert task.config == config
        assert task.oanda_account == account

    def test_validation_wrong_user_config(self):
        user1 = UserFactory()
        user2 = UserFactory()
        config = StrategyConfigurationFactory(user=user2)
        account = OandaAccountFactory(user=user1)

        request = _fake_request(user1)
        data = {
            "config_id": str(config.pk),
            "account_id": account.pk,
            "name": "Bad Task",
        }

        serializer = TradingTaskCreateSerializer(data=data, context={"request": request})
        assert not serializer.is_valid()
        assert "config_id" in serializer.errors

    def test_validation_inactive_account(self):
        user = UserFactory()
        config = StrategyConfigurationFactory(user=user)
        account = OandaAccountFactory(user=user, is_active=False)

        request = _fake_request(user)
        data = {
            "config_id": str(config.pk),
            "account_id": account.pk,
            "name": "Inactive Account Task",
        }

        serializer = TradingTaskCreateSerializer(data=data, context={"request": request})
        assert not serializer.is_valid()
        assert "account_id" in serializer.errors

    def test_validation_missing_required_fields(self):
        user = UserFactory()
        request = _fake_request(user)
        data = {"name": "No Config or Account"}

        serializer = TradingTaskCreateSerializer(data=data, context={"request": request})
        assert not serializer.is_valid()


@pytest.mark.django_db
class TestBacktestTaskSerializerProgress:
    """Tests for progress via summary service (moved from serializer)."""

    def test_progress_via_summary_service(self):
        from apps.trading.services.summary import compute_task_summary

        now = datetime.now(timezone.utc)
        start = now - timedelta(days=10)
        end = now - timedelta(days=1)
        midpoint = start + (end - start) / 2

        task = BacktestTaskFactory(
            status=TaskStatus.RUNNING,
            start_time=start,
            end_time=end,
        )
        from uuid import uuid4

        execution_id = uuid4()
        task.execution_id = execution_id
        task.save()

        ExecutionState.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=execution_id,
            strategy_state={},
            current_balance=Decimal("10000"),
            ticks_processed=500,
            last_tick_timestamp=midpoint,
        )

        result = compute_task_summary(
            task_type="backtest",
            task_id=str(task.pk),
            execution_id=str(execution_id),
        )
        # Midpoint should be ~50%
        assert 45 <= result.task.progress <= 55

    def test_progress_no_state(self):
        from uuid import uuid4

        from apps.trading.services.summary import compute_task_summary

        task = BacktestTaskFactory(status=TaskStatus.RUNNING)
        execution_id = uuid4()
        task.execution_id = execution_id
        task.save()

        result = compute_task_summary(
            task_type="backtest",
            task_id=str(task.pk),
            execution_id=str(execution_id),
        )
        assert result.task.progress == 0


@pytest.mark.django_db
class TestTradingTaskSummary:
    """Tests for trading-task summary fields."""

    def test_uses_oanda_account_currency_for_trading_summary(self):
        from uuid import uuid4

        from apps.trading.services.summary import compute_task_summary

        execution_id = uuid4()
        account = OandaAccountFactory(currency="JPY")
        task = TradingTaskFactory(
            oanda_account=account,
            instrument="USD_JPY",
            status=TaskStatus.RUNNING,
            execution_id=execution_id,
        )
        ExecutionState.objects.create(
            task_type=TaskType.TRADING,
            task_id=task.pk,
            execution_id=execution_id,
            strategy_state={
                "broker_reconciliation_status": "warning",
                "broker_reconciliation_warnings": ["broker drift warning"],
                "broker_reconciled_at": "2026-01-01T00:00:00+00:00",
            },
            current_balance=Decimal("3000000"),
            ticks_processed=42,
            last_tick_timestamp=datetime.now(timezone.utc),
            resume_cursor_timestamp=datetime.now(timezone.utc),
            last_tick_bid=Decimal("158.80"),
            last_tick_ask=Decimal("158.84"),
            last_tick_price=Decimal("158.82"),
        )

        result = compute_task_summary(
            task_type="trading",
            task_id=str(task.pk),
            execution_id=str(execution_id),
        )

        assert result.execution.account_currency == "JPY"
        assert result.execution.display_currency == "JPY"
        assert result.execution.current_balance_display_money == {
            "amount": "3000000",
            "currency": "JPY",
        }
        assert result.execution.recovery_status == "warning"
        assert result.execution.recovery_warnings == ["broker drift warning"]
        assert result.execution.resume_cursor_timestamp is not None
