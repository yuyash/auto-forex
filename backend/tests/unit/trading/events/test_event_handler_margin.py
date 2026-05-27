"""Unit tests for margin protection partial-close execution in EventHandler."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from apps.trading.enums import EventType, TaskType
from apps.trading.events import MarginProtectionEvent
from apps.trading.events.handler import EventHandler


def _position(units: int, layer_index: int = 1):
    return SimpleNamespace(
        id=uuid4(),
        is_open=True,
        units=units,
        layer_index=layer_index,
        direction="long",
        instrument="USD_JPY",
        entry_price=Decimal("150.000"),
        entry_time=None,
        exit_price=None,
        exit_time=None,
        planned_exit_price=None,
        oanda_trade_id=None,
    )


class TestEventHandlerMarginPartialClose:
    """Tests unit-based close behavior for margin protection."""

    def test_close_position_receives_units_in_fifo_order(self) -> None:
        order_service = MagicMock()
        order_service.task = SimpleNamespace(id=uuid4(), execution_id=uuid4())
        order_service.task_type = TaskType.TRADING
        order_service.dry_run = False

        handler = EventHandler(order_service=order_service, instrument="USD_JPY")
        p1 = _position(units=1000, layer_index=1)
        p2 = _position(units=1500, layer_index=1)
        ordered = [p1, p2]
        handler._ordered_positions_for_margin_close = MagicMock(return_value=ordered)  # type: ignore[method-assign]
        handler._prune_closed_position = MagicMock()  # type: ignore[method-assign]
        handler._record_trade = MagicMock()  # type: ignore[method-assign]

        close_calls: list[int | None] = []

        def _close(position, units=None, override_price=None, tick_timestamp=None):
            _ = override_price
            close_calls.append(units)
            remaining = abs(position.units) - (units or abs(position.units))
            position.is_open = remaining > 0
            position.units = remaining if remaining > 0 else position.units
            return position, Decimal("0"), None

        order_service.close_position.side_effect = _close

        event = MarginProtectionEvent(
            event_type=EventType.MARGIN_PROTECTION,
            reason="test",
            positions_closed=2,
            units_to_close=1200,
        )
        handler.handle_margin_protection(event)

        # FIFO: first close 1000, then remaining 200 from second position.
        assert close_calls == [1000, 200]
