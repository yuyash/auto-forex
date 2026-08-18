"""Action-specific strategy execution handlers."""

from __future__ import annotations

from autoforex.core.models.brokers import Order, OrderStatus
from autoforex.core.models.values import Units
from autoforex.core.orders.closing import (
    BrokerCloseTradeTargetResolver,
    CloseTradeDryRunOrderFactory,
)
from autoforex.core.orders.factory import OrderFactory
from autoforex.core.orders.matching import LogicalTradeIdResolver
from autoforex.core.ports.brokers import Broker
from autoforex.core.strategies.execution import (
    StrategyEventRequest,
    StrategyExecutionResponse,
    TradeSide,
)


class DryRunExecutionSimulator:
    """Create filled broker orders for dry-run strategy execution."""

    @staticmethod
    def filled_order(order: Order) -> Order:
        """Return a filled copy of an order."""
        return order.evolve(
            status=OrderStatus.FILLED,
            filled_units=order.units,
            average_fill_price=order.price,
        )


class StrategyExecutionErrorResponseFactory:
    """Create normalized strategy execution error responses."""

    @staticmethod
    def from_exception(
        event: StrategyEventRequest,
        exc: Exception,
    ) -> StrategyExecutionResponse:
        """Return an execution response for an unexpected exception."""
        return StrategyExecutionResponse(
            event=event,
            execution_error=f"{exc.__class__.__name__}: {exc}",
        )

    @staticmethod
    def from_message(
        event: StrategyEventRequest,
        message: str,
    ) -> StrategyExecutionResponse:
        """Return an execution response for a validation or broker error."""
        return StrategyExecutionResponse(event=event, execution_error=message)


class OpenTradeExecutor:
    """Execute open-trade strategy requests."""

    def __init__(
        self,
        *,
        broker: Broker | None,
        dry_run: bool,
        order_factory: OrderFactory,
        simulator: DryRunExecutionSimulator,
    ) -> None:
        self.broker = broker
        self.dry_run = dry_run
        self.order_factory = order_factory
        self.simulator = simulator

    def execute(self, event: StrategyEventRequest) -> StrategyExecutionResponse:
        """Execute one open-trade request."""
        side = event.side
        units = event.units
        if side is None or units is None:
            return StrategyExecutionErrorResponseFactory.from_message(
                event,
                "open-trade event requires side and units",
            )
        order = self.order_factory.open_trade_order(
            event=event,
            side=side,
            units=units,
        )
        if self.dry_run:
            return StrategyExecutionResponse(
                event=event,
                order=self.simulator.filled_order(order),
            )
        if self.broker is None:
            return StrategyExecutionErrorResponseFactory.from_message(
                event,
                "broker is required when dry_run is false",
            )
        return StrategyExecutionResponse(event=event, order=self.broker.place_order(order))


class CloseTradeExecutor:
    """Execute close-trade strategy requests."""

    def __init__(
        self,
        *,
        broker: Broker | None,
        dry_run: bool,
        simulator: DryRunExecutionSimulator,
        matcher: type[LogicalTradeIdResolver] = LogicalTradeIdResolver,
        dry_run_orders: CloseTradeDryRunOrderFactory | None = None,
    ) -> None:
        self.broker = broker
        self.dry_run = dry_run
        self.simulator = simulator
        self.matcher = matcher
        self.dry_run_orders = dry_run_orders or CloseTradeDryRunOrderFactory()

    def execute(self, event: StrategyEventRequest) -> tuple[StrategyExecutionResponse, ...]:
        """Execute one close-trade request."""
        side = event.side
        units = event.units
        if side is None:
            return (
                StrategyExecutionErrorResponseFactory.from_message(
                    event,
                    "close-trade event requires side",
                ),
            )
        if self.dry_run:
            return self._execute_dry_run(event, side=side, units=units)
        if self.broker is None:
            return (
                StrategyExecutionErrorResponseFactory.from_message(
                    event,
                    "broker is required when dry_run is false",
                ),
            )
        logical_trade_id = self.matcher.from_event(event)
        if logical_trade_id:
            return self._close_matching_trades(
                event,
                side=side,
                logical_trade_id=logical_trade_id,
                units=units,
            )
        return self._close_matching_positions(event, units=units)

    def _execute_dry_run(
        self,
        event: StrategyEventRequest,
        *,
        side: TradeSide,
        units: Units | None,
    ) -> tuple[StrategyExecutionResponse, ...]:
        if units is None:
            return (
                StrategyExecutionErrorResponseFactory.from_message(
                    event,
                    "dry-run close-trade event requires units",
                ),
            )
        order = self.dry_run_orders.order(event, side=side, units=units)
        return (
            StrategyExecutionResponse(
                event=event,
                order=self.simulator.filled_order(order),
            ),
        )

    def _close_matching_trades(
        self,
        event: StrategyEventRequest,
        *,
        side: TradeSide,
        logical_trade_id: str,
        units: Units | None,
    ) -> tuple[StrategyExecutionResponse, ...]:
        if self.broker is None:
            return ()
        reports: list[StrategyExecutionResponse] = []
        try:
            matching_trades = BrokerCloseTradeTargetResolver(
                broker=self.broker,
                matcher=self.matcher,
            ).trades(event, side=side, logical_trade_id=logical_trade_id)
        except Exception as exc:
            return (StrategyExecutionErrorResponseFactory.from_exception(event, exc),)
        if not matching_trades:
            return (
                StrategyExecutionErrorResponseFactory.from_message(
                    event,
                    f"no matching broker trade found: {logical_trade_id}",
                ),
            )
        for trade in matching_trades:
            try:
                order = self.broker.close_trade(trade, units=units)
            except Exception as exc:
                reports.append(StrategyExecutionErrorResponseFactory.from_exception(event, exc))
                continue
            reports.append(StrategyExecutionResponse(event=event, order=order))
        return tuple(reports)

    def _close_matching_positions(
        self,
        event: StrategyEventRequest,
        *,
        units: Units | None,
    ) -> tuple[StrategyExecutionResponse, ...]:
        reports: list[StrategyExecutionResponse] = []
        try:
            if self.broker is None:
                return ()
            matching_position_sides = BrokerCloseTradeTargetResolver(
                broker=self.broker,
                matcher=self.matcher,
            ).position_sides(event)
        except Exception as exc:
            return (StrategyExecutionErrorResponseFactory.from_exception(event, exc),)
        for position, position_side in matching_position_sides:
            try:
                order = self.broker.close_position(
                    position=position,
                    side=position_side,
                    units=units,
                )
            except Exception as exc:
                reports.append(StrategyExecutionErrorResponseFactory.from_exception(event, exc))
                continue
            reports.append(StrategyExecutionResponse(event=event, order=order))
        if not reports:
            reports.append(
                StrategyExecutionErrorResponseFactory.from_message(
                    event,
                    "no matching broker position found",
                )
            )
        return tuple(reports)
