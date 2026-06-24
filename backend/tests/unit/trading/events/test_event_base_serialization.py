"""Tests for apps.trading.events.base – to_dict / from_dict serialization."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from apps.trading.enums import EventType
from apps.trading.events.base import (
    AddLayerEvent,
    InitialEntryEvent,
    MarginProtectionEvent,
    OpenPositionEvent,
    RebuildPositionEvent,
    RemoveLayerEvent,
    RetracementEvent,
    StrategyEvent,
    TakeProfitEvent,
    VolatilityHedgeNeutralizeEvent,
    VolatilityLockEvent,
)

NOW = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# InitialEntryEvent
# ---------------------------------------------------------------------------


class TestInitialEntryEventSerialization:
    def test_to_dict_minimal(self):
        event = InitialEntryEvent(
            event_type=EventType.INITIAL_ENTRY,
            layer_number=1,
            direction="long",
            price=Decimal("1.1000"),
            units=1000,
        )
        d = event.to_dict()
        assert d["event_type"] == "initial_entry"
        assert d["layer_number"] == 1
        assert d["direction"] == "long"
        assert d["price"] == "1.1000"
        assert d["units"] == 1000
        assert d["retracement_count"] == 0
        assert "entry_time" not in d
        assert "entry_id" not in d

    def test_to_dict_full(self):
        event = InitialEntryEvent(
            event_type=EventType.INITIAL_ENTRY,
            timestamp=NOW,
            layer_number=2,
            direction="short",
            price=Decimal("150.25"),
            units=500,
            entry_time=NOW,
            retracement_count=3,
            entry_id=42,
        )
        d = event.to_dict()
        assert d["timestamp"] == NOW.isoformat()
        assert d["entry_time"] == NOW.isoformat()
        assert d["entry_id"] == 42
        assert d["retracement_count"] == 3

    def test_from_dict_minimal(self):
        d = {
            "event_type": "initial_entry",
            "layer_number": 1,
            "direction": "long",
            "price": "1.1000",
            "units": 1000,
        }
        event = InitialEntryEvent.from_dict(d)
        assert event.event_type == EventType.INITIAL_ENTRY
        assert event.layer_number == 1
        assert event.price == Decimal("1.1000")
        assert event.units == 1000
        assert event.timestamp is None

    def test_from_dict_full(self):
        d = {
            "event_type": "initial_entry",
            "timestamp": NOW.isoformat(),
            "layer_number": 2,
            "direction": "short",
            "price": "150.25",
            "units": 500,
            "entry_time": NOW.isoformat(),
            "retracement_count": 3,
            "entry_id": 42,
        }
        event = InitialEntryEvent.from_dict(d)
        assert event.timestamp is not None
        assert event.entry_time is not None
        assert event.entry_id == 42
        assert event.retracement_count == 3

    def test_roundtrip(self):
        original = InitialEntryEvent(
            event_type=EventType.INITIAL_ENTRY,
            timestamp=NOW,
            layer_number=1,
            direction="long",
            price=Decimal("1.1000"),
            units=1000,
            entry_time=NOW,
            retracement_count=2,
            entry_id=7,
        )
        restored = InitialEntryEvent.from_dict(original.to_dict())
        assert restored.layer_number == original.layer_number
        assert restored.price == original.price
        assert restored.units == original.units
        assert restored.entry_id == original.entry_id

    def test_from_dict_invalid_timestamp(self):
        d = {
            "event_type": "initial_entry",
            "timestamp": "not-a-date",
            "price": "1.0",
            "units": 1,
        }
        event = InitialEntryEvent.from_dict(d)
        assert event.timestamp is None

    def test_from_dict_datetime_object_timestamp(self):
        d = {
            "event_type": "initial_entry",
            "timestamp": NOW,
            "entry_time": NOW,
            "price": "1.0",
            "units": 1,
        }
        event = InitialEntryEvent.from_dict(d)
        assert event.timestamp == NOW
        assert event.entry_time == NOW


# ---------------------------------------------------------------------------
# OpenPositionEvent / RebuildPositionEvent
# ---------------------------------------------------------------------------


class TestOpenPositionEventSerialization:
    def test_roundtrip_preserves_planned_exit_bound(self):
        original = OpenPositionEvent(
            event_type=EventType.OPEN_POSITION,
            timestamp=NOW,
            layer_number=2,
            direction="long",
            price=Decimal("161.053"),
            planned_entry_price=Decimal("161.003"),
            units=1000,
            entry_id=9,
            planned_exit_price=Decimal("161.1598888889"),
            planned_exit_price_formula="min(161.003 + 20 * 0.01, 161.15989)",
            planned_exit_price_bound=Decimal("161.1598888889"),
            planned_exit_price_bound_mode="min",
        )

        restored = OpenPositionEvent.from_dict(original.to_dict())

        assert restored.planned_exit_price == Decimal("161.1598888889")
        assert restored.planned_exit_price_formula == "min(161.003 + 20 * 0.01, 161.15989)"
        assert restored.planned_exit_price_bound == Decimal("161.1598888889")
        assert restored.planned_exit_price_bound_mode == "min"


class TestRebuildPositionEventSerialization:
    def test_roundtrip_preserves_planned_exit_bound(self):
        original = RebuildPositionEvent(
            event_type=EventType.REBUILD_POSITION,
            timestamp=NOW,
            layer_number=2,
            direction="short",
            price=Decimal("147.207"),
            planned_entry_price=Decimal("147.257"),
            units=1000,
            entry_id=9,
            planned_exit_price=Decimal("147.08269"),
            planned_exit_price_formula="max(147.257 - 20 * 0.01, 147.08269)",
            planned_exit_price_bound=Decimal("147.08269"),
            planned_exit_price_bound_mode="max",
            original_position_id="original-position",
        )

        restored = RebuildPositionEvent.from_dict(original.to_dict())

        assert restored.planned_exit_price == Decimal("147.08269")
        assert restored.planned_exit_price_formula == "max(147.257 - 20 * 0.01, 147.08269)"
        assert restored.planned_exit_price_bound == Decimal("147.08269")
        assert restored.planned_exit_price_bound_mode == "max"
        assert restored.original_position_id == "original-position"


# ---------------------------------------------------------------------------
# RetracementEvent
# ---------------------------------------------------------------------------


class TestRetracementEventSerialization:
    def test_to_dict(self):
        event = RetracementEvent(
            event_type=EventType.RETRACEMENT,
            timestamp=NOW,
            layer_number=1,
            direction="long",
            price=Decimal("1.0950"),
            units=500,
            retracement_count=2,
            entry_id=10,
            entry_time=NOW,
        )
        d = event.to_dict()
        assert d["event_type"] == "retracement"
        assert d["retracement_count"] == 2
        assert d["entry_id"] == 10
        assert "entry_time" in d

    def test_from_dict(self):
        d = {
            "event_type": "retracement",
            "timestamp": NOW.isoformat(),
            "layer_number": 1,
            "direction": "long",
            "price": "1.0950",
            "units": 500,
            "retracement_count": 2,
            "entry_id": 10,
            "entry_time": NOW.isoformat(),
        }
        event = RetracementEvent.from_dict(d)
        assert event.event_type == EventType.RETRACEMENT
        assert event.retracement_count == 2
        assert event.entry_id == 10

    def test_roundtrip(self):
        original = RetracementEvent(
            event_type=EventType.RETRACEMENT,
            timestamp=NOW,
            layer_number=1,
            direction="short",
            price=Decimal("1.0950"),
            units=500,
            retracement_count=3,
        )
        restored = RetracementEvent.from_dict(original.to_dict())
        assert restored.direction == "short"
        assert restored.retracement_count == 3

    def test_from_dict_no_entry_id(self):
        d = {"event_type": "retracement", "price": "1.0", "units": 1}
        event = RetracementEvent.from_dict(d)
        assert event.entry_id is None


# ---------------------------------------------------------------------------
# TakeProfitEvent
# ---------------------------------------------------------------------------


class TestTakeProfitEventSerialization:
    def test_to_dict(self):
        event = TakeProfitEvent(
            event_type=EventType.TAKE_PROFIT,
            timestamp=NOW,
            layer_number=1,
            direction="long",
            entry_price=Decimal("1.1000"),
            exit_price=Decimal("1.1050"),
            units=1000,
            pnl=Decimal("50.00"),
            pips=Decimal("5.0"),
            entry_time=NOW,
            exit_time=NOW,
            retracement_count=1,
            entry_id=5,
            position_id="pos-uuid-123",
        )
        d = event.to_dict()
        assert d["event_type"] == "take_profit"
        assert d["entry_price"] == "1.1000"
        assert d["exit_price"] == "1.1050"
        assert d["pnl"] == "50.00"
        assert d["pips"] == "5.0"
        assert d["entry_id"] == 5
        assert d["position_id"] == "pos-uuid-123"
        assert "entry_time" in d
        assert "exit_time" in d

    def test_from_dict(self):
        d = {
            "event_type": "take_profit",
            "timestamp": NOW.isoformat(),
            "layer_number": 1,
            "direction": "long",
            "entry_price": "1.1000",
            "exit_price": "1.1050",
            "units": 1000,
            "pnl": "50.00",
            "pips": "5.0",
            "entry_time": NOW.isoformat(),
            "exit_time": NOW.isoformat(),
            "retracement_count": 1,
            "entry_id": 5,
            "position_id": "pos-uuid-123",
        }
        event = TakeProfitEvent.from_dict(d)
        assert event.entry_price == Decimal("1.1000")
        assert event.exit_price == Decimal("1.1050")
        assert event.pnl == Decimal("50.00")
        assert event.position_id == "pos-uuid-123"

    def test_roundtrip(self):
        original = TakeProfitEvent(
            event_type=EventType.TAKE_PROFIT,
            timestamp=NOW,
            layer_number=1,
            direction="long",
            entry_price=Decimal("1.1000"),
            exit_price=Decimal("1.1050"),
            units=1000,
            pnl=Decimal("50.00"),
            pips=Decimal("5.0"),
        )
        restored = TakeProfitEvent.from_dict(original.to_dict())
        assert restored.pnl == original.pnl
        assert restored.pips == original.pips

    def test_from_dict_no_optional_fields(self):
        d = {"event_type": "take_profit"}
        event = TakeProfitEvent.from_dict(d)
        assert event.entry_id is None
        assert event.position_id is None
        assert event.entry_time is None
        assert event.exit_time is None


# ---------------------------------------------------------------------------
# AddLayerEvent
# ---------------------------------------------------------------------------


class TestAddLayerEventSerialization:
    def test_to_dict(self):
        event = AddLayerEvent(
            event_type=EventType.ADD_LAYER,
            timestamp=NOW,
            layer_number=2,
            add_time=NOW,
        )
        d = event.to_dict()
        assert d["event_type"] == "add_layer"
        assert d["layer_number"] == 2
        assert "add_time" in d

    def test_to_dict_no_add_time(self):
        event = AddLayerEvent(event_type=EventType.ADD_LAYER, layer_number=3)
        d = event.to_dict()
        assert "add_time" not in d

    def test_from_dict(self):
        d = {
            "event_type": "add_layer",
            "timestamp": NOW.isoformat(),
            "layer_number": 2,
            "add_time": NOW.isoformat(),
        }
        event = AddLayerEvent.from_dict(d)
        assert event.layer_number == 2
        assert event.add_time is not None

    def test_roundtrip(self):
        original = AddLayerEvent(
            event_type=EventType.ADD_LAYER,
            timestamp=NOW,
            layer_number=4,
            add_time=NOW,
        )
        restored = AddLayerEvent.from_dict(original.to_dict())
        assert restored.layer_number == 4


# ---------------------------------------------------------------------------
# RemoveLayerEvent
# ---------------------------------------------------------------------------


class TestRemoveLayerEventSerialization:
    def test_to_dict(self):
        event = RemoveLayerEvent(
            event_type=EventType.REMOVE_LAYER,
            timestamp=NOW,
            layer_number=3,
            add_time=NOW,
            remove_time=NOW,
        )
        d = event.to_dict()
        assert d["event_type"] == "remove_layer"
        assert d["layer_number"] == 3
        assert "add_time" in d
        assert "remove_time" in d

    def test_to_dict_no_times(self):
        event = RemoveLayerEvent(event_type=EventType.REMOVE_LAYER, layer_number=1)
        d = event.to_dict()
        assert "add_time" not in d
        assert "remove_time" not in d

    def test_from_dict(self):
        d = {
            "event_type": "remove_layer",
            "timestamp": NOW.isoformat(),
            "layer_number": 3,
            "add_time": NOW.isoformat(),
            "remove_time": NOW.isoformat(),
        }
        event = RemoveLayerEvent.from_dict(d)
        assert event.layer_number == 3
        assert event.add_time is not None
        assert event.remove_time is not None

    def test_roundtrip(self):
        original = RemoveLayerEvent(
            event_type=EventType.REMOVE_LAYER,
            timestamp=NOW,
            layer_number=2,
            add_time=NOW,
            remove_time=NOW,
        )
        restored = RemoveLayerEvent.from_dict(original.to_dict())
        assert restored.layer_number == 2

    def test_from_dict_invalid_times(self):
        d = {
            "event_type": "remove_layer",
            "timestamp": "bad",
            "add_time": "bad",
            "remove_time": "bad",
        }
        event = RemoveLayerEvent.from_dict(d)
        assert event.timestamp is None
        assert event.add_time is None
        assert event.remove_time is None


# ---------------------------------------------------------------------------
# VolatilityLockEvent
# ---------------------------------------------------------------------------


class TestVolatilityLockEventSerialization:
    def test_to_dict(self):
        event = VolatilityLockEvent(
            event_type=EventType.VOLATILITY_LOCK,
            timestamp=NOW,
            reason="ATR exceeded threshold",
            atr_value=Decimal("0.25"),
            threshold=Decimal("0.20"),
        )
        event.tick_bid = Decimal("1.1000")
        event.tick_ask = Decimal("1.1002")
        event.tick_mid = Decimal("1.1001")
        d = event.to_dict()
        assert d["event_type"] == "volatility_lock"
        assert d["reason"] == "ATR exceeded threshold"
        assert d["atr_value"] == "0.25"
        assert d["threshold"] == "0.20"
        assert d["tick_bid"] == "1.1000"
        assert d["tick_ask"] == "1.1002"
        assert d["tick_mid"] == "1.1001"

    def test_to_dict_no_optionals(self):
        event = VolatilityLockEvent(
            event_type=EventType.VOLATILITY_LOCK,
            reason="test",
        )
        d = event.to_dict()
        assert "atr_value" not in d
        assert "threshold" not in d

    def test_from_dict(self):
        d = {
            "event_type": "volatility_lock",
            "timestamp": NOW.isoformat(),
            "reason": "ATR exceeded",
            "atr_value": "0.25",
            "threshold": "0.20",
            "tick_bid": "1.1000",
            "tick_ask": "1.1002",
            "tick_mid": "1.1001",
        }
        event = VolatilityLockEvent.from_dict(d)
        assert event.atr_value == Decimal("0.25")
        assert event.threshold == Decimal("0.20")
        assert event.tick_bid == Decimal("1.1000")
        assert event.tick_ask == Decimal("1.1002")
        assert event.tick_mid == Decimal("1.1001")

    def test_roundtrip(self):
        original = VolatilityLockEvent(
            event_type=EventType.VOLATILITY_LOCK,
            timestamp=NOW,
            reason="high vol",
            atr_value=Decimal("0.30"),
            threshold=Decimal("0.25"),
        )
        restored = VolatilityLockEvent.from_dict(original.to_dict())
        assert restored.atr_value == original.atr_value
        assert restored.reason == original.reason

    def test_from_dict_no_atr(self):
        d = {"event_type": "volatility_lock", "reason": "test"}
        event = VolatilityLockEvent.from_dict(d)
        assert event.atr_value is None
        assert event.threshold is None


# ---------------------------------------------------------------------------
# VolatilityHedgeNeutralizeEvent
# ---------------------------------------------------------------------------


class TestVolatilityHedgeNeutralizeEventSerialization:
    def test_to_dict(self):
        instructions = [
            {"direction": "short", "units": 1000, "layer_index": 0, "source_entry_id": 1}
        ]
        event = VolatilityHedgeNeutralizeEvent(
            event_type=EventType.VOLATILITY_HEDGE_NEUTRALIZE,
            timestamp=NOW,
            reason="Neutralize positions",
            atr_value=Decimal("0.30"),
            threshold=Decimal("0.25"),
            hedge_instructions=instructions,
        )
        event.tick_bid = Decimal("1.1000")
        event.tick_ask = Decimal("1.1002")
        d = event.to_dict()
        assert d["event_type"] == "volatility_hedge_neutralize"
        assert d["reason"] == "Neutralize positions"
        assert d["atr_value"] == "0.30"
        assert d["hedge_instructions"] == instructions
        assert d["tick_bid"] == "1.1000"
        assert d["tick_ask"] == "1.1002"

    def test_from_dict(self):
        instructions = [
            {"direction": "short", "units": 1000, "layer_index": 0, "source_entry_id": 1}
        ]
        d = {
            "event_type": "volatility_hedge_neutralize",
            "timestamp": NOW.isoformat(),
            "reason": "Neutralize",
            "atr_value": "0.30",
            "threshold": "0.25",
            "hedge_instructions": instructions,
            "tick_bid": "1.1000",
            "tick_ask": "1.1002",
        }
        event = VolatilityHedgeNeutralizeEvent.from_dict(d)
        assert event.atr_value == Decimal("0.30")
        assert len(event.hedge_instructions) == 1
        assert event.hedge_instructions[0]["direction"] == "short"
        assert event.tick_bid == Decimal("1.1000")
        assert event.tick_ask == Decimal("1.1002")

    def test_roundtrip(self):
        instructions = [{"direction": "long", "units": 500, "layer_index": 1, "source_entry_id": 2}]
        original = VolatilityHedgeNeutralizeEvent(
            event_type=EventType.VOLATILITY_HEDGE_NEUTRALIZE,
            timestamp=NOW,
            reason="test",
            atr_value=Decimal("0.40"),
            threshold=Decimal("0.35"),
            hedge_instructions=instructions,
        )
        restored = VolatilityHedgeNeutralizeEvent.from_dict(original.to_dict())
        assert restored.hedge_instructions == instructions

    def test_from_dict_empty_instructions(self):
        d = {"event_type": "volatility_hedge_neutralize", "reason": "test"}
        event = VolatilityHedgeNeutralizeEvent.from_dict(d)
        assert event.hedge_instructions == []

    def test_from_dict_no_atr(self):
        d = {"event_type": "volatility_hedge_neutralize", "reason": "test"}
        event = VolatilityHedgeNeutralizeEvent.from_dict(d)
        assert event.atr_value is None
        assert event.threshold is None


# ---------------------------------------------------------------------------
# MarginProtectionEvent
# ---------------------------------------------------------------------------


class TestMarginProtectionEventSerialization:
    def test_to_dict(self):
        event = MarginProtectionEvent(
            event_type=EventType.MARGIN_PROTECTION,
            timestamp=NOW,
            reason="Margin threshold exceeded",
            current_margin=Decimal("0.05"),
            threshold=Decimal("0.10"),
            positions_closed=2,
            units_to_close=500,
        )
        event.tick_bid = Decimal("1.1000")
        event.tick_ask = Decimal("1.1002")
        d = event.to_dict()
        assert d["event_type"] == "margin_protection"
        assert d["reason"] == "Margin threshold exceeded"
        assert d["current_margin"] == "0.05"
        assert d["threshold"] == "0.10"
        assert d["positions_closed"] == 2
        assert d["units_to_close"] == 500
        assert d["tick_bid"] == "1.1000"
        assert d["tick_ask"] == "1.1002"

    def test_to_dict_no_optionals(self):
        event = MarginProtectionEvent(
            event_type=EventType.MARGIN_PROTECTION,
            reason="test",
        )
        d = event.to_dict()
        assert "current_margin" not in d
        assert "threshold" not in d
        assert "positions_closed" not in d
        assert "units_to_close" not in d

    def test_from_dict(self):
        d = {
            "event_type": "margin_protection",
            "timestamp": NOW.isoformat(),
            "reason": "Margin exceeded",
            "current_margin": "0.05",
            "threshold": "0.10",
            "positions_closed": 2,
            "units_to_close": 500,
            "tick_bid": "1.1000",
            "tick_ask": "1.1002",
        }
        event = MarginProtectionEvent.from_dict(d)
        assert event.current_margin == Decimal("0.05")
        assert event.threshold == Decimal("0.10")
        assert event.positions_closed == 2
        assert event.units_to_close == 500
        assert event.tick_bid == Decimal("1.1000")
        assert event.tick_ask == Decimal("1.1002")

    def test_roundtrip(self):
        original = MarginProtectionEvent(
            event_type=EventType.MARGIN_PROTECTION,
            timestamp=NOW,
            reason="margin low",
            current_margin=Decimal("0.03"),
            threshold=Decimal("0.10"),
            positions_closed=1,
            units_to_close=200,
        )
        restored = MarginProtectionEvent.from_dict(original.to_dict())
        assert restored.current_margin == original.current_margin
        assert restored.positions_closed == original.positions_closed
        assert restored.units_to_close == original.units_to_close

    def test_from_dict_no_optionals(self):
        d = {"event_type": "margin_protection", "reason": "test"}
        event = MarginProtectionEvent.from_dict(d)
        assert event.current_margin is None
        assert event.threshold is None
        assert event.positions_closed is None
        assert event.units_to_close is None

    def test_from_dict_invalid_timestamp(self):
        d = {"event_type": "margin_protection", "reason": "test", "timestamp": "bad"}
        event = MarginProtectionEvent.from_dict(d)
        assert event.timestamp is None


# ---------------------------------------------------------------------------
# StrategyEvent.from_dict factory dispatch
# ---------------------------------------------------------------------------


class TestStrategyEventFromDictDispatch:
    def test_initial_entry(self):
        d = {"event_type": "initial_entry", "price": "1.0", "units": 1}
        event = StrategyEvent.from_dict(d)
        assert isinstance(event, InitialEntryEvent)

    def test_retracement(self):
        d = {"event_type": "retracement", "price": "1.0", "units": 1}
        event = StrategyEvent.from_dict(d)
        assert isinstance(event, RetracementEvent)

    def test_take_profit(self):
        d = {"event_type": "take_profit"}
        event = StrategyEvent.from_dict(d)
        assert isinstance(event, TakeProfitEvent)

    def test_add_layer(self):
        d = {"event_type": "add_layer"}
        event = StrategyEvent.from_dict(d)
        assert isinstance(event, AddLayerEvent)

    def test_remove_layer(self):
        d = {"event_type": "remove_layer"}
        event = StrategyEvent.from_dict(d)
        assert isinstance(event, RemoveLayerEvent)

    def test_volatility_lock(self):
        d = {"event_type": "volatility_lock", "reason": "test"}
        event = StrategyEvent.from_dict(d)
        assert isinstance(event, VolatilityLockEvent)

    def test_volatility_hedge_neutralize(self):
        d = {"event_type": "volatility_hedge_neutralize", "reason": "test"}
        event = StrategyEvent.from_dict(d)
        assert isinstance(event, VolatilityHedgeNeutralizeEvent)

    def test_margin_protection(self):
        d = {"event_type": "margin_protection", "reason": "test"}
        event = StrategyEvent.from_dict(d)
        assert isinstance(event, MarginProtectionEvent)

    def test_unknown_event_type(self):
        d = {"event_type": "totally_unknown_type", "foo": "bar"}
        event = StrategyEvent.from_dict(d)
        # Should fall back to GenericStrategyEvent
        assert event is not None
