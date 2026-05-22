"""Unit tests for trading serializers trading."""

from unittest.mock import MagicMock, patch

import pytest
from rest_framework import serializers

from apps.trading.enums import TaskStatus, TradingMode

from apps.trading.serializers.trading import (
    TradingTaskCreateSerializer,
    TradingTaskListSerializer,
    TradingTaskSerializer,
)


class TestTradingTaskSerializer:
    """Test TradingTaskSerializer."""

    def test_meta_fields(self):
        fields = TradingTaskSerializer.Meta.fields
        assert "id" in fields
        assert "status" in fields
        assert "sell_on_stop" in fields
        assert "account_currency" in fields
        assert "display_currency" in fields
        assert "money_context" in fields
        assert "tick_granularity" in fields
        assert "has_strategy_state" in fields
        assert "can_resume" in fields
        assert "instrument_context" in fields

    def test_instrument_is_model_field(self):
        fields = TradingTaskSerializer().get_fields()
        assert fields["instrument"].read_only is True

    def test_get_has_strategy_state(self):
        serializer = TradingTaskSerializer()
        obj = MagicMock()
        obj.has_strategy_state.return_value = True
        assert serializer.get_has_strategy_state(obj) is True

    def test_get_can_resume(self):
        serializer = TradingTaskSerializer()
        obj = MagicMock()
        obj.can_resume.return_value = False
        assert serializer.get_can_resume(obj) is False


class TestTradingTaskListSerializer:
    """Test TradingTaskListSerializer."""

    def test_meta_fields(self):
        fields = TradingTaskListSerializer.Meta.fields
        assert "id" in fields
        assert "status" in fields
        assert "account_currency" in fields
        assert "display_currency" in fields
        assert "money_context" in fields
        assert "tick_granularity" in fields
        assert "instrument_context" in fields
        # List view should not have has_strategy_state
        assert "has_strategy_state" not in fields

    def test_instrument_is_model_field(self):
        fields = TradingTaskListSerializer().get_fields()
        assert fields["instrument"].read_only is True


class TestTradingTaskCreateSerializer:
    """Test TradingTaskCreateSerializer."""

    def test_meta_fields(self):
        fields = TradingTaskCreateSerializer.Meta.fields
        assert "config_id" in fields
        assert "account_id" in fields
        assert "name" in fields
        assert "tick_granularity" in fields

    @patch("apps.trading.serializers.trading.TradingTask.objects.create")
    def test_create_sets_trading_mode_from_hedging_flag(self, mock_create):
        request = MagicMock()
        request.user = MagicMock()
        serializer = TradingTaskCreateSerializer(context={"request": request})
        config = MagicMock()
        config.parameters = {}

        serializer.create(
            {
                "config": config,
                "oanda_account": MagicMock(),
                "name": "Task",
                "hedging_enabled": False,
            }
        )

        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["trading_mode"] == TradingMode.NETTING

    def test_update_validation_error_suppresses_exception_chain(self):
        serializer = TradingTaskCreateSerializer()
        task = MagicMock()
        task.status = TaskStatus.RUNNING

        with pytest.raises(serializers.ValidationError) as exc_info:
            serializer.update(task, {"name": "Updated"})

        assert exc_info.value.__cause__ is None
