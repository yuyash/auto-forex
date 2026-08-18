"""Optional in-memory event history."""

from __future__ import annotations

from threading import RLock

from autoforex.core.events.event import Event
from autoforex.core.events.routing import EventPredicate


class EventHistoryRecorder:
    """Record and query event history when enabled."""

    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled
        self._events: list[Event] = []
        self._lock = RLock()

    def record(self, event: Event) -> None:
        """Record one event when history is enabled."""
        if not self.enabled:
            return
        with self._lock:
            self._events.append(event)

    def snapshot(self) -> tuple[Event, ...]:
        """Return all recorded events."""
        with self._lock:
            return tuple(self._events)

    def select(self, predicate: EventPredicate) -> tuple[Event, ...]:
        """Return recorded events matching a predicate."""
        with self._lock:
            return tuple(event for event in self._events if predicate(event))
