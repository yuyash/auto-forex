"""Backtest tick publisher task runner."""

from __future__ import annotations

import time
from datetime import datetime
from decimal import Decimal
from logging import Logger, getLogger
from typing import Any

from celery import shared_task
from django.conf import settings

from apps.market.models import CeleryTaskStatus
from apps.market.services.backtest_ticks import (
    iter_aggregated_backtest_ticks,
    iter_raw_backtest_ticks,
)
from apps.market.services.backtest_tick_quality import BacktestTickQualityFilter
from apps.market.services.celery import CeleryTaskService
from apps.market.tasks.base import (
    backtest_stream_key_for_request,
    current_task_id,
    isoformat,
    lock_value,
    parse_iso_datetime,
    redis_client,
)

logger: Logger = getLogger(name=__name__)


@shared_task(bind=True, name="market.tasks.publish_ticks_for_backtest")
def publish_ticks_for_backtest(
    self: Any,
    instrument: str,
    start: str,
    end: str,
    request_id: str,
    tick_granularity: str = "tick",
    tick_window_value_mode: str = "last",
    execution_id: str | None = None,
    pip_size: str | None = None,
    bar_range_warning_pips: str | None = None,
    spread_filter_enabled: bool = False,
    max_spread_pips: str | None = None,
    oanda_candle_filter_enabled: bool = False,
    oanda_candle_filter_account_id: int | str | None = None,
    oanda_candle_filter_granularity: str = "M1",
    oanda_candle_filter_tolerance_pips: str | None = None,
) -> None:
    """Publish historical ticks from DB to Redis for a backtest run.

    Each signal creates a new Celery task. This task streams TickData rows in
    bounded chunks (doesn't load all ticks at once), publishes each tick to a
    dedicated per-request Redis channel, emits an EOF marker, then exits.

    Args:
        instrument: Currency pair
        start: Start time (ISO format)
        end: End time (ISO format)
        request_id: Unique request identifier
        execution_id: Optional execution UUID.  When provided, the stream
            key is scoped to this execution run so a restarted task never
            reuses leftover entries from a previous execution.
        pip_size: Pip size (as a decimal string) for the instrument.  Used
            together with ``bar_range_warning_pips`` to emit warnings on
            aggregated buckets whose intra-bar range is wider than the
            threshold.  Ignored when ``tick_granularity == "tick"``.
        bar_range_warning_pips: Intra-bar bid range (in pips) above which
            a WARNING is logged per bucket.  ``None`` or non-positive
            disables the check.
    """
    logger.info(
        f"[CELERY:PUBLISHER] Task started - request_id={request_id}, "
        f"execution_id={execution_id}, instrument={instrument}, "
        f"start={start}, end={end}, "
        f"tick_granularity={tick_granularity}, "
        f"tick_window_value_mode={tick_window_value_mode}, "
        f"celery_task_id={self.request.id}, worker={self.request.hostname}"
    )
    runner = BacktestTickPublisherRunner()
    runner.run(
        instrument,
        start,
        end,
        request_id,
        tick_granularity=tick_granularity,
        tick_window_value_mode=tick_window_value_mode,
        execution_id=execution_id,
        pip_size=pip_size,
        bar_range_warning_pips=bar_range_warning_pips,
        spread_filter_enabled=spread_filter_enabled,
        max_spread_pips=max_spread_pips,
        oanda_candle_filter_enabled=oanda_candle_filter_enabled,
        oanda_candle_filter_account_id=oanda_candle_filter_account_id,
        oanda_candle_filter_granularity=oanda_candle_filter_granularity,
        oanda_candle_filter_tolerance_pips=oanda_candle_filter_tolerance_pips,
    )
    logger.info(
        f"[CELERY:PUBLISHER] Task completed - request_id={request_id}, "
        f"celery_task_id={self.request.id}"
    )


