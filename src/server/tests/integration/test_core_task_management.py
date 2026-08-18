from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from time import sleep

import pytest
from autoforex.core import (
    Account,
    AccountId,
    BacktestTaskDefinition,
    Broker,
    BrokerOrderId,
    CurrencyPair,
    DataSource,
    EventBus,
    EventType,
    Money,
    Order,
    OrderSide,
    OrderStatus,
    Position,
    PositionSide,
    Strategy,
    StrategyAction,
    StrategyContext,
    StrategyDecisionCode,
    StrategyDecisionReason,
    StrategyEvent,
    StrategyEventRequest,
    StrategyExecutionResponse,
    StrategyResult,
    TaskManager,
    TaskStatus,
    Tick,
    Trade,
    TradeSide,
    TradingTaskDefinition,
    Units,
)

USD_JPY = CurrencyPair.of("USD_JPY")
TEST_ACCOUNT = Account(id=AccountId.of("test-account"))


class MemoryDataSource(DataSource):
    def __init__(
        self,
        ticks: Iterable[Tick],
        *,
        repeat: bool = False,
        delay_seconds: float = 0,
    ) -> None:
        self._ticks = tuple(ticks)
        self._repeat = repeat
        self._delay_seconds = delay_seconds

    def _raw_ticks(
        self,
        *,
        instrument: CurrencyPair,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Tick]:
        _ = start_at
        _ = end_at
        while True:
            for tick in self._ticks:
                if tick.instrument != instrument:
                    continue
                if self._delay_seconds:
                    sleep(self._delay_seconds)
                yield tick
            if not self._repeat:
                return


class OpeningStrategy(Strategy):
    def on_tick(self, tick: Tick, context: StrategyContext) -> StrategyResult:
        return StrategyResult(
            events=(
                StrategyEventRequest(
                    timestamp=tick.timestamp,
                    task_id=context.task_id,
                    action=StrategyAction.OPEN_TRADE,
                    instrument=tick.instrument,
                    side=TradeSide.BUY,
                    units=Units("1000"),
                    price=tick.ask,
                    reason=StrategyDecisionReason(
                        code=StrategyDecisionCode.ENTRY_SIGNAL,
                        rule_id="opening.first_tick",
                    ),
                ),
            )
        )


class HoldStrategy(Strategy):
    def on_tick(self, tick: Tick, context: StrategyContext) -> StrategyResult:
        _ = tick
        _ = context
        return StrategyResult()


class MemoryBroker(Broker):
    def __init__(self) -> None:
        self.orders: list[Order] = []

    def place_order(self, order: Order) -> Order:
        self.orders.append(order)
        return order.evolve(
            status=OrderStatus.FILLED,
            broker_order_id=BrokerOrderId.of("order-1"),
            filled_units=order.units,
            average_fill_price=order.price,
        )

    def close_position(
        self,
        *,
        position: Position,
        side: PositionSide,
        units: Units | None = None,
    ) -> Order:
        state = position.require_side(side)
        amount = units or state.units
        return Order(
            status=OrderStatus.FILLED,
            broker_order_id=BrokerOrderId.of("close-order-1"),
            instrument=position.instrument,
            side=OrderSide.SELL if side == PositionSide.LONG else OrderSide.BUY,
            units=amount,
            filled_units=amount,
            average_fill_price=state.average_entry_price,
        )

    def positions(self, *, instrument: CurrencyPair | None = None) -> Sequence[Position]:
        _ = instrument
        return ()

    def trades(self, *, instrument: CurrencyPair | None = None) -> Sequence[Trade]:
        _ = instrument
        return ()

    def close_trade(self, trade: Trade, *, units: Units | None = None) -> Order:
        amount = units or trade.units
        return Order(
            status=OrderStatus.FILLED,
            broker_order_id=BrokerOrderId.of("close-trade-order-1"),
            instrument=trade.instrument,
            side=OrderSide.SELL if trade.side == PositionSide.LONG else OrderSide.BUY,
            units=amount,
            filled_units=amount,
            average_fill_price=trade.price,
        )


