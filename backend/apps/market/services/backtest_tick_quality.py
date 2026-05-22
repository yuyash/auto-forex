"""Backtest tick quality filters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from logging import Logger, getLogger
from typing import Any

from django.conf import settings

from apps.market.models import OandaAccounts
from apps.market.services.oanda_candles import (
    OANDA_GRANULARITY_SECONDS,
    OandaCandleHistoryService,
)

logger: Logger = getLogger(name=__name__)


@dataclass
class TickQualityFilterStats:
    """Runtime counters for backtest tick filtering."""

    seen: int = 0
    skipped_spread: int = 0
    skipped_candle_outlier: int = 0
    candle_missing_allowed: int = 0
    candle_fetch_errors: int = 0
    invalid_rows_allowed: int = 0

    @property
    def skipped_total(self) -> int:
        return self.skipped_spread + self.skipped_candle_outlier


@dataclass(frozen=True)
class CandleRange:
    """Comparable candle range for one OANDA candle bucket."""

    start: datetime
    low: Decimal
    high: Decimal


class BacktestTickQualityFilter:
    """Skip suspicious backtest ticks without failing the publisher."""

    _SKIP_LOG_LIMIT = 20
    _MISSING_CANDLE_LOG_LIMIT = 10

    def __init__(
        self,
        *,
        request_id: str,
        instrument: str,
        start_dt: datetime,
        end_dt: datetime,
        pip_size: str | Decimal | None,
        spread_filter_enabled: bool = False,
        max_spread_pips: str | Decimal | None = None,
        candle_filter_enabled: bool = False,
        candle_filter_account_id: int | str | None = None,
        candle_filter_granularity: str = "M1",
        candle_filter_tolerance_pips: str | Decimal | None = None,
        candle_history: OandaCandleHistoryService | None = None,
    ) -> None:
        self.request_id = str(request_id)
        self.instrument = str(instrument)
        self.start_dt = self._as_utc(start_dt)
        self.end_dt = self._as_utc(end_dt)
        self.pip_size = self._to_decimal(pip_size)
        self.spread_filter_enabled = bool(spread_filter_enabled)
        self.max_spread_pips = self._to_decimal(max_spread_pips)
        self.candle_filter_enabled = bool(candle_filter_enabled)
        self._summary_enabled = self.spread_filter_enabled or self.candle_filter_enabled
        self.candle_filter_account_id = candle_filter_account_id
        self.candle_filter_granularity = str(candle_filter_granularity or "M1")
        self.candle_filter_tolerance_pips = self._to_decimal(candle_filter_tolerance_pips)
        self.candle_history = candle_history or OandaCandleHistoryService()
        self.stats = TickQualityFilterStats()

        self._api_context: Any | None = None
        self._candle_filter_disabled = False
        self._candles: dict[datetime, CandleRange] = {}
        self._loaded_until: datetime | None = None
        self._refresh_at: datetime | None = None
        self._skip_log_count = 0
        self._missing_candle_log_count = 0

        if self.spread_filter_enabled and (not self.pip_size or not self.max_spread_pips):
            logger.warning(
                "[PUBLISHER:TICK_FILTER] Spread filter disabled due to missing threshold "
                "- request_id=%s, pip_size=%s, max_spread_pips=%s",
                self.request_id,
                self.pip_size,
                self.max_spread_pips,
            )
            self.spread_filter_enabled = False

        if self.candle_filter_enabled:
            self._prepare_candle_filter()

    @property
    def enabled(self) -> bool:
        return self.spread_filter_enabled or (
            self.candle_filter_enabled and not self._candle_filter_disabled
        )

    def should_publish(self, row: dict[str, Any]) -> bool:
        """Return False when the row should be skipped."""
        if not self.enabled:
            return True

        self.stats.seen += 1
        ts = row.get("timestamp")
        if not isinstance(ts, datetime):
            self.stats.invalid_rows_allowed += 1
            return True

        bid = self._to_decimal(row.get("bid"))
        ask = self._to_decimal(row.get("ask"))
        mid = self._to_decimal(row.get("mid"))
        if bid is None or ask is None or mid is None:
            self.stats.invalid_rows_allowed += 1
            return True

        if self._is_spread_outlier(bid=bid, ask=ask):
            self.stats.skipped_spread += 1
            spread_pips = (ask - bid) / self.pip_size if self.pip_size else None
            self._log_skip(
                reason="spread",
                ts=ts,
                bid=bid,
                ask=ask,
                mid=mid,
                extra=f"spread_pips={spread_pips}, max_spread_pips={self.max_spread_pips}",
            )
            return False

        if self._is_candle_outlier(ts=ts, mid=mid):
            self.stats.skipped_candle_outlier += 1
            return False

        return True

    def log_summary(self, *, published: int, source_count: int) -> None:
        """Emit one summary line for the completed publisher run."""
        if not self._summary_enabled:
            return
        logger.info(
            "[PUBLISHER:TICK_FILTER] Summary - request_id=%s, instrument=%s, "
            "source_count=%s, published=%s, seen=%s, skipped_total=%s, "
            "skipped_spread=%s, skipped_candle_outlier=%s, "
            "candle_missing_allowed=%s, candle_fetch_errors=%s, invalid_rows_allowed=%s",
            self.request_id,
            self.instrument,
            source_count,
            published,
            self.stats.seen,
            self.stats.skipped_total,
            self.stats.skipped_spread,
            self.stats.skipped_candle_outlier,
            self.stats.candle_missing_allowed,
            self.stats.candle_fetch_errors,
            self.stats.invalid_rows_allowed,
        )

    def _prepare_candle_filter(self) -> None:
        if not self.pip_size or not self.candle_filter_tolerance_pips:
            logger.warning(
                "[PUBLISHER:TICK_FILTER] OANDA candle filter disabled due to missing "
                "pip size or tolerance - request_id=%s, pip_size=%s, tolerance_pips=%s",
                self.request_id,
                self.pip_size,
                self.candle_filter_tolerance_pips,
            )
            self._candle_filter_disabled = True
            return

        if self.candle_filter_granularity not in OANDA_GRANULARITY_SECONDS:
            logger.warning(
                "[PUBLISHER:TICK_FILTER] OANDA candle filter disabled due to unsupported "
                "granularity - request_id=%s, granularity=%s",
                self.request_id,
                self.candle_filter_granularity,
            )
            self._candle_filter_disabled = True
            return

        account = (
            OandaAccounts.objects.filter(pk=self.candle_filter_account_id, is_active=True).first()
            if self.candle_filter_account_id
            else None
        )
        if account is None:
            logger.warning(
                "[PUBLISHER:TICK_FILTER] OANDA candle filter disabled because account "
                "was not found or inactive - request_id=%s, account_id=%s",
                self.request_id,
                self.candle_filter_account_id,
            )
            self._candle_filter_disabled = True
            return

        try:
            import v20

            self._api_context = v20.Context(
                hostname=account.api_hostname,
                token=account.get_api_token(),
                application="auto-forex-trading",
                poll_timeout=int(getattr(settings, "OANDA_REST_TIMEOUT", 10)),
            )
        except Exception:
            logger.exception(
                "[PUBLISHER:TICK_FILTER] OANDA candle filter disabled during API "
                "context setup - request_id=%s, account_pk=%s",
                self.request_id,
                account.pk,
            )
            self._candle_filter_disabled = True

    def _is_spread_outlier(self, *, bid: Decimal, ask: Decimal) -> bool:
        if not self.spread_filter_enabled or not self.pip_size or not self.max_spread_pips:
            return False
        spread = ask - bid
        if spread <= 0:
            return False
        return spread / self.pip_size > self.max_spread_pips

    def _is_candle_outlier(self, *, ts: datetime, mid: Decimal) -> bool:
        if not self.candle_filter_enabled or self._candle_filter_disabled:
            return False

        candle = self._candle_for(ts)
        if candle is None:
            self.stats.candle_missing_allowed += 1
            if self._missing_candle_log_count < self._MISSING_CANDLE_LOG_LIMIT:
                self._missing_candle_log_count += 1
                logger.info(
                    "[PUBLISHER:TICK_FILTER] Allowing tick because matching OANDA "
                    "candle is missing - request_id=%s, instrument=%s, timestamp=%s, "
                    "granularity=%s",
                    self.request_id,
                    self.instrument,
                    ts.isoformat(),
                    self.candle_filter_granularity,
                )
            return False

        assert self.pip_size is not None
        assert self.candle_filter_tolerance_pips is not None
        tolerance = self.candle_filter_tolerance_pips * self.pip_size
        lower_bound = candle.low - tolerance
        upper_bound = candle.high + tolerance
        if lower_bound <= mid <= upper_bound:
            return False

        self._log_skip(
            reason="oanda_candle_outlier",
            ts=ts,
            bid=None,
            ask=None,
            mid=mid,
            extra=(
                f"candle_start={candle.start.isoformat()}, candle_low={candle.low}, "
                f"candle_high={candle.high}, tolerance_pips={self.candle_filter_tolerance_pips}"
            ),
        )
        return True

    def _candle_for(self, ts: datetime) -> CandleRange | None:
        ts = self._as_utc(ts)
        self._ensure_candle_window(ts)
        return self._candles.get(self._bucket_start(ts))

    def _ensure_candle_window(self, ts: datetime) -> None:
        if self._candle_filter_disabled:
            return
        if self._loaded_until is not None and ts < self._loaded_until:
            if self._refresh_at is None or ts < self._refresh_at:
                return

        from_dt = self._loaded_until if self._loaded_until and self._loaded_until > ts else ts
        from_dt = self._bucket_start(from_dt)
        seconds = OANDA_GRANULARITY_SECONDS[self.candle_filter_granularity]
        max_candles = max(
            1,
            min(
                int(getattr(settings, "MARKET_BACKTEST_OANDA_CANDLE_PREFETCH_CANDLES", 720)),
                5000,
            ),
        )
        lookahead = timedelta(seconds=seconds * max_candles)
        to_dt = min(from_dt + lookahead, self.end_dt + timedelta(seconds=seconds))
        if to_dt <= from_dt:
            to_dt = from_dt + timedelta(seconds=seconds)

        try:
            self._load_candle_range(from_dt, to_dt)
        except Exception:
            self.stats.candle_fetch_errors += 1
            self._candle_filter_disabled = True
            logger.exception(
                "[PUBLISHER:TICK_FILTER] OANDA candle filter disabled after fetch "
                "failure - request_id=%s, instrument=%s, granularity=%s, from=%s, to=%s",
                self.request_id,
                self.instrument,
                self.candle_filter_granularity,
                from_dt.isoformat(),
                to_dt.isoformat(),
            )
            return

        self._loaded_until = max(self._loaded_until or to_dt, to_dt)
        refresh_seconds = max(int((to_dt - from_dt).total_seconds() * 0.75), seconds)
        self._refresh_at = min(from_dt + timedelta(seconds=refresh_seconds), self._loaded_until)
        self._prune_old_candles(ts)

    def _load_candle_range(self, from_dt: datetime, to_dt: datetime) -> None:
        if self._api_context is None:
            self._candle_filter_disabled = True
            return

        raw_candles = self.candle_history.fetch_range(
            self._api_context,
            self.instrument,
            self.candle_filter_granularity,
            self._to_rfc3339(from_dt),
            self._to_rfc3339(to_dt),
            {"granularity": self.candle_filter_granularity},
        )
        parsed = self.candle_history.parser.parse_many(raw_candles)
        for record in parsed:
            start = datetime.fromtimestamp(int(record["time"]), tz=UTC)
            low = self._to_decimal(record["low"])
            high = self._to_decimal(record["high"])
            if low is None or high is None:
                continue
            self._candles[start] = CandleRange(start=start, low=low, high=high)

        logger.info(
            "[PUBLISHER:TICK_FILTER] Loaded OANDA candles - request_id=%s, "
            "instrument=%s, granularity=%s, from=%s, to=%s, candles=%s",
            self.request_id,
            self.instrument,
            self.candle_filter_granularity,
            from_dt.isoformat(),
            to_dt.isoformat(),
            len(parsed),
        )

    def _prune_old_candles(self, ts: datetime) -> None:
        seconds = OANDA_GRANULARITY_SECONDS[self.candle_filter_granularity]
        keep_from = self._bucket_start(ts) - timedelta(seconds=seconds * 2)
        for key in [key for key in self._candles if key < keep_from]:
            del self._candles[key]

    def _bucket_start(self, ts: datetime) -> datetime:
        ts = self._as_utc(ts)
        seconds = OANDA_GRANULARITY_SECONDS[self.candle_filter_granularity]
        bucket_ts = int(ts.timestamp()) // seconds * seconds
        return datetime.fromtimestamp(bucket_ts, tz=UTC)

    def _log_skip(
        self,
        *,
        reason: str,
        ts: datetime,
        bid: Decimal | None,
        ask: Decimal | None,
        mid: Decimal,
        extra: str,
    ) -> None:
        if self._skip_log_count >= self._SKIP_LOG_LIMIT:
            return
        self._skip_log_count += 1
        logger.warning(
            "[PUBLISHER:TICK_FILTER] Skipping tick - request_id=%s, instrument=%s, "
            "reason=%s, timestamp=%s, bid=%s, ask=%s, mid=%s, %s",
            self.request_id,
            self.instrument,
            reason,
            ts.isoformat(),
            bid,
            ask,
            mid,
            extra,
        )

    @staticmethod
    def _to_decimal(value: Any) -> Decimal | None:
        if value is None or value == "":
            return None
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _to_rfc3339(value: datetime) -> str:
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
