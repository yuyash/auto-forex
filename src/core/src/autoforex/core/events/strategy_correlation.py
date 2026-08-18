"""Strategy request/response correlation for event publication."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

from autoforex.core.events.aggregation import StrategyEventAggregator
from autoforex.core.events.event import Event
from autoforex.core.events.pending_strategy import StrategyRequestTimeout
from autoforex.core.strategies.execution import StrategyEventRequest


class StrategyEventCorrelation:
    """Correlate strategy requests and broker execution responses."""

    def __init__(self, *, request_timeout: timedelta | None = None) -> None:
        self._aggregator = StrategyEventAggregator(request_timeout=request_timeout)

    @property
    def request_timeout(self) -> timedelta | None:
        """Return how long a strategy request may remain without a broker response."""
        return self._aggregator.request_timeout

    @request_timeout.setter
    def request_timeout(self, timeout: timedelta | None) -> None:
        self._aggregator.request_timeout = StrategyRequestTimeout.validate(timeout)

    def events_for(self, event: Event) -> tuple[Event, ...]:
        """Return concrete events derived from a publication input."""
        return self._aggregator.events_for(event)

    @property
    def pending_requests(self) -> Sequence[StrategyEventRequest]:
        """Return strategy requests waiting for an execution response."""
        return self._aggregator.pending_requests

    @property
    def pending_request_count(self) -> int:
        """Return the number of strategy requests waiting for execution responses."""
        return self._aggregator.pending_request_count

    def expire_pending(
        self,
        *,
        timestamp: datetime,
        task_id: UUID | None = None,
        timeout: timedelta | None = None,
    ) -> tuple[Event, ...]:
        """Fail pending strategy requests older than the configured timeout."""
        return self._aggregator.expire_pending(
            timestamp=timestamp,
            task_id=task_id,
            timeout=timeout,
        )

    def clear_pending(
        self,
        *,
        task_id: UUID | None = None,
        reason: str,
        timestamp: datetime | None = None,
    ) -> tuple[Event, ...]:
        """Clear pending strategy requests, returning diagnostics."""
        return self._aggregator.clear_pending(
            task_id=task_id,
            reason=reason,
            timestamp=timestamp,
        )
