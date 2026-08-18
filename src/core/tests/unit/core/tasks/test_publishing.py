from collections.abc import Sequence
from datetime import UTC, datetime

from autoforex.core import (
    BacktestTaskDefinition,
    CurrencyPair,
    EventBus,
    ExecutableTask,
    InMemoryTaskRegistry,
    ManualClock,
    Money,
    RecordingEventHandler,
    Strategy,
    StrategyAction,
    StrategyContext,
    StrategyEvent,
    StrategyEventHandler,
    StrategyEventRequest,
    StrategyExecutionResponse,
    StrategyExecutor,
    StrategyParameters,
    StrategyPublisher,
    StrategyResponseHandler,
    StrategyResult,
    StrategyState,
    TaskExecutionControl,
    Tick,
    TradeSide,
    Units,
    new_uuid,
)
from autoforex.core.tasks.runner import TaskLifecycle
from autoforex.core.tasks.runner_support import ObserverNotifier


class RecordingExecutionStrategy(Strategy):
    def __init__(self) -> None:
        super().__init__(name="recording-execution")
        self.reports: list[tuple[StrategyExecutionResponse, ...]] = []
        self.balances: list[Money] = []

    def on_start(self, context: StrategyContext) -> StrategyResult:
        return StrategyResult(
            events=(
                StrategyEventRequest(
                    task_id=context.task_id,
                    timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                    display_id="T1",
                    action=StrategyAction.OPEN_TRADE,
                    instrument=context.instrument,
                    side=TradeSide.BUY,
                    units=Units("100"),
                    price=Money.of("10", "USD"),
                ),
            )
        )

    def on_tick(self, tick: Tick, context: StrategyContext) -> StrategyResult:
        return StrategyResult(
            events=(
                StrategyEventRequest(
                    task_id=context.task_id,
                    timestamp=tick.timestamp,
                    display_id="T1",
                    action=StrategyAction.CLOSE_TRADE,
                    instrument=context.instrument,
                    side=TradeSide.SELL,
                    units=Units("100"),
                    price=tick.bid,
                ),
            )
        )

    def on_execution_reports(
        self,
        reports: Sequence[StrategyExecutionResponse],
        context: StrategyContext,
    ) -> StrategyState:
        self.reports.append(tuple(reports))
        self.balances.append(context.account_balance)
        report_count = int(context.state.get("report_count", 0)) + len(reports)
        return StrategyState.of(report_count=report_count)


class MultiRequestRecordingStrategy(RecordingExecutionStrategy):
    def on_start(self, context: StrategyContext) -> StrategyResult:
        requests = tuple(
            StrategyEventRequest(
                task_id=context.task_id,
                timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                display_id=f"T{index}",
                action=StrategyAction.OPEN_TRADE,
                instrument=context.instrument,
                side=TradeSide.BUY,
                units=Units("100"),
                price=Money.of("10", "USD"),
            )
            for index in range(1, 3)
        )
        return StrategyResult(events=requests)

    def on_tick(self, tick: Tick, context: StrategyContext) -> StrategyResult:
        _ = tick
        _ = context
        return StrategyResult()


class PassiveRecordingStrategy(RecordingExecutionStrategy):
    def on_start(self, context: StrategyContext) -> StrategyResult:
        _ = context
        return StrategyResult()

    def on_tick(self, tick: Tick, context: StrategyContext) -> StrategyResult:
        _ = tick
        _ = context
        return StrategyResult()


def task_definition() -> BacktestTaskDefinition:
    return BacktestTaskDefinition(
        name="Publisher test",
        instrument=CurrencyPair.of("EUR_USD"),
        parameters=StrategyParameters.of(
            account={
                "initial_balance": {
                    "amount": "1000",
                    "currency": "USD",
                }
            }
        ),
        start_at=datetime(2026, 1, 1, tzinfo=UTC),
        end_at=datetime(2026, 1, 2, tzinfo=UTC),
    )


def strategy_executor(
    *,
    strategy: Strategy,
    bus: EventBus,
) -> tuple[ExecutableTask, InMemoryTaskRegistry, StrategyExecutor]:
    definition = task_definition()
    task = ExecutableTask.from_definition(definition)
    registry = InMemoryTaskRegistry((task,))
    clock = ManualClock(definition.start_at)
    response_handler = StrategyResponseHandler(bus)
    executor = StrategyExecutor(
        task_id=task.id,
        strategy=strategy,
        publisher=StrategyPublisher(bus),
        event_handler=StrategyEventHandler(
            response_handler=response_handler,
            dry_run=True,
        ),
        registry=registry,
        observer_notifier=ObserverNotifier(
            observers=(),
            event_bus=bus,
            clock=clock,
            task_id=task.id,
        ),
        event_bus=bus,
        lifecycle=TaskLifecycle(
            task_id=task.id,
            event_bus=bus,
            registry=registry,
            clock=clock,
        ),
    )
    return task, registry, executor


