from __future__ import annotations

from collections.abc import Callable

_ENDPOINTS_ATTRIBUTE = "__oanda_e2e_endpoints__"


def covers_endpoints(
    *endpoints: str,
) -> Callable[[Callable[..., object]], Callable[..., object]]:
    """Declare the OANDA endpoint methods exercised by an E2E test."""

    def decorator(test: Callable[..., object]) -> Callable[..., object]:
        setattr(test, _ENDPOINTS_ATTRIBUTE, frozenset(endpoints))
        return test

    return decorator


def covered_endpoints(test: object) -> frozenset[str]:
    """Return endpoint declarations attached to a collected test."""
    value = getattr(test, _ENDPOINTS_ATTRIBUTE, ())
    return frozenset(str(endpoint) for endpoint in value)
