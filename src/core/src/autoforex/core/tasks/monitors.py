"""Background task execution monitors."""

from __future__ import annotations

from datetime import datetime, timedelta
from threading import Event as ThreadEvent
from threading import Thread

from autoforex.core.clock import SystemClock
from autoforex.core.events.bus import EventBus
from autoforex.core.logging import get_logger
from autoforex.core.tasks.registry import TaskRegistry
from autoforex.core.tasks.runtime import TaskRuntimeRegistry

_LOGGER = get_logger(__name__)


class StrategyRequestTimeoutMonitor:
    """Expire pending broker requests for live trading tasks without ticks."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        registry: TaskRegistry,
        runtimes: TaskRuntimeRegistry,
        interval: timedelta | None,
    ) -> None:
        self.event_bus = event_bus
        self.registry = registry
        self.runtimes = runtimes
        self.interval = interval
        self._stop = ThreadEvent()
        self._thread = self._start()

    @classmethod
    def interval_for(
        cls,
        *,
        configured: timedelta | None,
        timeout: timedelta | None,
    ) -> timedelta | None:
        """Return the effective monitor polling interval."""
        if configured is not None:
            if configured <= timedelta(0):
                msg = "strategy_request_timeout_check_interval must be greater than zero"
                raise ValueError(msg)
            return configured
        if timeout is None:
            return None
        seconds = min(max(timeout.total_seconds() / 2, 0.1), 5.0)
        return timedelta(seconds=seconds)

    def shutdown(self, *, wait: bool) -> None:
        """Stop the monitor thread."""
        self._stop.set()
        if wait and self._thread is not None:
            self._thread.join(timeout=1)

    def _start(self) -> Thread | None:
        if self.interval is None:
            return None
        thread = Thread(
            target=self._run,
            name="core-strategy-request-timeout-monitor",
            daemon=True,
        )
        thread.start()
        return thread

    def _run(self) -> None:
        if self.interval is None:
            return
        interval_seconds = self.interval.total_seconds()
        clock = SystemClock()
        while not self._stop.wait(interval_seconds):
            try:
                self._expire_trading_requests(timestamp=clock.now())
            except Exception:
                _LOGGER.exception("Strategy request timeout monitor failed")

    def _expire_trading_requests(self, *, timestamp: datetime) -> None:
        for task_id, runtime in self.runtimes.items():
            if runtime.type != "trading" or runtime.future.done():
                continue
            try:
                task = self.registry.get(task_id)
            except Exception:
                continue
            if not self.runtimes.is_active_task(task):
                continue
            self.event_bus.expire_pending_strategy_requests(
                task_id=task_id,
                timestamp=timestamp,
            )
