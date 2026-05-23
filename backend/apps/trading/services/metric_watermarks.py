"""Metric watermark extraction and incremental update helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal


WatermarkMode = Literal["max", "min"]


@dataclass(frozen=True, slots=True)
class MetricWatermarkSource:
    """Metric source key and scale for one watermark."""

    key: str
    scale: Decimal = Decimal("1")


@dataclass(frozen=True, slots=True)
class MetricWatermarkSpec:
    """Watermark target built from one or more metric source keys."""

    key: str
    sources: tuple[MetricWatermarkSource, ...]
    mode: WatermarkMode
    select_extreme_source: bool = False


WATERMARK_SPECS: tuple[MetricWatermarkSpec, ...] = (
    MetricWatermarkSpec(
        key="margin_ratio_max",
        sources=(
            MetricWatermarkSource("margin_ratio"),
            MetricWatermarkSource("snowball_net_margin_ratio_pct", Decimal("0.01")),
        ),
        mode="max",
        select_extreme_source=True,
    ),
    MetricWatermarkSpec(
        key="base_units_max",
        sources=(
            MetricWatermarkSource("current_base_units"),
            MetricWatermarkSource("snowball_current_base_units"),
        ),
        mode="max",
    ),
    MetricWatermarkSpec(
        key="open_long_units_max",
        sources=(MetricWatermarkSource("open_long_units"),),
        mode="max",
    ),
    MetricWatermarkSpec(
        key="open_short_units_max",
        sources=(MetricWatermarkSource("open_short_units"),),
        mode="max",
    ),
    MetricWatermarkSpec(
        key="realized_pnl_max",
        sources=(
            MetricWatermarkSource("realized_pnl_quote"),
            MetricWatermarkSource("realized_pnl"),
        ),
        mode="max",
    ),
    MetricWatermarkSpec(
        key="unrealized_pnl_min",
        sources=(
            MetricWatermarkSource("unrealized_pnl_quote"),
            MetricWatermarkSource("unrealized_pnl"),
        ),
        mode="min",
    ),
    MetricWatermarkSpec(
        key="open_positions_max",
        sources=(MetricWatermarkSource("open_positions"),),
        mode="max",
    ),
    MetricWatermarkSpec(
        key="active_cycles_max",
        sources=(MetricWatermarkSource("active_cycles"),),
        mode="max",
    ),
)


def update_watermarks(
    watermarks: dict[str, Any] | None,
    *,
    timestamp: datetime,
    metrics: dict[str, Any],
) -> dict[str, Any]:
    """Return watermark map updated with one metric snapshot."""

    updated = dict(watermarks or {})
    for spec in WATERMARK_SPECS:
        candidate = _candidate_value(metrics, spec)
        if candidate is None:
            continue
        value, source_key = candidate
        current = _entry_decimal(updated.get(spec.key))
        if current is not None and not _is_more_extreme(value, current, spec.mode):
            continue
        updated[spec.key] = {
            "value": str(value),
            "timestamp": timestamp.isoformat(),
            "source_metric": source_key,
        }
    return updated


def _candidate_value(
    metrics: dict[str, Any],
    spec: MetricWatermarkSpec,
) -> tuple[Decimal, str] | None:
    candidates: list[tuple[Decimal, str]] = []
    for source in spec.sources:
        value = _decimal_metric(metrics.get(source.key))
        if value is None:
            continue
        candidates.append((value * source.scale, source.key))
    if not candidates:
        return None
    if not spec.select_extreme_source:
        return candidates[0]
    if spec.mode == "min":
        return min(candidates, key=lambda candidate: candidate[0])
    return max(candidates, key=lambda candidate: candidate[0])


def _decimal_metric(raw: Any) -> Decimal | None:
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _entry_decimal(raw: Any) -> Decimal | None:
    if not isinstance(raw, dict):
        return None
    return _decimal_metric(raw.get("value"))


def _is_more_extreme(value: Decimal, current: Decimal, mode: WatermarkMode) -> bool:
    if mode == "min":
        return value < current
    return value > current
