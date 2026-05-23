"""Task summary service.

Computes a comprehensive summary for a given task including:
- PnL (realized, unrealized)
- Trade / position counts
- Execution state (balance, ticks processed)
- Tick info (timestamp, bid, ask, mid)
- Task status and timing information
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from django.core.cache import cache
from django.db.models import Case, Count, DecimalField, F, IntegerField, Sum, Value, When

from apps.trading.money import AccountCurrency, Money
from apps.trading.models.positions import Position
from apps.trading.models.trades import Trade
from apps.trading.services.conversion_context import CurrencyConversionContext
from apps.trading.services.display_money import DISPLAY_MONEY
from apps.trading.services.fx_rates import FX_CONVERSION, FxConversionService
from apps.trading.services.metric_watermarks import WATERMARK_SPECS, update_watermarks
from apps.trading.services.public_errors import (
    task_public_error_code,
    task_public_error_message,
)
from apps.trading.services.status_reasons import status_reason_from_task
from apps.trading.utils import Instrument


@dataclass(frozen=True)
class TickInfo:
    """Last tick information."""

    timestamp: str | None
    bid: Decimal | None
    ask: Decimal | None
    mid: Decimal | None

    def to_dict(self) -> dict[str, object]:
        """Return serializer-ready tick data."""
        return {
            "timestamp": self.timestamp,
            "bid": self.bid,
            "ask": self.ask,
            "mid": self.mid,
        }


@dataclass(frozen=True)
class TickDeliveryInfo:
    """Live tick delivery diagnostics."""

    status: str | None
    tick_timestamp: str | None
    observed_at: str | None
    age_seconds: float | None
    max_age_seconds: int | None
    message: str | None

    def to_dict(self) -> dict[str, object]:
        """Return serializer-ready delivery diagnostics."""
        return {
            "status": self.status,
            "tick_timestamp": self.tick_timestamp,
            "observed_at": self.observed_at,
            "age_seconds": self.age_seconds,
            "max_age_seconds": self.max_age_seconds,
            "message": self.message,
        }


@dataclass(frozen=True)
class PnlInfo:
    """Profit and loss information."""

    realized: Decimal
    unrealized: Decimal
    currency: str | None
    realized_display_money: dict[str, str] | None = None
    unrealized_display_money: dict[str, str] | None = None
    total_display_money: dict[str, str] | None = None
    display_conversion_context: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        """Return serializer-ready PnL data."""
        total = self.realized + self.unrealized
        return {
            "realized": self.realized,
            "unrealized": self.unrealized,
            "currency": self.currency,
            "realized_money": (
                Money.coerce(self.realized, self.currency).as_dict() if self.currency else None
            ),
            "unrealized_money": (
                Money.coerce(self.unrealized, self.currency).as_dict() if self.currency else None
            ),
            "total_money": (
                Money.coerce(total, self.currency).as_dict() if self.currency else None
            ),
            "realized_display_money": self.realized_display_money,
            "unrealized_display_money": self.unrealized_display_money,
            "total_display_money": self.total_display_money,
            "display_conversion_context": self.display_conversion_context,
        }


@dataclass(frozen=True)
class CountsInfo:
    """Trade and position counts."""

    total_trades: int
    open_positions: int
    closed_positions: int
    open_long_units: int
    open_short_units: int
    winning_trades: int
    losing_trades: int

    def to_dict(self) -> dict[str, object]:
        """Return serializer-ready count data."""
        return {
            "total_trades": self.total_trades,
            "open_positions": self.open_positions,
            "closed_positions": self.closed_positions,
            "open_long_units": self.open_long_units,
            "open_short_units": self.open_short_units,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
        }


@dataclass(frozen=True)
class ExecutionInfo:
    """Execution state information."""

    current_balance: Decimal | None
    ticks_processed: int
    account_currency: str | None
    current_balance_currency: str | None
    current_balance_money: dict[str, str] | None
    current_balance_display: Decimal | None
    display_currency: str | None
    current_balance_display_money: dict[str, str] | None
    resume_cursor_timestamp: str | None
    margin_ratio: Decimal | None
    current_atr: Decimal | None
    recovery_status: str | None
    recovery_warnings: list[str]
    recovery_blockers: list[str]
    reconciled_at: str | None
    tick_delivery: TickDeliveryInfo | None
    current_balance_display_conversion_context: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        """Return serializer-ready execution data."""
        return {
            "current_balance": self.current_balance,
            "ticks_processed": self.ticks_processed,
            "account_currency": self.account_currency,
            "current_balance_currency": self.current_balance_currency,
            "current_balance_money": self.current_balance_money,
            "current_balance_display": self.current_balance_display,
            "display_currency": self.display_currency,
            "current_balance_display_money": self.current_balance_display_money,
            "current_balance_display_conversion_context": (
                self.current_balance_display_conversion_context
            ),
            "resume_cursor_timestamp": self.resume_cursor_timestamp,
            "margin_ratio": self.margin_ratio,
            "current_atr": self.current_atr,
            "recovery_status": self.recovery_status,
            "recovery_warnings": self.recovery_warnings,
            "recovery_blockers": self.recovery_blockers,
            "reconciled_at": self.reconciled_at,
            "tick_delivery": (
                self.tick_delivery.to_dict() if self.tick_delivery is not None else None
            ),
        }


@dataclass(frozen=True)
class TaskInfo:
    """Task status information."""

    status: str
    started_at: str | None
    completed_at: str | None
    error_message: str | None
    error_code: str | None
    stop_reason: str | None
    progress: int
    status_reason_code: str | None = None
    status_reason_message: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return serializer-ready task data."""
        return {
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error_message": self.error_message,
            "error_code": self.error_code,
            "status_reason_code": self.status_reason_code,
            "status_reason_message": self.status_reason_message,
            "stop_reason": self.stop_reason,
            "progress": self.progress,
        }