class TestTaskEventPublishing:
    def test_strategy_response_handler_publishes_response_through_event_bus(self) -> None:
        bus = EventBus(record_history=True)
        recorder = RecordingEventHandler(event_class=StrategyExecutionResponse)
        bus.subscribe(recorder, event_class=StrategyExecutionResponse)
        handler = StrategyResponseHandler(bus)
        request = StrategyEventRequest(
            task_id=new_uuid(),
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            display_id="T1",
            action=StrategyAction.OPEN_TRADE,
            instrument=CurrencyPair.of("EUR_USD"),
            side=TradeSide.BUY,
            units=Units("100"),
            price=Money.of("10", "USD"),
        )
        response = StrategyExecutionResponse(
            event=request,
            execution_error="broker rejected request",
        )

        handler.handle(response)

        assert recorder.events == [response]
        assert bus.select(event_class=StrategyExecutionResponse) == (response,)

    def test_strategy_executor_receives_responses_through_event_bus(self) -> None:
        strategy = RecordingExecutionStrategy()
        bus = EventBus(record_history=True)
        task, registry, executor = strategy_executor(strategy=strategy, bus=bus)
        instrument = task.instrument
        tick = Tick(
            instrument=instrument,
            timestamp=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
            bid=Money.of("12", "USD"),
            ask=Money.of("12", "USD"),
        )

        with executor:
            task = executor.start(task)
            step = executor.tick(
                task=task,
                tick=tick,
                control=TaskExecutionControl(),
            )
            context = registry.current_context(step.task.id)

        assert context.account_balance == Money.of("1200", "USD")
        assert context.state == StrategyState.of(report_count=2)
        assert strategy.balances == [
            Money.of("1000", "USD"),
            Money.of("1200", "USD"),
        ]
        assert len(strategy.reports) == 2
        assert sum(isinstance(event, StrategyEventRequest) for event in bus.history) == 2
        assert sum(isinstance(event, StrategyExecutionResponse) for event in bus.history) == 2
        assert sum(isinstance(event, StrategyEvent) for event in bus.history) == 2
        assert bus.pending_strategy_request_count == 0

        orphan_request = StrategyEventRequest(
            id=new_uuid(),
            task_id=task.id,
            timestamp=datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
            display_id="T2",
            action=StrategyAction.OPEN_TRADE,
            instrument=instrument,
            side=TradeSide.BUY,
            units=Units("100"),
            price=Money.of("12", "USD"),
        )
        bus.publish(orphan_request)

        assert bus.pending_strategy_requests == (orphan_request,)

    def test_strategy_executor_processes_responses_in_delivery_order(self) -> None:
        strategy = MultiRequestRecordingStrategy()
        bus = EventBus()
        task, registry, executor = strategy_executor(strategy=strategy, bus=bus)

        with executor:
            task = executor.start(task)
            context = registry.current_context(task.id)

        assert len(strategy.reports) == 2
        assert all(len(reports) == 1 for reports in strategy.reports)
        assert [reports[0].event.display_id for reports in strategy.reports] == ["T1", "T2"]
        assert context.state == StrategyState.of(report_count=2)

    def test_strategy_executor_handles_external_response_through_event_bus(self) -> None:
        strategy = PassiveRecordingStrategy()
        bus = EventBus()
        task, registry, executor = strategy_executor(strategy=strategy, bus=bus)

        with executor:
            executor.start(task)
            request = StrategyEventRequest(
                task_id=task.id,
                timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                display_id="T1",
                action=StrategyAction.OPEN_TRADE,
                instrument=task.instrument,
                side=TradeSide.BUY,
                units=Units("100"),
                price=Money.of("10", "USD"),
            )
            StrategyResponseHandler(bus).handle(
                StrategyExecutionResponse(
                    event=request,
                    execution_error="broker rejected request",
                )
            )

        assert len(strategy.reports) == 1
        assert len(strategy.reports[0]) == 1
        assert registry.get(task.id).strategy_state == StrategyState.of(report_count=1)
