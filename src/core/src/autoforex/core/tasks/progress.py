"""Task progress snapshots."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Any, Protocol
from uuid import UUID

from autoforex.core.tasks.state import TaskStatus


@dataclass(frozen=True, slots=True)
class TaskProgress:
    """Point-in-time progress for a managed task run."""

    task_id: UUID
    task_name: str
    status: TaskStatus
    current_at: datetime | None
    start_at: datetime | None
    end_at: datetime | None
    completed_units: float | None
    total_units: float | None
    unit: str

    @property
    def fraction(self) -> float | None:
        """Return progress as a value from 0.0 to 1.0 when bounded."""
        if self.completed_units is None or self.total_units is None:
            return None
        if self.total_units <= 0:
            return 1.0
        return max(0.0, min(1.0, self.completed_units / self.total_units))

    @property
    def percent(self) -> float | None:
        """Return progress as a percentage when bounded."""
        if self.fraction is None:
            return None
        return self.fraction * 100


class TaskProgressReporter(Protocol):
    """Observer for progress changes while waiting for a task."""

    def on_start(self, progress: TaskProgress) -> None:
        """Handle the first progress snapshot."""

    def on_update(self, progress: TaskProgress) -> None:
        """Handle a refreshed progress snapshot."""

    def on_finish(self, progress: TaskProgress) -> None:
        """Handle the final progress snapshot."""

    def close(self) -> None:
        """Release resources when waiting exits before task completion."""


class TqdmProgressReporter:
    """Render task progress with tqdm."""

    def __init__(
        self,
        *,
        tqdm_factory: Callable[..., Any] | None = None,
        description: str | None = None,
        current_time_format: str = "%Y-%m-%d %H:%M:%S %Z",
        current_time_zone: tzinfo | None = None,
        **options: Any,
    ) -> None:
        self._tqdm_factory = tqdm_factory
        self._description = description
        self._current_time_format = current_time_format
        self._current_time_zone = current_time_zone
        self._options = options
        self._bar: Any | None = None
        self._completed_units = 0.0

    def on_start(self, progress: TaskProgress) -> None:
        """Create the tqdm bar from the first progress snapshot."""
        if self._bar is not None:
            return
        options = dict(self._options)
        options.setdefault("desc", self._description or progress.task_name)
        options.setdefault("bar_format", self._bar_format(progress))
        self._bar = self._resolve_tqdm_factory()(
            total=progress.total_units,
            unit=progress.unit,
            **options,
        )
        self._completed_units = 0.0
        self._advance(progress)

    def on_update(self, progress: TaskProgress) -> None:
        """Update the tqdm bar from the latest progress snapshot."""
        if self._bar is None:
            self.on_start(progress)
            return
        self._advance(progress)

    def on_finish(self, progress: TaskProgress) -> None:
        """Update and close the tqdm bar."""
        self.on_update(progress)
        self.close()

    def close(self) -> None:
        """Close the tqdm bar if it was opened."""
        if self._bar is None:
            return
        self._bar.close()
        self._bar = None

    def _advance(self, progress: TaskProgress) -> None:
        if self._bar is None:
            return
        if progress.total_units != self._bar.total:
            self._bar.total = progress.total_units
        if progress.completed_units is not None:
            completed_units = max(self._completed_units, progress.completed_units)
            self._bar.update(completed_units - self._completed_units)
            self._completed_units = completed_units
        self._bar.set_postfix_str(
            f"current={self._format_current_at(progress)}, status={progress.status.value}"
        )
        self._bar.refresh()

    @staticmethod
    def _bar_format(progress: TaskProgress) -> str:
        if progress.total_units is None:
            return "{desc}: {postfix} [{elapsed}, {rate_fmt}]"
        return "{l_bar}{bar}| {postfix} [{elapsed}<{remaining}, {rate_fmt}]"

    def _format_current_at(self, progress: TaskProgress) -> str:
        if progress.current_at is None:
            return "-"
        current_at = progress.current_at.astimezone(self._current_time_zone)
        return current_at.strftime(self._current_time_format).strip()

    def _resolve_tqdm_factory(self) -> Callable[..., Any]:
        if self._tqdm_factory is not None:
            return self._tqdm_factory
        try:
            from tqdm import tqdm
        except ImportError as exc:
            msg = "TqdmProgressReporter requires the 'tqdm' package"
            raise RuntimeError(msg) from exc
        return tqdm
