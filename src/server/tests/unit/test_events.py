from __future__ import annotations

from datetime import UTC, datetime

import pytest
from autoforex.core import (
    CurrencyPair,
    Event,
    EventBus,
    EventHandlerError,
    EventSource,
    EventType,
    Metadata,
    Money,
    Order,
    OrderSide,
    OrderStatus,
    RecordingEventHandler,
    StrategyAction,
    StrategyEvent,
    StrategyEventRequest,
    StrategyExecutionResponse,
    TradeSide,
    Units,
    new_uuid,
)


class RaisingEventHandler:
    def handle(self, event: Event) -> None:
        _ = event
        msg = "handler failed"
        raise RuntimeError(msg)


class TestEvents:
    def test_event_bus_records_handler_failures_as_error_events(self) -> None:
        recording_handler = RecordingEventHandler()
        event_bus = EventBus(record_history=True)
        event_bus.subscribe(RaisingEventHandler())
        event_bus.subscribe(recording_handler)
        event = Event(type=EventType.TASK_STARTED, source=EventSource.CORE)

        with pytest.raises(EventHandlerError) as raised:
            event_bus.publish(event)

        assert event_bus.history[0] == event
        assert recording_handler.events == []

        failure_event = event_bus.history[1]
        assert isinstance(raised.value.cause, RuntimeError)
        assert failure_event in event_bus.history
        assert failure_event.type == EventType.ERROR_OCCURRED
        assert failure_event.source == EventSource.CORE
        assert failure_event.metadata["original_event_id"] == str(event.id)
        assert failure_event.metadata["original_event_type"] == EventType.TASK_STARTED.value
        assert failure_event.metadata["exception_type"] == "RuntimeError"
        assert failure_event.metadata["exception_message"] == "handler failed"

    def test_event_bus_records_aggregated_strategy_event_from_request_and_response(
        self,
    ) -> None:
        recording_handler = RecordingEventHandler()
        event_bus = EventBus(handlers=[recording_handler], record_history=True)
        request = StrategyEventRequest(
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            task_id=new_uuid(),
            action=StrategyAction.CLOSE_TRADE,
            instrument=CurrencyPair.of("USD_JPY"),
            side=TradeSide.SELL,
            units=Units("1000"),
            price=Money.of("150.50", "JPY"),
            metadata=Metadata.of(
                close_reason="take_profit",
                planned_take_profit_price="150.50 JPY",
                filled_price_metadata_key="filled_take_profit_price",
            ),
        )
        response = StrategyExecutionResponse(
            event=request,
            order=Order(
                instrument=CurrencyPair.of("USD_JPY"),
                side=OrderSide.SELL,
                units=Units("1000"),
                price=Money.of("150.52", "JPY"),
                status=OrderStatus.FILLED,
                filled_units=Units("1000"),
            ),
        )

        event_bus.publish(request)
        assert event_bus.pending_strategy_requests == (request,)

        event_bus.publish(response)

        aggregate = event_bus.select(event_class=StrategyEvent)[0]
        assert event_bus.pending_strategy_requests == ()
        assert recording_handler.events == [request, response, aggregate]
        assert aggregate.request is request
        assert aggregate.response is response
        assert aggregate.metadata["planned_take_profit_price"] == "150.50 JPY"
        assert aggregate.metadata["filled_take_profit_price"] == "150.52 JPY"
