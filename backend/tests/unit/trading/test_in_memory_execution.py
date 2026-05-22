"""Unit tests for in-memory backtest execution helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from apps.trading.dataclasses import EventContext
from apps.trading.enums import Direction, EventType, TaskType
from apps.trading.events import (
    ClosePositionEvent,
    GenericStrategyEvent,
    InitialEntryEvent,
    OpenPositionEvent,
    RebuildPositionEvent,
)
from apps.trading.in_memory_execution import InMemoryEventHandler, InMemoryOrderService
from apps.trading.models import Position, TradingEvent
from apps.trading.tasks.event_persistence import materialize_execution_events
from tests.integration.factories import UserFactory


def _position() -> Position:
    return Position(
        task_type=TaskType.BACKTEST.value,
        task_id=uuid4(),
        execution_id=uuid4(),
        instrument="USD_JPY",
        direction=Direction.LONG.value,
        units=1000,
        entry_price=Decimal("150.00"),
        entry_time=datetime(2026, 1, 1, tzinfo=UTC),
        is_open=True,
    )


def test_rebinding_position_to_cycle_drops_stale_cycle_references() -> None:
    position = _position()
    order_service = MagicMock(task_type=TaskType.BACKTEST)
    handler = InMemoryEventHandler(order_service, "USD_JPY")

    handler._bind_position_to_cycle(
        position=position,
        cycle_id="old-cycle",
        event=OpenPositionEvent(event_type=EventType.OPEN_POSITION, entry_id=1),
    )
    handler._bind_position_to_cycle(
        position=position,
        cycle_id="new-cycle",
        event=OpenPositionEvent(
            event_type=EventType.OPEN_POSITION,
            entry_id=2,
            root_entry_id=20,
            parent_entry_id=1,
        ),
    )

    position_id = str(position.id)
    assert handler._position_id_to_cycle_id[position_id] == "new-cycle"
    assert "old-cycle" not in handler._cycle_id_to_position_ids
    assert handler._cycle_id_to_position_ids["new-cycle"] == {position_id}
    assert handler._entry_id_to_cycle_id[1] == "new-cycle"
    assert handler._entry_id_to_cycle_id[2] == "new-cycle"
    assert handler._entry_id_to_cycle_id[20] == "new-cycle"


def test_completed_cycles_are_pruned_when_no_open_positions_remain() -> None:
    position = _position()
    order_service = MagicMock(task_type=TaskType.BACKTEST)
    order_service.get_open_positions.return_value = []
    handler = InMemoryEventHandler(order_service, "USD_JPY")

    handler._bind_position_to_cycle(
        position=position,
        cycle_id="cycle",
        event=OpenPositionEvent(event_type=EventType.OPEN_POSITION, entry_id=1),
    )

    position.is_open = False
    handler._prune_completed_cycles()

    assert handler._position_id_to_cycle_id == {}
    assert handler._cycle_id_to_position_ids == {}
    assert handler._cycle_id_to_entry_ids == {}
    assert handler._entry_id_to_cycle_id == {}


def test_pending_rebuild_cycles_are_not_pruned() -> None:
    position = _position()
    order_service = MagicMock(task_type=TaskType.BACKTEST)
    order_service.get_open_positions.return_value = []
    handler = InMemoryEventHandler(order_service, "USD_JPY")

    handler._bind_position_to_cycle(
        position=position,
        cycle_id="cycle",
        event=OpenPositionEvent(event_type=EventType.OPEN_POSITION, entry_id=2),
    )
    handler._track_pending_rebuild_cycle(
        ClosePositionEvent(
            event_type=EventType.CLOSE_POSITION,
            entry_id=2,
            position_id=str(position.id),
        )
    )

    position.is_open = False
    handler._prune_completed_cycles()

    position_id = str(position.id)
    assert handler._position_id_to_cycle_id[position_id] == "cycle"
    assert handler._cycle_id_to_position_ids["cycle"] == {position_id}
    assert handler._entry_id_to_cycle_id[2] == "cycle"
    assert handler._pending_rebuild_position_ids[position_id] == "cycle"


def test_multiple_pending_rebuilds_in_same_cycle_survive_partial_rebuild() -> None:
    first_position = _position()
    second_position = _position()
    order_service = MagicMock(task_type=TaskType.BACKTEST)
    order_service.get_open_positions.return_value = []
    handler = InMemoryEventHandler(order_service, "USD_JPY")

    handler._bind_position_to_cycle(
        position=first_position,
        cycle_id="cycle",
        event=OpenPositionEvent(
            event_type=EventType.OPEN_POSITION,
            entry_id=27,
            root_entry_id=27,
        ),
    )
    handler._bind_position_to_cycle(
        position=second_position,
        cycle_id="cycle",
        event=OpenPositionEvent(
            event_type=EventType.OPEN_POSITION,
            entry_id=30,
            root_entry_id=27,
            parent_entry_id=27,
        ),
    )
    handler._track_pending_rebuild_cycle(
        ClosePositionEvent(
            event_type=EventType.CLOSE_POSITION,
            entry_id=27,
            root_entry_id=27,
            position_id=str(first_position.id),
        )
    )
    handler._track_pending_rebuild_cycle(
        ClosePositionEvent(
            event_type=EventType.CLOSE_POSITION,
            entry_id=30,
            root_entry_id=27,
            parent_entry_id=27,
            position_id=str(second_position.id),
        )
    )

    handler._pending_rebuild_position_ids.pop(str(first_position.id), None)
    handler._prune_completed_cycles()

    second_position_id = str(second_position.id)
    assert str(first_position.id) not in handler._position_id_to_cycle_id
    assert handler._pending_rebuild_position_ids == {second_position_id: "cycle"}
    assert handler._position_id_to_cycle_id[second_position_id] == "cycle"
    assert handler._entry_id_to_cycle_id[27] == "cycle"
    assert handler._entry_id_to_cycle_id[30] == "cycle"


@pytest.mark.django_db
def test_rebuild_cycle_can_resolve_from_original_position_mapping() -> None:
    position = _position()
    order_service = MagicMock(task_type=TaskType.BACKTEST)
    order_service.task = SimpleNamespace(id=position.task_id)
    order_service.execution_id = position.execution_id
    handler = InMemoryEventHandler(order_service, "USD_JPY")

    handler._bind_position_to_cycle(
        position=position,
        cycle_id="cycle",
        event=OpenPositionEvent(event_type=EventType.OPEN_POSITION, entry_id=2),
    )
    handler._entry_id_to_cycle_id.clear()
    handler._cycle_id_to_entry_ids.clear()

    cycle_id = handler._resolve_rebuild_cycle_id(
        RebuildPositionEvent(
            event_type=EventType.REBUILD_POSITION,
            entry_id=5,
            root_entry_id=2,
            original_position_id=str(position.id),
        )
    )

    assert cycle_id == "cycle"


@pytest.mark.django_db
def test_materialize_execution_events_keeps_only_transient_execution_events() -> None:
    task_id = uuid4()
    execution_id = uuid4()
    context = EventContext(
        user=UserFactory(),
        account=None,
        instrument="USD_JPY",
        task_id=task_id,
        execution_id=execution_id,
        task_type=TaskType.BACKTEST,
    )

    records = materialize_execution_events(
        events=[
            GenericStrategyEvent(event_type=EventType.STRATEGY_SIGNAL),
            OpenPositionEvent(
                event_type=EventType.OPEN_POSITION,
                direction=Direction.LONG.value,
                price=Decimal("150.00"),
                units=1000,
                entry_id=10,
            ),
        ],
        context=context,
        execution_id=execution_id,
        strategy_type="snowball",
    )

    assert len(records) == 1
    record = records[0]
    assert record.pk == -2
    assert getattr(record, "_in_memory") is True
    assert record.event_type == EventType.OPEN_POSITION.value
    assert record.task_id == task_id
    assert record.execution_id == execution_id
    assert record.entry_id == 10
    assert TradingEvent.objects.count() == 0


@pytest.mark.django_db
def test_materialize_execution_events_attaches_execution_event_fast_path() -> None:
    task_id = uuid4()
    execution_id = uuid4()
    context = EventContext(
        user=UserFactory(),
        account=None,
        instrument="USD_JPY",
        task_id=task_id,
        execution_id=execution_id,
        task_type=TaskType.BACKTEST,
    )
    event = InitialEntryEvent(
        event_type=EventType.INITIAL_ENTRY,
        direction=Direction.LONG.value,
        price=Decimal("150.00"),
        units=1000,
        entry_id=10,
    )

    records = materialize_execution_events(
        events=[event],
        context=context,
        execution_id=execution_id,
        strategy_type="snowball",
    )

    assert len(records) == 1
    record = records[0]
    attached = getattr(record, "_strategy_event")
    assert isinstance(attached, OpenPositionEvent)
    assert attached.event_type == EventType.OPEN_POSITION
    assert attached.entry_id == 10


def test_in_memory_order_service_uses_lightweight_broker_gateway() -> None:
    class BacktestTaskDouble(SimpleNamespace):
        pass

    task = BacktestTaskDouble(
        id=uuid4(),
        execution_id=uuid4(),
        account_currency="USD",
    )
    service = InMemoryOrderService(account=None, task=task, dry_run=True)

    position, order = service.open_position(
        instrument="USD_JPY",
        units=1000,
        direction=Direction.LONG,
        override_price=Decimal("150.25"),
        tick_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert order.broker_order_id == "MEM-1"
    assert order.fill_price == Decimal("150.25")
    assert position.entry_price == Decimal("150.25")
