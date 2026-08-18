"""Event aggregation policies layered on top of the in-process event bus."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from autoforex.core.events.event import Event
from autoforex.core.events.pending_strategy import (
    PendingStrategyRequestEventFactory,
    PendingStrategyRequestStore,
    StrategyRequestTimeout,
)
from autoforex.core.strategies.execution import (
    StrategyEvent,
    StrategyEventRequest,
    StrategyExecutionResponse,
)


@dataclass(slots=True)
class StrategyEventAggregator:
    """Aggregate strategy requests and broker responses into StrategyEvent records."""

    request_timeout: timedelta | None = None
    pending: PendingStrategyRequestStore = field(
        default_factory=PendingStrategyRequestStore,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        self.request_timeout = StrategyRequestTimeout.validate(self.request_timeout)

    def events_for(self, event: Event) -> tuple[Event, ...]:
        """Return the concrete events that should be published for one input event."""
        if isinstance(event, StrategyEventRequest):
            return self._events_for_request(event)
        if isinstance(event, StrategyExecutionResponse):
            return self._events_for_response(event)
        return (event,)

    @property
    def pending_requests(self) -> Sequence[StrategyEventRequest]:
        """Return strategy requests waiting for broker execution responses."""
        return self.pending.values()

    @property
    def pending_request_count(self) -> int:
        """Return the number of strategy requests waiting for broker responses."""
        return self.pending.count()

    def expire_pending(
        self,
        *,
        timestamp: datetime,
        task_id: UUID | None = None,
        timeout: timedelta | None = None,
    ) -> tuple[Event, ...]:
        """Remove timed-out pending requests and return diagnostic events."""
        effective_timeout = (
            StrategyRequestTimeout.validate(timeout)
            if timeout is not None
            else self.request_timeout
        )
        if effective_timeout is None:
            return ()
        expired = self.pending.expire(
            timestamp=timestamp,
            timeout=effective_timeout,
            task_id=task_id,
        )
        return PendingStrategyRequestEventFactory.events(
            expired,
            reason="strategy execution response timeout",
            timestamp=timestamp,
        )

    def clear_pending(
        self,
        *,
        task_id: UUID | None = None,
        reason: str,
        timestamp: datetime | None = None,
    ) -> tuple[Event, ...]:
        """Remove pending requests and return diagnostic events."""
        cleared = self.pending.clear(task_id=task_id)
        return PendingStrategyRequestEventFactory.events(
            cleared,
            reason=reason,
            timestamp=timestamp,
        )

    def _events_for_request(self, request: StrategyEventRequest) -> tuple[Event, ...]:
        if request.requires_broker:
            self.pending.add(request)
            return (request,)
        return (
            request,
            StrategyEvent(
                task_id=request.task_id,
                instrument=request.instrument,
                request=request,
            ),
        )

    def _events_for_response(self, response: StrategyExecutionResponse) -> tuple[Event, ...]:
        request = self._request_for(response)
        return (
            response,
            StrategyEvent(
                task_id=request.task_id,
                instrument=request.instrument,
                request=request,
                response=response,
            ),
        )

    def _request_for(self, response: StrategyExecutionResponse) -> StrategyEventRequest:
        return self.pending.pop(response.event.id, response.event)
