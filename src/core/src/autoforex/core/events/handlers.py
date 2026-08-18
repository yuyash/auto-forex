"""In-process event handlers."""

from __future__ import annotations

from collections.abc import Callable

from autoforex.core.events.event import Event

type EventPredicate = Callable[[Event], bool]


class RecordingEventHandler:
    """Event handler that records all received events."""

    def __init__(
        self,
        *,
        predicate: EventPredicate | None = None,
        event_class: type[Event] | None = None,
    ) -> None:
        self.predicate = predicate
        self.event_class = event_class
        self.events: list[Event] = []

    def handle(self, event: Event) -> None:
        """Record one event."""
        if self.event_class is not None and not isinstance(event, self.event_class):
            return
        if self.predicate is not None and not self.predicate(event):
            return
        self.events.append(event)
