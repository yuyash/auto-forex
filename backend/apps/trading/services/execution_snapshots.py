"""Persistence helpers for execution summary snapshots."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from apps.trading.models import TaskExecutionSnapshot
from apps.trading.services.execution_metrics import build_execution_metrics
from apps.trading.services.summary import (
    CountsInfo,
    ExecutionInfo,
    ExecutionWatermarks,
    PnlInfo,
    TaskInfo,
    TaskSummary,
    TASK_SUMMARY_READ_MODEL,
    TickDeliveryInfo,
    TickInfo,
    WatermarkInfo,
)

TERMINAL_SNAPSHOT_STATUSES = frozenset({"completed", "stopped", "failed"})


def should_persist_snapshot(*, task) -> bool:
    """Whether the task is in a state that should persist a terminal snapshot."""
    execution_id = getattr(task, "execution_id", None)
    status = str(getattr(task, "status", "") or "").lower()
    return execution_id is not None and status in TERMINAL_SNAPSHOT_STATUSES


def sync_execution_snapshot(*, task, task_type: str) -> TaskExecutionSnapshot | None:
    """Persist a snapshot when the task is terminal, otherwise no-op."""
    if not should_persist_snapshot(task=task):
        return None
    return persist_execution_snapshot(task=task, task_type=task_type)


def ensure_execution_snapshot(
    *,
    task,
    task_type: str,
    execution_id: str | None,
) -> TaskExecutionSnapshot | None:
    """Return an existing snapshot or create one for the current terminal run."""
    if _is_current_active_execution(task=task, execution_id=execution_id):
        return None

    snapshot = _get_snapshot(
        task_type=task_type,
        task_id=str(task.pk),
        execution_id=execution_id,
    )
    if snapshot is not None:
        return snapshot

    current_execution_id = getattr(task, "execution_id", None)
    if execution_id is None or str(current_execution_id or "") != str(execution_id):
        return None
    return sync_execution_snapshot(task=task, task_type=task_type)


def get_summary_snapshot(
    *,
    task=None,
    task_type: str,
    task_id: str,
    execution_id: str | None,
) -> TaskSummary | None:
    """Return a persisted summary snapshot when it exists."""
    snapshot = (
        ensure_execution_snapshot(task=task, task_type=task_type, execution_id=execution_id)
        if task is not None
        else _get_snapshot(
            task_type=task_type,
            task_id=task_id,
            execution_id=execution_id,
        )
    )
    if snapshot is None or not isinstance(snapshot.summary, dict) or not snapshot.summary:
        return None
    return _deserialize_summary(snapshot.summary)


def get_metrics_snapshot(
    *,
    task=None,
    task_type: str,
    task_id: str,
    execution_id: str | None,
) -> dict[str, Any] | None:
    """Return persisted metrics snapshot when it exists."""
    snapshot = (
        ensure_execution_snapshot(task=task, task_type=task_type, execution_id=execution_id)
        if task is not None
        else _get_snapshot(
            task_type=task_type,
            task_id=task_id,
            execution_id=execution_id,
        )
    )
    if snapshot is None or not isinstance(snapshot.metrics, dict) or not snapshot.metrics:
        return None
    return snapshot.metrics


def persist_execution_snapshot(*, task, task_type: str) -> TaskExecutionSnapshot | None:
    """Persist summary and metrics for the task's current execution."""
    execution_id = getattr(task, "execution_id", None)
    if execution_id is None:
        return None
    task_id = str(task.pk)
    run_id = str(execution_id)
    summary = TASK_SUMMARY_READ_MODEL.compute(
        task_type=task_type,
        task_id=task_id,
        execution_id=execution_id,
    )
    metrics = build_execution_metrics(
        task=task,
        task_type=task_type,
        task_id=task_id,
        execution_id=run_id,
        summary=summary,
        fallback_mid_rate=summary.tick.mid,
    )
    existing_snapshot = TaskExecutionSnapshot.objects.filter(
        task_type=task_type,
        task_id=task.pk,
        execution_id=execution_id,
    ).first()
    from apps.trading.services.resume_config import build_config_snapshot_defaults

    config_defaults = build_config_snapshot_defaults(snapshot=existing_snapshot, task=task)
    snapshot, _ = TaskExecutionSnapshot.objects.update_or_create(
        task_type=task_type,
        task_id=task.pk,
        execution_id=execution_id,
        defaults={
            "completed_at": getattr(task, "completed_at", None),
            "summary": _make_json_safe(summary.to_dict()),
            "metrics": _make_json_safe(metrics),
            **config_defaults,
        },
    )
    return snapshot


def _get_snapshot(
    *,
    task_type: str,
    task_id: str,
    execution_id: str | None,
) -> TaskExecutionSnapshot | None:
    if execution_id is None:
        return None
    return (
        TaskExecutionSnapshot.objects.filter(
            task_type=task_type,
            task_id=task_id,
            execution_id=execution_id,
        )
        .only("summary", "metrics")
        .first()
    )


