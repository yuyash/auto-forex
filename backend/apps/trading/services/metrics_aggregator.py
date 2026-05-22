"""In-memory metrics aggregator that flushes minute-level records to the DB.

MetricsAggregator collects per-tick strategy metrics and writes one row
per minute bucket to the Metrics table.  Within each bucket the *last*
observed value for every key is kept (snapshot semantics).
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from django.db import connection
from django.utils import timezone

logger = logging.getLogger(__name__)

ROLLUP_GRANULARITIES_SECONDS = {
    "M5": 5 * 60,
    "M15": 15 * 60,
    "H1": 60 * 60,
    "H4": 4 * 60 * 60,
    "D": 24 * 60 * 60,
}
METRIC_RECORD_INTERVAL_SECONDS = 60

NON_TIMESERIES_METRIC_KEYS = frozenset(
    {
        # Large per-tick diagnostic payload. Keep it in ExecutionState when
        # explicitly enabled, but do not copy it into every minute snapshot.
        "snowball_decision_trace",
    }
)


def _truncate_to_minute(dt: datetime) -> datetime:
    """Return *dt* with seconds and microseconds zeroed out."""
    return dt.replace(second=0, microsecond=0)


def _serialise_value(v: Any) -> Any:
    """Convert Decimal / other non-JSON-native types to float."""
    if isinstance(v, Decimal):
        return float(v)
    return v


def _bucket_start(dt: datetime, seconds: int) -> datetime:
    """Return the UTC bucket start for a rollup granularity."""
    if timezone.is_naive(dt):
        aware = timezone.make_aware(dt, timezone=UTC)
    else:
        aware = dt.astimezone(UTC)
    epoch = int(aware.timestamp())
    bucket_epoch = epoch // seconds * seconds
    return datetime.fromtimestamp(bucket_epoch, tz=UTC)


def _decimal_metric(snapshot: dict[str, Any], key: str) -> Decimal | None:
    raw = snapshot.get(key)
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw))
    except Exception:  # nosec B110
        return None


@dataclass(frozen=True, slots=True)
class _TickRateAnchor:
    timestamp: datetime
    ticks_processed: Decimal
    execution_elapsed_seconds: Decimal | None = None


class MetricsAggregator:
    """Collect per-tick metrics and flush minute-level snapshots to the DB.

    Usage inside ``TaskExecutor``::

        agg = MetricsAggregator(task_type="backtest", task_id=uuid, execution_id=uuid)
        # on every tick:
        agg.record(tick.timestamp, state.strategy_state.get("metrics", {}))
        # periodically (e.g. after each batch):
        agg.flush()
        # at end of execution:
        agg.flush(final=True)
    """

    def __init__(
        self,
        *,
        task_type: str,
        task_id: str,
        execution_id: str | None,
    ) -> None:
        self.task_type = task_type
        self.task_id = task_id
        self.execution_id = execution_id
        # bucket_key (datetime truncated to minute) → latest metrics dict
        self._buckets: dict[datetime, dict[str, Any]] = {}
        self._tick_rate_anchor: _TickRateAnchor | None = None
        self._tick_rate_anchor_loaded = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(self, timestamp: datetime, metrics: dict[str, Any]) -> None:
        """Record a tick's metrics into the appropriate minute bucket."""
        if not metrics:
            return
        bucket_key = _truncate_to_minute(timestamp)
        serialised = {
            k: _serialise_value(v)
            for k, v in metrics.items()
            if v is not None and k not in NON_TIMESERIES_METRIC_KEYS
        }
        if not serialised:
            return
        # Last-write-wins within the same minute
        existing = self._buckets.get(bucket_key)
        if existing is None:
            self._buckets[bucket_key] = serialised
        else:
            existing.update(serialised)

    def flush(self, *, final: bool = False) -> int:
        """Write completed minute buckets to the database.

        By default only buckets whose minute has *ended* (i.e. a newer
        bucket exists) are flushed.  When *final* is True every remaining
        bucket is flushed — call this at the end of execution.

        Returns the number of rows written.
        """
        if not self._buckets:
            return 0

        from apps.trading.models.metrics import Metrics
        from apps.trading.models.metrics import ExecutionMetricAggregate
        from apps.trading.models.metrics import MetricsRollup

        sorted_keys = sorted(self._buckets)

        if final:
            keys_to_flush = sorted_keys
        else:
            # Flush all buckets except the latest (still accumulating).
            keys_to_flush = sorted_keys[:-1]

        if not keys_to_flush:
            return 0

        self._apply_tick_rates(metrics_model=Metrics, keys=keys_to_flush)

        objs = [
            Metrics(
                task_type=self.task_type,
                task_id=self.task_id,
                execution_id=self.execution_id,
                timestamp=bucket_key,
                metrics=self._buckets[bucket_key],
            )
            for bucket_key in keys_to_flush
        ]

        created = Metrics.objects.bulk_create(objs, ignore_conflicts=True)
        count = len(created)

        if keys_to_flush:
            latest_key = keys_to_flush[-1]
            latest_snapshot = self._buckets[latest_key]
            aggregate, _ = ExecutionMetricAggregate.objects.get_or_create(
                task_type=self.task_type,
                task_id=self.task_id,
                execution_id=self.execution_id,
                defaults={
                    "latest_timestamp": latest_key,
                    "latest_metrics": latest_snapshot,
                    "sample_count": 0,
                    "balance_min": _decimal_metric(latest_snapshot, "current_balance"),
                    "balance_max": _decimal_metric(latest_snapshot, "current_balance"),
                    "margin_ratio_min": _decimal_metric(latest_snapshot, "margin_ratio"),
                    "margin_ratio_max": _decimal_metric(latest_snapshot, "margin_ratio"),
                },
            )
            aggregate.latest_timestamp = latest_key
            aggregate.latest_metrics = latest_snapshot
            aggregate.sample_count = int(aggregate.sample_count) + len(keys_to_flush)
            current_balance = _decimal_metric(latest_snapshot, "current_balance")
            if current_balance is not None:
                aggregate.balance_min = (
                    current_balance
                    if aggregate.balance_min is None
                    else min(aggregate.balance_min, current_balance)
                )
                aggregate.balance_max = (
                    current_balance
                    if aggregate.balance_max is None
                    else max(aggregate.balance_max, current_balance)
                )
            margin_ratio = _decimal_metric(latest_snapshot, "margin_ratio")
            if margin_ratio is not None:
                aggregate.margin_ratio_min = (
                    margin_ratio
                    if aggregate.margin_ratio_min is None
                    else min(aggregate.margin_ratio_min, margin_ratio)
                )
                aggregate.margin_ratio_max = (
                    margin_ratio
                    if aggregate.margin_ratio_max is None
                    else max(aggregate.margin_ratio_max, margin_ratio)
                )
            aggregate.save(
                update_fields=[
                    "latest_timestamp",
                    "latest_metrics",
                    "sample_count",
                    "balance_min",
                    "balance_max",
                    "margin_ratio_min",
                    "margin_ratio_max",
                    "updated_at",
                ]
            )

            rollups = (
                self._build_rollup_rows(MetricsRollup, keys_to_flush)
                if connection.vendor == "postgresql"
                else []
            )
            if rollups:
                MetricsRollup.objects.bulk_create(
                    rollups,
                    update_conflicts=True,
                    update_fields=["source_timestamp", "metrics", "updated_at"],
                    unique_fields=[
                        "task_type",
                        "task_id",
                        "execution_id",
                        "granularity",
                        "bucket",
                    ],
                )

        logger.debug(
            "MetricsAggregator flushed %d/%d buckets (final=%s) for task %s",
            count,
            len(keys_to_flush),
            final,
            self.task_id,
        )

        for k in keys_to_flush:
            del self._buckets[k]

        return count

    def _apply_tick_rates(self, *, metrics_model: type[Any], keys: list[datetime]) -> None:
        """Derive ticks/sec from cumulative tick counts between metric rows."""
        if not keys:
            return

        anchor = self._tick_rate_anchor
        if anchor is None and not self._tick_rate_anchor_loaded:
            anchor = self._load_tick_rate_anchor(metrics_model=metrics_model, before=keys[0])
            self._tick_rate_anchor = anchor
            self._tick_rate_anchor_loaded = True

        for bucket_key in keys:
            snapshot = self._buckets[bucket_key]
            ticks_processed = _decimal_metric(snapshot, "ticks_processed")
            if ticks_processed is None:
                continue
            execution_elapsed_seconds = _decimal_metric(snapshot, "execution_elapsed_seconds")

            if anchor is None:
                tick_delta = ticks_processed
                interval_seconds = (
                    execution_elapsed_seconds
                    if execution_elapsed_seconds is not None and execution_elapsed_seconds > 0
                    else Decimal(METRIC_RECORD_INTERVAL_SECONDS)
                )
            else:
                tick_delta = ticks_processed - anchor.ticks_processed
                seconds = _tick_rate_interval_seconds(
                    current_elapsed=execution_elapsed_seconds,
                    anchor_elapsed=anchor.execution_elapsed_seconds,
                    later=bucket_key,
                    earlier=anchor.timestamp,
                )
                if seconds <= 0:
                    anchor = _TickRateAnchor(
                        timestamp=bucket_key,
                        ticks_processed=ticks_processed,
                        execution_elapsed_seconds=execution_elapsed_seconds,
                    )
                    self._tick_rate_anchor = anchor
                    continue
                interval_seconds = seconds

            tick_rate = max(tick_delta, Decimal("0")) / interval_seconds
            snapshot["ticks_per_second"] = f"{tick_rate:.6f}"
            anchor = _TickRateAnchor(
                timestamp=bucket_key,
                ticks_processed=ticks_processed,
                execution_elapsed_seconds=execution_elapsed_seconds,
            )
            self._tick_rate_anchor = anchor

    def _load_tick_rate_anchor(
        self,
        *,
        metrics_model: type[Any],
        before: datetime,
    ) -> _TickRateAnchor | None:
        """Return the latest persisted tick-count snapshot before this flush."""
        previous = (
            metrics_model.objects.filter(
                task_type=self.task_type,
                task_id=self.task_id,
                execution_id=self.execution_id,
                timestamp__lt=before,
            )
            .order_by("-timestamp")
            .only("timestamp", "metrics")
            .first()
        )
        if previous is None or not isinstance(previous.metrics, dict):
            return None
        ticks_processed = _decimal_metric(previous.metrics, "ticks_processed")
        if ticks_processed is None:
            return None
        return _TickRateAnchor(
            timestamp=previous.timestamp,
            ticks_processed=ticks_processed,
            execution_elapsed_seconds=_decimal_metric(
                previous.metrics, "execution_elapsed_seconds"
            ),
        )

    def _build_rollup_rows(
        self, metrics_rollup_model: type[Any], keys: list[datetime]
    ) -> list[Any]:
        """Build latest-per-bucket rollup rows for the flushed minute snapshots."""

        now = timezone.now()
        latest_by_bucket: dict[tuple[str, datetime], tuple[datetime, dict[str, Any]]] = {}
        for source_timestamp in keys:
            snapshot = self._buckets[source_timestamp]
            for granularity, seconds in ROLLUP_GRANULARITIES_SECONDS.items():
                bucket = _bucket_start(source_timestamp, seconds)
                key = (granularity, bucket)
                existing = latest_by_bucket.get(key)
                if existing is None or source_timestamp >= existing[0]:
                    latest_by_bucket[key] = (source_timestamp, snapshot)

        return [
            metrics_rollup_model(
                task_type=self.task_type,
                task_id=self.task_id,
                execution_id=self.execution_id,
                granularity=granularity,
                bucket=bucket,
                source_timestamp=source_timestamp,
                metrics=snapshot,
                created_at=now,
                updated_at=now,
            )
            for (granularity, bucket), (source_timestamp, snapshot) in latest_by_bucket.items()
        ]


def _seconds_between(*, later: datetime, earlier: datetime) -> float:
    """Return elapsed seconds, treating naive metric timestamps as UTC."""
    later_aware = timezone.make_aware(later, timezone=UTC) if timezone.is_naive(later) else later
    earlier_aware = (
        timezone.make_aware(earlier, timezone=UTC) if timezone.is_naive(earlier) else earlier
    )
    return (later_aware.astimezone(UTC) - earlier_aware.astimezone(UTC)).total_seconds()


def _tick_rate_interval_seconds(
    *,
    current_elapsed: Decimal | None,
    anchor_elapsed: Decimal | None,
    later: datetime,
    earlier: datetime,
) -> Decimal:
    """Return wall-clock metric interval when available, else timestamp interval."""
    if current_elapsed is not None and anchor_elapsed is not None:
        elapsed_delta = current_elapsed - anchor_elapsed
        if elapsed_delta > 0:
            return elapsed_delta
    return Decimal(str(_seconds_between(later=later, earlier=earlier)))
