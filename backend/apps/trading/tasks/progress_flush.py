"""Progress flush policy for task execution loops."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from django.conf import settings

from apps.trading.enums import TaskType


@dataclass(slots=True)
class ProgressFlushPolicy:
    """Decide when execution progress should be persisted."""

    batch_interval: int
    max_interval_seconds: float
    _last_flush_at: float = 0

    @classmethod
    def for_task_type(
        cls,
        task_type: TaskType,
        *,
        in_memory_mode: bool = False,
    ) -> "ProgressFlushPolicy":
        """Build a policy using task-type-specific settings."""
        if in_memory_mode and task_type == TaskType.BACKTEST:
            batch_interval = int(
                getattr(settings, "TRADING_IN_MEMORY_BACKTEST_PROGRESS_FLUSH_BATCHES", 250)
            )
            max_interval_seconds = float(
                getattr(settings, "TRADING_IN_MEMORY_BACKTEST_PROGRESS_FLUSH_SECONDS", 10.0)
            )
        elif task_type == TaskType.TRADING:
            batch_interval = int(getattr(settings, "TRADING_LIVE_PROGRESS_FLUSH_BATCHES", 10))
            max_interval_seconds = float(
                getattr(settings, "TRADING_LIVE_PROGRESS_FLUSH_SECONDS", 1.0)
            )
        else:
            batch_interval = int(getattr(settings, "TRADING_BACKTEST_PROGRESS_FLUSH_BATCHES", 25))
            max_interval_seconds = float(
                getattr(settings, "TRADING_BACKTEST_PROGRESS_FLUSH_SECONDS", 2.0)
            )
        return cls(
            batch_interval=max(batch_interval, 1),
            max_interval_seconds=max(max_interval_seconds, 0.0),
            _last_flush_at=monotonic(),
        )

    def should_flush(self, *, batch_count: int, force: bool = False) -> bool:
        """Return whether progress should be persisted for this batch."""
        if force:
            self.mark_flushed()
            return True
        if batch_count <= 1:
            self.mark_flushed()
            return True
        if self.batch_interval <= 1:
            self.mark_flushed()
            return True
        if batch_count % self.batch_interval == 0:
            self.mark_flushed()
            return True
        if (
            self.max_interval_seconds > 0
            and monotonic() - self._last_flush_at >= self.max_interval_seconds
        ):
            self.mark_flushed()
            return True
        return False

    def mark_flushed(self) -> None:
        """Record that a flush has happened now."""
        self._last_flush_at = monotonic()