class BacktestTickPublisherRunner:
    """Runner for backtest tick publisher task."""

    def __init__(self) -> None:
        """Initialize the backtest publisher runner."""
        self.task_service: CeleryTaskService | None = None
        self._last_executor_stop_check_monotonic = 0.0
        self._cached_executor_should_stop = False

    def run(
        self,
        instrument: str,
        start: str,
        end: str,
        request_id: str,
        *,
        tick_granularity: str = "tick",
        tick_window_value_mode: str = "last",
        execution_id: str | None = None,
        pip_size: str | None = None,
        bar_range_warning_pips: str | None = None,
        spread_filter_enabled: bool = False,
        max_spread_pips: str | None = None,
        oanda_candle_filter_enabled: bool = False,
        oanda_candle_filter_account_id: int | str | None = None,
        oanda_candle_filter_granularity: str = "M1",
        oanda_candle_filter_tolerance_pips: str | None = None,
    ) -> None:
        """Execute the backtest tick publishing task.

        Args:
            instrument: Currency pair
            start: Start time (ISO format)
            end: End time (ISO format)
            request_id: Unique request identifier
            pip_size: Pip size as a decimal string.  Required (paired with
                ``bar_range_warning_pips``) to enable aggregated-bar range
                warnings.
            bar_range_warning_pips: Intra-bar bid range threshold in pips.
                Non-positive or missing disables the warning.
        """
        logger.info(
            f"[PUBLISHER:RUN] Starting publisher runner - request_id={request_id}, "
            f"instrument={instrument}, start={start}, end={end}, "
            f"tick_granularity={tick_granularity}, "
            f"tick_window_value_mode={tick_window_value_mode}"
        )

        task_name = "market.tasks.publish_ticks_for_backtest"
        instance_key = str(request_id)
        self.task_service = CeleryTaskService(
            task_name=task_name,
            instance_key=instance_key,
            stop_check_interval_seconds=float(
                getattr(settings, "MARKET_BACKTEST_STOP_CHECK_INTERVAL_SECONDS", 1.0)
            ),
            heartbeat_interval_seconds=5.0,
        )

        logger.info(
            f"[PUBLISHER:RUN] Starting task service - request_id={request_id}, "
            f"task_name={task_name}, instance_key={instance_key}"
        )

        self.task_service.start(
            celery_task_id=current_task_id(),
            worker=lock_value(),
            meta={
                "instrument": str(instrument),
                "start": str(start),
                "end": str(end),
                "tick_granularity": str(tick_granularity),
                "tick_window_value_mode": str(tick_window_value_mode),
            },
        )

        channel = backtest_stream_key_for_request(str(request_id), execution_id)
        batch_size = int(getattr(settings, "MARKET_BACKTEST_PUBLISH_BATCH_SIZE", 1000))
        stream_maxlen = int(getattr(settings, "MARKET_BACKTEST_STREAM_MAXLEN", 200_000))
        high_watermark = int(
            getattr(settings, "MARKET_BACKTEST_BACKPRESSURE_HIGH_WATERMARK", 100_000)
        )
        low_watermark = int(getattr(settings, "MARKET_BACKTEST_BACKPRESSURE_LOW_WATERMARK", 50_000))
        backpressure_check_interval = self._backpressure_check_interval(
            stream_maxlen=stream_maxlen,
            high_watermark=high_watermark,
            configured_interval=int(
                getattr(settings, "MARKET_BACKTEST_BACKPRESSURE_CHECK_INTERVAL", 100)
            ),
        )
        backpressure_sleep = float(
            getattr(settings, "MARKET_BACKTEST_BACKPRESSURE_SLEEP_SECONDS", 0.5)
        )
        consumer_group = str(getattr(settings, "MARKET_BACKTEST_STREAM_CONSUMER_GROUP", "backtest"))

        start_dt = parse_iso_datetime(start)
        end_dt = parse_iso_datetime(end)

        logger.info(
            f"[PUBLISHER:RUN] Configuration - request_id={request_id}, "
            f"stream={channel}, batch_size={batch_size}, "
            f"stream_maxlen={stream_maxlen}, "
            f"backpressure_high={high_watermark}, backpressure_low={low_watermark}, "
            f"backpressure_check_interval={backpressure_check_interval}, "
            f"consumer_group={consumer_group}, "
            f"start_dt={start_dt}, end_dt={end_dt}, "
            f"tick_granularity={tick_granularity}, "
            f"tick_window_value_mode={tick_window_value_mode}"
        )

        client = redis_client()
        published = 0

        # Ensure the consumer group starts fresh.  Do not delete the stream
        # here: the subscriber can already be blocked on XREADGROUP after
        # triggering this publisher, and Redis unblocks that reader with
        # ``UNBLOCKED the stream key no longer exists`` when the key is
        # deleted.  The stream key includes execution_id for normal runs,
        # so stale entries from older executions are isolated by key.  For
        # same-key legacy/recovery cases, recreating the group at "$" below
        # keeps this execution from reading pre-existing entries.
        try:
            destroyed = client.xgroup_destroy(channel, consumer_group)
            if destroyed:
                logger.info(
                    f"[PUBLISHER:RUN] Destroyed stale consumer group - "
                    f"request_id={request_id}, stream={channel}, group={consumer_group}"
                )
        except Exception as exc:  # nosec B110
            # Stream not found, group not found, etc. — all non-fatal.
            logger.debug(
                f"[PUBLISHER:RUN] xgroup_destroy failed (non-fatal) - "
                f"request_id={request_id}, error={exc}"
            )

        # Create the consumer group the subscriber will read from.  The
        # group reads start at ``$`` so only entries added by the
        # current run are delivered.  ``MKSTREAM`` creates the stream
        # if it does not already exist.
        self._ensure_consumer_group(client, channel, consumer_group, request_id)

        try:
            logger.info(f"[PUBLISHER:RUN] Starting tick publishing - request_id={request_id}")
            published, source_count, last_tick_ts, stopped_early = self._publish_ticks(
                client,
                channel,
                instrument,
                start_dt,
                end_dt,
                batch_size,
                request_id,
                tick_granularity=tick_granularity,
                tick_window_value_mode=tick_window_value_mode,
                stream_maxlen=stream_maxlen,
                high_watermark=high_watermark,
                low_watermark=low_watermark,
                backpressure_check_interval=backpressure_check_interval,
                backpressure_sleep=backpressure_sleep,
                consumer_group=consumer_group,
                pip_size=pip_size,
                bar_range_warning_pips=bar_range_warning_pips,
                spread_filter_enabled=spread_filter_enabled,
                max_spread_pips=max_spread_pips,
                oanda_candle_filter_enabled=oanda_candle_filter_enabled,
                oanda_candle_filter_account_id=oanda_candle_filter_account_id,
                oanda_candle_filter_granularity=oanda_candle_filter_granularity,
                oanda_candle_filter_tolerance_pips=oanda_candle_filter_tolerance_pips,
            )

            if stopped_early:
                logger.info(
                    f"[PUBLISHER:RUN] Publishing stopped before completion - request_id={request_id}, "
                    f"published={published}, source_count={source_count}, last_tick_ts={last_tick_ts}"
                )
                return

            # Check for insufficient data coverage
            data_gap = self._check_data_coverage(
                instrument, start_dt, end_dt, source_count, last_tick_ts, request_id
            )

            if data_gap:
                # Data does not cover the requested range — mark as failed
                logger.error(
                    f"[PUBLISHER:RUN] INSUFFICIENT_DATA - request_id={request_id}, "
                    f"published={published}, source_count={source_count}, last_tick_ts={last_tick_ts}, "
                    f"end_dt={end_dt}, gap={data_gap}"
                )
                self._send_error(
                    client,
                    channel,
                    request_id,
                    instrument,
                    f"Insufficient tick data: {data_gap}",
                )
                assert self.task_service is not None
                self.task_service.mark_stopped(
                    status=CeleryTaskStatus.Status.FAILED,
                    status_message=f"Insufficient tick data: {data_gap}",
                )
                # Also mark the BacktestTask as failed
                self._mark_backtest_task_failed(request_id, data_gap)
                return

            # Send EOF marker
            logger.info(
                f"[PUBLISHER:RUN] Publishing completed, sending EOF - request_id={request_id}, "
                f"published={published}"
            )
            self._send_eof(client, channel, request_id, instrument, start, end, published)

            logger.info(
                f"[PUBLISHER:RUN] Finished successfully - request_id={request_id}, "
                f"published={published}"
            )

            assert self.task_service is not None
            self.task_service.mark_stopped(
                status=CeleryTaskStatus.Status.COMPLETED,
                status_message=f"published={published}",
            )
        except Exception as exc:
            logger.exception(
                f"[PUBLISHER:RUN] FAILED - request_id={request_id}, "
                f"published={published}, error={exc}"
            )
            self._send_error(client, channel, request_id, instrument, str(exc))

            assert self.task_service is not None
            self.task_service.mark_stopped(
                status=CeleryTaskStatus.Status.FAILED,
                status_message=str(exc),
            )
            raise

        finally:
            try:
                client.close()
                logger.info(f"[PUBLISHER:RUN] Redis client closed - request_id={request_id}")
            except Exception as exc:  # nosec B110
                # Log cleanup failure but don't raise
                logger.debug(
                    f"[PUBLISHER:RUN] Failed to close Redis client - request_id={request_id}, "
                    f"error={exc}"
                )

    def _publish_ticks(
        self,
        client: Any,
        channel: str,
        instrument: str,
        start_dt: datetime,
        end_dt: datetime,
        batch_size: int,
        request_id: str,
        *,
        tick_granularity: str = "tick",
        tick_window_value_mode: str = "last",
        stream_maxlen: int = 200_000,
        high_watermark: int = 100_000,
        low_watermark: int = 50_000,
        backpressure_check_interval: int = 100,
        backpressure_sleep: float = 0.5,
        consumer_group: str = "backtest",
        pip_size: str | None = None,
        bar_range_warning_pips: str | None = None,
        spread_filter_enabled: bool = False,
        max_spread_pips: str | None = None,
        oanda_candle_filter_enabled: bool = False,
        oanda_candle_filter_account_id: int | str | None = None,
        oanda_candle_filter_granularity: str = "M1",
        oanda_candle_filter_tolerance_pips: str | None = None,
    ) -> tuple[int, int, datetime | None, bool]:
        """Publish ticks to the per-request Redis Stream.

        Uses ``XADD`` with ``MAXLEN`` trimming for a bounded stream and
        consumer-group-aware backpressure via ``XPENDING``: when the number
        of **unacknowledged** entries (i.e. delivered to the consumer but
        not yet processed) exceeds ``high_watermark`` the publisher pauses
        until the consumer has drained below ``low_watermark``.

        This is essential because plain ``XLEN`` is a pure push-side
        counter — it never decreases as the consumer reads, so an
        ``XLEN``-based backpressure loop would deadlock the moment the
        subscriber has read every entry but before the stream is trimmed.
        ``XPENDING`` reflects real consumer lag.

        Returns:
            Tuple of (published_count, source_count, last_source_timestamp, stopped_early).
        """
        assert self.task_service is not None

        logger.info(
            f"[PUBLISHER:PUBLISH] Starting tick query - request_id={request_id}, "
            f"instrument={instrument}, start_dt={start_dt}, end_dt={end_dt}, "
            f"tick_granularity={tick_granularity}, "
            f"tick_window_value_mode={tick_window_value_mode}"
        )

        published = 0
        source_count = 0
        last_ts: datetime | None = None
        last_published_ts: datetime | None = None
        backpressure_waiting = False

        # Window-level tracking so we can emit an INFO log for every
        # publisher "batch" (every ``progress_every`` ticks) that
        # records the simulated-time range of the ticks written to
        # Redis in that window along with wall-clock time.  This makes
        # it trivially easy to answer "when did the publisher send
        # ticks covering simulated time X?" without having to parse
        # per-tick logs.
        progress_every = max(batch_size * 10, 1)
        window_first_ts: datetime | None = None
        window_count = 0

        logger.info(
            f"[PUBLISHER:PUBLISH] Query created, starting iteration - request_id={request_id}"
        )

        if tick_granularity != "tick":
            raise ValueError(
                "Backtest execution requires raw tick replay. Aggregated tick granularity "
                f"({tick_granularity}) can produce synthetic or out-of-order fills."
            )

        tick_filter = BacktestTickQualityFilter(
            request_id=request_id,
            instrument=instrument,
            start_dt=start_dt,
            end_dt=end_dt,
            pip_size=pip_size,
            spread_filter_enabled=spread_filter_enabled,
            max_spread_pips=max_spread_pips,
            candle_filter_enabled=oanda_candle_filter_enabled,
            candle_filter_account_id=oanda_candle_filter_account_id,
            candle_filter_granularity=oanda_candle_filter_granularity,
            candle_filter_tolerance_pips=oanda_candle_filter_tolerance_pips,
        )

        rows_iter = self._iter_raw_ticks(
            instrument=instrument,
            start_dt=start_dt,
            end_dt=end_dt,
            batch_size=batch_size,
        )

        for row in rows_iter:
            # Check stop signal before every tick.  The service and executor
            # status probes are cached internally, so this keeps stop
            # responsiveness without issuing DB queries per row.
            if self._should_stop_publishing(request_id):
                logger.info(
                    f"[PUBLISHER:PUBLISH] Stop signal received - request_id={request_id}, "
                    f"instrument={instrument}, published={published}"
                )
                self._send_stopped(client, channel, request_id, instrument, published)
                self.task_service.mark_stopped(
                    status=CeleryTaskStatus.Status.STOPPED,
                    status_message=f"published={published}",
                )
                tick_filter.log_summary(published=published, source_count=source_count)
                return published, source_count, last_ts, True

            ts = row["timestamp"]
            if not isinstance(ts, datetime):
                continue
            source_count += 1
            last_ts = ts

            if not tick_filter.should_publish(row):
                continue

            # Backpressure: pause when the consumer is falling behind.
            # ``XPENDING`` returns the count of delivered-but-unacknowledged
            # entries, which is the true consumer-group lag.  Plain
            # ``XLEN`` would be wrong here — it never decreases as the
            # consumer reads, so it would hold the publisher indefinitely
            # after the first ``high_watermark`` entries have been
            # delivered.
            if high_watermark > 0 and self._should_check_backpressure(
                published=published,
                check_interval=backpressure_check_interval,
                already_waiting=backpressure_waiting,
            ):
                backpressure_waiting = self._apply_backpressure(
                    client=client,
                    channel=channel,
                    request_id=request_id,
                    high_watermark=high_watermark,
                    low_watermark=low_watermark,
                    sleep_seconds=backpressure_sleep,
                    already_waiting=backpressure_waiting,
                    consumer_group=consumer_group,
                )
                # If a stop signal arrived while we were waiting, bail out.
                if self._should_stop_publishing(request_id, force=True):
                    logger.info(
                        f"[PUBLISHER:PUBLISH] Stop signal received during backpressure - "
                        f"request_id={request_id}, published={published}"
                    )
                    self._send_stopped(client, channel, request_id, instrument, published)
                    self.task_service.mark_stopped(
                        status=CeleryTaskStatus.Status.STOPPED,
                        status_message=f"published={published}",
                    )
                    tick_filter.log_summary(published=published, source_count=source_count)
                    return published, source_count, last_ts, True

            try:
                client.xadd(
                    channel,
                    {
                        "type": "tick",
                        "request_id": str(request_id),
                        "instrument": str(instrument),
                        "timestamp": isoformat(ts),
                        "bid": str(row["bid"]),
                        "ask": str(row["ask"]),
                        "mid": str(row["mid"]),
                    },
                    maxlen=stream_maxlen,
                    approximate=True,
                )
            except Exception as exc:
                logger.exception(
                    f"[PUBLISHER:PUBLISH] XADD failed - request_id={request_id}, "
                    f"published={published}, error={exc}"
                )
                raise

            published += 1
            last_published_ts = ts
            if window_first_ts is None:
                window_first_ts = ts
            window_count += 1

            if published % progress_every == 0:
                logger.info(
                    f"[PUBLISHER:BATCH] Published batch - request_id={request_id}, "
                    f"published={published}, window_count={window_count}, "
                    f"window_first_ts={window_first_ts.isoformat() if window_first_ts else None}, "
                    f"window_last_ts={ts.isoformat() if ts else None}"
                )
                self.task_service.heartbeat(
                    status_message=f"published={published}",
                    meta_update={"published": published},
                )
                window_first_ts = None
                window_count = 0

        # Flush the tail window that did not reach ``progress_every``
        # so the final simulated-time coverage is always logged.
        if window_count > 0 and window_first_ts is not None and last_published_ts is not None:
            logger.info(
                f"[PUBLISHER:BATCH] Published batch (tail) - request_id={request_id}, "
                f"published={published}, window_count={window_count}, "
                f"window_first_ts={window_first_ts.isoformat()}, "
                f"window_last_ts={last_published_ts.isoformat()}"
            )

        logger.info(
            f"[PUBLISHER:PUBLISH] Iteration complete - request_id={request_id}, "
            f"source_count={source_count}, total_published={published}, "
            f"last_source_ts={last_ts}, last_published_ts={last_published_ts}"
        )
        tick_filter.log_summary(published=published, source_count=source_count)
        return published, source_count, last_ts, False

    @staticmethod
    def _backpressure_check_interval(
        *,
        stream_maxlen: int,
        high_watermark: int,
        configured_interval: int,
    ) -> int:
        """Return a safe interval for Redis lag checks.

        The publisher can overshoot the high watermark by at most this
        interval.  Clamp it to half of the stream headroom so a slow
        subscriber still has room before Redis MAXLEN trimming can remove
        undelivered entries.
        """
        if high_watermark <= 0:
            return 1
        headroom = stream_maxlen - high_watermark
        if headroom <= 1:
            return 1
        safe_interval = max(1, headroom // 2)
        return max(1, min(int(configured_interval or 1), safe_interval))

    @staticmethod
    def _should_check_backpressure(
        *,
        published: int,
        check_interval: int,
        already_waiting: bool,
    ) -> bool:
        if already_waiting:
            return True
        return published % max(check_interval, 1) == 0

    @staticmethod
    def _ensure_consumer_group(
        client: Any, channel: str, consumer_group: str, request_id: str
    ) -> None:
        """Create the stream's consumer group, ignoring BUSYGROUP errors.

        ``XGROUP CREATE ... MKSTREAM`` also creates an empty stream if it
        does not already exist.  ``$`` starts the group from the tip of
        the stream, which is the right default because the publisher
        clears the stream before creating the group.
        """
        try:
            client.xgroup_create(channel, consumer_group, id="$", mkstream=True)
            logger.info(
                f"[PUBLISHER:GROUP] Created consumer group - request_id={request_id}, "
                f"stream={channel}, group={consumer_group}"
            )
        except Exception as exc:
            if "BUSYGROUP" in str(exc):
                logger.info(
                    f"[PUBLISHER:GROUP] Reusing existing consumer group - "
                    f"request_id={request_id}, stream={channel}, group={consumer_group}"
                )
                return
            logger.exception(
                f"[PUBLISHER:GROUP] Failed to create consumer group - "
                f"request_id={request_id}, stream={channel}, group={consumer_group}"
            )
            raise

    @staticmethod
    def _xpending_count(client: Any, channel: str, consumer_group: str) -> int:
        """Return the total number of pending (unACKed) entries.

        ``XPENDING stream group`` returns a summary array whose first
        element is the pending count.  Different ``redis-py`` versions
        and fakeredis builds return this either as a raw list/tuple or
        as a dict (``{"pending": n, ...}``).  We accept both shapes.
        """
        try:
            info = client.xpending(channel, consumer_group)
        except Exception:
            return 0

        if info is None:
            return 0

        if isinstance(info, dict):
            return int(info.get("pending", 0) or 0)

        # ``(pending_count, min_id, max_id, [[consumer, count], ...])``
        try:
            return int(info[0])
        except (IndexError, TypeError, ValueError):
            return 0

    @staticmethod
    def _group_lag(client: Any, channel: str, consumer_group: str) -> int | None:
        """Return the consumer group's total lag (undelivered + pending).

        ``XINFO GROUPS`` reports a ``lag`` field per group which counts
        the entries that have been added to the stream but not yet
        delivered to any consumer in the group, i.e. those that the
        subscriber would obtain from its next ``XREADGROUP ... >``.
        Adding the group's ``pending`` count gives the true queue depth
        the subscriber still has to work through.  This is the signal
        we must back-pressure on — ``XPENDING`` alone only counts
        entries the subscriber has already read with ``XREADGROUP`` but
        has not yet ACKed, so if the subscriber stalls before even
        reading an entry, ``XPENDING`` stays at zero and the publisher
        would happily keep adding entries, eventually forcing MAXLEN
        trim to drop undelivered data.

        Returns ``None`` when ``XINFO GROUPS`` does not expose ``lag``
        (older Redis or fakeredis).  Callers must fall back to
        ``XLEN`` + ``XPENDING`` heuristics in that case.
        """
        try:
            groups = client.xinfo_groups(channel)
        except Exception:
            return None

        if not isinstance(groups, (list, tuple)) or not groups:
            return None

        for group in groups:
            name = None
            lag = None
            pending = None
            if isinstance(group, dict):
                name = group.get("name")
                lag = group.get("lag")
                pending = group.get("pending")
            else:
                try:
                    mapping = dict(zip(group[::2], group[1::2], strict=False))
                except (TypeError, ValueError):
                    continue
                name = mapping.get("name")
                lag = mapping.get("lag")
                pending = mapping.get("pending")

            if str(name) != consumer_group:
                continue
            if lag is None:
                return None
            try:
                lag_int = int(lag)
            except (TypeError, ValueError):
                return None
            try:
                pending_int = int(pending) if pending is not None else 0
            except (TypeError, ValueError):
                pending_int = 0
            return lag_int + pending_int

        return None

    def _consumer_lag(self, client: Any, channel: str, consumer_group: str) -> int:
        """Best-effort consumer lag: prefer XINFO GROUPS lag, fall back
        to XPENDING. ``XLEN`` is a very conservative fallback because
        it does not shrink on ACK, but it is only used when the
        previous two probes are unavailable.
        """
        group_lag = self._group_lag(client, channel, consumer_group)
        if group_lag is not None:
            return group_lag
        pending = self._xpending_count(client, channel, consumer_group)
        try:
            return max(pending, int(client.xlen(channel)))
        except Exception:
            return pending

    def _apply_backpressure(
        self,
        *,
        client: Any,
        channel: str,
        request_id: str,
        high_watermark: int,
        low_watermark: int,
        sleep_seconds: float,
        already_waiting: bool,
        consumer_group: str,
    ) -> bool:
        """Sleep while more entries are pending than allowed.

        Uses :meth:`_consumer_lag` (XINFO GROUPS ``lag`` + ``pending``)
        so ticks that the publisher has written but the subscriber has
        not yet read via ``XREADGROUP ... >`` still count toward the
        queue depth.  This is crucial: ``XPENDING`` alone only tracks
        entries that were delivered then not ACKed, so a stalled
        subscriber would leave ``XPENDING`` at zero and the publisher
        would happily keep adding entries until ``MAXLEN`` trim
        silently dropped undelivered data.  We hit that exact failure
        mode once (see task 788010da in April 2026, which produced a
        five-day tick gap because ~700k undelivered entries aged out
        of a 200k stream).

        Returns the updated ``waiting`` flag so the caller can avoid
        spamming the log.  We only log once at the start and end of
        each back-pressure episode.
        """
        lag = self._consumer_lag(client, channel, consumer_group)

        if lag < high_watermark:
            if already_waiting and lag <= low_watermark:
                logger.info(
                    f"[PUBLISHER:BACKPRESSURE] Consumer caught up, resuming - "
                    f"request_id={request_id}, lag={lag}"
                )
                return False
            return already_waiting

        if not already_waiting:
            logger.info(
                f"[PUBLISHER:BACKPRESSURE] Consumer falling behind, pausing - "
                f"request_id={request_id}, lag={lag}, "
                f"high_watermark={high_watermark}, low_watermark={low_watermark}"
            )

        # Block here until pending entries drain below the low watermark
        # or the consumer disappears.  We re-check periodically so a stop
        # signal isn't delayed for more than ``sleep_seconds``.
        while True:
            time.sleep(max(sleep_seconds, 0.01))
            # Allow the publisher to bail out during long pauses.
            if self._should_stop_publishing(request_id, force=True):
                logger.info(
                    f"[PUBLISHER:BACKPRESSURE] Stop signal received while paused - "
                    f"request_id={request_id}, lag={lag}"
                )
                return True
            lag = self._consumer_lag(client, channel, consumer_group)
            if lag <= low_watermark:
                logger.info(
                    f"[PUBLISHER:BACKPRESSURE] Drained below low watermark - "
                    f"request_id={request_id}, lag={lag}"
                )
                return False

    @staticmethod
    def _iter_raw_ticks(
        *,
        instrument: str,
        start_dt: datetime,
        end_dt: datetime,
        batch_size: int,
    ) -> Any:
        for row in iter_raw_backtest_ticks(
            instrument=instrument,
            start_dt=start_dt,
            end_dt=end_dt,
            batch_size=batch_size,
        ):
            yield {
                "timestamp": row.timestamp,
                "bid": row.bid,
                "ask": row.ask,
                "mid": row.mid,
            }

    @staticmethod
    def _iter_aggregated_ticks(
        *,
        instrument: str,
        start_dt: datetime,
        end_dt: datetime,
        granularity: str,
        mode: str,
        batch_size: int,
        pip_size: str | None = None,
        range_warning_pips: str | None = None,
        request_id: str | None = None,
    ) -> Any:
        pip_size_dec: Decimal | None
        try:
            pip_size_dec = Decimal(pip_size) if pip_size else None
        except (ArithmeticError, ValueError):
            pip_size_dec = None
        range_warning_dec: Decimal | None
        try:
            range_warning_dec = (
                Decimal(range_warning_pips) if range_warning_pips is not None else None
            )
        except (ArithmeticError, ValueError):
            range_warning_dec = None

        for row in iter_aggregated_backtest_ticks(
            instrument=instrument,
            start_dt=start_dt,
            end_dt=end_dt,
            granularity=granularity,
            mode=mode,
            batch_size=batch_size,
            range_warning_pips=range_warning_dec,
            pip_size=pip_size_dec,
            request_id=request_id,
        ):
            yield {
                "timestamp": row.timestamp,
                "bid": row.bid,
                "ask": row.ask,
                "mid": row.mid,
            }

    @staticmethod
    def _check_data_coverage(
        instrument: str,
        start_dt: datetime,
        end_dt: datetime,
        source_count: int,
        last_tick_ts: datetime | None,
        request_id: str,
    ) -> str | None:
        """Check whether published ticks adequately cover the requested range.

        Returns a human-readable gap description if coverage is insufficient,
        or ``None`` when the data looks fine.
        """
        if source_count == 0:
            return (
                f"No tick data found for {instrument} "
                f"between {start_dt.isoformat()} and {end_dt.isoformat()}"
            )

        if last_tick_ts is None:
            return None  # shouldn't happen when source_count > 0

        # Allow a tolerance of 2 hours for the gap between the last tick and
        # end_dt.  Forex market close (Fri 21:00 → Sun 21:00 UTC) creates a
        # natural ~48 h gap, but if end_dt falls *within* a trading session and
        # the last tick is more than 2 h before it, data is likely missing.
        from datetime import timedelta

        gap = end_dt - last_tick_ts
        # Tolerance: if the gap is larger than 2 hours AND the end_dt does not
        # fall inside a known market-close window, flag it.
        tolerance = timedelta(hours=2)

        if gap <= tolerance:
            return None

        # Check whether the gap is explained by a weekend market close.
        # Forex closes Fri 21:00 UTC → Sun 21:00 UTC.
        if _gap_spans_only_market_close(last_tick_ts, end_dt):
            return None

        logger.warning(
            f"[PUBLISHER:COVERAGE] Data gap detected - request_id={request_id}, "
            f"last_tick_ts={last_tick_ts}, end_dt={end_dt}, gap={gap}"
        )
        return (
            f"Tick data for {instrument} ends at {last_tick_ts.isoformat()} "
            f"but the requested end_time is {end_dt.isoformat()} "
            f"(gap: {gap})"
        )

    @staticmethod
    def _mark_backtest_task_failed(request_id: str, reason: str) -> None:
        """Mark the BacktestTask as FAILED with an error message."""
        try:
            from django.utils import timezone as dj_timezone

            from apps.trading.enums import TaskStatus
            from apps.trading.models import BacktestTask

            rows = BacktestTask.objects.filter(
                pk=request_id,
                status=TaskStatus.RUNNING,
            ).update(
                status=TaskStatus.FAILED,
                completed_at=dj_timezone.now(),
                error_message=f"Insufficient tick data: {reason}",
            )
            if rows:
                logger.info(
                    f"[PUBLISHER:FAIL_TASK] BacktestTask marked FAILED - request_id={request_id}"
                )
            else:
                logger.warning(
                    f"[PUBLISHER:FAIL_TASK] Could not mark BacktestTask FAILED "
                    f"(not in RUNNING state) - request_id={request_id}"
                )
        except Exception as exc:
            logger.error(
                f"[PUBLISHER:FAIL_TASK] Error marking BacktestTask FAILED - "
                f"request_id={request_id}, error={exc}",
                exc_info=True,
            )

    def _should_stop_publishing(self, request_id: str, *, force: bool = False) -> bool:
        """Check if publishing should stop.

        Checks both the publisher's own stop signal and the executor's status.

        Args:
            request_id: The backtest request ID (matches BacktestTask.id)

        Returns:
            True if publishing should stop, False otherwise
        """
        assert self.task_service is not None

        if self.task_service.should_stop(force=force):
            logger.info(
                f"[PUBLISHER:STOP_CHECK] Publisher stop signal detected - request_id={request_id}"
            )
            return True

        if self._cached_executor_should_stop:
            return True

        now_monotonic = time.monotonic()
        stop_check_interval_seconds = float(
            getattr(self.task_service, "stop_check_interval_seconds", 1.0)
        )
        if (
            not force
            and (now_monotonic - self._last_executor_stop_check_monotonic)
            < stop_check_interval_seconds
        ):
            return False

        # Check executor's status via BacktestTask
        try:
            from apps.trading.enums import TaskStatus
            from apps.trading.models import BacktestTask

            task_status = (
                BacktestTask.objects.filter(id=request_id).values_list("status", flat=True).first()
            )

            if task_status in (TaskStatus.STOPPING, TaskStatus.STOPPED, TaskStatus.FAILED):
                self._cached_executor_should_stop = True
                logger.info(
                    f"[PUBLISHER:STOP_CHECK] Executor stop detected - request_id={request_id}, "
                    f"task_status={task_status}"
                )
                return True

            self._cached_executor_should_stop = False
            self._last_executor_stop_check_monotonic = now_monotonic

        except Exception as exc:
            logger.warning(
                f"[PUBLISHER:STOP_CHECK] Failed to check executor status - request_id={request_id}, "
                f"error={exc}"
            )
            self._last_executor_stop_check_monotonic = now_monotonic

        return False

    def _send_eof(
        self,
        client: Any,
        channel: str,
        request_id: str,
        instrument: str,
        start: str,
        end: str,
        count: int,
    ) -> None:
        """Append EOF marker to the stream.

        EOF is written as a regular stream entry so it cannot be dropped
        mid-flight like a pub/sub message.  ``maxlen`` is not applied here —
        the marker is small and we want to guarantee it reaches the
        subscriber even if the stream is near capacity.
        """
        logger.info(
            f"[PUBLISHER:EOF] Sending EOF marker - request_id={request_id}, "
            f"stream={channel}, count={count}"
        )

        try:
            entry_id = client.xadd(
                channel,
                {
                    "type": "eof",
                    "request_id": str(request_id),
                    "instrument": str(instrument),
                    "start": str(start),
                    "end": str(end),
                    "count": str(count),
                },
            )
        except Exception as exc:
            logger.exception(
                f"[PUBLISHER:EOF] XADD EOF failed - request_id={request_id}, error={exc}"
            )
            raise

        logger.info(
            f"[PUBLISHER:EOF] EOF sent - request_id={request_id}, "
            f"stream={channel}, count={count}, entry_id={entry_id}"
        )

    def _send_stopped(
        self, client: Any, channel: str, request_id: str, instrument: str, count: int
    ) -> None:
        """Append stopped marker to the stream."""
        logger.info(
            f"[PUBLISHER:STOPPED] Sending stopped marker - request_id={request_id}, "
            f"stream={channel}, count={count}"
        )
        try:
            entry_id = client.xadd(
                channel,
                {
                    "type": "stopped",
                    "request_id": str(request_id),
                    "instrument": str(instrument),
                    "count": str(count),
                },
            )
            logger.info(
                f"[PUBLISHER:STOPPED] Stopped marker sent - request_id={request_id}, "
                f"stream={channel}, count={count}, entry_id={entry_id}"
            )
        except Exception as exc:  # nosec B110
            logger.warning(
                f"[PUBLISHER:STOPPED] Failed to append stopped marker - "
                f"request_id={request_id}, error={exc}"
            )

    def _send_error(
        self, client: Any, channel: str, request_id: str, instrument: str, message: str
    ) -> None:
        """Append error marker to the stream."""
        logger.info(
            f"[PUBLISHER:ERROR] Sending error marker - request_id={request_id}, "
            f"stream={channel}, message={message}"
        )
        try:
            entry_id = client.xadd(
                channel,
                {
                    "type": "error",
                    "request_id": str(request_id),
                    "instrument": str(instrument),
                    "message": message,
                },
            )
            logger.info(
                f"[PUBLISHER:ERROR] Error marker sent - request_id={request_id}, "
                f"stream={channel}, entry_id={entry_id}"
            )
        except Exception as exc:  # nosec B110
            logger.warning(
                f"[PUBLISHER:ERROR] Failed to append error marker - request_id={request_id}, "
                f"error={exc}"
            )


def _gap_spans_only_market_close(last_tick: datetime, end_dt: datetime) -> bool:
    """Return True if the gap between *last_tick* and *end_dt* is fully
    explained by a forex weekend market closure (Fri 21:00 → Sun 21:00 UTC).

    The check is intentionally generous: if *last_tick* falls on Friday after
    20:00 UTC and *end_dt* falls anywhere during the weekend (Saturday,
    Sunday before reopen) or after the Sunday reopen / on a weekday, the gap
    is considered a normal weekend closure.
    """
    from datetime import timedelta

    lt_weekday = last_tick.weekday()  # 0=Mon … 6=Sun
    et_weekday = end_dt.weekday()

    # last_tick on Friday (4) evening
    if lt_weekday == 4 and last_tick.hour >= 20:
        # end_dt on Saturday (5), Sunday before/after reopen (6), or weekday
        if et_weekday == 5 or (et_weekday == 6) or et_weekday in (0, 1, 2, 3, 4):
            # Sanity: gap should be less than ~3 days
            if (end_dt - last_tick) < timedelta(days=3, hours=6):
                return True

    return False
