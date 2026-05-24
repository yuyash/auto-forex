"""Unit tests for EventHandler class."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.trading.dataclasses import EventExecutionResult
from apps.trading.enums import EventType, TaskType
from apps.trading.events import (
    ClosePositionEvent,
    MarginProtectionEvent,
    OpenPositionEvent,
    VolatilityHedgeNeutralizeEvent,
    VolatilityLockEvent,
)
from apps.trading.events.handler import (
    ClosePositionResolutionError,
    CycleResolutionError,
    EventHandler,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_order_service(task_type=TaskType.TRADING):
    svc = MagicMock()
    svc.task = SimpleNamespace(id=uuid4(), execution_id=uuid4())
    svc.task_type = task_type
    svc.execution_id = svc.task.execution_id
    svc.dry_run = False
    return svc


def _make_position(units=1000, layer_index=1, is_open=True, direction="long"):
    return SimpleNamespace(
        id=uuid4(),
        is_open=is_open,
        units=units,
        layer_index=layer_index,
        retracement_count=0,
        direction=direction,
        instrument="EUR_USD",
        entry_price=Decimal("1.10000"),
        entry_time=None,
        exit_price=None,
        exit_time=None,
        planned_exit_price=None,
        planned_exit_price_formula=None,
        oanda_trade_id="oanda-123",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEventHandlerInit:
    """Tests for __init__."""

    def test_stores_order_service_and_instrument(self):
        svc = _make_order_service()
        handler = EventHandler(order_service=svc, instrument="EUR_USD")

        assert handler.order_service is svc
        assert handler.instrument == "EUR_USD"

    def test_position_map_starts_empty(self):
        handler = EventHandler(order_service=_make_order_service(), instrument="EUR_USD")

        assert handler.position_map == {}
        assert handler._position_cache == {}
        assert handler.layer_position_ids == {}

    def test_live_trade_timestamp_uses_order_fill_time(self):
        handler = EventHandler(order_service=_make_order_service(), instrument="EUR_USD")
        strategy_timestamp = datetime(2026, 5, 6, 4, 43, 40, tzinfo=UTC)
        broker_fill_time = datetime(2026, 5, 6, 4, 57, 38, tzinfo=UTC)
        order = MagicMock(filled_at=broker_fill_time)

        assert (
            handler._trade_execution_timestamp(
                fallback_timestamp=strategy_timestamp,
                order=order,
            )
            == broker_fill_time
        )

    def test_dry_run_trade_timestamp_keeps_strategy_timestamp(self):
        order_service = _make_order_service()
        order_service.dry_run = True
        handler = EventHandler(order_service=order_service, instrument="EUR_USD")
        strategy_timestamp = datetime(2026, 5, 6, 4, 43, 40, tzinfo=UTC)
        simulator_fill_time = datetime(2026, 5, 6, 4, 57, 38, tzinfo=UTC)
        order = MagicMock(filled_at=simulator_fill_time)

        assert (
            handler._trade_execution_timestamp(
                fallback_timestamp=strategy_timestamp,
                order=order,
            )
            == strategy_timestamp
        )


class TestHandleOpenPosition:
    """Tests for handle_open_position."""

    def test_opens_position_and_caches(self):
        svc = _make_order_service()
        position = _make_position()
        order = MagicMock()
        svc.open_position.return_value = (position, order)

        handler = EventHandler(order_service=svc, instrument="EUR_USD")
        handler._record_trade = MagicMock()

        event = OpenPositionEvent(
            event_type=EventType.OPEN_POSITION,
            layer_number=1,
            direction="long",
            units=1000,
            price=Decimal("1.10000"),
        )

        result = handler.handle_open_position(event)

        assert result is position
        svc.open_position.assert_called_once()
        # Position should be cached
        assert handler.position_map[1] is position
        assert str(position.id) in handler._position_cache

    def test_records_trade(self):
        svc = _make_order_service()
        position = _make_position()
        order = MagicMock()
        svc.open_position.return_value = (position, order)

        handler = EventHandler(order_service=svc, instrument="EUR_USD")

        with patch.object(handler, "_record_trade") as mock_record:
            event = OpenPositionEvent(
                event_type=EventType.OPEN_POSITION,
                layer_number=1,
                direction="long",
                units=1000,
            )
            handler.handle_open_position(event)
            mock_record.assert_called_once()

    def test_dispatch_open_position_returns_fill_price_in_binding(self):
        svc = _make_order_service()
        position = _make_position()
        order = MagicMock()
        svc.open_position.return_value = (position, order)

        handler = EventHandler(order_service=svc, instrument="EUR_USD")
        handler._record_trade = MagicMock()

        event = OpenPositionEvent(
            event_type=EventType.OPEN_POSITION,
            layer_number=1,
            direction="long",
            units=1000,
            entry_id=7,
        )

        result = handler._dispatch_open_position(event)

        assert isinstance(result, EventExecutionResult)
        assert result.entry_binding is not None
        assert result.entry_binding.entry_id == 7
        assert result.entry_binding.position_id == str(position.id)
        assert result.entry_binding.fill_price == position.entry_price

    def test_passes_retracement_count(self):
        svc = _make_order_service()
        position = _make_position()
        svc.open_position.return_value = (position, MagicMock())

        handler = EventHandler(order_service=svc, instrument="EUR_USD")
        handler._record_trade = MagicMock()

        event = OpenPositionEvent(
            event_type=EventType.OPEN_POSITION,
            layer_number=2,
            direction="short",
            units=750,
            retracement_count=3,
        )
        handler.handle_open_position(event)

        call_kwargs = svc.open_position.call_args
        assert call_kwargs.kwargs.get("retracement_count") == 3


class TestHandleClosePosition:
    """Tests for handle_close_position."""

    def test_closes_position_returns_pnl(self):
        svc = _make_order_service()
        position = _make_position()
        closed_position = _make_position(is_open=False)
        closed_position.exit_price = Decimal("1.11000")
        svc.close_position.return_value = (closed_position, Decimal("10.00"), MagicMock())

        handler = EventHandler(order_service=svc, instrument="EUR_USD")
        handler._find_close_position_target = MagicMock(return_value=position)
        handler._prune_closed_position = MagicMock()
        handler._record_trade = MagicMock()

        event = ClosePositionEvent(
            event_type=EventType.CLOSE_POSITION,
            layer_number=1,
            direction="long",
            units=1000,
        )

        result = handler.handle_close_position(event)

        assert result[0] == Decimal("10.00")
        svc.close_position.assert_called_once()

    def test_no_target_position_raises(self):
        svc = _make_order_service()
        handler = EventHandler(order_service=svc, instrument="EUR_USD")
        handler._find_close_position_target = MagicMock(return_value=None)

        event = ClosePositionEvent(
            event_type=EventType.CLOSE_POSITION,
            layer_number=1,
            direction="long",
            units=1000,
        )

        with pytest.raises(ClosePositionResolutionError):
            handler.handle_close_position(event)
        svc.close_position.assert_not_called()

    def test_find_close_position_target_uses_entry_binding(self):
        svc = _make_order_service()
        position = _make_position(direction="short")
        handler = EventHandler(order_service=svc, instrument="EUR_USD")
        handler._entry_id_to_position_id[42] = str(position.id)
        handler._get_open_position_by_id = MagicMock(return_value=position)

        event = ClosePositionEvent(
            event_type=EventType.CLOSE_POSITION,
            layer_number=1,
            direction="short",
            units=1000,
            entry_id=42,
        )

        assert handler._find_close_position_target(event) is position
        handler._get_open_position_by_id.assert_called_once_with(str(position.id))

    def test_find_close_position_target_does_not_replace_stale_position_id(self):
        svc = _make_order_service()
        handler = EventHandler(order_service=svc, instrument="EUR_USD")
        handler._entry_id_to_position_id[42] = str(uuid4())
        handler._get_open_position_by_id = MagicMock(return_value=None)
        stale_position_id = str(uuid4())

        event = ClosePositionEvent(
            event_type=EventType.CLOSE_POSITION,
            layer_number=1,
            direction="short",
            units=1000,
            entry_id=42,
            position_id=stale_position_id,
        )

        with pytest.raises(ClosePositionResolutionError):
            handler._find_close_position_target(event)
        handler._get_open_position_by_id.assert_called_once_with(stale_position_id)

    def test_close_cycle_mismatch_raises(self):
        svc = _make_order_service()
        position = _make_position()
        handler = EventHandler(order_service=svc, instrument="EUR_USD")
        handler._resolve_cycle_id_for_position = MagicMock(return_value="position-cycle")
        handler._entry_id_to_cycle_id[42] = "event-cycle"

        event = ClosePositionEvent(
            event_type=EventType.CLOSE_POSITION,
            layer_number=1,
            direction="long",
            units=1000,
            entry_id=42,
        )

        with pytest.raises(CycleResolutionError):
            handler._resolve_cycle_id_for_close(event, position)

    def test_close_does_not_spill_into_another_position(self):
        svc = _make_order_service()
        p1 = _make_position(units=500)

        handler = EventHandler(order_service=svc, instrument="EUR_USD")
        handler._find_close_position_target = MagicMock(return_value=p1)
        handler._prune_closed_position = MagicMock()
        handler._record_trade = MagicMock()

        event = ClosePositionEvent(
            event_type=EventType.CLOSE_POSITION,
            layer_number=1,
            direction="long",
            units=1000,
        )

        with pytest.raises(ClosePositionResolutionError):
            handler.handle_close_position(event)
        svc.close_position.assert_not_called()

    def test_partial_close_records_order_fill_price(self):
        svc = _make_order_service()
        position = _make_position(units=1000)
        updated_position = _make_position(units=500, is_open=True)
        updated_position.exit_price = None
        close_order = SimpleNamespace(
            id=uuid4(),
            fill_price=Decimal("1.10500"),
            broker_order_id=None,
            oanda_trade_id=None,
        )
        svc.close_position.return_value = (
            updated_position,
            Decimal("2.50"),
            close_order,
        )

        handler = EventHandler(order_service=svc, instrument="EUR_USD")
        handler._find_close_position_target = MagicMock(return_value=position)
        handler._prune_closed_position = MagicMock()
        handler._record_trade = MagicMock()

        event = ClosePositionEvent(
            event_type=EventType.CLOSE_POSITION,
            layer_number=1,
            direction="long",
            units=500,
        )

        result = handler.handle_close_position(event)

        assert result == (Decimal("2.50"), Decimal("2.50000"))
        assert handler._last_close_execution_price == Decimal("1.10500")
        assert handler._record_trade.call_args.kwargs["price"] == Decimal("1.10500")


class TestResolveCycleIdFromDb:
    """Tests for DB-backed cycle resolution fallback."""

    def test_filters_by_direction_and_sequence_number(self):
        svc = _make_order_service()
        handler = EventHandler(order_service=svc, instrument="EUR_USD")
        event_timestamp = timezone.now()
        expected_cycle_id = uuid4()

        with (
            patch("apps.trading.events.handler.TradingEvent.objects") as trading_event_objects,
            patch("apps.trading.events.handler.Trade.objects") as trade_objects,
        ):
            trading_event_objects.filter.return_value.values.return_value.first.return_value = {
                "event_timestamp": event_timestamp,
                "sequence_number": 7,
                "direction": "short",
            }
            exact_trade_qs = trade_objects.filter.return_value
            exact_trade_qs.filter.return_value.values_list.return_value.first.return_value = (
                expected_cycle_id
            )

            resolved = handler._resolve_cycle_id_from_db(101, None, direction="short")

        assert resolved == str(expected_cycle_id)
        trade_objects.filter.assert_called_once_with(
            task_type=svc.task_type.value,
            task_id=svc.task.id,
            execution_id=svc.task.execution_id,
            timestamp=event_timestamp,
            execution_method="open_position",
            cycle_id__isnull=False,
            sequence_number=7,
        )
        exact_trade_qs.filter.assert_called_once_with(direction__iexact="short")

    def test_legacy_fallback_keeps_direction_constraint(self):
        svc = _make_order_service()
        handler = EventHandler(order_service=svc, instrument="EUR_USD")
        event_timestamp = timezone.now()
        expected_cycle_id = uuid4()

        with (
            patch("apps.trading.events.handler.TradingEvent.objects") as trading_event_objects,
            patch("apps.trading.events.handler.Trade.objects") as trade_objects,
        ):
            trading_event_objects.filter.return_value.values.return_value.first.return_value = {
                "event_timestamp": event_timestamp,
                "sequence_number": 11,
                "direction": "",
            }
            exact_trade_qs = MagicMock()
            exact_trade_qs.filter.return_value.values_list.return_value.first.return_value = None
            legacy_trade_qs = MagicMock()
            legacy_trade_qs.filter.return_value.values_list.return_value.first.return_value = (
                expected_cycle_id
            )
            trade_objects.filter.side_effect = [exact_trade_qs, legacy_trade_qs]

            resolved = handler._resolve_cycle_id_from_db(202, None, direction="short")

        assert resolved == str(expected_cycle_id)
        assert trade_objects.filter.call_count == 2
        legacy_trade_qs.filter.assert_called_once_with(direction__iexact="short")


class TestHandleVolatilityLock:
    """Tests for handle_volatility_lock."""

    def test_closes_all_positions(self):
        svc = _make_order_service()
        p1 = _make_position(units=1000, layer_index=1)
        p2 = _make_position(units=500, layer_index=2)

        closed_p1 = _make_position(units=1000, is_open=False, layer_index=1)
        closed_p1.exit_price = Decimal("1.11000")
        closed_p2 = _make_position(units=500, is_open=False, layer_index=2)
        closed_p2.exit_price = Decimal("1.11000")

        svc.close_position.side_effect = [
            (closed_p1, Decimal("10.00"), MagicMock()),
            (closed_p2, Decimal("5.00"), MagicMock()),
        ]

        handler = EventHandler(order_service=svc, instrument="EUR_USD")
        handler._ordered_positions_for_margin_close = MagicMock(return_value=[p1, p2])
        handler._prune_closed_position = MagicMock()
        handler._record_trade = MagicMock()

        event = VolatilityLockEvent(
            event_type=EventType.VOLATILITY_LOCK,
            reason="ATR exceeded",
        )

        result = handler.handle_volatility_lock(event)

        assert result[0] == Decimal("15.00")
        assert svc.close_position.call_count == 2

    def test_clears_caches_after_close(self):
        svc = _make_order_service()
        handler = EventHandler(order_service=svc, instrument="EUR_USD")
        handler._ordered_positions_for_margin_close = MagicMock(return_value=[])
        handler.position_map[1] = _make_position()
        handler._position_cache["x"] = _make_position()
        handler.layer_position_ids[1] = ["x"]

        event = VolatilityLockEvent(
            event_type=EventType.VOLATILITY_LOCK,
            reason="test",
        )
        handler.handle_volatility_lock(event)

        assert handler.position_map == {}
        assert handler._position_cache == {}
        assert handler.layer_position_ids == {}

    def test_continues_on_order_service_error(self):
        from apps.trading.order import OrderServiceError

        svc = _make_order_service()
        p1 = _make_position(units=1000, layer_index=1)
        p2 = _make_position(units=500, layer_index=2)

        closed_p2 = _make_position(units=500, is_open=False, layer_index=2)
        closed_p2.exit_price = Decimal("1.11000")

        svc.close_position.side_effect = [
            OrderServiceError("fail"),
            (closed_p2, Decimal("5.00"), MagicMock()),
        ]

        handler = EventHandler(order_service=svc, instrument="EUR_USD")
        handler._ordered_positions_for_margin_close = MagicMock(return_value=[p1, p2])
        handler._prune_closed_position = MagicMock()
        handler._record_trade = MagicMock()

        event = VolatilityLockEvent(
            event_type=EventType.VOLATILITY_LOCK,
            reason="test",
        )
        result = handler.handle_volatility_lock(event)
        assert result[0] == Decimal("5.00")


class TestHandleVolatilityHedgeNeutralize:
    """Tests for handle_volatility_hedge_neutralize."""

    def test_opens_hedge_positions(self):
        svc = _make_order_service()
        hedged = _make_position()
        svc.open_position.return_value = (hedged, MagicMock())

        handler = EventHandler(order_service=svc, instrument="EUR_USD")

        event = VolatilityHedgeNeutralizeEvent(
            event_type=EventType.VOLATILITY_HEDGE_NEUTRALIZE,
            reason="hedge",
            hedge_instructions=[
                {"direction": "short", "units": 1000, "layer_index": 1, "source_entry_id": "e1"},
            ],
        )

        result = handler.handle_volatility_hedge_neutralize(event)

        assert result == Decimal("0")
        svc.open_position.assert_called_once()

    def test_skips_zero_units(self):
        svc = _make_order_service()
        handler = EventHandler(order_service=svc, instrument="EUR_USD")

        event = VolatilityHedgeNeutralizeEvent(
            event_type=EventType.VOLATILITY_HEDGE_NEUTRALIZE,
            reason="hedge",
            hedge_instructions=[
                {"direction": "short", "units": 0, "layer_index": 1},
            ],
        )
        handler.handle_volatility_hedge_neutralize(event)
        svc.open_position.assert_not_called()


class TestHandleMarginProtection:
    """Tests for handle_margin_protection."""

    def test_closes_positions(self):
        svc = _make_order_service()
        p1 = _make_position(units=1000, layer_index=1)
        closed_p1 = _make_position(units=1000, is_open=False, layer_index=1)
        closed_p1.exit_price = Decimal("1.09000")

        svc.close_position.return_value = (closed_p1, Decimal("-10.00"), MagicMock())

        handler = EventHandler(order_service=svc, instrument="EUR_USD")
        handler._ordered_positions_for_margin_close = MagicMock(return_value=[p1])
        handler._prune_closed_position = MagicMock()
        handler._record_trade = MagicMock()

        event = MarginProtectionEvent(
            event_type=EventType.MARGIN_PROTECTION,
            reason="margin call",
        )

        result = handler.handle_margin_protection(event)

        assert result[0] == Decimal("-10.00")
        svc.close_position.assert_called_once()

    def test_respects_units_to_close_limit(self):
        svc = _make_order_service()
        p1 = _make_position(units=1000, layer_index=1)
        p2 = _make_position(units=1500, layer_index=2)

        close_calls = []

        def _close(position, units=None, tick_timestamp=None):
            close_calls.append(units)
            closed = _make_position(
                units=position.units, is_open=False, layer_index=position.layer_index
            )
            closed.exit_price = Decimal("1.09000")
            return closed, Decimal("0"), MagicMock()

        svc.close_position.side_effect = _close

        handler = EventHandler(order_service=svc, instrument="EUR_USD")
        handler._ordered_positions_for_margin_close = MagicMock(return_value=[p1, p2])
        handler._prune_closed_position = MagicMock()
        handler._record_trade = MagicMock()

        event = MarginProtectionEvent(
            event_type=EventType.MARGIN_PROTECTION,
            reason="margin call",
            units_to_close=1200,
            positions_closed=5,
        )
        handler.handle_margin_protection(event)

        assert close_calls == [1000, 200]


class TestGetOpenPositions:
    """Tests for get_open_positions."""

    def test_returns_open_positions(self):
        handler = EventHandler(order_service=_make_order_service(), instrument="EUR_USD")
        open_pos = _make_position(is_open=True)
        closed_pos = _make_position(is_open=False)
        handler.position_map = {1: open_pos, 2: closed_pos}

        result = handler.get_open_positions()

        assert len(result) == 1
        assert result[0] is open_pos

    def test_returns_empty_when_no_positions(self):
        handler = EventHandler(order_service=_make_order_service(), instrument="EUR_USD")
        assert handler.get_open_positions() == []


class TestClearPositions:
    """Tests for clear_positions."""

    def test_clears_all_caches(self):
        handler = EventHandler(order_service=_make_order_service(), instrument="EUR_USD")
        handler.position_map[1] = _make_position()
        handler._position_cache["x"] = _make_position()
        handler.layer_position_ids[1] = ["x"]
        handler._entry_id_to_position_id[1] = "x"

        handler.clear_positions()

        assert handler.position_map == {}
        assert handler._position_cache == {}
        assert handler.layer_position_ids == {}
        assert handler._entry_id_to_position_id == {}


class TestHandleEvent:
    """Tests for handle_event dispatch."""

    def test_dispatches_open_position(self):
        svc = _make_order_service()
        position = _make_position()
        svc.open_position.return_value = (position, MagicMock())

        handler = EventHandler(order_service=svc, instrument="EUR_USD")
        handler._record_trade = MagicMock()

        trading_event = MagicMock()
        trading_event.details = {
            "event_type": "open_position",
            "strategy_event_type": "initial_entry",
            "layer_number": 1,
            "direction": "long",
            "units": 1000,
            "price": "1.10000",
        }

        result = handler.handle_event(trading_event)

        assert result.realized_pnl_delta == Decimal("0")
        assert result.entry_binding is not None

    def test_dispatches_close_position(self):
        svc = _make_order_service()
        handler = EventHandler(order_service=svc, instrument="EUR_USD")
        handler._find_close_position_target = MagicMock(return_value=None)

        trading_event = MagicMock()
        trading_event.details = {
            "event_type": "close_position",
            "strategy_event_type": "take_profit",
            "layer_number": 1,
            "direction": "long",
            "units": 1000,
        }

        with pytest.raises(ClosePositionResolutionError):
            handler.handle_event(trading_event)

    def test_unknown_event_returns_zero(self):
        svc = _make_order_service()
        handler = EventHandler(order_service=svc, instrument="EUR_USD")

        trading_event = MagicMock()
        trading_event.details = {
            "event_type": "add_layer",
            "layer_number": 3,
        }

        result = handler.handle_event(trading_event)
        assert result.realized_pnl_delta == Decimal("0")
        assert result.entry_binding is None

    def test_custom_event_handler_registration(self):
        svc = _make_order_service()
        handler = EventHandler(order_service=svc, instrument="EUR_USD")

        def _custom_handler(_event):
            return EventExecutionResult(
                realized_pnl_delta=Decimal("123.45"),
                entry_binding=None,
            )

        handler.register_event_handler("custom_event", _custom_handler)

        trading_event = MagicMock()
        trading_event.details = {
            "event_type": "custom_event",
            "payload": "ok",
        }

        result = handler.handle_event(trading_event)
        assert result.realized_pnl_delta == Decimal("123.45")
        assert result.entry_binding is None
