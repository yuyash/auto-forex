"""apps.trading.services.data_source

Data source interfaces and implementations for tick data.

This module provides abstractions for tick data sources used by executors,
allowing different implementations (Redis, database, file, etc.) while
maintaining a consistent interface.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from logging import Logger, getLogger
from typing import Any, Callable, Iterator

import redis
from django.conf import settings

from apps.trading.dataclasses import Tick

logger: Logger = getLogger(name=__name__)
_MAX_BACKTEST_SPREAD_PIPS = Decimal(
    str(getattr(settings, "TRADING_MAX_BACKTEST_SPREAD_PIPS", "50"))
)
_TICK_GRANULARITY_SECONDS = {
    "1s": 1,
    "10s": 10,
    "15s": 15,
    "30s": 30,
    "1m": 60,
    "5m": 5 * 60,
    "15m": 15 * 60,
    "30m": 30 * 60,
    "1h": 60 * 60,
}


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (ValueError, InvalidOperation):
        return None


def _granularity_seconds(granularity: str) -> int | None:
    value = str(granularity or "tick")
    if value == "tick":
        return None
    try:
        return _TICK_GRANULARITY_SECONDS[value]
    except KeyError as exc:
        raise ValueError(f"Unsupported tick granularity: {value}") from exc


def _tick_bucket_start(timestamp: datetime, granularity_seconds: int) -> datetime:
    timestamp_utc = timestamp.astimezone(UTC) if timestamp.tzinfo else timestamp.replace(tzinfo=UTC)
    epoch_seconds = int(timestamp_utc.timestamp())
    bucket_epoch = epoch_seconds - (epoch_seconds % granularity_seconds)
    return datetime.fromtimestamp(bucket_epoch, UTC)


def _backtest_bar_range_warning_pips() -> str | None:
    try:
        value = Decimal(str(getattr(settings, "MARKET_BACKTEST_BAR_RANGE_WARNING_PIPS", 0) or 0))
    except (ValueError, InvalidOperation):
        return None
    return str(value) if value > 0 else None


def _gap_spans_only_market_close(last_tick: datetime, end_dt: datetime) -> bool:
    """Return True if a coverage gap is explained by the regular weekend close."""
    lt_weekday = last_tick.weekday()
    et_weekday = end_dt.weekday()
    if lt_weekday == 4 and last_tick.hour >= 20:
        if et_weekday == 5 or et_weekday == 6 or et_weekday in (0, 1, 2, 3, 4):
            return (end_dt - last_tick) < timedelta(days=3, hours=6)
    return False


class TickDataSource(ABC):
    """Abstract base class for tick data sources.

    A TickDataSource provides an iterator over batches of ticks for
    backtest or live trading execution. Different implementations can
    provide ticks from various sources (Redis pub/sub, database queries,
    file streams, etc.)."""

    @abstractmethod
    def __iter__(self) -> Iterator[list[Tick]]:
        """Return an iterator that yields batches of ticks.

        Yields:
            Batches of Tick objects"""
        pass

    @abstractmethod
    def close(self) -> None:
        """Close the data source and release resources.

        This method should be called when the data source is no longer needed
        to properly clean up connections, file handles, etc.
        """
        pass


class RedisTickDataSource(TickDataSource):
    """Legacy Redis Pub/Sub backtest tick data source.

    .. deprecated:: 0.x
        Pub/Sub is fire-and-forget and silently drops messages when the
        subscriber's Redis output buffer overflows (configured by
        ``client-output-buffer-limit pubsub``).  Historically this caused
        entire weeks of ticks to be lost mid-backtest, producing silently
        corrupted backtest results.  New code must use
        :class:`RedisStreamTickDataSource` instead, which reads from a
        persistent Redis Stream.

    Kept around for reference and for legacy callers that still subscribe
    to pub/sub channels (e.g. some test fixtures).
    """

    def __init__(
        self,
        channel: str,
        batch_size: int = 100,
        trigger_publisher: Callable[[], None] | None = None,
    ) -> None:
        """Initialize the Redis tick data source.

        Args:
            channel: Redis channel name to subscribe to
            batch_size: Number of ticks to batch before yielding (default: 100)
            trigger_publisher: Optional callback to trigger the tick publisher
        """
        self.channel = channel
        self.batch_size = batch_size
        self.trigger_publisher = trigger_publisher
        self.client = None
        self.pubsub = None

    def __iter__(self) -> Iterator[list[Tick]]:
        # Initialize Redis connection FIRST before triggering publisher
        self.client = redis.Redis.from_url(settings.MARKET_REDIS_URL, decode_responses=True)
        self.pubsub = self.client.pubsub(ignore_subscribe_messages=True)
        self.pubsub.subscribe(self.channel)
        logger.info(f"RedisTickDataSource subscribed to channel: {self.channel}")

        # CRITICAL: Wait a moment to ensure subscription is fully established
        # This prevents race condition where publisher sends messages before we're ready
        import time

        time.sleep(0.1)

        # Drain any stale messages left on the channel by a previous publisher
        # (e.g. after a task restart while the old publisher was still running).
        # Without this, the new execution would process leftover ticks from a
        # different point in the historical timeline, causing timestamp inversions.
        drained = 0
        while True:
            stale = self.pubsub.get_message(timeout=0.05)
            if stale is None:
                break
            drained += 1
        if drained:
            logger.info(
                "RedisTickDataSource: drained %d stale messages from channel %s",
                drained,
                self.channel,
            )

        # Trigger the publisher AFTER subscription is established
        if self.trigger_publisher:
            logger.info(f"Triggering publisher for channel: {self.channel}")
            # In Celery eager mode, apply_async runs synchronously.  If the
            # publisher finishes before we start reading, all pub/sub messages
            # are lost.  Run the callback in a daemon thread so that the
            # iterator can consume messages as they arrive.
            from celery import current_app

            if getattr(current_app.conf, "task_always_eager", False):
                import threading

                threading.Thread(target=self.trigger_publisher, daemon=True).start()
            else:
                self.trigger_publisher()

        batch: list[Tick] = []
        max_reconnect_attempts = 3
        reconnect_count = 0
        messages_received = 0

        # Timeout mechanism to prevent infinite waiting
        consecutive_timeouts = 0
        max_consecutive_timeouts = 300  # 5 minutes of consecutive timeouts (300 * 1 second)

        try:
            while True:
                try:
                    message = self.pubsub.get_message(timeout=1.0)
                    reconnect_count = 0  # Reset on successful message
                except (redis.ConnectionError, ConnectionError) as e:
                    reconnect_count += 1
                    if reconnect_count > max_reconnect_attempts:
                        raise RuntimeError(
                            f"Failed to reconnect to Redis after {max_reconnect_attempts} attempts"
                        ) from e

                    # Reconnect on connection error
                    try:
                        self.pubsub.close()
                    except Exception as exc:  # pylint: disable=broad-exception-caught  # nosec B110
                        import logging

                        logger_local = logging.getLogger(__name__)
                        logger_local.debug("Failed to close pubsub on reconnect: %s", exc)

                    self.client = redis.Redis.from_url(
                        settings.MARKET_REDIS_URL, decode_responses=True
                    )
                    self.pubsub = self.client.pubsub(ignore_subscribe_messages=True)
                    self.pubsub.subscribe(self.channel)
                    continue

                if not message:
                    consecutive_timeouts += 1

                    # Check if we've been waiting too long without messages
                    if consecutive_timeouts >= max_consecutive_timeouts:
                        logger.warning(
                            f"RedisTickDataSource: No messages received for {max_consecutive_timeouts} seconds "
                            f"on channel {self.channel}. Assuming stream ended. "
                            f"Total messages received: {messages_received}"
                        )
                        # Yield any pending batch before exiting
                        if batch:
                            yield batch
                        break

                    # Yield any pending batch on timeout
                    if batch:
                        yield batch
                        batch = []
                    continue

                # Reset timeout counter when we receive a message
                consecutive_timeouts = 0

                if message.get("type") != "message":
                    continue

                payload_raw = message.get("data")
                try:
                    payload = json.loads(payload_raw) if isinstance(payload_raw, str) else {}
                except Exception as exc:  # pylint: disable=broad-exception-caught  # nosec B112
                    # Log parsing error but continue with next message
                    import logging

                    logger_local = logging.getLogger(__name__)
                    logger_local.warning("Failed to parse tick message: %s", exc)
                    continue

                kind = str(payload.get("type") or "tick")

                # Handle EOF - end of data stream
                if kind == "eof":
                    logger.info(
                        f"RedisTickDataSource: Received EOF on channel {self.channel}. "
                        f"Total messages received: {messages_received}"
                    )
                    # Yield any remaining ticks
                    if batch:
                        yield batch
                    break

                # Handle terminal messages
                if kind in {"stopped", "error"}:
                    logger.info(
                        f"RedisTickDataSource: Received {kind} signal on channel {self.channel}. "
                        f"Total messages received: {messages_received}"
                    )
                    if batch:
                        yield batch
                    break

                # Process tick
                if kind == "tick":
                    # Parse required fields
                    instrument = str(payload.get("instrument") or "")
                    timestamp_raw = str(payload.get("timestamp") or "")

                    if not instrument or not timestamp_raw:
                        continue  # Skip invalid ticks

                    # Parse timestamp
                    try:
                        from datetime import UTC, datetime

                        timestamp_str = timestamp_raw.strip()
                        if timestamp_str.endswith("Z"):
                            timestamp_str = timestamp_str[:-1] + "+00:00"
                        timestamp = datetime.fromisoformat(timestamp_str)
                        if timestamp.tzinfo is None:
                            timestamp = timestamp.replace(tzinfo=UTC)
                    except (ValueError, AttributeError):
                        continue  # Skip ticks with invalid timestamp

                    # Parse prices as Decimal
                    try:
                        bid_raw = payload.get("bid")
                        ask_raw = payload.get("ask")
                        mid_raw = payload.get("mid")

                        if bid_raw is None or ask_raw is None:
                            continue  # Skip ticks without bid/ask

                        bid = Decimal(str(bid_raw))
                        ask = Decimal(str(ask_raw))

                        # Calculate mid if missing
                        if mid_raw is None or str(mid_raw).lower() in {"none", "null", "nan", ""}:
                            mid = (bid + ask) / Decimal("2")
                        else:
                            mid = Decimal(str(mid_raw))

                        tick = Tick(
                            instrument=instrument,
                            timestamp=timestamp,
                            bid=bid,
                            ask=ask,
                            mid=mid,
                        )
                    except (ValueError, InvalidOperation):
                        continue  # Skip ticks with invalid prices

                    if not self._is_valid_backtest_tick(tick):
                        continue

                    batch.append(tick)

                    # Yield batch when it reaches the target size
                    if len(batch) >= self.batch_size:
                        yield batch
                        batch = []

        finally:
            self.close()

    def close(self) -> None:
        """Close Redis connections."""
        import logging

        logger_local = logging.getLogger(__name__)

        if self.pubsub:
            try:
                self.pubsub.close()
            except Exception as exc:  # pylint: disable=broad-exception-caught  # nosec B110
                logger_local.debug("Failed to close pubsub: %s", exc)
        if self.client:
            try:
                self.client.close()
            except Exception as exc:  # pylint: disable=broad-exception-caught  # nosec B110
                logger_local.debug("Failed to close Redis client: %s", exc)

    @staticmethod
    def _is_valid_backtest_tick(tick: Tick) -> bool:
        """Return True when a replay tick has sane executable prices."""
        from apps.trading.utils import pip_size_for_instrument

        if tick.ask < tick.bid:
            logger.warning(
                "RedisTickDataSource: dropping invalid backtest tick with ask < bid "
                "(instrument=%s, timestamp=%s, bid=%s, ask=%s)",
                tick.instrument,
                tick.timestamp,
                tick.bid,
                tick.ask,
            )
            return False

        if tick.mid < tick.bid or tick.mid > tick.ask:
            logger.warning(
                "RedisTickDataSource: dropping invalid backtest tick with mid outside bid/ask "
                "(instrument=%s, timestamp=%s, bid=%s, ask=%s, mid=%s)",
                tick.instrument,
                tick.timestamp,
                tick.bid,
                tick.ask,
                tick.mid,
            )
            return False

        pip_size = pip_size_for_instrument(tick.instrument)
        if pip_size <= 0:
            return True

        spread_pips = (tick.ask - tick.bid) / pip_size
        if spread_pips > _MAX_BACKTEST_SPREAD_PIPS:
            logger.warning(
                "RedisTickDataSource: dropping anomalous backtest tick spread "
                "(instrument=%s, timestamp=%s, bid=%s, ask=%s, spread_pips=%s, max=%s)",
                tick.instrument,
                tick.timestamp,
                tick.bid,
                tick.ask,
                spread_pips,
                _MAX_BACKTEST_SPREAD_PIPS,
            )
            return False

        return True


class DirectBacktestTickDataSource(TickDataSource):
    """In-process backtest tick source for high-throughput in-memory runs."""

    def __init__(
        self,
        *,
        request_id: str,
        instrument: str,
        start_dt: datetime,
        end_dt: datetime,
        batch_size: int = 1000,
        tick_granularity: str = "tick",
        tick_window_value_mode: str = "last",
        pip_size: str | Decimal | None = None,
        bar_range_warning_pips: str | Decimal | None = None,
        spread_filter_enabled: bool = False,
        max_spread_pips: str | Decimal | None = None,
        oanda_candle_filter_enabled: bool = False,
        oanda_candle_filter_account_id: int | str | None = None,
        oanda_candle_filter_granularity: str = "M1",
        oanda_candle_filter_tolerance_pips: str | Decimal | None = None,
    ) -> None:
        self.request_id = str(request_id)
        self.instrument = str(instrument)
        self.start_dt = start_dt
        self.end_dt = end_dt
        self.batch_size = max(int(batch_size), 1)
        self.tick_granularity = str(tick_granularity or "tick")
        self.tick_window_value_mode = str(tick_window_value_mode or "last")
        self.pip_size = pip_size
        self.bar_range_warning_pips = bar_range_warning_pips
        self.spread_filter_enabled = bool(spread_filter_enabled)
        self.max_spread_pips = max_spread_pips
        self.oanda_candle_filter_enabled = bool(oanda_candle_filter_enabled)
        self.oanda_candle_filter_account_id = oanda_candle_filter_account_id
        self.oanda_candle_filter_granularity = str(oanda_candle_filter_granularity or "M1")
        self.oanda_candle_filter_tolerance_pips = oanda_candle_filter_tolerance_pips

    @classmethod
    def from_task(
        cls,
        task: Any,
        *,
        batch_size: int,
        start_dt: datetime | None = None,
    ) -> "DirectBacktestTickDataSource":
        """Create a direct source from a BacktestTask-like object."""
        return cls(
            request_id=str(task.pk),
            instrument=str(task.instrument),
            start_dt=start_dt or task.start_time,
            end_dt=task.end_time,
            batch_size=batch_size,
            tick_granularity=getattr(task, "tick_granularity", "tick"),
            tick_window_value_mode=getattr(task, "tick_window_value_mode", "last"),
            pip_size=str(getattr(task, "pip_size", "") or ""),
            bar_range_warning_pips=_backtest_bar_range_warning_pips(),
            spread_filter_enabled=getattr(task, "spread_filter_enabled", False) is True,
            max_spread_pips=(
                getattr(task, "max_spread_pips", None)
                if getattr(task, "spread_filter_enabled", False) is True
                else None
            ),
            oanda_candle_filter_enabled=(
                getattr(task, "oanda_candle_filter_enabled", False) is True
            ),
            oanda_candle_filter_account_id=(
                getattr(task, "oanda_candle_filter_account_id", None)
                if getattr(task, "oanda_candle_filter_enabled", False) is True
                else None
            ),
            oanda_candle_filter_granularity=(
                getattr(task, "oanda_candle_filter_granularity", "M1")
                if getattr(task, "oanda_candle_filter_enabled", False) is True
                else "M1"
            ),
            oanda_candle_filter_tolerance_pips=(
                getattr(task, "oanda_candle_filter_tolerance_pips", None)
                if getattr(task, "oanda_candle_filter_enabled", False) is True
                else None
            ),
        )

    def __iter__(self) -> Iterator[list[Tick]]:
        logger.info(
            "DirectBacktestTickDataSource opened request_id=%s instrument=%s "
            "start=%s end=%s batch_size=%s tick_granularity=%s tick_window_value_mode=%s",
            self.request_id,
            self.instrument,
            self.start_dt,
            self.end_dt,
            self.batch_size,
            self.tick_granularity,
            self.tick_window_value_mode,
        )

        tick_filter = self._tick_filter()
        rows_iter = (
            self._iter_raw_ticks(
                instrument=self.instrument,
                start_dt=self.start_dt,
                end_dt=self.end_dt,
                batch_size=self.batch_size,
            )
            if self.tick_granularity == "tick"
            else self._iter_aggregated_ticks(
                instrument=self.instrument,
                start_dt=self.start_dt,
                end_dt=self.end_dt,
                granularity=self.tick_granularity,
                mode=self.tick_window_value_mode,
                batch_size=self.batch_size,
                pip_size=self.pip_size,
                range_warning_pips=self.bar_range_warning_pips,
                request_id=self.request_id,
            )
        )

        batch: list[Tick] = []
        published = 0
        source_count = 0
        last_ts: datetime | None = None

        for row in rows_iter:
            ts = row.get("timestamp")
            if not isinstance(ts, datetime):
                continue
            source_count += 1
            last_ts = ts

            if not tick_filter.should_publish(row):
                continue

            tick = self._build_tick_from_row(row)
            if tick is None or not RedisTickDataSource._is_valid_backtest_tick(tick):
                continue

            batch.append(tick)
            published += 1
            if len(batch) >= self.batch_size:
                yield batch
                batch = []

        if batch:
            yield batch

        tick_filter.log_summary(published=published, source_count=source_count)
        data_gap = self._check_data_coverage(source_count=source_count, last_tick_ts=last_ts)
        if data_gap:
            self._mark_backtest_task_failed(data_gap)

        logger.info(
            "DirectBacktestTickDataSource completed request_id=%s source_count=%s "
            "published=%s last_source_ts=%s",
            self.request_id,
            source_count,
            published,
            last_ts,
        )

    def close(self) -> None:
        """Direct DB iteration does not hold long-lived resources."""
        return None

    def _tick_filter(self):
        from apps.market.services.backtest_tick_quality import BacktestTickQualityFilter

        return BacktestTickQualityFilter(
            request_id=self.request_id,
            instrument=self.instrument,
            start_dt=self.start_dt,
            end_dt=self.end_dt,
            pip_size=self.pip_size,
            spread_filter_enabled=self.spread_filter_enabled,
            max_spread_pips=self.max_spread_pips,
            candle_filter_enabled=self.oanda_candle_filter_enabled,
            candle_filter_account_id=self.oanda_candle_filter_account_id,
            candle_filter_granularity=self.oanda_candle_filter_granularity,
            candle_filter_tolerance_pips=self.oanda_candle_filter_tolerance_pips,
        )

    @staticmethod
    def _iter_raw_ticks(
        *,
        instrument: str,
        start_dt: datetime,
        end_dt: datetime,
        batch_size: int,
    ) -> Any:
        from apps.market.models import TickData

        qs = (
            TickData.objects.filter(
                instrument=str(instrument),
                timestamp__gte=start_dt,
                timestamp__lte=end_dt,
            )
            .order_by("timestamp")
            .values("timestamp", "bid", "ask", "mid")
        )
        return qs.iterator(chunk_size=batch_size)

    @staticmethod
    def _iter_aggregated_ticks(
        *,
        instrument: str,
        start_dt: datetime,
        end_dt: datetime,
        granularity: str,
        mode: str,
        batch_size: int,
        pip_size: str | Decimal | None = None,
        range_warning_pips: str | Decimal | None = None,
        request_id: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        from apps.market.services.backtest_ticks import iter_aggregated_backtest_ticks

        pip_size_dec = _optional_decimal(pip_size)
        range_warning_dec = _optional_decimal(range_warning_pips)
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

    def _build_tick_from_row(self, row: dict[str, Any]) -> Tick | None:
        ts = row.get("timestamp")
        if not isinstance(ts, datetime):
            return None
        bid = _optional_decimal(row.get("bid"))
        ask = _optional_decimal(row.get("ask"))
        mid = _optional_decimal(row.get("mid"))
        if bid is None or ask is None:
            return None
        return Tick.create(
            instrument=self.instrument,
            timestamp=ts,
            bid=bid,
            ask=ask,
            mid=mid,
        )

    def _check_data_coverage(
        self,
        *,
        source_count: int,
        last_tick_ts: datetime | None,
    ) -> str | None:
        if source_count == 0:
            return (
                f"No tick data found for {self.instrument} "
                f"between {self.start_dt.isoformat()} and {self.end_dt.isoformat()}"
            )
        if last_tick_ts is None:
            return None

        gap = self.end_dt - last_tick_ts
        if gap <= timedelta(hours=2):
            return None
        if _gap_spans_only_market_close(last_tick_ts, self.end_dt):
            return None

        logger.warning(
            "[DIRECT_BACKTEST:COVERAGE] Data gap detected - request_id=%s, "
            "last_tick_ts=%s, end_dt=%s, gap=%s",
            self.request_id,
            last_tick_ts,
            self.end_dt,
            gap,
        )
        return (
            f"Tick data for {self.instrument} ends at {last_tick_ts.isoformat()} "
            f"but the requested end_time is {self.end_dt.isoformat()} "
            f"(gap: {gap})"
        )

    def _mark_backtest_task_failed(self, reason: str) -> None:
        try:
            from django.utils import timezone as dj_timezone

            from apps.trading.enums import TaskStatus
            from apps.trading.models import BacktestTask

            BacktestTask.objects.filter(
                pk=self.request_id,
                status=TaskStatus.RUNNING,
            ).update(
                status=TaskStatus.FAILED,
                completed_at=dj_timezone.now(),
                error_message=f"Insufficient tick data: {reason}",
            )
        except Exception:
            logger.debug(
                "DirectBacktestTickDataSource failed to mark insufficient data",
                exc_info=True,
            )


class RedisStreamTickDataSource(TickDataSource):
    """Reliable backtest tick data source backed by a Redis Stream.

    Uses Redis **consumer groups** (``XREADGROUP`` + ``XACK``) rather than
    plain ``XREAD``.  This gives two important guarantees that the earlier
    pub/sub and naïve-stream versions could not provide:

    * The publisher can measure true consumer lag via ``XPENDING`` and
      apply backpressure based on unacknowledged entries.  Without a
      consumer group the publisher could only see ``XLEN``, which never
      decreases as entries are read, leading to a deadlock.
    * The subscriber distinguishes "no new entries available" from
      "publisher paused while consumer is still catching up" by comparing
      its last-read id with the stream's ``last-generated-id``.  Idle
      timeout only fires when the consumer is truly caught up, so the
      backpressure-pause-idle-timeout cascade can no longer kill a run.

    On reconnect the subscriber re-reads any previously delivered but
    not-yet-ACKed entries via ``XREADGROUP ... 0`` before switching back
    to ``>`` for new entries — so transient Redis disconnects resume
    from exactly the right point.
    """

    def __init__(
        self,
        stream_key: str,
        batch_size: int = 100,
        trigger_publisher: Callable[[], None] | None = None,
        *,
        block_ms: int | None = None,
        read_count: int | None = None,
        idle_timeout_reads: int | None = None,
        consumer_group: str | None = None,
        consumer_name: str | None = None,
    ) -> None:
        """Initialize the stream-backed tick data source.

        Args:
            stream_key: Redis stream key to read from.
            batch_size: Number of ticks to batch before yielding.
            trigger_publisher: Optional callback to trigger the publisher.
            block_ms: How long ``XREADGROUP`` blocks per iteration
                (milliseconds).  Shorter values improve stop-signal
                responsiveness.
            read_count: Maximum number of entries fetched per
                ``XREADGROUP`` call.
            idle_timeout_reads: Abort after this many consecutive empty
                reads **once the consumer is caught up with the
                publisher**.  Empty reads while the publisher is still
                producing (or is paused for backpressure) do not count.
            consumer_group: Name of the consumer group to read from.
                Defaults to ``MARKET_BACKTEST_STREAM_CONSUMER_GROUP``.
            consumer_name: Unique name for this consumer within the
                group.  Multiple consumers are not currently used but
                each run receives a distinct name so ``XPENDING`` can
                attribute work correctly.
        """
        self.stream_key = stream_key
        self.batch_size = batch_size
        self.trigger_publisher = trigger_publisher
        self.block_ms = (
            int(block_ms)
            if block_ms is not None
            else int(getattr(settings, "MARKET_BACKTEST_STREAM_BLOCK_MS", 1000))
        )
        self.read_count = (
            int(read_count)
            if read_count is not None
            else int(getattr(settings, "MARKET_BACKTEST_STREAM_READ_COUNT", 500))
        )
        self.idle_timeout_reads = (
            int(idle_timeout_reads)
            if idle_timeout_reads is not None
            else int(getattr(settings, "MARKET_BACKTEST_STREAM_IDLE_TIMEOUT_READS", 300))
        )
        self.consumer_group = consumer_group or str(
            getattr(settings, "MARKET_BACKTEST_STREAM_CONSUMER_GROUP", "backtest")
        )
        # A unique consumer name per run avoids XPENDING attribution
        # colliding with an earlier aborted run that still has pending
        # entries for the previous consumer.
        import os
        import uuid

        self.consumer_name = consumer_name or f"worker-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self.client = None
        # Track the last entry id we have received via ``>`` so that
        # XINFO STREAM's ``last-generated-id`` can be compared against
        # it to tell whether the publisher has really stopped or is
        # just between batches.
        self._last_seen_id: str = "0-0"

    def __iter__(self) -> Iterator[list[Tick]]:
        # Connect before triggering the publisher so we never miss entries.
        self.client = redis.Redis.from_url(settings.MARKET_REDIS_URL, decode_responses=True)
        logger.info(
            "RedisStreamTickDataSource opened stream=%s group=%s consumer=%s "
            "block_ms=%s read_count=%s",
            self.stream_key,
            self.consumer_group,
            self.consumer_name,
            self.block_ms,
            self.read_count,
        )

        # Trigger publisher after the client is ready.  The publisher is
        # responsible for creating a fresh consumer group via XGROUP CREATE
        # MKSTREAM before its first ``XADD`` (see
        # ``BacktestTickPublisherRunner.run``), so the subscriber does not
        # need to do any cleanup of its own.  Unlike the legacy pub/sub
        # source, Redis Stream entries persist until consumed; eager-mode
        # tests can run the publisher synchronously without losing ticks.
        # This also avoids a second SQLite connection trying to write from
        # a background thread while the test transaction is open.
        if self.trigger_publisher:
            logger.info(f"Triggering publisher for stream: {self.stream_key}")
            self.trigger_publisher()

        # The publisher creates the consumer group; but if the subscriber
        # is racing ahead (eager-mode tests) or running stand-alone (unit
        # tests), ensure the group exists so the first XREADGROUP does
        # not fail with NOGROUP.
        self._ensure_consumer_group()

        batch: list[Tick] = []
        empty_reads_while_caught_up = 0
        reconnect_count = 0
        max_reconnect_attempts = 5
        total_ticks = 0
        # Window-level tracking so the subscriber emits an INFO log
        # for every ``progress_every`` ticks received with the
        # simulated-time range of the ticks in that window.  Wall-
        # clock time (from the log prefix) tells us when we received
        # them, ts_first/ts_last tells us which simulated-time slice
        # they represent.  Paired with the publisher's matching
        # [PUBLISHER:BATCH] log this makes the hand-off observable.
        progress_every = max(self.batch_size * 10, 1)
        window_first_ts = None
        window_last_ts = None
        window_count = 0
        # IDs that we have read from the group but not yet ACKed.  The
        # executor can still reject/drop ticks (invalid payloads etc.)
        # after we've consumed them from the stream; those entries must
        # still be ACKed so ``XPENDING`` reflects accurate progress.
        pending_ack: list = []

        def _flush_acks() -> None:
            """ACK all entries the subscriber has consumed so far."""
            nonlocal pending_ack
            if not pending_ack or self.client is None:
                pending_ack = []
                return
            try:
                self.client.xack(self.stream_key, self.consumer_group, *pending_ack)
            except Exception as exc:  # nosec B110
                logger.debug(
                    "RedisStreamTickDataSource: XACK failed (non-fatal) stream=%s group=%s err=%s",
                    self.stream_key,
                    self.consumer_group,
                    exc,
                )
            pending_ack = []

        try:
            while True:
                try:
                    entries = self.client.xreadgroup(
                        self.consumer_group,
                        self.consumer_name,
                        {self.stream_key: ">"},
                        count=self.read_count,
                        block=self.block_ms,
                    )
                    reconnect_count = 0  # reset on successful call
                except redis.ResponseError as exc:
                    # NOGROUP means the publisher has not yet created
                    # the consumer group, or a concurrent run destroyed
                    # it (e.g. the publisher just called
                    # ``XGROUP DESTROY`` to reset the group in
                    # eager-mode tests).  Recreate the group at ``0``:
                    # the stream key is execution-scoped for normal
                    # runs, and starting at ``$`` here can skip ticks
                    # and the EOF marker if the eager-mode publisher
                    # already finished before this recovery path runs.
                    if "NOGROUP" in str(exc):
                        logger.info(
                            "RedisStreamTickDataSource: NOGROUP on %s, "
                            "(re)creating group %s and retrying",
                            self.stream_key,
                            self.consumer_group,
                        )
                        self._ensure_consumer_group(from_start=True)
                        continue
                    raise
                except (redis.ConnectionError, ConnectionError) as exc:
                    reconnect_count += 1
                    if reconnect_count > max_reconnect_attempts:
                        raise RuntimeError(
                            "RedisStreamTickDataSource failed to reconnect after "
                            f"{max_reconnect_attempts} attempts"
                        ) from exc
                    import time

                    backoff = min(2 ** (reconnect_count - 1), 5)
                    logger.warning(
                        "RedisStreamTickDataSource reconnecting (%s/%s) after error: %s",
                        reconnect_count,
                        max_reconnect_attempts,
                        exc,
                    )
                    time.sleep(backoff)
                    try:
                        if self.client is not None:
                            self.client.close()
                    except Exception:  # nosec B110
                        pass
                    self.client = redis.Redis.from_url(
                        settings.MARKET_REDIS_URL, decode_responses=True
                    )
                    # Before switching back to "new entries only" (``>``),
                    # drain any entries that were delivered to this
                    # consumer but never ACKed.  ``0`` replays the
                    # consumer's pending-entries list.
                    self._drain_pending_history(batch, pending_ack)
                    continue

                if not entries:
                    # No new entries.  Decide whether this is a genuine
                    # idle (publisher done) or just a pause (publisher is
                    # still producing or is in backpressure).
                    if self._consumer_caught_up_with_publisher():
                        empty_reads_while_caught_up += 1
                        if empty_reads_while_caught_up >= self.idle_timeout_reads:
                            total_idle_ms = empty_reads_while_caught_up * self.block_ms
                            logger.warning(
                                "RedisStreamTickDataSource: idle timeout on stream %s "
                                "after %s ms (caught up with publisher). "
                                "Total messages received: %s",
                                self.stream_key,
                                total_idle_ms,
                                total_ticks,
                            )
                            _flush_acks()
                            if batch:
                                yield batch
                            break
                    else:
                        # Publisher has more entries to come (or is
                        # paused for backpressure).  Reset the idle
                        # counter and keep waiting.
                        empty_reads_while_caught_up = 0

                    # Yield pending batch during idle gaps so the
                    # executor can check stop signals.  ACK what we
                    # already consumed now that the executor is about
                    # to observe them.
                    if batch:
                        _flush_acks()
                        yield batch
                        batch = []
                    continue

                empty_reads_while_caught_up = 0

                # ``xreadgroup`` returns [(stream_key, [(entry_id, {field: value, ...}), ...])].
                should_stop = False
                for _stream, stream_entries in entries:
                    for entry_id, fields in stream_entries:
                        self._last_seen_id = entry_id
                        pending_ack.append(entry_id)

                        # Redis returns ``fields=None`` for a pending
                        # entry whose payload has been trimmed (MAXLEN)
                        # between the XADD that placed it in this
                        # consumer's Pending Entries List and the
                        # XREADGROUP call that re-delivered it.  That
                        # is silent data loss, so we log loudly and
                        # ACK the tombstone to keep the pending list
                        # clean.  The surviving defensive gap check in
                        # the executor will still catch any resulting
                        # simulated-time gap.
                        if fields is None:
                            logger.error(
                                "[SUBSCRIBER:TRIMMED] Entry %s on %s was trimmed "
                                "before redelivery — a tick was LOST. total_ticks=%s",
                                entry_id,
                                self.stream_key,
                                total_ticks,
                            )
                            continue

                        kind = str(fields.get("type") or "tick")

                        if kind == "eof":
                            logger.info(
                                "RedisStreamTickDataSource: received EOF on %s, total=%s",
                                self.stream_key,
                                total_ticks,
                            )
                            should_stop = True
                            break

                        if kind in {"stopped", "error"}:
                            logger.info(
                                "RedisStreamTickDataSource: received %s on %s, total=%s",
                                kind,
                                self.stream_key,
                                total_ticks,
                            )
                            should_stop = True
                            break

                        if kind != "tick":
                            continue

                        tick = self._build_tick_from_entry(fields)
                        if tick is None:
                            continue

                        if not self._is_valid_backtest_tick(tick):
                            continue

                        batch.append(tick)
                        total_ticks += 1
                        if window_first_ts is None:
                            window_first_ts = tick.timestamp
                        window_last_ts = tick.timestamp
                        window_count += 1

                        if total_ticks % progress_every == 0:
                            logger.info(
                                "[SUBSCRIBER:BATCH] Consumed batch - "
                                "stream=%s total_ticks=%s window_count=%s "
                                "window_first_ts=%s window_last_ts=%s "
                                "last_stream_id=%s",
                                self.stream_key,
                                total_ticks,
                                window_count,
                                window_first_ts.isoformat() if window_first_ts else None,
                                window_last_ts.isoformat() if window_last_ts else None,
                                self._last_seen_id,
                            )
                            window_first_ts = None
                            window_last_ts = None
                            window_count = 0

                        if len(batch) >= self.batch_size:
                            _flush_acks()
                            yield batch
                            batch = []
                    if should_stop:
                        break

                if should_stop:
                    _flush_acks()
                    if batch:
                        yield batch
                    break

        finally:
            # Emit a final [SUBSCRIBER:BATCH] tail log so the last
            # partial window is also observable.  Helpful to see
            # exactly which simulated-time tick was the last one this
            # consumer actually processed.
            if window_count > 0:
                logger.info(
                    "[SUBSCRIBER:BATCH] Consumed batch (tail) - "
                    "stream=%s total_ticks=%s window_count=%s "
                    "window_first_ts=%s window_last_ts=%s "
                    "last_stream_id=%s",
                    self.stream_key,
                    total_ticks,
                    window_count,
                    window_first_ts.isoformat() if window_first_ts else None,
                    window_last_ts.isoformat() if window_last_ts else None,
                    self._last_seen_id,
                )
            _flush_acks()
            self.close()

    def _ensure_consumer_group(self, *, from_start: bool = False) -> None:
        """Create the consumer group if it does not already exist.

        In normal operation the publisher creates the group before its
        first XADD; this defensive call is for tests and for the case
        where the subscriber races the publisher.  If ``from_start``
        is True the group is created at id ``0`` so any entries
        already written by the publisher are delivered on the next
        ``XREADGROUP``; otherwise the group starts at ``$`` (tip).

        ``BUSYGROUP`` is ignored — the publisher or a previous
        defensive call may have already created it.
        """
        if self.client is None:
            return
        start_id = "0" if from_start else "$"
        try:
            self.client.xgroup_create(
                self.stream_key, self.consumer_group, id=start_id, mkstream=True
            )
        except Exception as exc:
            if "BUSYGROUP" in str(exc):
                return
            logger.debug(
                "RedisStreamTickDataSource: XGROUP CREATE failed stream=%s group=%s err=%s",
                self.stream_key,
                self.consumer_group,
                exc,
            )

    def _consumer_caught_up_with_publisher(self) -> bool:
        """Return True when this consumer has received every entry the
        publisher has written so far.

        We compare our ``_last_seen_id`` with the stream's
        ``last-generated-id`` reported by ``XINFO STREAM``.  If they
        match, there is nothing left to deliver — a genuine idle state.
        If they differ there are still entries the publisher has added
        that we have not yet read, so we must keep waiting even though
        the last ``XREADGROUP`` returned empty (this happens briefly
        around consumer-group setup and is harmless).
        """
        if self.client is None:
            return True
        try:
            info = self.client.xinfo_stream(self.stream_key)
        except Exception:
            # If we cannot inspect the stream, assume we are caught up
            # to avoid hanging forever.
            return True

        if not isinstance(info, dict):
            return True

        # ``last-generated-id`` is the canonical field on modern Redis
        # servers.  fakeredis (used in tests) does not expose it but
        # does expose ``last-entry`` with the entry id, so fall back.
        last_generated = info.get("last-generated-id")
        if not last_generated:
            last_entry = info.get("last-entry")
            if isinstance(last_entry, (list, tuple)) and last_entry:
                last_generated = last_entry[0]
        if not last_generated:
            # Stream is empty — we are trivially caught up.
            return True
        return self._stream_id_ge(self._last_seen_id, str(last_generated))

    @staticmethod
    def _stream_id_ge(a: str, b: str) -> bool:
        """Return True when stream id ``a`` >= ``b`` (lexicographic on
        ``(ms, seq)`` integer tuple)."""

        def parse(x: str) -> tuple[int, int]:
            if "-" in x:
                ms_str, seq_str = x.split("-", 1)
            else:
                ms_str, seq_str = x, "0"
            try:
                return (int(ms_str), int(seq_str))
            except ValueError:
                return (0, 0)

        return parse(a) >= parse(b)

    def _drain_pending_history(self, batch: list, pending_ack: list) -> None:
        """Replay previously-delivered-but-unACKed entries after reconnect.

        ``XREADGROUP`` with id ``0`` replays the consumer's pending
        entries list so we never lose a delivered tick across a
        connection blip.  Entries read here are already counted in
        ``XPENDING`` from the publisher's viewpoint, so we do not need
        to do anything special for backpressure accounting — ACKing is
        sufficient.
        """
        if self.client is None:
            return
        try:
            replay = self.client.xreadgroup(
                self.consumer_group,
                self.consumer_name,
                {self.stream_key: "0"},
                count=self.read_count,
            )
        except Exception as exc:  # nosec B110
            logger.debug(
                "RedisStreamTickDataSource: replay failed stream=%s err=%s",
                self.stream_key,
                exc,
            )
            return

        if not replay:
            return

        for _stream, stream_entries in replay:
            for entry_id, fields in stream_entries:
                pending_ack.append(entry_id)
                kind = str(fields.get("type") or "tick")
                if kind != "tick":
                    continue
                tick = self._build_tick_from_entry(fields)
                if tick is None or not self._is_valid_backtest_tick(tick):
                    continue
                batch.append(tick)

    def close(self) -> None:
        """Close Redis connection."""
        if self.client is not None:
            try:
                self.client.close()
            except Exception as exc:  # nosec B110
                logger.debug("Failed to close Redis client: %s", exc)
            self.client = None

    @staticmethod
    def _build_tick_from_entry(fields: dict) -> Tick | None:
        """Parse a stream entry payload into a Tick instance."""
        from datetime import UTC, datetime

        instrument = str(fields.get("instrument") or "")
        timestamp_raw = str(fields.get("timestamp") or "")
        if not instrument or not timestamp_raw:
            return None

        try:
            timestamp_str = timestamp_raw.strip()
            if timestamp_str.endswith("Z"):
                timestamp_str = timestamp_str[:-1] + "+00:00"
            timestamp = datetime.fromisoformat(timestamp_str)
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
        except (ValueError, AttributeError):
            return None

        bid_raw = fields.get("bid")
        ask_raw = fields.get("ask")
        mid_raw = fields.get("mid")
        if bid_raw is None or ask_raw is None:
            return None

        try:
            bid = Decimal(str(bid_raw))
            ask = Decimal(str(ask_raw))
            if mid_raw is None or str(mid_raw).lower() in {"none", "null", "nan", ""}:
                mid = (bid + ask) / Decimal("2")
            else:
                mid = Decimal(str(mid_raw))
        except (ValueError, InvalidOperation):
            return None

        return Tick(
            instrument=instrument,
            timestamp=timestamp,
            bid=bid,
            ask=ask,
            mid=mid,
        )

    # Reuse the same validation as the pub/sub source.  A class-level
    # attribute lookup keeps the method accessible without duplicating code.
    _is_valid_backtest_tick = staticmethod(RedisTickDataSource._is_valid_backtest_tick)


class LiveTickDataSource(TickDataSource):
    """Live tick data source for real-time trading.

    This data source subscribes to a Redis pub/sub channel for real-time
    market data and yields individual ticks as they arrive. It's used for
    live trading where ticks are streamed in real-time.
    """

    def __init__(
        self,
        channel: str,
        instrument: str,
        *,
        tick_granularity: str = "tick",
        batch_size: int | None = None,
        batch_max_latency_seconds: float | None = None,
    ) -> None:
        """Initialize the live tick data source.

        Args:
            channel: Redis channel name to subscribe to
            instrument: Trading instrument to filter for
        """
        self.channel = channel
        self.instrument = instrument
        self.tick_granularity = str(tick_granularity or "tick")
        self._granularity_seconds = _granularity_seconds(self.tick_granularity)
        self._last_emitted_bucket_start: datetime | None = None
        self.batch_size = max(
            int(batch_size or getattr(settings, "LIVE_TICK_BATCH_SIZE", 10)),
            1,
        )
        self.batch_max_latency_seconds = max(
            float(
                batch_max_latency_seconds
                if batch_max_latency_seconds is not None
                else getattr(settings, "LIVE_TICK_BATCH_MAX_LATENCY_SECONDS", 0.25)
            ),
            0.0,
        )
        self.client = None
        self.pubsub = None

    def __iter__(self) -> Iterator[list[Tick]]:
        """Iterate over ticks from real-time market data.

        Yields:
            Low-latency batches containing one or more Tick objects"""
        import json

        import redis
        from django.conf import settings

        # Initialize Redis connection
        self.client = redis.Redis.from_url(settings.MARKET_REDIS_URL, decode_responses=True)
        self.pubsub = self.client.pubsub(ignore_subscribe_messages=True)
        self.pubsub.subscribe(self.channel)
        logger.info(
            "LiveTickDataSource subscribed to channel: %s tick_granularity=%s",
            self.channel,
            self.tick_granularity,
        )

        # Give Redis a brief moment to establish the subscription before we
        # start relying on the stream. This mirrors the backtest source and
        # avoids missing the first tick when the publisher resumes immediately.
        import time

        time.sleep(0.1)

        try:
            idle_seconds = 0
            reconnect_attempts = 0
            max_reconnect_attempts = 5
            ticks_received = 0
            pending_ticks: list[Tick] = []
            batch_started_at: float | None = None
            last_yielded_at = time.monotonic()
            while True:
                try:
                    timeout = 1.0
                    if pending_ticks and batch_started_at is not None:
                        elapsed = time.monotonic() - batch_started_at
                        timeout = max(
                            min(self.batch_max_latency_seconds - elapsed, 1.0),
                            0.0,
                        )
                    message = self.pubsub.get_message(timeout=timeout)
                    reconnect_attempts = 0
                except (redis.ConnectionError, ConnectionError) as exc:
                    reconnect_attempts += 1
                    if reconnect_attempts > max_reconnect_attempts:
                        raise RuntimeError(
                            f"LiveTickDataSource failed to reconnect after {max_reconnect_attempts} attempts"
                        ) from exc

                    # Exponential backoff capped at 5 seconds.
                    import time

                    backoff = min(2 ** (reconnect_attempts - 1), 5)
                    logger.warning(
                        "LiveTickDataSource reconnecting (%s/%s) after error: %s",
                        reconnect_attempts,
                        max_reconnect_attempts,
                        exc,
                    )
                    time.sleep(backoff)

                    try:
                        self.close()
                    except Exception:  # nosec
                        pass

                    self.client = redis.Redis.from_url(
                        settings.MARKET_REDIS_URL, decode_responses=True
                    )
                    self.pubsub = self.client.pubsub(ignore_subscribe_messages=True)
                    self.pubsub.subscribe(self.channel)
                    continue
                if not message:
                    if pending_ticks and batch_started_at is not None:
                        elapsed = time.monotonic() - batch_started_at
                        if elapsed >= self.batch_max_latency_seconds:
                            yield pending_ticks
                            pending_ticks = []
                            batch_started_at = None
                            last_yielded_at = time.monotonic()
                        continue
                    idle_seconds += 1
                    # Yield empty batch every 5 seconds so the executor can
                    # check stop signals and send heartbeats during market close
                    if idle_seconds >= 5:
                        idle_seconds = 0
                        last_yielded_at = time.monotonic()
                        yield []
                    continue

                idle_seconds = 0
                ticks_received += 1
                if ticks_received == 1:
                    logger.info(
                        "LiveTickDataSource first tick received on channel %s",
                        self.channel,
                    )

                if message.get("type") != "message":
                    continue

                payload_raw = message.get("data")
                try:
                    payload = json.loads(payload_raw) if isinstance(payload_raw, str) else {}
                except Exception as exc:  # pylint: disable=broad-exception-caught  # nosec B112
                    # Log parsing error but continue with next message
                    import logging

                    logger_local = logging.getLogger(__name__)
                    logger_local.warning("Failed to parse tick message: %s", exc)
                    continue

                # Parse tick data
                instrument = str(payload.get("instrument") or "")
                timestamp_raw = str(payload.get("timestamp") or "")

                if not instrument or not timestamp_raw:
                    continue  # Skip invalid ticks

                # Parse timestamp
                try:
                    from datetime import UTC, datetime

                    timestamp_str = timestamp_raw.strip()
                    if timestamp_str.endswith("Z"):
                        timestamp_str = timestamp_str[:-1] + "+00:00"
                    timestamp = datetime.fromisoformat(timestamp_str)
                    if timestamp.tzinfo is None:
                        timestamp = timestamp.replace(tzinfo=UTC)
                except (ValueError, AttributeError):
                    continue  # Skip ticks with invalid timestamp

                # Parse prices as Decimal
                try:
                    bid_raw = payload.get("bid")
                    ask_raw = payload.get("ask")
                    mid_raw = payload.get("mid")

                    if bid_raw is None or ask_raw is None:
                        continue  # Skip ticks without bid/ask

                    bid = Decimal(str(bid_raw))
                    ask = Decimal(str(ask_raw))

                    # Calculate mid if missing
                    if mid_raw is None or str(mid_raw).lower() in {"none", "null", "nan", ""}:
                        mid = (bid + ask) / Decimal("2")
                    else:
                        mid = Decimal(str(mid_raw))

                    tick = Tick.from_dict(
                        {
                            "instrument": instrument,
                            "timestamp": timestamp,
                            "bid": bid,
                            "ask": ask,
                            "mid": mid,
                            "oanda_tick_publish_latency_seconds": payload.get(
                                "oanda_tick_publish_latency_seconds"
                            ),
                            "oanda_tick_published_at": payload.get("oanda_tick_published_at"),
                        }
                    )
                except (ValueError, InvalidOperation):
                    continue  # Skip ticks with invalid prices

                if not self._should_emit_tick(tick):
                    if not pending_ticks and time.monotonic() - last_yielded_at >= 5:
                        last_yielded_at = time.monotonic()
                        yield []
                    continue

                if not pending_ticks:
                    batch_started_at = time.monotonic()
                pending_ticks.append(tick)
                batch_age = (
                    time.monotonic() - batch_started_at if batch_started_at is not None else 0.0
                )
                if len(pending_ticks) >= self.batch_size or (
                    self.batch_max_latency_seconds == 0
                    or batch_age >= self.batch_max_latency_seconds
                ):
                    yield pending_ticks
                    pending_ticks = []
                    batch_started_at = None
                    last_yielded_at = time.monotonic()

        finally:
            self.close()

    def _should_emit_tick(self, tick: Tick) -> bool:
        """Return True when a live tick should be delivered to the executor."""
        if self._granularity_seconds is None:
            return True

        bucket_start = _tick_bucket_start(tick.timestamp, self._granularity_seconds)
        if (
            self._last_emitted_bucket_start is not None
            and bucket_start <= self._last_emitted_bucket_start
        ):
            return False

        self._last_emitted_bucket_start = bucket_start
        return True

    def close(self) -> None:
        """Close Redis connections."""
        import logging

        logger_local = logging.getLogger(__name__)

        if self.pubsub:
            try:
                self.pubsub.close()
            except Exception as exc:  # pylint: disable=broad-exception-caught  # nosec B110
                logger_local.debug("Failed to close pubsub: %s", exc)
        if self.client:
            try:
                self.client.close()
            except Exception as exc:  # pylint: disable=broad-exception-caught  # nosec B110
                logger_local.debug("Failed to close Redis client: %s", exc)
