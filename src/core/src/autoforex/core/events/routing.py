"""Event routing primitives for the in-process event bus."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from threading import RLock
from typing import Protocol

from autoforex.core.events.event import Event
from autoforex.core.events.types import EventType

type EventPredicate = Callable[[Event], bool]


class EventHandler(Protocol):
    """Handler boundary for in-process event processing."""

    def handle(self, event: Event) -> None:
        """Process one event."""


@dataclass(frozen=True, slots=True)
class EventSubscription:
    """One event-bus subscription."""

    handler: EventHandler
    predicate: EventPredicate

    def matches(self, event: Event) -> bool:
        """Return whether this subscription should handle the event."""
        return self.predicate(event)


class EventPredicateFactory:
    """Create event predicates from filtering arguments."""

    @classmethod
    def create(
        cls,
        *,
        predicate: EventPredicate | None = None,
        event_type: EventType | None = None,
        event_class: type[Event] | None = None,
    ) -> EventPredicate:
        """Return one predicate composed from optional filters."""

        def matches(event: Event) -> bool:
            if event_class is not None and not isinstance(event, event_class):
                return False
            if event_type is not None and event.type != event_type:
                return False
            return predicate(event) if predicate is not None else True

        return matches


class EventSubscriptionRegistry:
    """Thread-safe event subscription registry."""

    def __init__(self, handlers: Iterable[EventHandler] = ()) -> None:
        self._subscriptions = [
            EventSubscription(handler=handler, predicate=lambda _event: True)
            for handler in handlers
        ]
        self._lock = RLock()

    def subscribe(
        self,
        handler: EventHandler,
        *,
        predicate: EventPredicate | None = None,
        event_type: EventType | None = None,
        event_class: type[Event] | None = None,
    ) -> EventSubscription:
        """Register an event handler."""
        subscription = EventSubscription(
            handler=handler,
            predicate=EventPredicateFactory.create(
                predicate=predicate,
                event_type=event_type,
                event_class=event_class,
            ),
        )
        with self._lock:
            self._subscriptions.append(subscription)
        return subscription

    def unsubscribe(self, subscription: EventSubscription) -> None:
        """Remove an event handler subscription."""
        with self._lock:
            self._subscriptions = [
                candidate for candidate in self._subscriptions if candidate is not subscription
            ]

    def matching(self, event: Event) -> tuple[EventSubscription, ...]:
        """Return subscriptions matching an event."""
        with self._lock:
            return tuple(
                subscription for subscription in self._subscriptions if subscription.matches(event)
            )
