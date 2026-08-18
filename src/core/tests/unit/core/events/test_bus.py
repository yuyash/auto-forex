from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from autoforex.core import (
    CurrencyPair,
    Event,
    EventBus,
    EventHandlerError,
    EventSource,
    EventType,
    Money,
    StrategyAction,
    StrategyEventRequest,
    TradeSide,
    Units,
    new_uuid,
)


class FailingHandler:
    def handle(self, event: Event) -> None:
        _ = event
        msg = "handler failed"
        raise RuntimeError(msg)


class TestEventBus:
    def test_event_bus_propagates_handler_failures_and_records_diagnostics(self) -> None:
        bus = EventBus(handlers=(FailingHandler(),), record_history=True)
        event = Event(
            type=EventType.TASK_STARTED,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            source=EventSource.CORE,
        )

        with pytest.raises(EventHandlerError) as raised:
            bus.publish(event)

        assert isinstance(raised.value.cause, RuntimeError)
        assert tuple(item.type for item in bus.history) == (
            EventType.TASK_STARTED,
            EventType.ERROR_OCCURRED,
        )

    def test_event_bus_expires_pending_strategy_requests(self) -> None:
        bus = EventBus(record_history=True, strategy_request_timeout=timedelta(minutes=1))
        task_id = new_uuid()
        request = StrategyEventRequest(
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            task_id=task_id,
            action=StrategyAction.OPEN_TRADE,
            instrument=CurrencyPair.of("USD_JPY"),
            side=TradeSide.BUY,
            units=Units("1000"),
            price=Money.of("150.10", "JPY"),
            display_id="C1L1R0B1",
        )

        bus.publish(request)
        expired = bus.expire_pending_strategy_requests(
            task_id=task_id,
            timestamp=datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
        )

        assert bus.pending_strategy_request_count == 0
        assert len(expired) == 1
        assert expired[0].display_id == "C1L1R0B1"
        assert expired[0].metadata["pending_strategy_request"] is True
        assert expired[0].metadata["reason"] == "strategy execution response timeout"

    def test_event_bus_rejects_non_positive_strategy_request_timeout(self) -> None:
        with pytest.raises(ValueError, match="strategy_request_timeout"):
            EventBus(strategy_request_timeout=timedelta(0))

        bus = EventBus(strategy_request_timeout=timedelta(seconds=1))
        with pytest.raises(ValueError, match="strategy_request_timeout"):
            bus.expire_pending_strategy_requests(
                timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                timeout=timedelta(0),
            )

    def test_event_bus_clears_pending_strategy_requests_for_task(self) -> None:
        bus = EventBus(record_history=True)
        task_id = new_uuid()
        request = StrategyEventRequest(
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            task_id=task_id,
            action=StrategyAction.CLOSE_TRADE,
            instrument=CurrencyPair.of("USD_JPY"),
            side=TradeSide.SELL,
            units=Units("1000"),
            price=Money.of("150.20", "JPY"),
        )

        bus.publish(request)
        cleared = bus.clear_pending_strategy_requests(task_id=task_id, reason="task completed")

        assert bus.pending_strategy_requests == ()
        assert len(cleared) == 1
        assert cleared[0].metadata["original_event_id"] == str(request.id)
        assert cleared[0].metadata["reason"] == "task completed"
