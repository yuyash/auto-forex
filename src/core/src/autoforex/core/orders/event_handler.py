"""Dispatch strategy events to action-specific execution handlers."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import nullcontext
from threading import RLock

from autoforex.core.events.event import Event
from autoforex.core.events.routing import EventHandler
from autoforex.core.orders.factory import OrderFactory
from autoforex.core.orders.handlers import (
    CloseTradeExecutor,
    DryRunExecutionSimulator,
    OpenTradeExecutor,
    StrategyExecutionErrorResponseFactory,
)
from autoforex.core.orders.recovery import BrokerExecutionUnresolvedError
from autoforex.core.ports.brokers import Broker
from autoforex.core.strategies.execution import (
    StrategyAction,
    StrategyEventRequest,
    StrategyExecutionResponse,
)


class StrategyEventHandler:
    """Execute strategy requests received through the event bus."""

    def __init__(
        self,
        *,
        response_handler: EventHandler | None = None,
        broker: Broker | None = None,
        dry_run: bool = False,
        order_factory: OrderFactory | None = None,
        simulator: DryRunExecutionSimulator | None = None,
    ) -> None:
        self.response_handler = response_handler
        self.broker = broker
        self.dry_run = dry_run
        self._lock = RLock()
        self.order_factory = order_factory or OrderFactory()
        self.simulator = simulator or DryRunExecutionSimulator()
        self._open_trades = OpenTradeExecutor(
            broker=broker,
            dry_run=dry_run,
            order_factory=self.order_factory,
            simulator=self.simulator,
        )
        self._close_trades = CloseTradeExecutor(
            broker=broker,
            dry_run=dry_run,
            simulator=self.simulator,
        )

    def handle(self, event: Event) -> None:
        """Execute one request and dispatch its responses."""
        if not isinstance(event, StrategyEventRequest):
            return
        if self.response_handler is None:
            msg = "strategy event executor requires a response handler when used as a handler"
            raise RuntimeError(msg)
        for response in self.execute_many((event,)):
            self.response_handler.handle(response)

    def execute_many(
        self,
        events: Sequence[StrategyEventRequest],
    ) -> tuple[StrategyExecutionResponse, ...]:
        """Execute events in order and return broker responses."""
        reports: list[StrategyExecutionResponse] = []
        with self._lock:
            for event in events:
                try:
                    reports.extend(
                        response
                        for response in self.execute(event)
                        if not bool(response.metadata.get("execution_response_applied", False))
                    )
                except BrokerExecutionUnresolvedError:
                    raise
                except Exception as exc:
                    reports.append(StrategyExecutionErrorResponseFactory.from_exception(event, exc))
        return tuple(reports)

    def execute(self, event: StrategyEventRequest) -> tuple[StrategyExecutionResponse, ...]:
        """Execute one strategy event."""
        scope_factory = getattr(self.broker, "execution_scope", None)
        scope = scope_factory(event) if callable(scope_factory) else nullcontext()
        with scope:
            if event.action == StrategyAction.HOLD:
                return ()
            if event.action == StrategyAction.OPEN_TRADE:
                return (self._open_trades.execute(event),)
            if event.action == StrategyAction.CLOSE_TRADE:
                return self._close_trades.execute(event)
            return (
                StrategyExecutionErrorResponseFactory.from_message(
                    event,
                    f"unsupported strategy event: {event.action.value}",
                ),
            )
