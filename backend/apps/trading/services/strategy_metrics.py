"""Metric and chart-layer projection for strategy data endpoints.

A single execution can produce hundreds of thousands of metric rows, so the
loaders here push pagination — and, where the database supports it, the
granularity bucketing — down to SQL rather than streaming every row into
Python. ``load_paginated_metric_points`` exposes the fast path used by
:class:`~apps.trading.services.strategy_data.StrategyDataService`. The
legacy in-memory helpers remain available for tests and light-weight call
sites that still iterate over complete result sets.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from django.conf import settings
from django.db import connection
from django.db.models import Max, Min, QuerySet

from apps.trading.models.metrics import ExecutionMetricAggregate, Metrics, MetricsRollup
from apps.trading.services.metric_money import MetricMoneyEnricher
from apps.trading.services.strategy_data_common import (
    DEFAULT_PAGE_SIZE,
    StrategyDataQuery,
    granularity_seconds,
)
from apps.trading.services.task_metrics import (
    ensure_metrics_dict,
    filter_metrics,
)

logger = logging.getLogger(__name__)

ROLLUP_GRANULARITY_BY_SECONDS = {
    5 * 60: "M5",
    15 * 60: "M15",
    60 * 60: "H1",
    4 * 60 * 60: "H4",
    24 * 60 * 60: "D",
}


@dataclass(frozen=True)
class MetricPageResult:
    rows: list[dict[str, Any]]
    count: int
    count_is_exact: bool = True
    has_next: bool = False
    elapsed_seconds: float = 0.0


@dataclass(frozen=True)
class SnowballMetricRepairContext:
    warmup_started_at: datetime | None
    warmup_completed_at: datetime


def load_paginated_metric_points(
    *, task: Any, task_type_label: str, query: StrategyDataQuery
) -> MetricPageResult:
    """Load one page of metric points along with the total row count.

    * ``raw`` granularity: a plain ``ORDER BY ... LIMIT/OFFSET`` over the
      ``metrics`` table. Runs on any backend Django supports.
    * bucketed granularities (``M5``, ``H1``, ``D`` …): rely on PostgreSQL
      window functions to keep only the latest row per bucket. On non-
      PostgreSQL backends we fall back to in-memory aggregation.
    """

    descending = query.ordering == "-timestamp"
    offset = max(0, (query.page - 1) * query.page_size)
    limit = query.page_size
    seconds = granularity_seconds(query.granularity)

    qs = _base_queryset(task=task, task_type_label=task_type_label, query=query)

    enricher = MetricMoneyEnricher.for_task(task=task, task_type_label=task_type_label)
    repair_context = _metric_repair_context(
        task=task,
        task_type_label=task_type_label,
        execution_id=query.execution_id,
    )
    started_at = time.monotonic()

    if seconds is None:
        result = _load_raw_page(
            qs=qs,
            query=query,
            enricher=enricher,
            descending=descending,
            limit=limit,
            offset=offset,
            repair_context=repair_context,
        )
        result = _with_elapsed(result, started_at)
        _log_metric_query(
            result=result,
            task=task,
            task_type_label=task_type_label,
            query=query,
            source="raw",
        )
        return result

    if connection.vendor == "postgresql":
        rollup_granularity = ROLLUP_GRANULARITY_BY_SECONDS.get(seconds)
        if rollup_granularity and _rollup_covers_query(
            task=task,
            task_type_label=task_type_label,
            query=query,
            seconds=seconds,
            granularity=rollup_granularity,
        ):
            result = _load_rollup_page(
                task=task,
                task_type_label=task_type_label,
                query=query,
                enricher=enricher,
                granularity=rollup_granularity,
                descending=descending,
                limit=limit,
                offset=offset,
                repair_context=repair_context,
            )
            result = _with_elapsed(result, started_at)
            _log_metric_query(
                result=result,
                task=task,
                task_type_label=task_type_label,
                query=query,
                source="rollup",
            )
            return result

        result = _load_bucketed_page_postgres(
            qs=qs,
            task=task,
            task_type_label=task_type_label,
            query=query,
            enricher=enricher,
            seconds=seconds,
            descending=descending,
            limit=limit,
            offset=offset,
            repair_context=repair_context,
        )
        result = _with_elapsed(result, started_at)
        _log_metric_query(
            result=result,
            task=task,
            task_type_label=task_type_label,
            query=query,
            source="bucketed_sql",
        )
        return result

    result = _load_bucketed_page_in_memory(
        qs=qs,
        query=query,
        enricher=enricher,
        seconds=seconds,
        descending=descending,
        limit=limit,
        offset=offset,
        repair_context=repair_context,
    )
    result = _with_elapsed(result, started_at)
    _log_metric_query(
        result=result,
        task=task,
        task_type_label=task_type_label,
        query=query,
        source="bucketed_memory",
    )
    return result


def load_latest_metric_point(
    *, task: Any, task_type_label: str, query: StrategyDataQuery
) -> dict[str, Any] | None:
    """Load the latest metric snapshot without counting the full execution."""
    repair_context = _metric_repair_context(
        task=task,
        task_type_label=task_type_label,
        execution_id=query.execution_id,
    )

    aggregate = (
        ExecutionMetricAggregate.objects.filter(
            task_type=task_type_label,
            task_id=task.pk,
            execution_id=query.execution_id,
        )
        .only("latest_timestamp", "latest_metrics")
        .first()
    )
    if (
        aggregate
        and aggregate.latest_timestamp is not None
        and isinstance(aggregate.latest_metrics, dict)
        and _timestamp_matches_query(aggregate.latest_timestamp, query)
    ):
        enricher = MetricMoneyEnricher.for_task(task=task, task_type_label=task_type_label)
        return _serialize_row(
            aggregate.latest_timestamp,
            aggregate.latest_metrics,
            query.metric_keys,
            enricher=enricher,
            repair_context=repair_context,
        )

    row = (
        _base_queryset(task=task, task_type_label=task_type_label, query=query)
        .order_by("-timestamp")
        .values_list("timestamp", "metrics")
        .first()
    )
    if row is None:
        return None
    timestamp, metrics = row
    enricher = MetricMoneyEnricher.for_task(task=task, task_type_label=task_type_label)
    return _serialize_row(
        timestamp,
        metrics,
        query.metric_keys,
        enricher=enricher,
        repair_context=repair_context,
    )


def load_metric_points(
    *, task: Any, task_type_label: str, query: StrategyDataQuery
) -> list[dict[str, Any]]:
    """Load every metric row for an execution into memory (legacy helper)."""

    qs = _base_queryset(task=task, task_type_label=task_type_label, query=query)
    enricher = MetricMoneyEnricher.for_task(task=task, task_type_label=task_type_label)
    repair_context = _metric_repair_context(
        task=task,
        task_type_label=task_type_label,
        execution_id=query.execution_id,
    )
    return [
        _serialize_row(
            timestamp,
            metrics,
            query.metric_keys,
            enricher=enricher,
            repair_context=repair_context,
        )
        for timestamp, metrics in qs.order_by("timestamp").values_list("timestamp", "metrics")
    ]


def aggregate_metric_points(rows: list[dict[str, Any]], granularity: str) -> list[dict[str, Any]]:
    """Collapse metric points to one row per bucket, keeping the latest entry."""

    seconds = granularity_seconds(granularity)
    if seconds is None:
        return rows
    bucketed: dict[int, dict[str, Any]] = {}
    for row in rows:
        bucket = int(row["t"]) // seconds * seconds
        bucketed[bucket] = row
    return [bucketed[key] for key in sorted(bucketed)]


def build_ohlc_layers(
    *,
    strategy_type: str,
    strategy_state: dict[str, Any],
    since: str | None,
    until: str | None,
    granularity: str,
    page: int,
    page_size: int,
    ordering: str,
) -> dict[str, Any]:
    return _empty_ohlc_layers()


def metric_consistency_warnings(*, task: Any, task_type_label: str, execution_id: Any) -> list[Any]:
    aggregate = (
        ExecutionMetricAggregate.objects.filter(
            task_type=task_type_label,
            task_id=task.pk,
            execution_id=execution_id,
        )
        .only("continuity_warnings")
        .first()
    )
    return (
        aggregate.continuity_warnings
        if aggregate and isinstance(aggregate.continuity_warnings, list)
        else []
    )


def _empty_ohlc_layers() -> dict[str, Any]:
    return {
        "price_series": [],
        "price_band_series": [],
        "pagination": {"count": 0, "page": 1, "page_size": DEFAULT_PAGE_SIZE},
    }


def _serialize_row(
    timestamp: Any,
    metrics: Any,
    metric_keys: tuple[str, ...],
    *,
    enricher: MetricMoneyEnricher | None = None,
    repair_context: SnowballMetricRepairContext | None = None,
) -> dict[str, Any]:
    metrics_dict = ensure_metrics_dict(metrics)
    if repair_context is not None:
        metrics_dict = _repair_snowball_stale_metrics(
            timestamp=timestamp,
            metrics=metrics_dict,
            context=repair_context,
        )
    if enricher is not None:
        metrics_dict = enricher.enrich(
            metrics_dict,
            timestamp=timestamp,
            metric_keys=metric_keys,
        )
    return {
        "t": int(timestamp.timestamp()),
        "timestamp": timestamp.isoformat(),
        "metrics": filter_metrics(metrics_dict, metric_keys),
    }


def _metric_repair_context(
    *,
    task: Any,
    task_type_label: str,
    execution_id: Any,
) -> SnowballMetricRepairContext | None:
    config = getattr(task, "config", None)
    if str(getattr(config, "strategy_type", "")) != "snowball":
        return None
    if execution_id is None:
        return None

    from apps.trading.models.state import ExecutionState

    strategy_state = (
        ExecutionState.objects.filter(
            task_type=task_type_label,
            task_id=task.pk,
            execution_id=execution_id,
        )
        .values_list("strategy_state", flat=True)
        .first()
    )
    if not isinstance(strategy_state, dict):
        return None

    completed_at = _parse_metric_datetime(strategy_state.get("warmup_completed_at"))
    if completed_at is None:
        return None
    return SnowballMetricRepairContext(
        warmup_started_at=_parse_metric_datetime(strategy_state.get("warmup_started_at")),
        warmup_completed_at=completed_at,
    )


def _repair_snowball_stale_metrics(
    *,
    timestamp: datetime,
    metrics: dict[str, Any],
    context: SnowballMetricRepairContext,
) -> dict[str, Any]:
    if _normalise_datetime(timestamp) < _normalise_datetime(context.warmup_completed_at):
        return metrics

    repaired = dict(metrics)
    repaired["warmup_status"] = "normal"
    repaired["warmup_block_reason"] = ""
    repaired["warmup_progress_pct"] = "100"
    repaired["warmup_unit_ratio_pct"] = "100"
    if context.warmup_started_at is not None:
        elapsed_minutes = int(
            (
                _normalise_datetime(timestamp) - _normalise_datetime(context.warmup_started_at)
            ).total_seconds()
            // 60
        )
        repaired["warmup_elapsed_minutes"] = str(max(0, elapsed_minutes))

    if not str(repaired.get("snowball_add_block_reason") or "").strip() and _is_blocked_metric(
        repaired.get("snowball_allow_new_positions")
    ):
        repaired["snowball_allow_new_positions"] = "1"
    if not str(repaired.get("snowball_rebuild_block_reason") or "").strip() and _is_blocked_metric(
        repaired.get("snowball_allow_rebuilds")
    ):
        repaired["snowball_allow_rebuilds"] = "1"
    return repaired


def _is_blocked_metric(value: Any) -> bool:
    return str(value).strip().lower() in {"0", "0.0", "false", "blocked", "stop", "stopped"}


def _parse_metric_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    raw = str(value)
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _normalise_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _base_queryset(
    *, task: Any, task_type_label: str, query: StrategyDataQuery
) -> QuerySet[Metrics]:
    qs = Metrics.objects.filter(
        task_type=task_type_label,
        task_id=task.pk,
        execution_id=query.execution_id,
    )
    if query.since is not None:
        qs = qs.filter(timestamp__gte=query.since)
    if query.until is not None:
        qs = qs.filter(timestamp__lte=query.until)
    return qs


def _timestamp_matches_query(timestamp: Any, query: StrategyDataQuery) -> bool:
    if query.since is not None and timestamp < query.since:
        return False
    if query.until is not None and timestamp > query.until:
        return False
    return True


def _load_raw_page(
    *,
    qs: QuerySet[Metrics],
    query: StrategyDataQuery,
    enricher: MetricMoneyEnricher,
    descending: bool,
    limit: int,
    offset: int,
    repair_context: SnowballMetricRepairContext | None,
) -> MetricPageResult:
    total = qs.count()
    order = "-timestamp" if descending else "timestamp"
    window = qs.order_by(order).values_list("timestamp", "metrics")[offset : offset + limit]
    rows = [
        _serialize_row(
            ts,
            metrics,
            query.metric_keys,
            enricher=enricher,
            repair_context=repair_context,
        )
        for ts, metrics in window
    ]
    return MetricPageResult(
        rows=rows,
        count=total,
        count_is_exact=True,
        has_next=offset + len(rows) < total,
    )


def _load_bucketed_page_postgres(
    *,
    qs: QuerySet[Metrics],
    task: Any,
    task_type_label: str,
    query: StrategyDataQuery,
    enricher: MetricMoneyEnricher,
    seconds: int,
    descending: bool,
    limit: int,
    offset: int,
    repair_context: SnowballMetricRepairContext | None,
) -> MetricPageResult:
    """Aggregate rows to one entry per bucket without sorting JSON payloads."""

    base_sql, base_params = (
        qs.order_by().values_list("timestamp", flat=True).query.sql_with_params()
    )

    order = "DESC" if descending else "ASC"
    page_sql = f"""
        WITH source_rows AS (
            SELECT source_timestamp
            FROM ({base_sql}) AS raw_metrics(source_timestamp)
        ),
        bucketed AS (
            SELECT
                (FLOOR(EXTRACT(EPOCH FROM source_timestamp) / %s) * %s)::bigint AS bucket,
                MAX(source_timestamp) AS source_timestamp
            FROM source_rows
            GROUP BY bucket
            ORDER BY bucket {order}
            LIMIT %s OFFSET %s
        )
        SELECT metrics.timestamp, metrics.metrics
        FROM bucketed
        JOIN metrics
          ON metrics.task_type = %s
         AND metrics.task_id = %s
         AND (
              (metrics.execution_id = %s)
              OR (metrics.execution_id IS NULL AND %s IS NULL)
         )
         AND metrics.timestamp = bucketed.source_timestamp
        ORDER BY bucketed.bucket {order}
    """  # nosec B608
    page_params = list(base_params) + [
        seconds,
        seconds,
        limit + 1,
        offset,
        task_type_label,
        task.pk,
        query.execution_id,
        query.execution_id,
    ]

    with connection.cursor() as cursor:
        cursor.execute(page_sql, page_params)
        raw_rows = cursor.fetchall()

    has_next = len(raw_rows) > limit
    raw_rows = raw_rows[:limit]
    rows = [
        _serialize_row(
            ts,
            metrics,
            query.metric_keys,
            enricher=enricher,
            repair_context=repair_context,
        )
        for ts, metrics in raw_rows
    ]
    return MetricPageResult(
        rows=rows,
        count=offset + len(rows) + (1 if has_next else 0),
        count_is_exact=False,
        has_next=has_next,
    )


def _load_bucketed_page_in_memory(
    *,
    qs: QuerySet[Metrics],
    query: StrategyDataQuery,
    enricher: MetricMoneyEnricher,
    seconds: int,
    descending: bool,
    limit: int,
    offset: int,
    repair_context: SnowballMetricRepairContext | None,
) -> MetricPageResult:
    """Fallback aggregation for non-PostgreSQL backends (primarily SQLite tests)."""

    bucketed: dict[int, tuple[Any, Any]] = {}
    for ts, metrics in qs.order_by("timestamp").values_list("timestamp", "metrics").iterator():
        bucket = int(ts.timestamp()) // seconds * seconds
        bucketed[bucket] = (ts, metrics)
    ordered = sorted(bucketed.items(), key=lambda item: item[0], reverse=descending)
    page = ordered[offset : offset + limit]
    rows = [
        _serialize_row(
            ts,
            metrics,
            query.metric_keys,
            enricher=enricher,
            repair_context=repair_context,
        )
        for _, (ts, metrics) in page
    ]
    total = len(ordered)
    return MetricPageResult(
        rows=rows,
        count=total,
        count_is_exact=True,
        has_next=offset + len(rows) < total,
    )


def _load_rollup_page(
    *,
    task: Any,
    task_type_label: str,
    query: StrategyDataQuery,
    enricher: MetricMoneyEnricher,
    granularity: str,
    descending: bool,
    limit: int,
    offset: int,
    repair_context: SnowballMetricRepairContext | None,
) -> MetricPageResult:
    qs = MetricsRollup.objects.filter(
        task_type=task_type_label,
        task_id=task.pk,
        execution_id=query.execution_id,
        granularity=granularity,
    )
    if query.since is not None:
        qs = qs.filter(bucket__gte=query.since)
    if query.until is not None:
        qs = qs.filter(bucket__lte=query.until)
    order = "-bucket" if descending else "bucket"
    raw_rows = list(
        qs.order_by(order).values_list("source_timestamp", "metrics")[offset : offset + limit + 1]
    )
    has_next = len(raw_rows) > limit
    raw_rows = raw_rows[:limit]
    rows = [
        _serialize_row(
            ts,
            metrics,
            query.metric_keys,
            enricher=enricher,
            repair_context=repair_context,
        )
        for ts, metrics in raw_rows
    ]
    return MetricPageResult(
        rows=rows,
        count=offset + len(rows) + (1 if has_next else 0),
        count_is_exact=False,
        has_next=has_next,
    )


def _rollup_covers_query(
    *,
    task: Any,
    task_type_label: str,
    query: StrategyDataQuery,
    seconds: int,
    granularity: str,
) -> bool:
    if query.since is not None or query.until is not None:
        return False

    rollup_qs = MetricsRollup.objects.filter(
        task_type=task_type_label,
        task_id=task.pk,
        execution_id=query.execution_id,
        granularity=granularity,
    )
    rollup_bounds = rollup_qs.aggregate(
        first=Min("bucket"),
        last_source=Max("source_timestamp"),
    )
    if rollup_bounds["first"] is None or rollup_bounds["last_source"] is None:
        return False

    metric_bounds_qs = Metrics.objects.filter(
        task_type=task_type_label,
        task_id=task.pk,
        execution_id=query.execution_id,
    )
    if query.since is not None:
        metric_bounds_qs = metric_bounds_qs.filter(timestamp__gte=query.since)
    if query.until is not None:
        metric_bounds_qs = metric_bounds_qs.filter(timestamp__lte=query.until)
    metric_bounds = metric_bounds_qs.aggregate(first=Min("timestamp"), last=Max("timestamp"))
    first_metric = metric_bounds["first"]
    last_metric = metric_bounds["last"]
    if first_metric is None or last_metric is None:
        return False

    return bool(
        rollup_bounds["first"] <= _datetime_bucket(first_metric, seconds)
        and rollup_bounds["last_source"] is not None
        and rollup_bounds["last_source"] >= last_metric
    )


def _datetime_bucket(value: Any, seconds: int) -> Any:
    epoch = int(value.timestamp())
    return datetime_from_epoch(epoch // seconds * seconds, value)


def datetime_from_epoch(epoch: int, sample: Any) -> Any:
    tzinfo = getattr(sample, "tzinfo", None)
    return datetime.fromtimestamp(epoch, tz=tzinfo)


def _with_elapsed(result: MetricPageResult, started_at: float) -> MetricPageResult:
    return MetricPageResult(
        rows=result.rows,
        count=result.count,
        count_is_exact=result.count_is_exact,
        has_next=result.has_next,
        elapsed_seconds=time.monotonic() - started_at,
    )


def _log_metric_query(
    *,
    result: MetricPageResult,
    task: Any,
    task_type_label: str,
    query: StrategyDataQuery,
    source: str,
) -> None:
    threshold = float(getattr(settings, "STRATEGY_METRICS_QUERY_LOG_THRESHOLD_SECONDS", 0.5))
    elapsed = result.elapsed_seconds
    if elapsed < threshold:
        return
    logger.info(
        "strategy metrics query source=%s task_type=%s task_id=%s execution_id=%s "
        "granularity=%s page=%s page_size=%s rows=%s count_exact=%s elapsed=%.3fs",
        source,
        task_type_label,
        task.pk,
        query.execution_id,
        query.granularity,
        query.page,
        query.page_size,
        len(result.rows),
        result.count_is_exact,
        elapsed,
    )
