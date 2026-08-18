"""Optional server dependency loading with actionable installation errors."""

from __future__ import annotations

from importlib import import_module
from types import ModuleType


class OptionalDependencyError(ImportError):
    """Raised when a configured server feature is not installed."""


def require_optional_dependency(
    module_name: str,
    *,
    extra: str,
    feature: str,
) -> ModuleType:
    """Import an optional module or raise an actionable installation error."""
    try:
        return import_module(module_name)
    except ModuleNotFoundError as exc:
        missing = exc.name or ""
        if missing != module_name and not module_name.startswith(f"{missing}."):
            raise
        command = f'pip install "auto-forex-server[{extra}]"'
        raise OptionalDependencyError(
            f"{feature} requires the optional '{extra}' dependencies; install them with `{command}`"
        ) from exc
