"""Task execution profiling."""

from __future__ import annotations

import cProfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock
from time import perf_counter
from typing import TypeVar
from uuid import UUID

from autoforex.core.tasks.profile_outputs import PyinstrumentProfiler, TaskProfileOutputWriter

FuncT = TypeVar("FuncT")


@dataclass(frozen=True, slots=True)
class TaskProfilingConfig:
    """Configuration for external task profilers."""

    cprofile: bool = False
    cprofile_output_path: Path | None = None
    pyinstrument: bool = False
    pyinstrument_output_path: Path | None = None
    pyinstrument_resample_interval: timedelta | None = None
    pyinstrument_target_html_samples: int = 10_000

    @classmethod
    def for_backtest_period(
        cls,
        *,
        start_at: datetime,
        end_at: datetime,
        cprofile: bool = False,
        cprofile_output_path: Path | None = None,
        pyinstrument: bool = False,
        pyinstrument_output_path: Path | None = None,
    ) -> TaskProfilingConfig:
        """Return profiling settings scaled for a backtest date range."""
        duration = end_at - start_at
        if duration <= timedelta(days=7):
            target_html_samples = 20_000
        elif duration <= timedelta(days=31):
            target_html_samples = 10_000
        else:
            target_html_samples = 5_000
        return cls(
            cprofile=cprofile,
            cprofile_output_path=cprofile_output_path,
            pyinstrument=pyinstrument,
            pyinstrument_output_path=pyinstrument_output_path,
            pyinstrument_target_html_samples=target_html_samples,
        )

    @property
    def active(self) -> bool:
        """Return whether any external profiler is active."""
        return self.cprofile or self.pyinstrument


@dataclass(frozen=True, slots=True)
class TaskProfile:
    """Snapshot of profiler output paths for a task run."""

    task_id: UUID
    task_name: str
    task_type: str
    cprofile_output_path: Path | None = None
    pyinstrument_output_path: Path | None = None


class TaskProfiler:
    """Profiler wrapper for one task run."""

    def __init__(
        self,
        *,
        task_id: UUID,
        task_name: str,
        task_type: str,
        config: TaskProfilingConfig | None = None,
    ) -> None:
        self.task_id = task_id
        self.task_name = task_name
        self.task_type = task_type
        self.config = config or TaskProfilingConfig()
        self.outputs = TaskProfileOutputWriter(task_id=task_id, config=self.config)
        self._cprofile_output_path: Path | None = None
        self._pyinstrument_output_path: Path | None = None
        self._lock = RLock()

    @property
    def active(self) -> bool:
        """Return whether any profiler is active."""
        return self.config.active

    def run(self, func: Callable[..., FuncT], *args: object, **kwargs: object) -> FuncT:
        """Run a callable under optional profiling."""
        if not self.active:
            return func(*args, **kwargs)

        profiler = cProfile.Profile() if self.config.cprofile else None
        pyinstrument_profiler = (
            PyinstrumentProfilerFactory.create() if self.config.pyinstrument else None
        )
        started_at = perf_counter()
        try:
            if profiler is not None:
                profiler.enable()
            if pyinstrument_profiler is not None:
                pyinstrument_profiler.start()
            return func(*args, **kwargs)
        finally:
            if profiler is not None:
                profiler.disable()
            if pyinstrument_profiler is not None:
                pyinstrument_profiler.stop()
            if profiler is not None:
                self.record_cprofile(profiler)
            if pyinstrument_profiler is not None:
                self.record_pyinstrument(
                    pyinstrument_profiler,
                    elapsed_seconds=perf_counter() - started_at,
                )

    def snapshot(self) -> TaskProfile:
        """Return the current profile snapshot."""
        with self._lock:
            cprofile_output_path = self._cprofile_output_path
            pyinstrument_output_path = self._pyinstrument_output_path
        return TaskProfile(
            task_id=self.task_id,
            task_name=self.task_name,
            task_type=self.task_type,
            cprofile_output_path=cprofile_output_path,
            pyinstrument_output_path=pyinstrument_output_path,
        )

    def record_cprofile(self, profiler: cProfile.Profile) -> None:
        """Persist cProfile output and remember its path."""
        output_path = self.outputs.cprofile(profiler)
        if output_path is not None:
            with self._lock:
                self._cprofile_output_path = output_path

    def record_pyinstrument(
        self,
        profiler: PyinstrumentProfiler,
        *,
        elapsed_seconds: float,
    ) -> None:
        """Persist pyinstrument output and remember its path."""
        output_path = self.outputs.pyinstrument(profiler, elapsed_seconds=elapsed_seconds)
        if output_path is not None:
            with self._lock:
                self._pyinstrument_output_path = output_path


class PyinstrumentProfilerFactory:
    """Create optional pyinstrument profilers."""

    @classmethod
    def create(cls) -> PyinstrumentProfiler:
        """Return a pyinstrument profiler or raise a dependency error."""
        try:
            from pyinstrument import Profiler
        except ImportError as exc:
            msg = "TaskProfilingConfig(pyinstrument=True) requires the 'pyinstrument' package"
            raise RuntimeError(msg) from exc
        return Profiler()
