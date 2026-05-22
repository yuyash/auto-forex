"""Persistence helpers for strategy-emitted events."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.trading.dataclasses import EventContext
from apps.trading.enums import EventScope, EventType
from apps.trading.events import StrategyEvent

if TYPE_CHECKING:
    from apps.trading.models import TradingEvent


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
) -> list["TradingEvent"]:
    """Build transient execution events without writing event rows.

    In-memory backtests still reuse the event-processing pipeline, but their
    strategy and trading events must not be stored.  Only events that require
    execution are materialized; purely informational/visualization events are
    intentionally discarded.
    """
    if not events:
        return []

    trading_records: list[Any] = []
    for seq, event in enumerate(events):
        event.sequence_number = seq
        event_type = str(getattr(getattr(event, "event_type", None), "value", event.event_type))
        if not EventType.requires_execution(event_type):
            continue
        execution_event_type = EventType.execution_event_type_for(event_type)
        record = _trading_record_for_execution_event(
            event=event,
            context=context,
            execution_id=execution_id,
            strategy_type=strategy_type,
            event_type=event_type,
            execution_event_type=execution_event_type,
        )
        record.pk = -(seq + 1)
        setattr(record, "_in_memory", True)
        setattr(record, "_strategy_event", _execution_strategy_event(record, event))
        trading_records.append(record)
    return trading_records


def _execution_strategy_event(record: "TradingEvent", event: StrategyEvent) -> StrategyEvent:
    """Return the event shape consumed by EventHandler without reparsing when possible."""
    if record.event_type == str(
        getattr(getattr(event, "event_type", None), "value", event.event_type)
    ):
        return event
    return StrategyEvent.from_dict(record.details)


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

    details = event.to_dict()
    details["strategy_event_type"] = event_type
    details["event_type"] = execution_event_type
    record.event_type = execution_event_type
    record.severity = "info"
    record.description = str(details)
    record.details = details
    return record
