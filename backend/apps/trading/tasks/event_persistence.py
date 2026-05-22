"""Persistence helpers for strategy-emitted events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from apps.trading.dataclasses import EventContext
from apps.trading.enums import EventScope, EventType
from apps.trading.events import StrategyEvent

if TYPE_CHECKING:
    from apps.trading.models import TradingEvent


@dataclass(slots=True)
class InMemoryExecutionEvent:
    """TradingEvent-compatible execution payload that never touches the ORM."""

    pk: int
    event_type: str
    details: dict[str, Any]
    sequence_number: int
    strategy_type: str
    task_id: Any = None
    execution_id: Any = None
    instrument: str = ""
    root_entry_id: int | None = None
    parent_entry_id: int | None = None
    entry_id: int | None = None
    position_id: UUID | None = None
    direction: str = ""
    is_processed: bool = False
    processed_at: datetime | None = None
    processing_error: str = ""
    _in_memory: bool = True
    _strategy_event: StrategyEvent | None = None


def persist_strategy_events(
    *,
    events: list[StrategyEvent],
    context: EventContext,
    execution_id: Any,
    strategy_type: str,
) -> list["TradingEvent"]:
    """Persist strategy events into execution and strategy-event tables."""
    if not events:
        return []

    from apps.trading import models as trading_models

    trading_records: list[Any] = []
    strategy_records: list[Any] = []

    for seq, event in enumerate(events):
        event.sequence_number = seq
        event_type = str(getattr(getattr(event, "event_type", None), "value", event.event_type))
        event_scope = EventType.scope_of(event_type)
        execution_event_type = EventType.execution_event_type_for(event_type)
        requires_execution = EventType.requires_execution(event_type)

        if requires_execution:
            trading_records.append(
                _trading_record_for_execution_event(
                    event=event,
                    context=context,
                    execution_id=execution_id,
                    strategy_type=strategy_type,
                    event_type=event_type,
                    execution_event_type=execution_event_type,
                )
            )

        if event_scope == EventScope.TASK.value and not requires_execution:
            trading_records.append(
                trading_models.TradingEvent.from_event(
                    event=event,
                    context=context,
                    execution_id=execution_id,
                    strategy_type=strategy_type,
                )
            )
        elif event_scope == EventScope.STRATEGY.value:
            strategy_records.append(
                trading_models.StrategyEventRecord.from_event(
                    event=event,
                    context=context,
                    execution_id=execution_id,
                    strategy_type=strategy_type,
                )
            )

    if trading_records:
        trading_models.TradingEvent.objects.bulk_create(trading_records)
    if strategy_records:
        trading_models.StrategyEventRecord.objects.bulk_create(strategy_records)

    return trading_records


def materialize_execution_events(
    *,
    events: list[StrategyEvent],
    context: EventContext,
    execution_id: Any,
    strategy_type: str,
) -> list[InMemoryExecutionEvent]:
    """Build in-memory execution events without writing or instantiating ORM rows.

    In-memory backtests still reuse the event-processing pipeline, but their
    strategy and trading events must not be stored.  Only events that require
    execution are materialized; purely informational/visualization events are
    intentionally discarded.
    """
    if not events:
        return []

    trading_records: list[InMemoryExecutionEvent] = []
    for seq, event in enumerate(events):
        event.sequence_number = seq
        event_type = str(getattr(getattr(event, "event_type", None), "value", event.event_type))
        if not EventType.requires_execution(event_type):
            continue
        execution_event_type = EventType.execution_event_type_for(event_type)
        details = _execution_event_details(
            event=event,
            event_type=event_type,
            execution_event_type=execution_event_type,
        )
        strategy_event = StrategyEvent.from_dict(details)
        if strategy_type:
            strategy_event.strategy_type = str(strategy_type)
        record = InMemoryExecutionEvent(
            pk=-(seq + 1),
            event_type=execution_event_type,
            details=details,
            sequence_number=seq,
            strategy_type=str(strategy_type or getattr(event, "strategy_type", "") or ""),
            task_id=context.task_id,
            execution_id=execution_id,
            instrument=context.instrument,
            root_entry_id=_optional_int(getattr(event, "root_entry_id", None)),
            parent_entry_id=_optional_int(getattr(event, "parent_entry_id", None)),
            entry_id=_optional_int(getattr(event, "entry_id", None)),
            position_id=_optional_uuid(getattr(event, "position_id", None)),
            direction=str(getattr(event, "direction", "") or ""),
            _strategy_event=strategy_event,
        )
        trading_records.append(record)
    return trading_records


def _execution_event_details(
    *,
    event: StrategyEvent,
    event_type: str,
    execution_event_type: str,
) -> dict[str, Any]:
    details = event.to_dict()
    if execution_event_type == event_type:
        return details
    details["strategy_event_type"] = event_type
    details["event_type"] = execution_event_type
    return details


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _optional_uuid(value: object) -> UUID | None:
    if value is None or isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _trading_record_for_execution_event(
    *,
    event: StrategyEvent,
    context: EventContext,
    execution_id: Any,
    strategy_type: str,
    event_type: str,
    execution_event_type: str,
) -> "TradingEvent":
    from apps.trading import models as trading_models

    record = trading_models.TradingEvent.from_event(
        event=event,
        context=context,
        execution_id=execution_id,
        strategy_type=strategy_type,
    )
    if execution_event_type == event_type:
        return record

    details = _execution_event_details(
        event=event,
        event_type=event_type,
        execution_event_type=execution_event_type,
    )
    record.event_type = execution_event_type
    record.severity = "info"
    record.description = str(details)
    record.details = details
    return record