def _is_current_active_execution(*, task, execution_id: str | None) -> bool:
    """Return True when the requested run is the task's current non-terminal run."""
    if task is None or execution_id is None:
        return False
    current_execution_id = getattr(task, "execution_id", None)
    if str(current_execution_id or "") != str(execution_id):
        return False
    status = str(getattr(task, "status", "") or "").lower()
    return status not in TERMINAL_SNAPSHOT_STATUSES


def _deserialize_summary(raw: dict[str, Any]) -> TaskSummary:
    pnl = raw.get("pnl", {})
    counts = raw.get("counts", {})
    execution = raw.get("execution", {})
    tick = raw.get("tick", {})
    task = raw.get("task", {})
    watermarks = raw.get("watermarks", {})
    return TaskSummary(
        timestamp=_to_str_or_none(raw.get("timestamp")),
        pnl=PnlInfo(
            realized=_to_decimal(pnl.get("realized")),
            unrealized=_to_decimal(pnl.get("unrealized")),
            currency=_to_str_or_none(pnl.get("currency")),
            realized_display_money=_to_money_dict(pnl.get("realized_display_money")),
            unrealized_display_money=_to_money_dict(pnl.get("unrealized_display_money")),
            total_display_money=_to_money_dict(pnl.get("total_display_money")),
            display_conversion_context=_to_conversion_context(
                pnl.get("display_conversion_context")
            ),
        ),
        counts=CountsInfo(
            total_trades=int(counts.get("total_trades") or 0),
            open_positions=int(counts.get("open_positions") or 0),
            closed_positions=int(counts.get("closed_positions") or 0),
            open_long_units=int(counts.get("open_long_units") or 0),
            open_short_units=int(counts.get("open_short_units") or 0),
            winning_trades=int(counts.get("winning_trades") or 0),
            losing_trades=int(counts.get("losing_trades") or 0),
        ),
        execution=ExecutionInfo(
            current_balance=_to_optional_decimal(execution.get("current_balance")),
            ticks_processed=int(execution.get("ticks_processed") or 0),
            account_currency=_to_str_or_none(execution.get("account_currency")),
            current_balance_currency=_to_str_or_none(execution.get("current_balance_currency")),
            current_balance_money=_to_money_dict(execution.get("current_balance_money")),
            current_balance_display=_to_optional_decimal(execution.get("current_balance_display")),
            display_currency=_to_str_or_none(execution.get("display_currency")),
            current_balance_display_money=_to_money_dict(
                execution.get("current_balance_display_money")
            ),
            current_balance_display_conversion_context=_to_conversion_context(
                execution.get("current_balance_display_conversion_context")
            ),
            resume_cursor_timestamp=_to_str_or_none(execution.get("resume_cursor_timestamp")),
            margin_ratio=_to_optional_decimal(execution.get("margin_ratio")),
            current_atr=_to_optional_decimal(execution.get("current_atr")),
            recovery_status=_to_str_or_none(execution.get("recovery_status")),
            recovery_warnings=[
                str(item) for item in execution.get("recovery_warnings", []) if item is not None
            ],
            recovery_blockers=[
                str(item) for item in execution.get("recovery_blockers", []) if item is not None
            ],
            reconciled_at=_to_str_or_none(execution.get("reconciled_at")),
            tick_delivery=_deserialize_tick_delivery(execution.get("tick_delivery")),
        ),
        tick=TickInfo(
            timestamp=_to_str_or_none(tick.get("timestamp")),
            bid=_to_optional_decimal(tick.get("bid")),
            ask=_to_optional_decimal(tick.get("ask")),
            mid=_to_optional_decimal(tick.get("mid")),
        ),
        task=TaskInfo(
            status=_to_str_or_none(task.get("status")) or "",
            started_at=_to_str_or_none(task.get("started_at")),
            completed_at=_to_str_or_none(task.get("completed_at")),
            error_message=_to_str_or_none(task.get("error_message")),
            error_code=_to_str_or_none(task.get("error_code")),
            status_reason_code=_to_str_or_none(task.get("status_reason_code")),
            status_reason_message=_to_str_or_none(task.get("status_reason_message")),
            stop_reason=_to_str_or_none(task.get("stop_reason")),
            progress=int(task.get("progress") or 0),
        ),
        watermarks=_deserialize_watermarks(watermarks),
    )


def _deserialize_tick_delivery(raw: Any) -> TickDeliveryInfo | None:
    if not isinstance(raw, dict):
        return None
    return TickDeliveryInfo(
        status=_to_str_or_none(raw.get("status")),
        tick_timestamp=_to_str_or_none(raw.get("tick_timestamp")),
        observed_at=_to_str_or_none(raw.get("observed_at")),
        age_seconds=_to_optional_float(raw.get("age_seconds")),
        max_age_seconds=_to_optional_int(raw.get("max_age_seconds")),
        message=_to_str_or_none(raw.get("message")),
    )