@dataclass(frozen=True)
class WatermarkInfo:
    """Single execution watermark value and timestamp."""

    value: Decimal | None
    timestamp: str | None
    source_metric: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return serializer-ready watermark data."""
        return {
            "value": self.value,
            "timestamp": self.timestamp,
            "source_metric": self.source_metric,
        }


@dataclass(frozen=True)
class ExecutionWatermarks:
    """Execution-level extrema derived from persisted metric snapshots."""

    margin_ratio_max: WatermarkInfo
    base_units_max: WatermarkInfo
    open_long_units_max: WatermarkInfo
    open_short_units_max: WatermarkInfo
    realized_pnl_max: WatermarkInfo
    unrealized_pnl_min: WatermarkInfo
    open_positions_max: WatermarkInfo
    active_cycles_max: WatermarkInfo

    def to_dict(self) -> dict[str, object]:
        """Return serializer-ready watermark data."""
        return {
            "margin_ratio_max": self.margin_ratio_max.to_dict(),
            "base_units_max": self.base_units_max.to_dict(),
            "open_long_units_max": self.open_long_units_max.to_dict(),
            "open_short_units_max": self.open_short_units_max.to_dict(),
            "realized_pnl_max": self.realized_pnl_max.to_dict(),
            "unrealized_pnl_min": self.unrealized_pnl_min.to_dict(),
            "open_positions_max": self.open_positions_max.to_dict(),
            "active_cycles_max": self.active_cycles_max.to_dict(),
        }


def _empty_execution_watermarks() -> ExecutionWatermarks:
    empty = WatermarkInfo(value=None, timestamp=None)
    return ExecutionWatermarks(
        margin_ratio_max=empty,
        base_units_max=empty,
        open_long_units_max=empty,
        open_short_units_max=empty,
        realized_pnl_max=empty,
        unrealized_pnl_min=empty,
        open_positions_max=empty,
        active_cycles_max=empty,
    )


@dataclass(frozen=True)
class TaskSummary:
    """Aggregated task summary with structured groups."""

    timestamp: str | None
    pnl: PnlInfo
    counts: CountsInfo
    execution: ExecutionInfo
    tick: TickInfo
    task: TaskInfo
    watermarks: ExecutionWatermarks = field(default_factory=_empty_execution_watermarks)

    def to_dict(self) -> dict[str, object]:
        """Return a serializer-ready task summary payload."""
        return {
            "timestamp": self.timestamp,
            "pnl": self.pnl.to_dict(),
            "counts": self.counts.to_dict(),
            "execution": self.execution.to_dict(),
            "tick": self.tick.to_dict(),
            "task": self.task.to_dict(),
            "watermarks": self.watermarks.to_dict(),
        }


class TaskSummaryResponseService:
    """Build task summary response payloads for API views."""

    def __init__(self, *, read_model: "TaskSummaryReadModel | None" = None) -> None:
        """Initialize with an injectable read-model collaborator."""
        self.read_model = read_model or TASK_SUMMARY_READ_MODEL

    def build(
        self,
        *,
        task,
        task_type: str,
        execution_id=None,
    ) -> dict[str, object]:
        """Return a serializer-ready summary for a task."""
        summary = self.read_model.compute_cached(
            task_type=task_type,
            task_id=str(task.pk),
            execution_id=execution_id,
        )
        if hasattr(summary, "to_dict"):
            return summary.to_dict()

        import dataclasses

        return dataclasses.asdict(summary)


class TaskSummaryReadModel:
    """Build and cache dashboard task summary read models."""

    def compute(
        self,
        *,
        task_type: str,
        task_id: str,
        execution_id=None,
    ) -> TaskSummary:
        """Compute an uncached summary for a task execution."""
        return compute_task_summary(
            task_type=task_type,
            task_id=task_id,
            execution_id=execution_id,
        )

    def compute_cached(
        self,
        *,
        task_type: str,
        task_id: str,
        execution_id=None,
    ) -> TaskSummary:
        """Compute a cached task summary keyed by task/state freshness."""
        from apps.trading.services.execution_snapshots import get_summary_snapshot

        task_obj = _get_task(task_type, task_id)
        persisted_snapshot = get_summary_snapshot(
            task=task_obj,
            task_type=task_type,
            task_id=task_id,
            execution_id=str(execution_id) if execution_id is not None else None,
        )
        if persisted_snapshot is not None and not _uses_runtime_pnl_metrics(task_obj):
            return persisted_snapshot

        state = _get_state(task_type, task_id, execution_id)
        snapshot_cache_key = _build_task_summary_snapshot_cache_key(
            task_type=task_type,
            task_id=task_id,
            execution_id=execution_id,
            task_obj=task_obj,
        )
        if snapshot_cache_key:
            cached_snapshot = cache.get(snapshot_cache_key)
            if isinstance(cached_snapshot, TaskSummary):
                return cached_snapshot

        cache_key = _build_task_summary_cache_key(
            task_type=task_type,
            task_id=task_id,
            execution_id=execution_id,
            task_obj=task_obj,
            state=state,
        )
        cached = cache.get(cache_key)
        if isinstance(cached, TaskSummary):
            return cached

        summary = self.compute(
            task_type=task_type,
            task_id=task_id,
            execution_id=execution_id,
        )
        cache.set(cache_key, summary, TASK_SUMMARY_CACHE_TTL_SECONDS)
        if snapshot_cache_key:
            cache.set(snapshot_cache_key, summary, TASK_SUMMARY_SNAPSHOT_CACHE_TTL_SECONDS)
        return summary


TASK_SUMMARY_READ_MODEL = TaskSummaryReadModel()


def compute_task_summary(
    task_type: str,
    task_id: str,
    execution_id=None,
) -> TaskSummary:
    """Compute comprehensive task summary using DB aggregation.

    Realized PnL is calculated from closed positions:
      LONG:  (exit_price - entry_price) * abs(units)
      SHORT: (entry_price - exit_price) * abs(units)

    Unrealized PnL is the sum of open positions' unrealized_pnl field,
    which is updated each tick batch by the executor.

    Args:
        task_type: "backtest" or "trading".
        task_id: UUID of the task.
        execution_id: Optional execution UUID filter.

    Returns:
        TaskSummary with structured PnL, counts, execution, tick, and task info.
    """
    base_filter: dict = {"task_type": task_type, "task_id": task_id}
    if execution_id is not None:
        base_filter["execution_id"] = execution_id

    # Realized PnL + win/loss breakdown: aggregate over closed positions in
    # a single DB roundtrip.  The win/loss counts are what drives the
    # overview tab so they must come from the authoritative DB record,
    # not from the runtime counters (which we've seen drift to zero
    # after restarts that reuse the same execution_id).
    realized_agg = (
        Position.objects.filter(**base_filter, is_open=False)
        .exclude(exit_price__isnull=True)
        .annotate(
            _pnl_value=Case(
                When(
                    direction="long",
                    then=(F("exit_price") - F("entry_price")) * _abs_units(),
                ),
                When(
                    direction="short",
                    then=(F("entry_price") - F("exit_price")) * _abs_units(),
                ),
                default=Value(Decimal("0")),
                output_field=DecimalField(max_digits=24, decimal_places=10),
            )
        )
        .aggregate(
            closed_position_count=Count("pk"),
            realized_pnl=Sum("_pnl_value"),
            winning_trades=Sum(
                Case(
                    When(_pnl_value__gt=0, then=Value(1)),
                    default=Value(0),
                    output_field=IntegerField(),
                )
            ),
            losing_trades=Sum(
                Case(
                    When(_pnl_value__lt=0, then=Value(1)),
                    default=Value(0),
                    output_field=IntegerField(),
                )
            ),
        )
    )
    realized_pnl = realized_agg["realized_pnl"] or Decimal("0")
    winning_trades = int(realized_agg["winning_trades"] or 0)
    losing_trades = int(realized_agg["losing_trades"] or 0)
    closed_position_count = int(realized_agg["closed_position_count"] or 0)

    # Unrealized PnL: sum of open positions' unrealized_pnl
    open_qs = Position.objects.filter(**base_filter, is_open=True)
    open_agg = open_qs.aggregate(
        unrealized_pnl=Sum("unrealized_pnl"),
        open_position_count=Count("pk"),
        open_long_units=Sum(
            Case(
                When(direction="long", then=_abs_units()),
                default=Value(0),
                output_field=IntegerField(),
            )
        ),
        open_short_units=Sum(
            Case(
                When(direction="short", then=_abs_units()),
                default=Value(0),
                output_field=IntegerField(),
            )
        ),
    )
    unrealized_pnl = open_agg["unrealized_pnl"] or Decimal("0")
    open_position_count = int(open_agg["open_position_count"] or 0)
    open_long_units = int(open_agg["open_long_units"] or 0)
    open_short_units = int(open_agg["open_short_units"] or 0)

    # Total trade count
    trade_filter: dict = {"task_type": task_type, "task_id": task_id}
    if execution_id is not None:
        trade_filter["execution_id"] = execution_id
    total_trades = Trade.objects.filter(**trade_filter).count()

    # Execution state
    current_balance = None
    ticks_processed = 0
    tick_timestamp = None
    tick_bid = None
    tick_ask = None
    tick_mid = None
    tick_as_of = None
    account_currency: str | None = None
    current_balance_currency: str | None = None
    current_balance_money: dict[str, str] | None = None
    current_balance_display: Decimal | None = None
    display_currency: str | None = None
    current_balance_display_money: dict[str, str] | None = None
    current_balance_display_conversion_context: dict[str, object] | None = None
    resume_cursor_timestamp: str | None = None
    margin_ratio: Decimal | None = None
    current_atr: Decimal | None = None
    recovery_status: str | None = None
    recovery_warnings: list[str] = []
    recovery_blockers: list[str] = []
    reconciled_at: str | None = None
    tick_delivery: TickDeliveryInfo | None = None
    metrics_dict: dict[str, object] = {}

    from apps.trading.models.state import ExecutionState

    state_filter: dict = {"task_type": task_type, "task_id": task_id}
    if execution_id is not None:
        state_filter["execution_id"] = execution_id
    state = ExecutionState.objects.filter(**state_filter).order_by("-updated_at").first()
    if state:
        current_balance = state.current_balance
        current_balance_currency = str(state.current_balance_currency or "").upper() or None
        ticks_processed = state.ticks_processed
        if state.last_tick_timestamp:
            tick_as_of = state.last_tick_timestamp
            tick_timestamp = state.last_tick_timestamp.isoformat()
        if state.resume_cursor_timestamp:
            resume_cursor_timestamp = state.resume_cursor_timestamp.isoformat()
        tick_bid = state.last_tick_bid
        tick_ask = state.last_tick_ask
        tick_mid = state.last_tick_price

        # Extract margin_ratio and current_atr from strategy_state.metrics
        ss = state.strategy_state if isinstance(state.strategy_state, dict) else {}
        raw_metrics = ss.get("metrics")
        metrics_dict = (
            {str(key): value for key, value in raw_metrics.items()}
            if isinstance(raw_metrics, dict)
            else {}
        )
        if metrics_dict:
            raw_mr = metrics_dict.get("margin_ratio")
            if raw_mr is not None:
                try:
                    margin_ratio = Decimal(str(raw_mr))
                except (InvalidOperation, TypeError, ValueError):
                    pass  # nosec B110
            raw_atr = metrics_dict.get("current_atr")
            if raw_atr is not None:
                try:
                    current_atr = Decimal(str(raw_atr))
                except (InvalidOperation, TypeError, ValueError):
                    pass  # nosec B110
        recovery_status = (
            str(ss.get("broker_reconciliation_status"))
            if ss.get("broker_reconciliation_status") is not None
            else None
        )
        recovery_warnings = (
            [str(item) for item in ss.get("broker_reconciliation_warnings", [])]
            if isinstance(ss.get("broker_reconciliation_warnings"), list)
            else []
        )
        recovery_blockers = (
            [str(item) for item in ss.get("broker_reconciliation_blockers", [])]
            if isinstance(ss.get("broker_reconciliation_blockers"), list)
            else []
        )
        reconciled_at = (
            str(ss.get("broker_reconciled_at")) if ss.get("broker_reconciled_at") else None
        )
        tick_delivery = _tick_delivery_info(ss.get("live_tick_delivery"))

    # Task info
    status = ""
    started_at = None
    completed_at = None
    error_message = None
    status_reason_code = None
    status_reason_message = None

    task_obj = _get_task(task_type, task_id)
    quote_ccy: str | None = None
    if task_obj:
        status = task_obj.status
        started_at = task_obj.started_at.isoformat() if task_obj.started_at else None
        completed_at = task_obj.completed_at.isoformat() if task_obj.completed_at else None
        error_message = task_public_error_message(task_obj.status)
        public_reason = status_reason_from_task(task_obj)
        if public_reason is not None:
            status_reason_code = public_reason.code
            status_reason_message = public_reason.message
        quote_ccy = Instrument(getattr(task_obj, "instrument", "")).quote_currency or None
    error_code = task_public_error_code(status)

    stop_reason = _compute_stop_reason(
        task_type=task_type,
        task_id=task_id,
        execution_id=execution_id,
        task=task_obj,
    )

    if _uses_runtime_summary_metrics(task_obj):
        # SnowballNet keeps one netted position and uses partial closes to
        # realize profit.  Those partial closes change current_balance and
        # runtime PnL counters, but they do not create separate closed
        # Position rows, so the DB closed-position aggregation above can
        # understate realized PnL.  In-memory backtests do not persist
        # execution rows at all, so their overview must come from runtime
        # metrics as well.
        runtime_realized_quote = _metric_decimal(metrics_dict, "realized_pnl_quote")
        runtime_realized_account = _metric_decimal(metrics_dict, "realized_pnl")
        if runtime_realized_quote is not None and (
            runtime_realized_quote != Decimal("0")
            or (runtime_realized_account is not None and runtime_realized_account != Decimal("0"))
        ):
            realized_pnl = runtime_realized_quote

        runtime_unrealized_quote = _metric_decimal(metrics_dict, "unrealized_pnl_quote")
        if runtime_unrealized_quote is not None:
            unrealized_pnl = runtime_unrealized_quote

        if _uses_in_memory_mode(task_obj):
            total_trades = _metric_int(metrics_dict, "total_trades") or 0
            open_position_count = _metric_int(metrics_dict, "open_positions") or 0
            closed_position_count = _metric_int(metrics_dict, "closed_positions") or 0
            winning_trades = _metric_int(metrics_dict, "winning_trades") or 0
            losing_trades = _metric_int(metrics_dict, "losing_trades") or 0
            open_long_units = _metric_int(metrics_dict, "open_long_units") or 0
            open_short_units = _metric_int(metrics_dict, "open_short_units") or 0

    # Currency conversion for display
    fx_conversion = FX_CONVERSION.with_cache()
    if task_obj:
        if task_type == "backtest":
            account_currency = getattr(task_obj, "account_currency", None)
        else:
            account = getattr(task_obj, "oanda_account", None)
            account_currency = getattr(account, "currency", None)
    account_currency = str(account_currency or "").upper() or None
    current_balance_currency = current_balance_currency or account_currency
    if current_balance is not None and current_balance_currency:
        current_balance_money = Money.coerce(current_balance, current_balance_currency).as_dict()

    instrument = Instrument(getattr(task_obj, "instrument", "") if task_obj else "")
    preferred_display_currency = ""
    if task_obj:
        preferred_display_currency = (
            str(
                getattr(task_obj, "effective_display_currency", "")
                or getattr(task_obj, "display_currency", "")
                or ""
            )
            .strip()
            .upper()
        )
    if task_obj and task_type == "backtest":
        quote_ccy = quote_ccy or instrument.quote_currency
        account = AccountCurrency(current_balance_currency or account_currency or "")
        if not preferred_display_currency and account.is_known:
            preferred_display_currency = account.code
    elif task_obj and task_type == "trading":
        account = AccountCurrency(current_balance_currency or account_currency or "")
        if not preferred_display_currency and account.is_known:
            preferred_display_currency = account.code
    else:
        account = AccountCurrency(current_balance_currency or account_currency or "")

    if current_balance is not None and account.is_known and preferred_display_currency:
        converted_balance = DISPLAY_MONEY.convert_many(
            {"current_balance": Money.coerce(current_balance, account.code)},
            target_currency=preferred_display_currency,
            instrument=instrument.name,
            mid_price=tick_mid,
            as_of=tick_as_of,
            fx_conversion=fx_conversion,
        )
        current_balance_display_money = converted_balance.values["current_balance"]
        if current_balance_display_money is not None:
            display_currency = current_balance_display_money["currency"]
            current_balance_display = Decimal(current_balance_display_money["amount"])
        current_balance_display_conversion_context = converted_balance.conversion_context

    watermarks = _compute_watermarks(
        task_type=task_type,
        task_id=task_id,
        execution_id=execution_id or getattr(task_obj, "execution_id", None),
        latest_metrics=metrics_dict,
        latest_timestamp=tick_as_of,
    )

    pnl_currency = quote_ccy or current_balance_currency or account_currency
    display_currency = display_currency or preferred_display_currency or account_currency
    pnl_display_money = _pnl_display_money(
        realized=realized_pnl,
        unrealized=unrealized_pnl,
        source_currency=pnl_currency,
        target_currency=display_currency,
        instrument=instrument.name,
        mid_price=tick_mid,
        as_of=tick_as_of,
        fx_conversion=fx_conversion,
    )

    return TaskSummary(
        timestamp=tick_timestamp,
        pnl=PnlInfo(
            realized=realized_pnl,
            unrealized=unrealized_pnl,
            currency=pnl_currency,
            realized_display_money=pnl_display_money["realized"],
            unrealized_display_money=pnl_display_money["unrealized"],
            total_display_money=pnl_display_money["total"],
            display_conversion_context=pnl_display_money["conversion_context"],
        ),
        counts=CountsInfo(
            total_trades=total_trades,
            open_positions=open_position_count,
            closed_positions=closed_position_count,
            open_long_units=open_long_units,
            open_short_units=open_short_units,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
        ),
        execution=ExecutionInfo(
            current_balance=current_balance,
            ticks_processed=ticks_processed,
            account_currency=account_currency,
            current_balance_currency=current_balance_currency,
            current_balance_money=current_balance_money,
            current_balance_display=current_balance_display,
            display_currency=display_currency,
            current_balance_display_money=current_balance_display_money,
            current_balance_display_conversion_context=(current_balance_display_conversion_context),
            resume_cursor_timestamp=resume_cursor_timestamp,
            margin_ratio=margin_ratio,
            current_atr=current_atr,
            recovery_status=recovery_status,
            recovery_warnings=recovery_warnings,
            recovery_blockers=recovery_blockers,
            reconciled_at=reconciled_at,
            tick_delivery=tick_delivery,
        ),
        tick=TickInfo(
            timestamp=tick_timestamp,
            bid=tick_bid,
            ask=tick_ask,
            mid=tick_mid,
        ),
        task=TaskInfo(
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            error_message=error_message,
            error_code=error_code,
            status_reason_code=status_reason_code,
            status_reason_message=status_reason_message,
            stop_reason=stop_reason,
            progress=_compute_progress(task_type, task_obj, state),
        ),
        watermarks=watermarks,
    )


def compute_cached_task_summary(
    task_type: str,
    task_id: str,
    execution_id=None,
) -> TaskSummary:
    """Compute a cached task summary keyed by task/state freshness."""
    return TASK_SUMMARY_READ_MODEL.compute_cached(
        task_type=task_type,
        task_id=task_id,
        execution_id=execution_id,
    )


def _compute_watermarks(
    *,
    task_type: str,
    task_id: str,
    execution_id,
    latest_metrics: dict[str, object],
    latest_timestamp: datetime | None,
) -> ExecutionWatermarks:
    """Load aggregate watermarks and fold in the current unflushed metrics."""

    watermarks: dict[str, object] = {}
    aggregate_latest_metrics: dict[str, object] = {}
    if execution_id is not None:
        from apps.trading.models.metrics import ExecutionMetricAggregate

        row = (
            ExecutionMetricAggregate.objects.filter(
                task_type=task_type,
                task_id=task_id,
                execution_id=execution_id,
            )
            .values("watermarks", "latest_metrics")
            .first()
        )
        if row and isinstance(row.get("watermarks"), dict):
            watermarks = dict(row["watermarks"])
        if row and isinstance(row.get("latest_metrics"), dict):
            aggregate_latest_metrics = dict(row["latest_metrics"])

        if _should_repair_margin_watermark(
            watermarks=watermarks,
            latest_metrics=latest_metrics,
            aggregate_latest_metrics=aggregate_latest_metrics,
        ):
            repaired = _snowball_net_margin_watermark_from_metrics(
                task_type=task_type,
                task_id=task_id,
                execution_id=execution_id,
            )
            if repaired is not None:
                watermarks["margin_ratio_max"] = repaired

    if latest_metrics and latest_timestamp is not None:
        watermarks = update_watermarks(
            watermarks,
            timestamp=latest_timestamp,
            metrics=latest_metrics,
        )

    return _watermarks_from_map(watermarks)


def _should_repair_margin_watermark(
    *,
    watermarks: dict[str, object],
    latest_metrics: dict[str, object],
    aggregate_latest_metrics: dict[str, object],
) -> bool:
    margin_watermark = watermarks.get("margin_ratio_max")
    if isinstance(margin_watermark, dict):
        margin_watermark_data = cast(dict[str, object], margin_watermark)
        source_metric = str(margin_watermark_data.get("source_metric") or "")
        if source_metric == "snowball_net_margin_ratio_pct":
            return False
    return _has_snowball_net_margin_metric(latest_metrics) or _has_snowball_net_margin_metric(
        aggregate_latest_metrics
    )


def _has_snowball_net_margin_metric(metrics: dict[str, object]) -> bool:
    return metrics.get("snowball_net_margin_ratio_pct") not in (None, "")


def _snowball_net_margin_watermark_from_metrics(
    *,
    task_type: str,
    task_id: str,
    execution_id,
) -> dict[str, object] | None:
    from apps.trading.models.metrics import Metrics

    best_value: Decimal | None = None
    best_timestamp: datetime | None = None
    rows = (
        Metrics.objects.filter(
            task_type=task_type,
            task_id=task_id,
            execution_id=execution_id,
        )
        .values("timestamp", "metrics")
        .iterator(chunk_size=1000)
    )
    for row in rows:
        metrics = row.get("metrics")
        if not isinstance(metrics, dict):
            continue
        pct = _optional_decimal_from_value(metrics.get("snowball_net_margin_ratio_pct"))
        if pct is None:
            continue
        value = pct * Decimal("0.01")
        if best_value is None or value > best_value:
            best_value = value
            timestamp = row.get("timestamp")
            best_timestamp = timestamp if isinstance(timestamp, datetime) else None

    if best_value is None or best_timestamp is None:
        return None
    return {
        "value": str(best_value),
        "timestamp": best_timestamp.isoformat(),
        "source_metric": "snowball_net_margin_ratio_pct",
    }


def _watermarks_from_map(raw: dict[str, object]) -> ExecutionWatermarks:
    values = {spec.key: _watermark_info(raw.get(spec.key)) for spec in WATERMARK_SPECS}
    return ExecutionWatermarks(
        margin_ratio_max=values["margin_ratio_max"],
        base_units_max=values["base_units_max"],
        open_long_units_max=values["open_long_units_max"],
        open_short_units_max=values["open_short_units_max"],
        realized_pnl_max=values["realized_pnl_max"],
        unrealized_pnl_min=values["unrealized_pnl_min"],
        open_positions_max=values["open_positions_max"],
        active_cycles_max=values["active_cycles_max"],
    )


def _watermark_info(raw: object) -> WatermarkInfo:
    if not isinstance(raw, dict):
        return WatermarkInfo(value=None, timestamp=None)
    data = cast(dict[str, object], raw)
    return WatermarkInfo(
        value=_optional_decimal_from_value(data.get("value")),
        timestamp=_str_or_none(data.get("timestamp")),
        source_metric=_str_or_none(data.get("source_metric")),
    )


def _get_task(task_type: str, task_id: str):
    """Retrieve the task object by type and ID."""
    try:
        if task_type == "backtest":
            from apps.trading.models.backtest import BacktestTask

            return BacktestTask.objects.select_related("config").filter(pk=task_id).first()
        else:
            from apps.trading.models.trading import TradingTask

            return (
                TradingTask.objects.select_related("config", "oanda_account")
                .filter(pk=task_id)
                .first()
            )
    except Exception:
        return None


def _get_state(task_type: str, task_id: str, execution_id=None):
    from apps.trading.models.state import ExecutionState

    state_filter: dict = {"task_type": task_type, "task_id": task_id}
    if execution_id is not None:
        state_filter["execution_id"] = execution_id
    return ExecutionState.objects.filter(**state_filter).order_by("-updated_at").first()


def _uses_runtime_pnl_metrics(task_obj) -> bool:
    strategy_type = getattr(getattr(task_obj, "config", None), "strategy_type", None)
    return strategy_type == "snowball_net"


def _uses_runtime_summary_metrics(task_obj) -> bool:
    return _uses_runtime_pnl_metrics(task_obj) or _uses_in_memory_mode(task_obj)


def _uses_in_memory_mode(task_obj) -> bool:
    return getattr(task_obj, "in_memory_mode", False) is True


def _metric_decimal(metrics: dict[str, object], key: str) -> Decimal | None:
    value = metrics.get(key)
    return _optional_decimal_from_value(value)


def _optional_decimal_from_value(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _metric_int(metrics: dict[str, object], key: str) -> int | None:
    value = metrics.get(key)
    if value in (None, ""):
        return None
    try:
        return int(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _pnl_display_money(
    *,
    realized: Decimal,
    unrealized: Decimal,
    source_currency: str | None,
    target_currency: str | None,
    instrument: str,
    mid_price: Decimal | None,
    as_of: datetime | None,
    fx_conversion: FxConversionService = FX_CONVERSION,
) -> dict[str, Any]:
    """Return realized/unrealized/total PnL converted to display currency."""
    if not source_currency or not target_currency:
        return {
            "realized": None,
            "unrealized": None,
            "total": None,
            "conversion_context": CurrencyConversionContext.unavailable(
                source_currency=source_currency,
                target_currency=target_currency,
            ).as_dict(),
        }

    source = AccountCurrency(source_currency)
    target = AccountCurrency(target_currency)
    converted = DISPLAY_MONEY.convert_many(
        {
            "realized": Money.coerce(realized, source.code),
            "unrealized": Money.coerce(unrealized, source.code),
            "total": Money.coerce(realized + unrealized, source.code),
        },
        target_currency=target.code,
        instrument=instrument,
        mid_price=mid_price,
        as_of=as_of,
        fx_conversion=fx_conversion,
    )
    return {
        "realized": converted.values["realized"],
        "unrealized": converted.values["unrealized"],
        "total": converted.values["total"],
        "conversion_context": converted.conversion_context,
    }


def _tick_delivery_info(raw: object) -> TickDeliveryInfo | None:
    if not isinstance(raw, dict):
        return None
    raw_map = cast(dict[str, object], raw)

    return TickDeliveryInfo(
        status=_str_or_none(raw_map.get("status")),
        tick_timestamp=_str_or_none(raw_map.get("tick_timestamp")),
        observed_at=_str_or_none(raw_map.get("observed_at")),
        age_seconds=_float_or_none(raw_map.get("age_seconds")),
        max_age_seconds=_int_or_none(raw_map.get("max_age_seconds")),
        message=_str_or_none(raw_map.get("message")),
    )


def _str_or_none(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _float_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            return float(value)
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _int_or_none(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _build_task_summary_cache_key(
    *, task_type: str, task_id: str, execution_id, task_obj, state
) -> str:
    task_updated_at = getattr(task_obj, "updated_at", None)
    task_updated_at_key = task_updated_at.isoformat() if task_updated_at else "na"
    state_updated_at = getattr(state, "updated_at", None)
    state_updated_at_key = state_updated_at.isoformat() if state_updated_at else "na"
    execution_key = str(execution_id or "latest")
    return (
        f"task-summary:{task_type}:{task_id}:{execution_key}:"
        f"{task_updated_at_key}:{state_updated_at_key}"
    )


def _build_task_summary_snapshot_cache_key(
    *, task_type: str, task_id: str, execution_id, task_obj
) -> str | None:
    if execution_id is None or not task_obj:
        return None
    current_execution_id = getattr(task_obj, "execution_id", None)
    if str(current_execution_id or "") != str(execution_id):
        return None
    if not _is_terminal_status(getattr(task_obj, "status", None)):
        return None
    return f"task-summary-snapshot:{task_type}:{task_id}:{execution_id}"


def _compute_progress(task_type: str, task_obj, state) -> int:
    """Compute progress percentage for a task.

    For backtest tasks, progress is calculated as:
      (last_tick_timestamp - start_time) / (end_time - start_time) * 100

    For trading tasks, progress is always 0 (no finite time range).

    Args:
        task_type: "backtest" or "trading".
        task_obj: The task model instance (or None).
        state: The ExecutionState instance (or None).

    Returns:
        int: Progress percentage (0-100).
    """
    if not task_obj:
        return 0

    if task_type != "backtest":
        return 0

    from apps.trading.enums import TaskStatus

    if task_obj.status == TaskStatus.COMPLETED:
        return 100
    if task_obj.status != TaskStatus.RUNNING:
        return 0

    if not state or not state.last_tick_timestamp:
        return 0

    try:
        total_duration = (task_obj.end_time - task_obj.start_time).total_seconds()
        if total_duration <= 0:
            return 0
        elapsed = (state.last_tick_timestamp - task_obj.start_time).total_seconds()
        progress = int((elapsed / total_duration) * 100)
        return max(0, min(progress, 99))
    except Exception:
        return 0


def _abs_units():
    """Return a DB expression for abs(units)."""
    return Case(
        When(units__lt=0, then=-F("units")),
        default=F("units"),
    )


TASK_SUMMARY_CACHE_TTL_SECONDS = 30
TASK_SUMMARY_SNAPSHOT_CACHE_TTL_SECONDS = 60 * 60 * 24
_PROGRESS_ONLY_STATUS_RE = re.compile(r"^Processed\s+\d+\s+ticks$", re.IGNORECASE)


def _is_terminal_status(status: str | None) -> bool:
    return status in {"completed", "stopped", "failed"}


def _compute_stop_reason(
    *,
    task_type: str,
    task_id: str,
    execution_id,
    task,
) -> str | None:
    """Derive a human-readable stop reason for the overview tab.

    Priority:
    1. For FAILED tasks, surface only a fixed public failure message.
    2. For terminal states (STOPPED/COMPLETED/PAUSED), return the
       ``CeleryTaskStatus.status_message`` from the matching execution
       when available (e.g. "Execution completed successfully",
       "Execution stopped by external signal").
    3. Otherwise return ``None`` so the UI can render its own neutral
       placeholder.
    """
    if task is None:
        return None

    status = str(getattr(task, "status", "") or "")
    terminal_states = {"failed", "stopped", "completed", "paused"}
    if status not in terminal_states:
        return None

    public_reason = status_reason_from_task(task)
    if public_reason is not None:
        return public_reason.message

    status_message = _fetch_celery_status_message(
        task_type=task_type,
        task_id=task_id,
        execution_id=execution_id or getattr(task, "execution_id", None),
    )

    if status == "failed":
        return task_public_error_message(status)

    if status_message and not _is_progress_only_status_message(status_message):
        return status_message

    # Last-resort default for normal terminal states without a stored
    # status message (e.g. older executions finalized before the executor
    # started recording status_message consistently).
    if status == "completed":
        return "Execution completed successfully"
    if status == "stopped":
        return "Execution stopped"
    if status == "paused":
        return "Execution paused"
    return None


def _is_progress_only_status_message(message: str) -> bool:
    """Return true when a status message is only heartbeat progress."""

    return bool(_PROGRESS_ONLY_STATUS_RE.match(message.strip()))


def _fetch_celery_status_message(
    *,
    task_type: str,
    task_id: str,
    execution_id,
) -> str | None:
    """Return the ``status_message`` from the CeleryTaskStatus row."""
    if not execution_id:
        return None

    from apps.trading.models.celery import CeleryTaskStatus

    task_name = (
        "trading.tasks.run_backtest_task"
        if task_type == "backtest"
        else "trading.tasks.run_trading_task"
    )
    instance_key = f"{task_id}:{execution_id}"
    row = (
        CeleryTaskStatus.objects.filter(task_name=task_name, instance_key=instance_key)
        .order_by("-created_at")
        .values("status_message")
        .first()
    )
    if not row:
        return None
    message = row.get("status_message")
    if not message:
        return None
    return str(message).strip() or None
