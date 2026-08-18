"""Pending strategy request storage and diagnostics."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from threading import RLock
from uuid import UUID

from autoforex.core.events.event import Event
from autoforex.core.events.types import EventSource, EventType
from autoforex.core.models.metadata import Metadata
from autoforex.core.strategies.execution import StrategyEventRequest


class StrategyRequestTimeout:
    """Validate pending strategy request timeout values."""

    @classmethod
    def validate(cls, timeout: timedelta | None) -> timedelta | None:
        """Return a valid timeout value."""
        if timeout is None:
            return None
        if timeout <= timedelta(0):
            msg = "strategy_request_timeout must be greater than zero"
            raise ValueError(msg)
        return timeout


class PendingStrategyRequestStore:
    """Thread-safe store for strategy requests awaiting broker responses."""

    def __init__(self) -> None:
        self._requests: dict[UUID, StrategyEventRequest] = {}
        self._lock = RLock()

    def add(self, request: StrategyEventRequest) -> None:
        """Store a pending strategy request."""
        with self._lock:
            self._requests[request.id] = request

    def pop(self, request_id: UUID, fallback: StrategyEventRequest) -> StrategyEventRequest:
        """Pop a pending request or return a fallback request."""
        with self._lock:
            return self._requests.pop(request_id, fallback)

    def values(self) -> Sequence[StrategyEventRequest]:
        """Return pending requests."""
        with self._lock:
            return tuple(self._requests.values())

    def count(self) -> int:
        """Return the pending request count."""
        with self._lock:
            return len(self._requests)

    def expire(
        self,
        *,
        timestamp: datetime,
        timeout: timedelta,
        task_id: UUID | None = None,
    ) -> Sequence[StrategyEventRequest]:
        """Remove and return expired pending requests."""
        expired: list[StrategyEventRequest] = []
        with self._lock:
            for request_id, request in tuple(self._requests.items()):
                if task_id is not None and request.task_id != task_id:
                    continue
                if timestamp - request.timestamp < timeout:
                    continue
                expired.append(self._requests.pop(request_id))
        return tuple(expired)

    def clear(self, *, task_id: UUID | None = None) -> Sequence[StrategyEventRequest]:
        """Remove and return pending requests."""
        cleared: list[StrategyEventRequest] = []
        with self._lock:
            for request_id, request in tuple(self._requests.items()):
                if task_id is not None and request.task_id != task_id:
                    continue
                cleared.append(self._requests.pop(request_id))
        return tuple(cleared)


class PendingStrategyRequestEventFactory:
    """Create diagnostics for pending strategy requests removed without responses."""

    @classmethod
    def events(
        cls,
        requests: Sequence[StrategyEventRequest],
        *,
        reason: str,
        timestamp: datetime | None,
    ) -> tuple[Event, ...]:
        """Return diagnostic events for pending requests."""
        return tuple(cls.event(request, reason=reason, timestamp=timestamp) for request in requests)

    @classmethod
    def event(
        cls,
        request: StrategyEventRequest,
        *,
        reason: str,
        timestamp: datetime | None,
    ) -> Event:
        """Return one diagnostic event for a pending request."""
        return Event(
            type=EventType.ERROR_OCCURRED,
            timestamp=timestamp or request.timestamp,
            task_id=request.task_id,
            display_id=request.display_id,
            source=EventSource.CORE,
            metadata=Metadata.of(
                original_event_id=str(request.id),
                original_event_type=request.type.value,
                original_event_source=request.source.value,
                strategy_action=request.action.value,
                display_id=request.display_id,
                reason=reason,
                pending_strategy_request=True,
            ),
        )