def _deserialize_watermarks(raw: Any) -> ExecutionWatermarks:
    data = raw if isinstance(raw, dict) else {}
    return ExecutionWatermarks(
        margin_ratio_max=_deserialize_watermark(data.get("margin_ratio_max")),
        base_units_max=_deserialize_watermark(data.get("base_units_max")),
        open_long_units_max=_deserialize_watermark(data.get("open_long_units_max")),
        open_short_units_max=_deserialize_watermark(data.get("open_short_units_max")),
        realized_pnl_max=_deserialize_watermark(data.get("realized_pnl_max")),
        unrealized_pnl_min=_deserialize_watermark(data.get("unrealized_pnl_min")),
        open_positions_max=_deserialize_watermark(data.get("open_positions_max")),
        active_cycles_max=_deserialize_watermark(data.get("active_cycles_max")),
    )


def _deserialize_watermark(raw: Any) -> WatermarkInfo:
    if not isinstance(raw, dict):
        return WatermarkInfo(value=None, timestamp=None)
    return WatermarkInfo(
        value=_to_optional_decimal(raw.get("value")),
        timestamp=_to_str_or_none(raw.get("timestamp")),
        source_metric=_to_str_or_none(raw.get("source_metric")),
    )


def _to_money_dict(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    amount = value.get("amount")
    currency = value.get("currency")
    if amount is None or currency is None:
        return None
    return {"amount": str(amount), "currency": str(currency)}


def _to_conversion_context(value: Any) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return {
        "source_currency": str(value.get("source_currency") or ""),
        "target_currency": str(value.get("target_currency") or ""),
        "rate": value.get("rate"),
        "rate_source": str(value.get("rate_source") or ""),
        "rate_as_of": value.get("rate_as_of"),
        "rate_path": [str(item) for item in value.get("rate_path", [])],
        "conversion_available": bool(value.get("conversion_available", False)),
        "conversion_policy": str(value.get("conversion_policy") or "unavailable"),
    }


def _to_decimal(value: Any) -> Decimal:
    return Decimal(str(value or "0"))


def _to_optional_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _to_str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _to_optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _to_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


class _DecimalEncoder(json.JSONEncoder):
    """JSON encoder that converts Decimal and datetime values to JSON-safe strings."""

    def default(self, o: Any) -> Any:
        if isinstance(o, Decimal):
            return str(o)
        if isinstance(o, datetime | date):
            return o.isoformat()
        return super().default(o)


def _make_json_safe(obj: Any) -> Any:
    """Round-trip through JSON to convert Decimal values to strings."""
    return json.loads(json.dumps(obj, cls=_DecimalEncoder))


def _snapshot_task_config(task: Any) -> dict[str, Any]:
    """Capture task-level settings as a JSON-safe dict."""
    from apps.trading.models import BacktestTask

    data: dict[str, Any] = {
        "instrument": getattr(task, "instrument", None),
        "pip_size": str(getattr(task, "pip_size", "") or ""),
        "hedging_enabled": getattr(task, "hedging_enabled", None),
    }
    if isinstance(task, BacktestTask):
        data.update(
            {
                "start_time": _iso_or_none(getattr(task, "start_time", None)),
                "end_time": _iso_or_none(getattr(task, "end_time", None)),
                "initial_balance": str(getattr(task, "initial_balance", "") or ""),
                "commission_per_trade": str(getattr(task, "commission_per_trade", "") or ""),
                "data_source": getattr(task, "data_source", None),
                "tick_granularity": getattr(task, "tick_granularity", None),
                "tick_window_value_mode": getattr(task, "tick_window_value_mode", None),
                "spread_filter_enabled": getattr(task, "spread_filter_enabled", None),
                "max_spread_pips": str(getattr(task, "max_spread_pips", "") or ""),
                "oanda_candle_filter_enabled": getattr(task, "oanda_candle_filter_enabled", None),
                "oanda_candle_filter_account_name": getattr(
                    getattr(task, "oanda_candle_filter_account", None),
                    "account_id",
                    None,
                ),
                "oanda_candle_filter_granularity": getattr(
                    task, "oanda_candle_filter_granularity", None
                ),
                "oanda_candle_filter_tolerance_pips": str(
                    getattr(task, "oanda_candle_filter_tolerance_pips", "") or ""
                ),
            }
        )
    else:
        data.update(
            {
                "sell_on_stop": getattr(task, "sell_on_stop", None),
                "dry_run": getattr(task, "dry_run", None),
            }
        )
    return data


def _snapshot_strategy_config(task: Any) -> dict[str, Any]:
    """Capture the StrategyConfiguration as a JSON-safe dict."""
    config = getattr(task, "config", None)
    if config is None:
        return {}
    return {
        "id": str(config.pk),
        "name": config.name,
        "strategy_type": config.strategy_type,
        "configuration_revision": getattr(config, "revision", None),
        "configuration_hash": getattr(config, "config_hash", "") or "",
        "parameters": _make_json_safe(config.parameters) if config.parameters else {},
    }


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