class FailingBroker(MemoryBroker):
    def place_order(self, order: Order) -> Order:
        _ = order
        msg = "broker did not return an order"
        raise RuntimeError(msg)


class TestTaskManagement:
    def test_backtest_manager_runs_ticks_and_handles_broker_events(self) -> None:
        tick = Tick(
            instrument=USD_JPY,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            bid=Money.of("150.10", "JPY"),
            ask=Money.of("150.12", "JPY"),
        )
        definition = BacktestTaskDefinition(
            name="Backtest USD_JPY",
            instrument=USD_JPY,
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        broker = MemoryBroker()
        event_bus = EventBus(record_history=True)
        manager = TaskManager(event_bus=event_bus, max_workers=1)

        run = manager.start_backtest(
            definition,
            data_source=MemoryDataSource([tick]),
            strategy=OpeningStrategy(
                name="opening",
            ),
            broker=broker,
        )
        finished = run.wait(timeout=2)
        manager.shutdown()

        assert run.task.status == TaskStatus.RUNNING
        assert run.task.started_at == definition.start_at
        assert finished.status == TaskStatus.COMPLETED
        assert finished.completed_at == definition.end_at
        assert finished.run_count == 1
        assert broker.orders[0].side == OrderSide.BUY
        assert broker.orders[0].id.value.version == 7
        assert any(event.type == EventType.TASK_COMPLETED for event in event_bus.history)
        strategy_event = event_bus.select(event_class=StrategyEvent)[0]
        report_event = event_bus.select(event_class=StrategyExecutionResponse)[0]
        completed_event = next(
            event for event in event_bus.history if event.type == EventType.TASK_COMPLETED
        )
        assert isinstance(strategy_event, StrategyEvent)
        assert isinstance(report_event, StrategyExecutionResponse)
        assert strategy_event.timestamp == tick.timestamp
        assert strategy_event.action == StrategyAction.OPEN_TRADE
        assert report_event.type == EventType.ORDER_FILLED
        assert strategy_event.request is report_event.event
        assert strategy_event.response is report_event
        assert completed_event.timestamp == definition.end_at

    def test_backtest_manager_records_broker_exceptions_as_execution_responses(
        self,
    ) -> None:
        tick = Tick(
            instrument=USD_JPY,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            bid=Money.of("150.10", "JPY"),
            ask=Money.of("150.12", "JPY"),
        )
        definition = BacktestTaskDefinition(
            name="Backtest USD_JPY",
            instrument=USD_JPY,
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        event_bus = EventBus(record_history=True)
        manager = TaskManager(event_bus=event_bus, max_workers=1)

        run = manager.start_backtest(
            definition,
            data_source=MemoryDataSource([tick]),
            strategy=OpeningStrategy(name="opening"),
            broker=FailingBroker(),
        )
        finished = run.wait(timeout=2)
        manager.shutdown()

        report_event = event_bus.select(event_class=StrategyExecutionResponse)[0]
        strategy_event = event_bus.select(event_class=StrategyEvent)[0]
        assert finished.status == TaskStatus.COMPLETED
        assert report_event.execution_error == "RuntimeError: broker did not return an order"
        assert strategy_event.request is report_event.event
        assert strategy_event.response is report_event
        assert event_bus.pending_strategy_requests == ()

    def test_backtest_manager_restarts_completed_task(self) -> None:
        tick = Tick(
            instrument=USD_JPY,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            bid=Money.of("150.10", "JPY"),
            ask=Money.of("150.12", "JPY"),
        )
        definition = BacktestTaskDefinition(
            name="Backtest USD_JPY",
            instrument=USD_JPY,
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        manager = TaskManager(max_workers=1)

        run = manager.start_backtest(
            definition,
            data_source=MemoryDataSource([tick]),
            strategy=HoldStrategy(
                name="hold",
            ),
        )
        first_finished = run.wait(timeout=2)
        restarted = run.restart(timeout=2)
        second_finished = restarted.wait(timeout=2)
        manager.shutdown()

        assert first_finished.status == TaskStatus.COMPLETED
        assert restarted.task.status == TaskStatus.RUNNING
        assert restarted.task.started_at == definition.start_at
        assert second_finished.status == TaskStatus.COMPLETED
        assert second_finished.completed_at == definition.end_at
        assert second_finished.run_count == 2

    def test_trading_manager_stops_running_task(self) -> None:
        tick = Tick(
            instrument=USD_JPY,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            bid=Money.of("150.10", "JPY"),
            ask=Money.of("150.12", "JPY"),
        )
        definition = TradingTaskDefinition(
            name="Trading USD_JPY",
            instrument=USD_JPY,
            account=TEST_ACCOUNT,
            dry_run=True,
        )
        manager = TaskManager(max_workers=1)

        run = manager.start_trading(
            definition,
            data_source=MemoryDataSource([tick], repeat=True, delay_seconds=0.01),
            strategy=HoldStrategy(
                name="hold",
            ),
        )
        sleep(0.03)
        stopped = run.stop()
        finished = run.wait(timeout=2)
        manager.shutdown()

        assert stopped.status == TaskStatus.STOPPED
        assert finished.status == TaskStatus.STOPPED

    def test_task_manager_context_manager_stops_running_tasks_on_exit(self) -> None:
        tick = Tick(
            instrument=USD_JPY,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            bid=Money.of("150.10", "JPY"),
            ask=Money.of("150.12", "JPY"),
        )
        definition = TradingTaskDefinition(
            name="Trading USD_JPY",
            instrument=USD_JPY,
            account=TEST_ACCOUNT,
            dry_run=True,
        )

        with TaskManager(max_workers=1) as manager:
            run = manager.start_trading(
                definition,
                data_source=MemoryDataSource([tick], repeat=True, delay_seconds=0.01),
                strategy=HoldStrategy(name="hold"),
            )
            sleep(0.03)

        assert manager.get(run.id).status == TaskStatus.STOPPED

    def test_trading_dry_run_does_not_call_broker_even_when_broker_is_configured(self) -> None:
        tick = Tick(
            instrument=USD_JPY,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            bid=Money.of("150.10", "JPY"),
            ask=Money.of("150.12", "JPY"),
        )
        definition = TradingTaskDefinition(
            name="Trading USD_JPY",
            instrument=USD_JPY,
            account=TEST_ACCOUNT,
            dry_run=True,
        )
        broker = MemoryBroker()
        event_bus = EventBus(record_history=True)
        manager = TaskManager(event_bus=event_bus, max_workers=1)

        run = manager.start_trading(
            definition,
            data_source=MemoryDataSource([tick]),
            strategy=OpeningStrategy(name="opening"),
            broker=broker,
        )
        finished = run.wait(timeout=2)
        manager.shutdown()

        assert finished.status == TaskStatus.STOPPED
        assert broker.orders == []
        report_event = event_bus.select(event_class=StrategyExecutionResponse)[0]
        assert isinstance(report_event, StrategyExecutionResponse)
        assert report_event.order is not None
        assert report_event.order.status == OrderStatus.FILLED

    def test_trading_requires_broker_when_dry_run_is_disabled(self) -> None:
        tick = Tick(
            instrument=USD_JPY,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            bid=Money.of("150.10", "JPY"),
            ask=Money.of("150.12", "JPY"),
        )
        definition = TradingTaskDefinition(
            name="Trading USD_JPY",
            instrument=USD_JPY,
            account=TEST_ACCOUNT,
            dry_run=False,
        )
        manager = TaskManager(max_workers=1)

        with pytest.raises(ValueError, match="requires broker"):
            manager.start_trading(
                definition,
                data_source=MemoryDataSource([tick]),
                strategy=OpeningStrategy(name="opening"),
            )

        manager.shutdown()
