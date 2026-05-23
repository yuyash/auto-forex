"""Public task status reason helpers.

Task ``error_message`` remains internal.  The helpers in this module produce
stable, public messages that can be safely exposed in API responses.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from apps.trading.enums import StopMode
from apps.trading.services.public_errors import (
    TASK_FAILED_ERROR_CODE,
    TASK_FAILED_PUBLIC_MESSAGE,
)


@dataclass(frozen=True, slots=True)
class PublicStatusReason:
    """Public explanation for the latest status transition trigger."""

    code: str
    message: str

    def as_update(self) -> dict[str, str]:
        """Return model update fields for this reason."""

        return {
            "status_reason_code": self.code,
            "status_reason_message": self.message,
        }


def empty_status_reason_update() -> dict[str, str]:
    """Return model update fields that clear any previous public reason."""

    return {
        "status_reason_code": "",
        "status_reason_message": "",
    }


def stop_request_reason(mode: StopMode | str) -> PublicStatusReason:
    """Return the public reason for a user-initiated stop request."""

    mode_value = str(getattr(mode, "value", mode))
    if mode_value == StopMode.IMMEDIATE.value:
        return PublicStatusReason(
            code="stop_requested_immediate",
            message="Immediate stop requested.",
        )
    if mode_value == StopMode.GRACEFUL_CLOSE.value:
        return PublicStatusReason(
            code="stop_requested_close_positions",
            message="Stop requested with open-position close.",
        )
    if mode_value == StopMode.DRAIN.value:
        return PublicStatusReason(
            code="stop_requested_drain",
            message=(
                "Drain stop requested; positions will be closed when they reach "
                "breakeven or profit."
            ),
        )
    return PublicStatusReason(
        code="stop_requested",
        message="Graceful stop requested.",
    )


def failure_reason_for_exception(error: Exception) -> PublicStatusReason:
    """Classify an execution exception into a public reason.

    Unknown exceptions intentionally collapse to the generic public failure
    message so API responses do not leak raw exception details.
    """

    error_type = type(error).__name__
    message = str(error)

    if error_type == "StrategyError":
        return _strategy_error_reason(message)

    if error_type == "ExecutionStateConflict":
        return PublicStatusReason(
            code="execution_state_conflict",
            message=(
                "Execution stopped because persisted state changed concurrently. "
                "Review recovery diagnostics before resuming."
            ),
        )

    return PublicStatusReason(
        code=TASK_FAILED_ERROR_CODE,
        message=TASK_FAILED_PUBLIC_MESSAGE,
    )


def status_reason_from_task(task: Any) -> PublicStatusReason | None:
    """Return a public reason stored on a task, if present."""

    code = str(getattr(task, "status_reason_code", "") or "").strip()
    message = str(getattr(task, "status_reason_message", "") or "").strip()
    if not code and not message:
        return None
    return PublicStatusReason(code=code or "status_reason", message=message)


_SNOWBALL_NET_EMERGENCY_RE = re.compile(
    r"^SnowballNet emergency margin threshold reached:\s*(?P<pct>[-+]?\d+(?:\.\d+)?)%$"
)


def _strategy_error_reason(message: str) -> PublicStatusReason:
    emergency = _snowball_net_emergency_reason(message)
    if emergency is not None:
        return emergency

    if message.startswith("live_tick_stale:"):
        return PublicStatusReason(
            code="live_tick_stale",
            message=(
                "Live tick became stale, so execution stopped before strategy or order processing."
            ),
        )

    return PublicStatusReason(
        code="strategy_error_stop",
        message="Strategy requested an error stop.",
    )


def _snowball_net_emergency_reason(message: str) -> PublicStatusReason | None:
    match = _SNOWBALL_NET_EMERGENCY_RE.match(message.strip())
    if match is None:
        return None

    pct = _normalize_decimal_text(match.group("pct"))
    return PublicStatusReason(
        code="snowball_net_emergency_margin",
        message=f"Emergency stop: margin closeout ratio reached {pct}%.",
    )


def _normalize_decimal_text(value: str) -> str:
    try:
        decimal_value = Decimal(value)
    except (InvalidOperation, ValueError):
        return value
    normalized = decimal_value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal("1")))
    return format(normalized, "f")
