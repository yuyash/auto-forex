"""Runtime metrics computed independently from strategy implementations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from apps.trading.money import AccountCurrency, Money
from apps.trading.models.positions import Position
from apps.trading.utils import Instrument


@dataclass(slots=True)
class _Candle:
    bucket_start_epoch: int
    close_price: Decimal
    high_price: Decimal
    low_price: Decimal


class RuntimeMetricsTracker:
    """Track common runtime metrics such as margin ratio and ATR."""

    def __init__(
        self,
        *,
        instrument: str,
        pip_size: Decimal,
        account_currency: str,
        margin_rate: Decimal,
        atr_period: int,
        atr_baseline_period: int | None = None,
        atr_periods: Mapping[str, int] | None = None,
        atr_baseline_periods: Mapping[str, int | None] | None = None,
        volatility_lock_multiplier: Decimal | None = None,
        initial_balance: Decimal = Decimal("0"),
    ) -> None:
        self.instrument = instrument
        self.pip_size = pip_size
        self.account_currency = account_currency
        self.margin_rate = margin_rate
        self.atr_period = max(1, atr_period)
        self.atr_baseline_period = (
            max(1, atr_baseline_period) if atr_baseline_period is not None else None
        )
        self.atr_periods = {
            str(name): max(1, int(period))
            for name, period in (atr_periods or {}).items()
            if str(name).strip()
        }
        self.atr_baseline_periods = {
            str(name): max(1, int(period))
            for name, period in (atr_baseline_periods or {}).items()
            if str(name).strip() and period is not None
        }
        self.volatility_lock_multiplier = volatility_lock_multiplier
        self._open_positions: dict[str, Position] = {}
        self._completed_candles: list[_Candle] = []
        self._current_candle: _Candle | None = None

        # Cumulative counters for dashboard metrics
        self._initial_balance = initial_balance
        self._realized_pnl = Decimal("0")
        self._realized_pnl_quote = Decimal("0")
        self._total_trades = 0
        self._closed_positions = 0
        self._winning_trades = 0
        self._losing_trades = 0
        self._latest_oanda_order_response_seconds: Decimal | None = None
        self._oanda_order_response_total_seconds = Decimal("0")
        self._oanda_order_response_max_seconds: Decimal | None = None
        self._oanda_order_response_count = 0

    def sync_open_positions(self, positions: Iterable[Position]) -> None:
        """Replace the in-memory open position cache with current open positions."""
        self._open_positions = {
            str(position.id): position for position in positions if position.is_open
        }

    def record_trade(self) -> None:
        """Increment the total trade counter (call once per trade created)."""
        self._total_trades += 1

    def record_position_closed(
        self, realized_pnl: Decimal, *, realized_pnl_quote: Decimal | None = None
    ) -> None:
        """Record a position closure with its realized PnL.

        Args:
            realized_pnl: PnL in account currency (used for current_balance updates).
            realized_pnl_quote: PnL in quote currency before conversion.  When
                provided, the metrics tab will use this value (converted at the
                current mid rate) instead of the per-trade converted amount so
                that it stays consistent with the overview tab's DB aggregation.
        """
        self._closed_positions += 1
        self._realized_pnl += realized_pnl
        self._realized_pnl_quote += (
            realized_pnl_quote if realized_pnl_quote is not None else Decimal("0")
        )
        if realized_pnl > 0:
            self._winning_trades += 1
        elif realized_pnl < 0:
            self._losing_trades += 1

    def record_oanda_order_response(self, seconds: Decimal | int | float | str | None) -> None:
        """Record elapsed wall-clock time for one broker order request."""
        if seconds in (None, ""):
            return
        try:
            value = Decimal(str(seconds))
        except (InvalidOperation, TypeError, ValueError):
            return
        if value < 0:
            return
        self._latest_oanda_order_response_seconds = value
        self._oanda_order_response_total_seconds += value
        self._oanda_order_response_count += 1
        if (
            self._oanda_order_response_max_seconds is None
            or value > self._oanda_order_response_max_seconds
        ):
            self._oanda_order_response_max_seconds = value

    def restore_counters(
        self,
        *,
        realized_pnl: Decimal,
        realized_pnl_quote: Decimal = Decimal("0"),
        total_trades: int,
        closed_positions: int,
        winning_trades: int,
        losing_trades: int,
    ) -> None:
        """Restore cumulative counters when resuming an execution."""
        self._realized_pnl = realized_pnl
        self._realized_pnl_quote = realized_pnl_quote
        self._total_trades = total_trades
        self._closed_positions = closed_positions
        self._winning_trades = winning_trades
        self._losing_trades = losing_trades

    def build_metrics(
        self,
        *,
        timestamp: datetime,
        bid: Decimal,
        ask: Decimal,
        mid: Decimal,
        current_balance: Decimal,
        ticks_processed: int = 0,
        execution_elapsed_seconds: float | int | Decimal | None = None,
        record_tick: bool = True,
    ) -> dict[str, Any]:
        """Update rolling state for a tick and return common metrics."""
        if record_tick:
            self._record_tick(timestamp=timestamp, mid=mid)

        instrument = Instrument(self.instrument)
        conv = instrument.quote_to_account_rate(mid, AccountCurrency(self.account_currency))

        # Unrealized PnL from cached open positions (quote currency),
        # marked to executable close prices.
        unrealized_pnl_quote = Decimal("0")
        for position in self._open_positions.values():
            units = Decimal(str(abs(position.units)))
            entry_price = Decimal(str(position.entry_price))
            if position.direction == "long":
                unrealized_pnl_quote += (bid - entry_price) * units
            else:
                unrealized_pnl_quote += (entry_price - ask) * units
        open_long_units = sum(
            abs(position.units)
            for position in self._open_positions.values()
            if position.direction == "long"
        )
        open_short_units = sum(
            abs(position.units)
            for position in self._open_positions.values()
            if position.direction == "short"
        )

        # Convert to account currency using current mid rate (same as overview tab)
        realized_pnl = (
            self._realized_pnl_quote * conv
            if self._realized_pnl_quote != Decimal("0")
            else self._realized_pnl
        )
        unrealized_pnl = unrealized_pnl_quote * conv
        total_pnl_quote = self._realized_pnl_quote + unrealized_pnl_quote
        total_pnl = realized_pnl + unrealized_pnl
        total_return = (
            (total_pnl / self._initial_balance * 100) if self._initial_balance > 0 else Decimal("0")
        )
        total_closed = self._winning_trades + self._losing_trades
        win_rate = (
            (Decimal(self._winning_trades) / Decimal(total_closed) * 100)
            if total_closed > 0
            else Decimal("0")
        )

        account_currency = str(self.account_currency or "").upper()
        quote_currency = instrument.quote_currency
        metrics: dict[str, Any] = {
            "margin_ratio": str(
                self._calculate_margin_ratio(
                    mid=mid,
                    current_balance=current_balance,
                    unrealized_pnl=unrealized_pnl,
                    conv=conv,
                )
            ),
            "current_balance": str(current_balance),
            "current_balance_currency": account_currency,
            "current_balance_money": Money.coerce(current_balance, account_currency).as_dict(),
            "realized_pnl": str(realized_pnl),
            "realized_pnl_currency": account_currency,
            "realized_pnl_money": Money.coerce(realized_pnl, account_currency).as_dict(),
            "realized_pnl_quote": str(self._realized_pnl_quote),
            "realized_pnl_quote_currency": quote_currency,
            "realized_pnl_quote_money": Money.coerce(
                self._realized_pnl_quote, quote_currency
            ).as_dict(),
            "unrealized_pnl": str(unrealized_pnl),
            "unrealized_pnl_currency": account_currency,
            "unrealized_pnl_money": Money.coerce(unrealized_pnl, account_currency).as_dict(),
            "unrealized_pnl_quote": str(unrealized_pnl_quote),
            "unrealized_pnl_quote_currency": quote_currency,
            "unrealized_pnl_quote_money": Money.coerce(
                unrealized_pnl_quote, quote_currency
            ).as_dict(),
            "total_pnl": str(total_pnl),
            "total_pnl_currency": account_currency,
            "total_pnl_money": Money.coerce(total_pnl, account_currency).as_dict(),
            "total_pnl_quote": str(total_pnl_quote),
            "total_pnl_quote_currency": quote_currency,
            "total_pnl_quote_money": Money.coerce(total_pnl_quote, quote_currency).as_dict(),
            "total_return": str(total_return),
            "open_positions": str(len(self._open_positions)),
            "open_long_units": str(open_long_units),
            "open_short_units": str(open_short_units),
            "closed_positions": str(self._closed_positions),
            "total_trades": str(self._total_trades),
            "winning_trades": str(self._winning_trades),
            "losing_trades": str(self._losing_trades),
            "win_rate": str(win_rate),
            "ticks_processed": str(ticks_processed),
            "pnl_currency": account_currency,
            "account_currency": account_currency,
            "quote_currency": quote_currency,
            "quote_to_account_rate": str(conv),
            "instrument": self.instrument,
            "bid_price": str(bid),
            "ask_price": str(ask),
            "mid_price": str(mid),
            "price_currency": quote_currency,
        }

        elapsed_seconds = _positive_float(execution_elapsed_seconds)
        if elapsed_seconds is not None:
            metrics["execution_elapsed_seconds"] = f"{elapsed_seconds:.6f}"
            metrics["ticks_per_second"] = f"{max(ticks_processed, 0) / elapsed_seconds:.6f}"

        if self._latest_oanda_order_response_seconds is not None:
            latest_ms = self._latest_oanda_order_response_seconds * Decimal("1000")
            avg_ms = (
                self._oanda_order_response_total_seconds
                / Decimal(self._oanda_order_response_count)
                * Decimal("1000")
            )
            max_ms = (self._oanda_order_response_max_seconds or Decimal("0")) * Decimal("1000")
            metrics.update(
                {
                    "oanda_order_response_ms": str(latest_ms),
                    "oanda_order_response_avg_ms": str(avg_ms),
                    "oanda_order_response_max_ms": str(max_ms),
                    "oanda_order_response_count": str(self._oanda_order_response_count),
                }
            )

        atr_cache: dict[int, Decimal] = {}

        def atr_for(period: int) -> Decimal:
            safe_period = max(1, period)
            if safe_period not in atr_cache:
                atr_cache[safe_period] = self._calculate_atr(safe_period)
            return atr_cache[safe_period]

        current_atr = atr_for(self.atr_period)
        metrics["current_atr"] = str(current_atr)

        if self.atr_baseline_period is not None:
            baseline_atr = atr_for(self.atr_baseline_period)
            metrics["baseline_atr"] = str(baseline_atr)
            if self.volatility_lock_multiplier is not None and baseline_atr > 0:
                metrics["volatility_threshold"] = str(
                    baseline_atr * self.volatility_lock_multiplier
                )

        for name, period in self.atr_periods.items():
            metrics[f"{name}_current_atr"] = str(atr_for(period))

        for name, period in self.atr_baseline_periods.items():
            metrics[f"{name}_baseline_atr"] = str(atr_for(period))

        return metrics

    def observe_tick(self, *, timestamp: datetime, mid: Decimal) -> None:
        """Update lightweight rolling price state without building metrics."""
        self._record_tick(timestamp=timestamp, mid=mid)

    def _record_tick(self, *, timestamp: datetime, mid: Decimal) -> None:
        if not isinstance(timestamp, datetime):
            timestamp_str = str(timestamp).strip()
            if timestamp_str.endswith("Z"):
                timestamp_str = timestamp_str[:-1] + "+00:00"
            timestamp = datetime.fromisoformat(timestamp_str)
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
        bucket_start_epoch = int(timestamp.timestamp()) // 60 * 60
        current = self._current_candle

        if current is None:
            self._current_candle = _Candle(
                bucket_start_epoch=bucket_start_epoch,
                close_price=mid,
                high_price=mid,
                low_price=mid,
            )
            return

        if current.bucket_start_epoch == bucket_start_epoch:
            current.close_price = mid
            if mid > current.high_price:
                current.high_price = mid
            if mid < current.low_price:
                current.low_price = mid
            return

        self._completed_candles.append(current)
        self._current_candle = _Candle(
            bucket_start_epoch=bucket_start_epoch,
            close_price=mid,
            high_price=mid,
            low_price=mid,
        )

        atr_periods = [
            self.atr_period,
            self.atr_baseline_period or 0,
            *self.atr_periods.values(),
            *self.atr_baseline_periods.values(),
        ]
        max_candles = max(atr_periods) + 2
        if len(self._completed_candles) > max_candles:
            self._completed_candles = self._completed_candles[-max_candles:]

    def _calculate_margin_ratio(
        self,
        *,
        mid: Decimal,
        current_balance: Decimal,
        unrealized_pnl: Decimal,
        conv: Decimal,
    ) -> Decimal:
        positions = list(self._open_positions.values())
        if not positions:
            return Decimal("0")

        long_units = sum(
            abs(position.units) for position in positions if position.direction == "long"
        )
        short_units = sum(
            abs(position.units) for position in positions if position.direction == "short"
        )
        total_units = max(long_units, short_units)
        if total_units <= 0 or mid <= 0:
            return Decimal("0")

        nav = current_balance + unrealized_pnl
        if nav <= 0:
            return Decimal("0")

        required_margin = mid * Decimal(str(total_units)) * self.margin_rate * conv
        return required_margin / nav

    def _calculate_atr(self, period: int) -> Decimal:
        candles = self._candles_for_atr()
        if len(candles) < 2:
            return Decimal("0")

        true_ranges: list[Decimal] = []
        for index in range(1, len(candles)):
            current = candles[index]
            previous_close = candles[index - 1].close_price
            true_ranges.append(
                max(
                    current.high_price - current.low_price,
                    abs(current.high_price - previous_close),
                    abs(current.low_price - previous_close),
                )
                / self.pip_size
            )

        window = true_ranges[-max(1, period) :]
        if not window:
            return Decimal("0")
        return sum(window, Decimal("0")) / Decimal(len(window))

    def _candles_for_atr(self) -> list[_Candle]:
        candles = list(self._completed_candles)
        if self._current_candle is not None:
            candles.append(self._current_candle)
        return candles


def config_decimal(
    config_dict: dict[str, Any], key: str, default: str | None = None
) -> Decimal | None:
    """Read a Decimal-like config value from a config dict."""
    raw = config_dict.get(key, default)
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        if default is None:
            return None
        return Decimal(default)


def config_int(config_dict: dict[str, Any], key: str, default: int) -> int:
    """Read an int-like config value from a config dict."""
    raw = config_dict.get(key, default)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _positive_float(value: float | int | Decimal | None) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
