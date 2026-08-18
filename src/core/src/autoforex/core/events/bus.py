"""Generic in-process event bus."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, TypeVar, overload
from uuid import UUID

from autoforex.core.events.event import Event
from autoforex.core.events.history import EventHistoryRecorder
from autoforex.core.events.routing import (
    EventHandler,
    EventPredicate,
    EventPredicateFactory,
    EventSubscription,
    EventSubscriptionRegistry,
)
from autoforex.core.events.strategy_correlation import StrategyEventCorrelation
from autoforex.core.events.types import EventSource, EventType
from autoforex.core.models.metadata import Metadata

if TYPE_CHECKING:
    from autoforex.core.strategies.execution import StrategyEventRequest

EventT = TypeVar("EventT", bound=Event)


@dataclass(frozen=True, slots=True)
class EventPublication:
    """Result of successfully publishing one event to matching handlers."""

    event: Event
    delivered_count: int


class EventHandlerError(RuntimeError):
    """Raised when an event handler fails while processing an event."""

    def __init__(self, *, event: Event, handler: EventHandler, cause: Exception) -> None:
        self.event = event
        self.handler = handler
        self.cause = cause
        handler_type = f"{handler.__class__.__module__}.{handler.__class__.__qualname__}"
        super().__init__(f"event handler {handler_type} failed for {event.type.value}: {cause}")


class EventBus:
    """Synchronous in-process event bus with filtering and handler results."""

    def __init__(
        self,
        handlers: Iterable[EventHandler] = (),
        *,
        record_history: bool = False,
        strategy_request_timeout: timedelta | None = None,
    ) -> None:
        self._subscriptions = EventSubscriptionRegistry(handlers)
        self._history = EventHistoryRecorder(enabled=record_history)
        self._strategy_events = StrategyEventCorrelation(request_timeout=strategy_request_timeout)

    @property
    def strategy_request_timeout(self) -> timedelta | None:
        """Return how long a strategy request may remain without a broker response."""
        return self._strategy_events.request_timeout

    @strategy_request_timeout.setter
    def strategy_request_timeout(self, timeout: timedelta | None) -> None:
        self._strategy_events.request_timeout = timeout

    def subscribe(
        self,
        handler: EventHandler,
        *,
        predicate: EventPredicate | None = None,
        event_type: EventType | None = None,
        event_class: type[Event] | None = None,
    ) -> EventSubscription:
        """Register an event handler."""
        return self._subscriptions.subscribe(
            handler,
            predicate=predicate,
            event_type=event_type,
            event_class=event_class,
        )

    def unsubscribe(self, subscription: EventSubscription) -> None:
        """Remove an event handler subscription."""
        self._subscriptions.unsubscribe(subscription)

    def publish(self, event: Event) -> EventPublication:
        """Publish one event to all handlers."""
        events = self._events_to_publish(event)
        delivered_count = 0
        for published_event in events:
            publication = self._publish_one(published_event)
            delivered_count += publication.delivered_count

        return EventPublication(
            event=event,
            delivered_count=delivered_count,
        )

    def _publish_one(self, event: Event) -> EventPublication:
        """Publish a concrete event without deriving aggregate events."""
        self._history.record(event)
        subscriptions = self._subscriptions.matching(event)

        delivered_count = 0
        for subscription in subscriptions:
            try:
                subscription.handler.handle(event)
            except Exception as exc:
                failure_event = self._handler_failure_event(event, subscription.handler, exc)
                self._history.record(failure_event)
                raise EventHandlerError(
                    event=event,
                    handler=subscription.handler,
                    cause=exc,
                ) from exc
            else:
                delivered_count += 1

        return EventPublication(
            event=event,
            delivered_count=delivered_count,
        )

    def _events_to_publish(self, event: Event) -> tuple[Event, ...]:
        return self._strategy_events.events_for(event)

    def publish_many(self, events: Iterable[Event]) -> None:
        """Publish events in order."""
        for event in events:
            self.publish(event)

    @property
    def pending_strategy_requests(self) -> Sequence[StrategyEventRequest]:
        """Return strategy requests waiting for an execution response."""
        return self._strategy_events.pending_requests

    @property
    def pending_strategy_request_count(self) -> int:
        """Return the number of strategy requests waiting for execution responses."""
        return self._strategy_events.pending_request_count

    def expire_pending_strategy_requests(
        self,
        *,
        timestamp: datetime,
        task_id: UUID | None = None,
        timeout: timedelta | None = None,
    ) -> tuple[Event, ...]:
        """Fail pending strategy requests older than the configured timeout."""
        events = self._strategy_events.expire_pending(
            timestamp=timestamp,
            task_id=task_id,
            timeout=timeout,
        )
        self.publish_many(events)
        return events

    def clear_pending_strategy_requests(
        self,
        *,
        task_id: UUID | None = None,
        reason: str,
        timestamp: datetime | None = None,
    ) -> tuple[Event, ...]:
        """Clear pending strategy requests, publishing diagnostics for each request."""
        events = self._strategy_events.clear_pending(
            task_id=task_id,
            reason=reason,
            timestamp=timestamp,
        )
        self.publish_many(events)
        return events

    @property
    def history(self) -> Sequence[Event]:
        """Return events published by this bus when history recording is enabled."""
        return self._history.snapshot()

    @overload
    def select(
        self,
        *,
        predicate: EventPredicate | None = None,
        event_type: EventType | None = None,
        event_class: type[EventT],
    ) -> tuple[EventT, ...]: ...

    @overload
    def select(
        self,
        *,
        predicate: EventPredicate | None = None,
        event_type: EventType | None = None,
        event_class: None = None,
    ) -> tuple[Event, ...]: ...

    def select(
        self,
        *,
        predicate: EventPredicate | None = None,
        event_type: EventType | None = None,
        event_class: type[Event] | None = None,
    ) -> tuple[Event, ...]:
        """Return historical events matching the given filters."""
        match = EventPredicateFactory.create(
            predicate=predicate,
            event_type=event_type,
            event_class=event_class,
        )
        return self._history.select(match)

    @staticmethod
    def _handler_failure_event(
        event: Event,
        handler: EventHandler,
        exc: Exception,
    ) -> Event:
        handler_type = f"{handler.__class__.__module__}.{handler.__class__.__qualname__}"
        return Event(
            type=EventType.ERROR_OCCURRED,
            task_id=event.task_id,
            source=EventSource.CORE,
            metadata=Metadata.of(
                original_event_id=str(event.id),
                original_event_type=event.type.value,
                original_event_source=event.source.value,
                handler_type=handler_type,
                exception_type=exc.__class__.__name__,
                exception_message=str(exc),
            ),
        )
