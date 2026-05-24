"""Period-bucketed trade outcome metrics for strategy dashboards."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone

from apps.trading.models.events import TradingEvent
from apps.trading.models.metrics import Metrics
from apps.trading.models.positions import Position
from apps.trading.services.strategy_data_common import StrategyDataQuery, string_or_none
from apps.trading.utils import Instrument

PERIODS = ("day", "week", "month", "year")
TP_CLOSE_REASONS = frozenset(
    {
        "tp",
        "counter_tp",
        "layer_initial_tp",
        "take_profit",
        "net_take_profit",
        "snowball_net_take_profit",
    }
)
SL_CLOSE_REASONS = frozenset({"stop_loss"})
OPEN_EVENT_TYPE = "open_position"
REBUILD_EVENT_TYPE = "rebuild_position"
CLOSE_EVENT_TYPE = "close_position"


def build_periodic_trade_metrics(
    *,
    task: Any,
    task_type_label: str,
    query: StrategyDataQuery,
    timezone_name: str | None = None,
) -> dict[str, Any]:
    """Build TP/SL PnL and position activity buckets for one execution."""

    local_tz = _timezone(timezone_name)
    buckets: dict[str, dict[int, dict[str, Any]]] = {period: {} for period in PERIODS}
    return_buckets: dict[str, dict[int, dict[str, Any]]] = {period: {} for period in PERIODS}
    close_event_by_position: dict[str, tuple[datetime, str]] = {}

    events_qs = TradingEvent.objects.filter(
        task_type=task_type_label,
        task_id=task.pk,
        execution_id=query.execution_id,
        event_timestamp__isnull=False,
        event_type__in=(OPEN_EVENT_TYPE, REBUILD_EVENT_TYPE, CLOSE_EVENT_TYPE),
    )
    if query.since is not None:
        events_qs = events_qs.filter(event_timestamp__gte=query.since)
    if query.until is not None:
        events_qs = events_qs.filter(event_timestamp__lte=query.until)

    for event in (
        events_qs.order_by("event_timestamp", "sequence_number")
        .values(
            "event_type",
            "close_reason",
            "event_timestamp",
            "position_id",
        )
        .iterator(chunk_size=5000)
    ):
        event_type = str(event["event_type"] or "")
        event_timestamp = _aware_datetime(event["event_timestamp"])
        if event_timestamp is None:
            continue

        if event_type == OPEN_EVENT_TYPE:
            _increment_all(buckets, event_timestamp, local_tz, "open_positions", 1)
            continue
        if event_type == REBUILD_EVENT_TYPE:
            _increment_all(buckets, event_timestamp, local_tz, "rebuild_opens", 1)
            continue

        close_reason = str(event["close_reason"] or "").strip().lower()
        if close_reason in TP_CLOSE_REASONS:
            _increment_all(buckets, event_timestamp, local_tz, "tp_closes", 1)
        elif close_reason in SL_CLOSE_REASONS:
            _increment_all(buckets, event_timestamp, local_tz, "sl_closes", 1)
        else:
            continue

        position_id = event["position_id"]
        if position_id:
            close_event_by_position[str(position_id)] = (event_timestamp, close_reason)

    if close_event_by_position:
        positions = Position.objects.filter(
            task_type=task_type_label,
            task_id=task.pk,
            execution_id=query.execution_id,
            id__in=close_event_by_position.keys(),
            is_open=False,
            exit_price__isnull=False,
        ).only("id", "direction", "units", "entry_price", "exit_price")
        for position in positions.iterator(chunk_size=5000):
            closed_at, close_reason = close_event_by_position[str(position.id)]
            pnl = _realized_pnl(position)
            if pnl is None:
                continue
            if close_reason in TP_CLOSE_REASONS:
                _increment_all(buckets, closed_at, local_tz, "tp_profit", pnl)
            elif close_reason in SL_CLOSE_REASONS:
                _increment_all(buckets, closed_at, local_tz, "sl_loss", pnl)

    _build_return_buckets(
        buckets=return_buckets,
        task=task,
        task_type_label=task_type_label,
        query=query,
        local_tz=local_tz,
    )

    return {
        "execution_id": string_or_none(query.execution_id),
        "strategy_type": str(getattr(task.config, "strategy_type", "") or ""),
        "instrument": getattr(task, "instrument", None),
        "currency": _quote_currency(task),
        "timezone": getattr(local_tz, "key", "UTC"),
        "periods": {
            period: [_serialize_bucket(bucket) for bucket in sorted(values.values(), key=_bucket_t)]
            for period, values in buckets.items()
        },
        "returns": {
            period: [
                _serialize_return_bucket(bucket)
                for bucket in sorted(values.values(), key=_bucket_t)
            ]
            for period, values in return_buckets.items()
        },
    }


def _build_return_buckets(
    *,
    buckets: dict[str, dict[int, dict[str, Any]]],
    task: Any,
    task_type_label: str,
    query: StrategyDataQuery,
    local_tz: ZoneInfo,
) -> None:
    current_bucket: dict[str, int | None] = {period: None for period in PERIODS}
    start_reference: dict[str, Decimal | None] = {period: None for period in PERIODS}
    previous_return: dict[str, Decimal | None] = {period: None for period in PERIODS}

    metrics_qs = Metrics.objects.filter(
        task_type=task_type_label,
        task_id=task.pk,
        execution_id=query.execution_id,
    )
    if query.since is not None:
        metrics_qs = metrics_qs.filter(timestamp__gte=query.since)
    if query.until is not None:
        metrics_qs = metrics_qs.filter(timestamp__lte=query.until)

    for timestamp, metrics in (
        metrics_qs.order_by("timestamp")
        .values_list("timestamp", "metrics")
        .iterator(chunk_size=5000)
    ):
        metric_timestamp = _aware_datetime(timestamp)
        if metric_timestamp is None:
            continue
        total_return = _total_return(metrics)
        if total_return is None:
            continue

        for period in PERIODS:
            start = _period_start(metric_timestamp, period, local_tz)
            bucket_key = int(start.timestamp())
            if current_bucket[period] != bucket_key:
                current_bucket[period] = bucket_key
                start_reference[period] = (
                    previous_return[period] if previous_return[period] is not None else total_return
                )

            reference = start_reference[period]
            if reference is None:
                reference = total_return
                start_reference[period] = reference

            bucket = _return_bucket_record(buckets[period], start, period)
            bucket["period_return"] = total_return - reference
            previous_return[period] = total_return


def _increment_all(
    buckets: dict[str, dict[int, dict[str, Any]]],
    timestamp: datetime,
    local_tz: ZoneInfo,
    key: str,
    amount: int | Decimal,
) -> None:
    for period in PERIODS:
        bucket = _bucket_record(buckets[period], timestamp, period, local_tz)
        bucket[key] += amount


def _bucket_record(
    bucket_map: dict[int, dict[str, Any]],
    timestamp: datetime,
    period: str,
    local_tz: ZoneInfo,
) -> dict[str, Any]:
    start = _period_start(timestamp, period, local_tz)
    unix_seconds = int(start.timestamp())
    record = bucket_map.get(unix_seconds)
    if record is None:
        record = {
            "t": unix_seconds,
            "timestamp": start.isoformat(),
            "label": _period_label(start, period),
            "tp_profit": Decimal("0"),
            "sl_loss": Decimal("0"),
            "open_positions": 0,
            "tp_closes": 0,
            "sl_closes": 0,
            "rebuild_opens": 0,
        }
        bucket_map[unix_seconds] = record
    return record


def _return_bucket_record(
    bucket_map: dict[int, dict[str, Any]],
    start: datetime,
    period: str,
) -> dict[str, Any]:
    unix_seconds = int(start.timestamp())
    record = bucket_map.get(unix_seconds)
    if record is None:
        record = {
            "t": unix_seconds,
            "timestamp": start.isoformat(),
            "label": _period_label(start, period),
            "period_return": Decimal("0"),
        }
        bucket_map[unix_seconds] = record
    return record


def _period_start(timestamp: datetime, period: str, local_tz: ZoneInfo) -> datetime:
    local = timestamp.astimezone(local_tz)
    if period == "day":
        return local.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        week_start = local - timedelta(days=local.weekday())
        return week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "month":
        return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if period == "year":
        return local.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    raise ValueError(f"Unsupported period: {period}")


def _period_label(start: datetime, period: str) -> str:
    if period == "day":
        return start.strftime("%Y-%m-%d")
    if period == "week":
        return start.strftime("%Y-%m-%d")
    if period == "month":
        return start.strftime("%Y-%m")
    if period == "year":
        return start.strftime("%Y")
    return start.isoformat()


def _serialize_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    return {
        "t": bucket["t"],
        "timestamp": bucket["timestamp"],
        "label": bucket["label"],
        "tp_profit": _decimal_string(bucket["tp_profit"]),
        "sl_loss": _decimal_string(bucket["sl_loss"]),
        "open_positions": int(bucket["open_positions"]),
        "tp_closes": int(bucket["tp_closes"]),
        "sl_closes": int(bucket["sl_closes"]),
        "rebuild_opens": int(bucket["rebuild_opens"]),
    }


def _serialize_return_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    return {
        "t": bucket["t"],
        "timestamp": bucket["timestamp"],
        "label": bucket["label"],
        "period_return": _decimal_string(bucket["period_return"]),
    }


def _bucket_t(bucket: dict[str, Any]) -> int:
    return int(bucket["t"])


def _realized_pnl(position: Position) -> Decimal | None:
    if position.entry_price is None or position.exit_price is None:
        return None
    units = Decimal(abs(int(position.units or 0)))
    direction = str(position.direction or "").lower()
    if direction == "long":
        return (position.exit_price - position.entry_price) * units
    if direction == "short":
        return (position.entry_price - position.exit_price) * units
    return Decimal("0")


def _total_return(metrics: Any) -> Decimal | None:
    if not isinstance(metrics, dict):
        return None
    raw = metrics.get("total_return")
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None


def _aware_datetime(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if timezone.is_naive(value):
        return timezone.make_aware(value)
    return value


def _timezone(value: str | None) -> ZoneInfo:
    name = str(value or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _quote_currency(task: Any) -> str | None:
    instrument = str(getattr(task, "instrument", "") or "")
    if instrument:
        quote = Instrument(instrument).quote_currency
        if quote:
            return quote
    for attr in ("display_currency", "account_currency"):
        value = str(getattr(task, attr, "") or "").strip().upper()
        if value:
            return value
    return None


def _decimal_string(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return format(normalized.quantize(Decimal("1")), "f")
    return format(normalized, "f")
