"""Helpers for querying aggregated historical ticks for backtests."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from statistics import median

from django.conf import settings
from django.db import connection

from apps.market.models import TickData

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BacktestTickRow:
    """Normalized tick row returned for backtest replay."""

    timestamp: datetime
    bid: Decimal
    ask: Decimal
    mid: Decimal


_INTERVAL_SQL_BY_GRANULARITY: dict[str, str] = {
    "1s": "1 second",
    "10s": "10 seconds",
    "15s": "15 seconds",
    "30s": "30 seconds",
    "1m": "1 minute",
    "5m": "5 minutes",
    "15m": "15 minutes",
    "30m": "30 minutes",
    "1h": "1 hour",
}

_INTERVAL_SECONDS_BY_GRANULARITY: dict[str, int] = {
    "1s": 1,
    "10s": 10,
    "15s": 15,
    "30s": 30,
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
}


def iter_raw_backtest_ticks(
    *,
    instrument: str,
    start_dt: datetime,
    end_dt: datetime,
    batch_size: int,
) -> Iterator[BacktestTickRow]:
    """Yield raw backtest tick rows using bounded keyset queries.

    A multi-year raw tick replay can contain tens of millions of rows.  Avoid a
    single long-lived ``SELECT`` cursor for the full period; each query fetches
    at most ``batch_size`` rows and resumes after the last timestamp returned.
    """
    page_size = max(int(batch_size), 1)
    last_timestamp: datetime | None = None

    while True:
        filters = {
            "instrument": str(instrument),
            "timestamp__lte": end_dt,
        }
        if last_timestamp is None:
            filters["timestamp__gte"] = start_dt
        else:
            filters["timestamp__gt"] = last_timestamp

        rows = list(
            TickData.objects.filter(**filters)
            .order_by("timestamp")
            .values_list("timestamp", "bid", "ask", "mid")[:page_size]
        )
        if not rows:
            return

        for timestamp, bid, ask, mid in rows:
            last_timestamp = timestamp
            yield BacktestTickRow(
                timestamp=timestamp,
                bid=Decimal(str(bid)),
                ask=Decimal(str(ask)),
                mid=Decimal(str(mid)),
            )

        if len(rows) < page_size:
            return


def iter_aggregated_backtest_ticks(
    *,
    instrument: str,
    start_dt: datetime,
    end_dt: datetime,
    granularity: str,
    mode: str,
    batch_size: int,
    range_warning_pips: Decimal | None = None,
    pip_size: Decimal | None = None,
    request_id: str | None = None,
) -> Iterator[BacktestTickRow]:
    """Yield aggregated backtest tick rows from PostgreSQL.

    When ``range_warning_pips`` and ``pip_size`` are provided, each
    bucket's intra-bar bid range (high - low) is compared against the
    threshold and a WARNING log entry is emitted for each bucket that
    exceeds it.  This highlights aggregation windows where the price
    travelled far enough inside a single bar to invalidate SL / TP
    trigger semantics that assume tick-level precision.  The returned
    row itself is unchanged — the warning is purely diagnostic.
    """
    warn_threshold = _range_warn_threshold_price(range_warning_pips, pip_size)
    warning_limit = _range_warning_limit()

    if connection.vendor != "postgresql":
        yield from _iter_aggregated_backtest_ticks_python(
            instrument=instrument,
            start_dt=start_dt,
            end_dt=end_dt,
            granularity=granularity,
            mode=mode,
            batch_size=batch_size,
            warn_threshold=warn_threshold,
            range_warning_pips=range_warning_pips,
            warning_limit=warning_limit,
            request_id=request_id,
        )
        return

    interval_sql = _INTERVAL_SQL_BY_GRANULARITY[granularity]
    sql = _build_aggregation_sql(mode=mode, include_range_stats=warn_threshold is not None)
    warnings_logged = 0
    warnings_suppressed = 0
    with connection.cursor() as cursor:
        cursor.execute(sql, [interval_sql, instrument, start_dt, end_dt])
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                _log_range_warning_summary(
                    suppressed=warnings_suppressed,
                    limit=warning_limit,
                    instrument=instrument,
                    granularity=granularity,
                    request_id=request_id,
                )
                return
            for timestamp, bid, ask, mid, bid_high, bid_low in rows:
                bid_dec = Decimal(str(bid))
                ask_dec = Decimal(str(ask))
                mid_dec = Decimal(str(mid))
                if warn_threshold is not None and bid_high is not None and bid_low is not None:
                    bh = Decimal(str(bid_high))
                    bl = Decimal(str(bid_low))
                    bar_range = bh - bl
                    if bar_range > warn_threshold:
                        if warnings_logged < warning_limit:
                            _log_range_warning(
                                timestamp=timestamp,
                                bar_range=bar_range,
                                pip_size=pip_size,
                                granularity=granularity,
                                instrument=instrument,
                                bid_high=bh,
                                bid_low=bl,
                                threshold_pips=range_warning_pips,
                                request_id=request_id,
                            )
                            warnings_logged += 1
                        else:
                            warnings_suppressed += 1
                yield BacktestTickRow(
                    timestamp=timestamp,
                    bid=bid_dec,
                    ask=ask_dec,
                    mid=mid_dec,
                )


def _range_warn_threshold_price(
    range_warning_pips: Decimal | None,
    pip_size: Decimal | None,
) -> Decimal | None:
    """Convert the pip-denominated warning threshold to price units.

    Returns ``None`` when the threshold is disabled (non-positive or
    missing, or when ``pip_size`` is unavailable).
    """
    if range_warning_pips is None or pip_size is None:
        return None
    if range_warning_pips <= 0 or pip_size <= 0:
        return None
    return range_warning_pips * pip_size


def _range_warning_limit() -> int:
    """Return max per-bucket warning logs before summary-only reporting."""
    return max(int(getattr(settings, "MARKET_BACKTEST_BAR_RANGE_WARNING_LIMIT", 25)), 0)


def _log_range_warning(
    *,
    timestamp: datetime,
    bar_range: Decimal,
    pip_size: Decimal | None,
    granularity: str,
    instrument: str,
    bid_high: Decimal,
    bid_low: Decimal,
    threshold_pips: Decimal | None,
    request_id: str | None,
) -> None:
    """Emit a WARNING for a bucket whose intra-bar range exceeds the threshold."""
    if pip_size and pip_size > 0:
        range_pips = bar_range / pip_size
        range_repr = f"{range_pips:.1f} pips"
    else:
        range_repr = f"{bar_range}"
    threshold_repr = f"{threshold_pips} pips" if threshold_pips is not None else "n/a"
    request_suffix = f" request_id={request_id}" if request_id else ""
    logger.warning(
        "Aggregated backtest bar range exceeds warning threshold: "
        "instrument=%s granularity=%s bucket=%s range=%s (high=%s low=%s) "
        "threshold=%s — strategy SL/TP semantics may be inaccurate on this bar.%s",
        instrument,
        granularity,
        timestamp.isoformat() if hasattr(timestamp, "isoformat") else timestamp,
        range_repr,
        bid_high,
        bid_low,
        threshold_repr,
        request_suffix,
    )


def _log_range_warning_summary(
    *,
    suppressed: int,
    limit: int,
    instrument: str,
    granularity: str,
    request_id: str | None,
) -> None:
    """Emit one summary when per-bucket range warnings were rate-limited."""
    if suppressed <= 0:
        return
    request_suffix = f" request_id={request_id}" if request_id else ""
    logger.warning(
        "Aggregated backtest bar range warnings suppressed: "
        "instrument=%s granularity=%s suppressed=%s logged_limit=%s.%s",
        instrument,
        granularity,
        suppressed,
        limit,
        request_suffix,
    )


def _build_aggregation_sql(*, mode: str, include_range_stats: bool) -> str:
    filtered_cte = """
        WITH filtered AS (
            SELECT
                date_bin(%s::interval, timestamp, TIMESTAMPTZ '1970-01-01 00:00:00+00') AS bucket,
                timestamp,
                bid,
                ask,
                mid
            FROM tick_data
            WHERE instrument = %s
              AND timestamp >= %s
              AND timestamp <= %s
        )
    """

    range_stats_select = (
        "MAX(f.bid) AS bid_high, MIN(f.bid) AS bid_low"
        if include_range_stats
        else "NULL::numeric AS bid_high, NULL::numeric AS bid_low"
    )

    if mode == "average":
        average_sql = f"""
            SELECT
                f.bucket AS timestamp,
                AVG(f.bid) AS bid,
                AVG(f.ask) AS ask,
                AVG(f.mid) AS mid,
                {range_stats_select}
            FROM filtered f
            GROUP BY f.bucket
            ORDER BY f.bucket
            """  # nosec B608
        return filtered_cte + average_sql

    if mode == "median":
        median_sql = f"""
            SELECT
                f.bucket AS timestamp,
                percentile_cont(0.5) WITHIN GROUP (ORDER BY f.bid) AS bid,
                percentile_cont(0.5) WITHIN GROUP (ORDER BY f.ask) AS ask,
                percentile_cont(0.5) WITHIN GROUP (ORDER BY f.mid) AS mid,
                {range_stats_select}
            FROM filtered f
            GROUP BY f.bucket
            ORDER BY f.bucket
            """  # nosec B608
        return filtered_cte + median_sql

    ordering = "ASC" if mode == "first" else "DESC"
    if not include_range_stats:
        distinct_sql = f"""
        SELECT DISTINCT ON (f.bucket)
            f.bucket AS timestamp,
            f.bid,
            f.ask,
            f.mid,
            NULL::numeric AS bid_high,
            NULL::numeric AS bid_low
        FROM filtered f
        ORDER BY f.bucket, f.timestamp {ordering}
        """  # nosec B608
        return filtered_cte + distinct_sql

    ranked_sql = f"""
        , selected AS (
            SELECT DISTINCT ON (bucket)
                bucket,
                bid,
                ask,
                mid
            FROM filtered
            ORDER BY bucket, timestamp {ordering}
        ),
        bucket_stats AS (
            SELECT
                bucket,
                MAX(bid) AS bid_high,
                MIN(bid) AS bid_low
            FROM filtered
            GROUP BY bucket
        )
        SELECT
            s.bucket AS timestamp,
            s.bid,
            s.ask,
            s.mid,
            bs.bid_high,
            bs.bid_low
        FROM selected s
        JOIN bucket_stats bs ON bs.bucket = s.bucket
        ORDER BY s.bucket
        """  # nosec B608
    return filtered_cte + ranked_sql


def _iter_aggregated_backtest_ticks_python(
    *,
    instrument: str,
    start_dt: datetime,
    end_dt: datetime,
    granularity: str,
    mode: str,
    batch_size: int,
    warn_threshold: Decimal | None = None,
    range_warning_pips: Decimal | None = None,
    warning_limit: int = 25,
    request_id: str | None = None,
) -> Iterator[BacktestTickRow]:
    bucket_seconds = _INTERVAL_SECONDS_BY_GRANULARITY[granularity]
    qs = (
        TickData.objects.filter(
            instrument=instrument,
            timestamp__gte=start_dt,
            timestamp__lte=end_dt,
        )
        .order_by("timestamp")
        .values("timestamp", "bid", "ask", "mid")
    )
    buckets: dict[datetime, list[dict[str, Decimal | datetime]]] = {}
    for row in qs.iterator(chunk_size=batch_size):
        bucket = _bucket_start(row["timestamp"], bucket_seconds)
        buckets.setdefault(bucket, []).append(row)

    pip_size = None
    if warn_threshold is not None and range_warning_pips is not None and range_warning_pips > 0:
        pip_size = warn_threshold / range_warning_pips

    warnings_logged = 0
    warnings_suppressed = 0
    for bucket, rows in sorted(buckets.items(), key=lambda item: item[0]):
        bid_high = None
        bid_low = None
        if warn_threshold is not None:
            bid_values = [Decimal(str(row["bid"])) for row in rows]
            bid_high = max(bid_values) if bid_values else None
            bid_low = min(bid_values) if bid_values else None
        if (
            warn_threshold is not None
            and bid_high is not None
            and bid_low is not None
            and (bid_high - bid_low) > warn_threshold
        ):
            if warnings_logged < warning_limit:
                _log_range_warning(
                    timestamp=bucket,
                    bar_range=bid_high - bid_low,
                    pip_size=pip_size,
                    granularity=granularity,
                    instrument=instrument,
                    bid_high=bid_high,
                    bid_low=bid_low,
                    threshold_pips=range_warning_pips,
                    request_id=request_id,
                )
                warnings_logged += 1
            else:
                warnings_suppressed += 1

        if mode == "first":
            selected = rows[0]
            yield BacktestTickRow(
                timestamp=bucket,
                bid=Decimal(str(selected["bid"])),
                ask=Decimal(str(selected["ask"])),
                mid=Decimal(str(selected["mid"])),
            )
            continue

        if mode == "last":
            selected = rows[-1]
            yield BacktestTickRow(
                timestamp=bucket,
                bid=Decimal(str(selected["bid"])),
                ask=Decimal(str(selected["ask"])),
                mid=Decimal(str(selected["mid"])),
            )
            continue

        if mode == "average":
            count = Decimal(len(rows))
            yield BacktestTickRow(
                timestamp=bucket,
                bid=sum(Decimal(str(row["bid"])) for row in rows) / count,
                ask=sum(Decimal(str(row["ask"])) for row in rows) / count,
                mid=sum(Decimal(str(row["mid"])) for row in rows) / count,
            )
            continue

        yield BacktestTickRow(
            timestamp=bucket,
            bid=Decimal(str(median([Decimal(str(row["bid"])) for row in rows]))),
            ask=Decimal(str(median([Decimal(str(row["ask"])) for row in rows]))),
            mid=Decimal(str(median([Decimal(str(row["mid"])) for row in rows]))),
        )

    _log_range_warning_summary(
        suppressed=warnings_suppressed,
        limit=warning_limit,
        instrument=instrument,
        granularity=granularity,
        request_id=request_id,
    )


def _bucket_start(timestamp: datetime, bucket_seconds: int) -> datetime:
    ts_utc = timestamp.astimezone(UTC)
    floored = int(ts_utc.timestamp()) // bucket_seconds * bucket_seconds
    return datetime.fromtimestamp(floored, tz=UTC)
