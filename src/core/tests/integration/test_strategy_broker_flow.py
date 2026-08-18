from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from decimal import Decimal

from autoforex.core import (
    Broker,
    BrokerOrderId,
    CurrencyPair,
    DataSource,
    Metadata,
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
    StrategyEventHandler,
    StrategyEventRequest,
    StrategyParameters,
    StrategyResult,
    TaskType,
    Tick,
    Trade,
    TradeSide,
    Units,
    new_uuid,
)

USD_JPY = CurrencyPair.of("USD_JPY")


class MemoryDataSource(DataSource):
    def __init__(self, ticks: Iterable[Tick]) -> None:
        self._ticks = tuple(ticks)

    def _raw_ticks(
        self,
        *,
        instrument: CurrencyPair,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Tick]:
        _ = start_at
        _ = end_at
        return (tick for tick in self._ticks if tick.instrument == instrument)


class HoldStrategy(Strategy):
    def on_tick(self, tick: Tick, context: StrategyContext) -> StrategyResult:
        return StrategyResult(
            events=(
                StrategyEventRequest(
                    timestamp=tick.timestamp,
                    task_id=context.task_id,
                    action=StrategyAction.HOLD,
                    instrument=tick.instrument,
                    side=None,
                    reason=StrategyDecisionReason(
                        code=StrategyDecisionCode.HOLD,
                        rule_id="hold.default",
                        evidence=Metadata.of(effective_mid=str(tick.effective_mid)),
                    ),
                ),
            )
        )


class MemoryBroker(Broker):
    def __init__(self) -> None:
        self.orders: list[Order] = []
        self.closed_trades: list[Trade] = []
        self.closed_positions: list[tuple[Position, PositionSide]] = []

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
        self.closed_positions.append((position, side))
        state = position.require_side(side)
        amount = units if units is not None else state.units
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
        position = Position.model_validate(
            {
                "instrument": USD_JPY,
                "long": {
                    "units": Units("1000"),
                    "average_entry_price": Money.of("150.10", "JPY"),
                },
            }
        )
        if instrument is not None and instrument != position.instrument:
            return ()
        return (position,)

    def trades(self, *, instrument: CurrencyPair | None = None) -> Sequence[Trade]:
        trade = Trade.model_validate(
            {
                "id": "broker-trade-1",
                "instrument": USD_JPY,
                "side": PositionSide.LONG,
                "units": Units("1000"),
                "price": Money.of("150.10", "JPY"),
                "metadata": Metadata.of(client_trade_id="C1L1R0B1"),
            }
        )
        if instrument is not None and instrument != trade.instrument:
            return ()
        return (trade,)

    def close_trade(self, trade: Trade, *, units: Units | None = None) -> Order:
        self.closed_trades.append(trade)
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


class TestStrategyBrokerFlow:
    def test_core_ports_work_together_for_strategy_and_broker_flow(self) -> None:
        task_id = new_uuid()
        tick = Tick(
            instrument=USD_JPY,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            bid=Money.of("150.10", "JPY"),
            ask=Money.of("150.12", "JPY"),
        )
        data_source = MemoryDataSource([tick])
        strategy = HoldStrategy(
            name="snowball",
            parameters=StrategyParameters.of(risk_percent=Decimal("1.5")),
        )
        context = StrategyContext(
            task_id=task_id,
            task_type=TaskType.BACKTEST,
            instrument=USD_JPY,
            metadata=Metadata.of(strategy_name="snowball"),
        )
        broker = MemoryBroker()

        loaded_ticks = tuple(data_source.ticks(instrument=USD_JPY))
        result = strategy.on_tick(loaded_ticks[0], context)
        placed_order = broker.place_order(
            Order(
                instrument=USD_JPY,
                side=OrderSide.BUY,
                units=Units("1000"),
                price=Money.of("150.12", "JPY"),
                metadata=Metadata.of(event_id="event-1"),
            )
        )

        assert result.events[0].task_id == task_id
        assert result.events[0].reason.code == StrategyDecisionCode.HOLD
        assert strategy.parameters == StrategyParameters.of(risk_percent=Decimal("1.5"))
        assert placed_order.status == OrderStatus.FILLED
        assert broker.orders[0].metadata == Metadata.of(event_id="event-1")

    def test_strategy_event_handler_closes_matching_logical_trade(self) -> None:
        broker = MemoryBroker()
        handler = StrategyEventHandler(broker=broker)
        event = StrategyEventRequest(
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            task_id=new_uuid(),
            display_id="C1L1R0B1",
            action=StrategyAction.CLOSE_TRADE,
            instrument=USD_JPY,
            side=TradeSide.SELL,
            units=Units("1000"),
            price=Money.of("150.20", "JPY"),
            reason=StrategyDecisionReason(
                code=StrategyDecisionCode.EXIT_SIGNAL,
                rule_id="snowball.close.take_profit",
            ),
        )

        reports = handler.execute(event)

        assert reports[0].filled
        assert tuple(str(trade.id) for trade in broker.closed_trades) == ("broker-trade-1",)
        assert broker.closed_positions == []
