"""CSV path resolution helpers."""

from __future__ import annotations

from collections.abc import Sequence
from os import PathLike
from pathlib import Path


class CSVSourcePaths:
    """Resolve CSV input file paths."""

    @classmethod
    def glob_sorted(cls, base: Path, pattern: str) -> list[Path]:
        """Return sorted files matching a glob pattern."""
        matched = sorted(base.glob(pattern))
        if not matched:
            msg = f"no files matching {pattern!r} found in {base}"
            raise FileNotFoundError(msg)
        return matched

    @classmethod
    def resolve(
        cls,
        *,
        single: str | PathLike[str] | None,
        multiple: Sequence[str | PathLike[str]] | None,
        label: str,
    ) -> tuple[Path, ...]:
        """Resolve singular or plural path arguments into a tuple of paths."""
        if single is not None and multiple is not None:
            msg = f"provide either {label}_path or {label}_paths, not both"
            raise ValueError(msg)
        if multiple is not None:
            return tuple(Path(item) for item in multiple)
        if single is not None:
            return (Path(single),)
        return ()
