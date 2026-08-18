"""Profile output path resolution and writing."""

from __future__ import annotations

import cProfile
from datetime import timedelta
from pathlib import Path
from typing import Protocol
from uuid import UUID


class PyinstrumentProfiler(Protocol):
    """Subset of pyinstrument's profiler API used for output generation."""

    def start(self) -> None: ...

    def stop(self) -> object: ...

    def output_html(self, resample_interval: float | None = None) -> str: ...


class TaskProfilingSettings(Protocol):
    """Configuration attributes required for profile output writing."""

    cprofile_output_path: Path | None
    pyinstrument_output_path: Path | None
    pyinstrument_resample_interval: timedelta | None
    pyinstrument_target_html_samples: int


class TaskProfilePathResolver:
    """Resolve task profile output paths."""

    def __init__(self, *, task_id: UUID, config: TaskProfilingSettings) -> None:
        self.task_id = task_id
        self.config = config

    def cprofile(self) -> Path | None:
        """Return the resolved cProfile output path."""
        return self.path(self.config.cprofile_output_path, suffix=".prof")

    def pyinstrument(self) -> Path | None:
        """Return the resolved pyinstrument output path."""
        return self.path(self.config.pyinstrument_output_path, suffix=".html")

    def path(self, base: Path | None, *, suffix: str) -> Path | None:
        """Resolve a file path from a configured file or directory path."""
        if base is None:
            return None
        if base.suffix:
            return base
        return base / f"{self.task_id}{suffix}"


class PyinstrumentResamplePolicy:
    """Choose pyinstrument HTML resampling intervals."""

    def __init__(self, config: TaskProfilingSettings) -> None:
        self.config = config

    def seconds(self, *, elapsed_seconds: float) -> float | None:
        """Return the renderer resample interval in seconds."""
        interval = self.config.pyinstrument_resample_interval
        if interval is None:
            return self.auto_seconds(elapsed_seconds=elapsed_seconds)
        return self.fixed_seconds(interval)

    def auto_seconds(self, *, elapsed_seconds: float) -> float | None:
        """Return an interval that keeps HTML samples around the configured target."""
        target_html_samples = self.config.pyinstrument_target_html_samples
        if target_html_samples <= 0:
            msg = "pyinstrument_target_html_samples must be greater than zero"
            raise ValueError(msg)
        if elapsed_seconds <= 0:
            return None
        return elapsed_seconds / target_html_samples

    @classmethod
    def fixed_seconds(cls, interval: timedelta) -> float:
        """Validate and return a fixed resample interval."""
        seconds = interval.total_seconds()
        if seconds <= 0:
            msg = "pyinstrument_resample_interval must be greater than zero"
            raise ValueError(msg)
        return seconds


class TaskProfileOutputWriter:
    """Write profiler outputs to disk."""

    def __init__(self, *, task_id: UUID, config: TaskProfilingSettings) -> None:
        self.paths = TaskProfilePathResolver(task_id=task_id, config=config)
        self.pyinstrument_resample = PyinstrumentResamplePolicy(config)

    def cprofile(self, profiler: cProfile.Profile) -> Path | None:
        """Write cProfile stats and return the output path."""
        output_path = self.paths.cprofile()
        if output_path is None:
            return None
        output_path.parent.mkdir(parents=True, exist_ok=True)
        profiler.dump_stats(output_path)
        return output_path

    def pyinstrument(
        self,
        profiler: PyinstrumentProfiler,
        *,
        elapsed_seconds: float,
    ) -> Path | None:
        """Write pyinstrument HTML and return the output path."""
        output_path = self.paths.pyinstrument()
        if output_path is None:
            return None
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            profiler.output_html(
                resample_interval=self.pyinstrument_resample.seconds(
                    elapsed_seconds=elapsed_seconds,
                )
            ),
            encoding="utf-8",
        )
        return output_path
