"""Unit tests for trading serializers events."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

from apps.trading.enums import EventType
from apps.trading.serializers.events import (
    OrderSerializer,
    PositionSerializer,
    TradeSerializer,
    TradingEventSerializer,
)


class TestTradingEventSerializer:
    """Test TradingEventSerializer."""

    def test_meta_fields_include_event_type(self):
        assert "event_type" in TradingEventSerializer.Meta.fields
        assert "event_type_display" in TradingEventSerializer.Meta.fields

    def test_get_event_type_display_valid(self):
        serializer = TradingEventSerializer()
        obj = MagicMock()
        obj.event_type = EventType.TICK_RECEIVED.value
        result = serializer.get_event_type_display(obj)
        assert result == "Tick Received"

    def test_get_event_type_display_invalid(self):
        serializer = TradingEventSerializer()
        obj = MagicMock()
        obj.event_type = "nonexistent_type"
        result = serializer.get_event_type_display(obj)
        assert result == "nonexistent_type"

    def test_get_event_scope_task(self):
        serializer = TradingEventSerializer()
        obj = MagicMock()
        obj.event_type = EventType.STATUS_CHANGED.value
        obj.details = {"kind": "task_stop_requested"}
        assert serializer.get_event_scope(obj) == "task"

    def test_get_event_scope_trading(self):
        serializer = TradingEventSerializer()
        obj = MagicMock()
        obj.event_type = EventType.OPEN_POSITION.value
        obj.details = {"event_type": "initial_entry", "strategy_event_type": "initial_entry"}
        assert serializer.get_event_scope(obj) == "trading"


class TestTradeSerializer:
    """Test TradeSerializer."""

    def test_fields_exist(self):
        serializer = TradeSerializer()
        assert "direction" in serializer.fields
        assert "units" in serializer.fields
        assert "instrument" in serializer.fields
        assert "price" in serializer.fields
        assert "oanda_trade_id" in serializer.fields
        assert "replayed_at" in serializer.fields
        assert "pnl" in serializer.fields
        assert "pnl_currency" in serializer.fields
        assert "pnl_money" in serializer.fields
        assert "pnl_display_money" in serializer.fields
        assert "display_conversion_context" in serializer.fields

    def test_serializes_trade_pnl_money_payloads(self):
        timestamp = datetime(2026, 1, 1, tzinfo=UTC)
        serializer = TradeSerializer(
            {
                "direction": "buy",
                "units": 1000,
                "instrument": "USD_JPY",
                "price": Decimal("150.100"),
                "price_currency": "JPY",
                "execution_method": EventType.TAKE_PROFIT.value,
                "timestamp": timestamp,
                "pnl": Decimal("100"),
                "pnl_currency": "JPY",
                "pnl_money": {"amount": "100", "currency": "JPY"},
                "pnl_display_money": {"amount": "0.666222518321119", "currency": "USD"},
                "display_conversion_context": {
                    "source_currency": "JPY",
                    "target_currency": "USD",
                    "rate": Decimal("0.00666222518321119"),
                    "rate_source": "instrument_mid",
                    "rate_as_of": timestamp,
                    "rate_path": ["USD/JPY", "inverse"],
                    "conversion_available": True,
                    "conversion_policy": "runtime_fx_rate",
                },
            }
        )

        data = serializer.data

        assert data["pnl_money"] == {"amount": "100.0000000000", "currency": "JPY"}
        assert data["pnl_display_money"]["currency"] == "USD"
        assert data["display_conversion_context"]["source_currency"] == "JPY"

    def test_get_execution_method_display_valid(self):
        serializer = TradeSerializer()
        obj = MagicMock()
        obj.execution_method = EventType.INITIAL_ENTRY.value
        result = serializer.get_execution_method_display(obj)
        assert result == "Initial Entry"

    def test_get_execution_method_display_empty(self):
        serializer = TradeSerializer()
        obj = MagicMock()
        obj.execution_method = None
        result = serializer.get_execution_method_display(obj)
        assert result == ""

    def test_get_execution_method_display_from_dict(self):
        serializer = TradeSerializer()
        obj = {"execution_method": EventType.TAKE_PROFIT.value}
        result = serializer.get_execution_method_display(obj)
        assert result == "Take Profit"


class TestPositionSerializer:
    """Test PositionSerializer."""

    def test_fields_exist(self):
        serializer = PositionSerializer()
        assert "id" in serializer.fields
        assert "instrument" in serializer.fields
        assert "direction" in serializer.fields
        assert "is_open" in serializer.fields
        assert "oanda_trade_id" in serializer.fields
        assert "replayed_at" in serializer.fields
        assert "realized_pnl_money" in serializer.fields
        assert "realized_pnl_display_money" in serializer.fields
        assert "realized_pnl_display_conversion_context" in serializer.fields
        assert "unrealized_pnl_money" in serializer.fields
        assert "unrealized_pnl_display_money" in serializer.fields
        assert "unrealized_pnl_display_conversion_context" in serializer.fields

    def test_serializes_position_pnl_money_payloads(self):
        timestamp = datetime(2026, 1, 1, tzinfo=UTC)
        serializer = PositionSerializer(
            {
                "id": "00000000-0000-4000-8000-000000000001",
                "instrument": "USD_JPY",
                "direction": "long",
                "units": 1000,
                "entry_price": Decimal("150.000"),
                "entry_time": timestamp,
                "exit_price": Decimal("150.100"),
                "exit_time": timestamp,
                "is_open": False,
                "unrealized_pnl": Decimal("0"),
                "unrealized_pnl_currency": "JPY",
                "realized_pnl": Decimal("100"),
                "realized_pnl_currency": "JPY",
                "realized_pnl_money": {"amount": "100", "currency": "JPY"},
                "realized_pnl_display_money": {
                    "amount": "0.666222518321119",
                    "currency": "USD",
                },
                "realized_pnl_display_conversion_context": {
                    "source_currency": "JPY",
                    "target_currency": "USD",
                    "rate": Decimal("0.00666222518321119"),
                    "rate_source": "instrument_mid",
                    "rate_as_of": timestamp,
                    "rate_path": ["USD/JPY", "inverse"],
                    "conversion_available": True,
                    "conversion_policy": "runtime_fx_rate",
                },
            }
        )

        data = serializer.data

        assert data["realized_pnl"] == "100.0000000000"
        assert data["realized_pnl_currency"] == "JPY"
        assert data["realized_pnl_money"] == {
            "amount": "100.0000000000",
            "currency": "JPY",
        }
        assert data["realized_pnl_display_money"]["currency"] == "USD"

    def test_get_trade_ids_with_prefetched(self):
        serializer = PositionSerializer(context={"include_trade_ids": True})
        obj = MagicMock()
        obj.prefetched_trade_ids = ["id1", "id2"]
        result = serializer.get_trade_ids(obj)
        assert result == ["id1", "id2"]

    def test_get_trade_ids_no_trades(self):
        serializer = PositionSerializer()
        obj = MagicMock(spec=[])  # No attributes
        result = serializer.get_trade_ids(obj)
        assert result == []


class TestOrderSerializer:
    """Test OrderSerializer."""

    def test_fields_exist(self):
        serializer = OrderSerializer()
        assert "id" in serializer.fields
        assert "instrument" in serializer.fields
        assert "status" in serializer.fields
        assert "is_dry_run" in serializer.fields
        assert "broker_order_id" in serializer.fields
        assert "oanda_trade_id" in serializer.fields
        assert "oanda_response_seconds" in serializer.fields
        assert "replayed_at" in serializer.fields
