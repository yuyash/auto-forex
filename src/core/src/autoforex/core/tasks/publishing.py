"""Publish strategy requests and execution responses."""

from __future__ import annotations

from autoforex.core.events.bus import EventBus
from autoforex.core.events.event import Event
from autoforex.core.strategies.base import StrategyResult
from autoforex.core.strategies.execution import StrategyExecutionResponse


class StrategyResponseHandler:
    """Publish execution responses to event-bus subscribers."""

    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus

    def handle(self, event: Event) -> None:
        """Publish one execution response."""
        if not isinstance(event, StrategyExecutionResponse):
            return
        self.event_bus.publish(event)


class StrategyPublisher:
    """Publish strategy requests to the event bus."""

    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus

    def publish(
        self,
        result: StrategyResult,
    ) -> None:
        """Publish strategy requests in result order."""
        self.event_bus.publish_many(result.events)
