from datetime import UTC, datetime

from autoforex.core import (
    BrokerOrderId,
    Confidence,
    Order,
    OrderSide,
    OrderStatus,
    StrategyExecutionResponse,
    Units,
)
from autoforex.core.events import (
    EventMessageKey,
    EventSource,
    EventType,
)
from autoforex.core.models import CurrencyPair, Metadata, Money, new_uuid
from autoforex.core.strategies import (
    StrategyAction,
    StrategyDecisionCode,
    StrategyDecisionReason,
    StrategyEvent,
    StrategyEventRequest,
    TradeSide,
)


class TestStrategyEvent:
    def test_strategy_event_request_models_decision_trace(self) -> None:
        task_id = new_uuid()
        event = StrategyEventRequest(
            task_id=task_id,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            action=StrategyAction.OPEN_TRADE,
            instrument=CurrencyPair.of("USD_JPY"),
            side=TradeSide.BUY,
            units=Units("1000"),
            price=Money.of("150.11", "JPY"),
            display_id="C1L1R0B1",
            reason=StrategyDecisionReason(
                code=StrategyDecisionCode.ENTRY_SIGNAL,
                rule_id="snowball.breakout",
                confidence=Confidence("0.8"),
                evidence=Metadata.of(bid="150.10", ask="150.11"),
            ),
        )

        assert event.type == EventType.STRATEGY_SIGNAL
        assert event.source == EventSource.STRATEGY
        assert event.message_key == EventMessageKey.STRATEGY_SIGNAL
        assert event.task_id == task_id
        assert event.display_id == "C1L1R0B1"
        assert event.reason.code == StrategyDecisionCode.ENTRY_SIGNAL
        assert event.reason.evidence == Metadata.of(bid="150.10", ask="150.11")

    def test_strategy_execution_response_is_order_event(self) -> None:
        task_id = new_uuid()
        event = StrategyEventRequest(
            task_id=task_id,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            action=StrategyAction.OPEN_TRADE,
            instrument=CurrencyPair.of("USD_JPY"),
            side=TradeSide.BUY,
            units=Units("1000"),
            price=Money.of("150.11", "JPY"),
            display_id="C1L1R0B1",
        )

        report = StrategyExecutionResponse(
            event=event,
            order=Order(
                instrument=CurrencyPair.of("USD_JPY"),
                side=OrderSide.BUY,
                units=Units("1000"),
                price=Money.of("150.11", "JPY"),
                status=OrderStatus.FILLED,
                filled_units=Units("1000"),
            ),
        )

        assert report.type == EventType.ORDER_FILLED
        assert report.source == EventSource.BROKER
        assert report.message_key == EventMessageKey.ORDER_FILLED
        assert report.task_id == task_id
        assert report.timestamp == event.timestamp
        assert report.display_id == "C1L1R0B1"
        assert report.metadata["filled_entry_price"] == "150.11 JPY"

        aggregate = StrategyEvent(
            task_id=event.task_id,
            request=event,
            response=report,
            instrument=event.instrument,
        )
        assert aggregate.source == EventSource.CORE
        assert aggregate.request is event
        assert aggregate.response is report
        assert aggregate.action == StrategyAction.OPEN_TRADE
        assert aggregate.metadata["filled_entry_price"] == "150.11 JPY"

    def test_strategy_execution_response_propagates_order_metadata(self) -> None:
        task_id = new_uuid()
        event = StrategyEventRequest(
            task_id=task_id,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            action=StrategyAction.OPEN_TRADE,
            instrument=CurrencyPair.of("USD_JPY"),
            side=TradeSide.BUY,
            units=Units("1000"),
            price=Money.of("150.11", "JPY"),
            display_id="C1L1R0B1",
            metadata=Metadata.of(strategy_key="request"),
        )

        report = StrategyExecutionResponse(
            event=event,
            order=Order(
                instrument=CurrencyPair.of("USD_JPY"),
                side=OrderSide.BUY,
                units=Units("1000"),
                price=Money.of("150.11", "JPY"),
                status=OrderStatus.FILLED,
                broker_order_id=BrokerOrderId.of("broker-order-1"),
                filled_units=Units("1000"),
                metadata=Metadata.of(
                    broker_trade_id="broker-trade-1",
                    logical_trade_id="C1L1R0B1",
                ),
            ),
            metadata=Metadata.of(execution_channel="paper"),
        )
        aggregate = StrategyEvent(
            task_id=event.task_id,
            request=event,
            response=report,
            instrument=event.instrument,
        )

        assert report.metadata["execution_channel"] == "paper"
        assert report.metadata["broker_trade_id"] == "broker-trade-1"
        assert report.metadata["logical_trade_id"] == "C1L1R0B1"
        assert report.metadata["broker_order_id"] == "broker-order-1"
        assert report.metadata["order_status"] == "filled"
        assert aggregate.metadata["strategy_key"] == "request"
        assert aggregate.metadata["broker_trade_id"] == "broker-trade-1"
        assert aggregate.metadata["broker_order_id"] == "broker-order-1"

    def test_strategy_execution_response_records_rebuild_fill_as_entry_and_rebuild(
        self,
    ) -> None:
        task_id = new_uuid()
        event = StrategyEventRequest(
            task_id=task_id,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            action=StrategyAction.OPEN_TRADE,
            instrument=CurrencyPair.of("USD_JPY"),
            side=TradeSide.BUY,
            units=Units("1000"),
            price=Money.of("149.92", "JPY"),
            display_id="C1L1R0B2",
            metadata=Metadata.of(
                is_rebuild=True,
                filled_price_metadata_keys=("filled_entry_price", "filled_rebuild_price"),
            ),
        )

        report = StrategyExecutionResponse(
            event=event,
            order=Order(
                instrument=CurrencyPair.of("USD_JPY"),
                side=OrderSide.BUY,
                units=Units("1000"),
                price=Money.of("149.92", "JPY"),
                status=OrderStatus.FILLED,
                filled_units=Units("1000"),
                average_fill_price=Money.of("149.95", "JPY"),
            ),
        )

        assert report.metadata["filled_entry_price"] == "149.95 JPY"
        assert report.metadata["filled_rebuild_price"] == "149.95 JPY"
