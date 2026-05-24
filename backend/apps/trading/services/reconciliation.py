"""Trading resume reconciliation service.

Ensures local task state is aligned with broker state before resuming an
orphaned live trading execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from logging import Logger, getLogger
from typing import Any, TypeVar

from django.db.models import F
from django.utils import timezone as dj_timezone

from apps.market.services.oanda import OandaAPIError, OandaService, OrderDirection
from apps.market.services.oanda_retry import (
    OandaRetryClassifier,
    OandaRetryPolicy,
    OandaRetryService,
)
from apps.trading.enums import Direction, TaskType
from apps.trading.models import Position, TradingTask
from apps.trading.models.state import ExecutionState
from apps.trading.services.broker_snapshot import BrokerSnapshotLoader
from apps.trading.utils import Instrument

logger: Logger = getLogger(name=__name__)

_T = TypeVar("_T")


class TradingSafetyError(RuntimeError):
    """Raised when broker state is unsafe for automatic trading continuation."""


class BrokerReadUnavailableError(RuntimeError):
    """Raised when broker reads are unavailable after exhausting retries."""


class BrokerReadFailurePolicy:
    """Classify broker read failures for reconciliation callers."""

    def __init__(self, *, retry_classifier: OandaRetryClassifier | None = None) -> None:
        self.retry_classifier = retry_classifier or OandaRetryClassifier()

    def raise_for(self, *, label: str, exc: OandaAPIError) -> None:
        """Raise the public runtime exception matching an OANDA read failure."""
        if self.is_retry_exhausted(exc):
            raise BrokerReadUnavailableError(
                f"{label} is temporarily unavailable after retry exhaustion."
            ) from exc
        raise RuntimeError(f"{label} failed: {exc}") from exc

    def is_retry_exhausted(self, exc: OandaAPIError) -> bool:
        """Return True when the failure represents retry exhaustion."""
        haystack = " ".join(
            part.strip().lower() for part in [str(exc), getattr(exc, "internal_detail", "")] if part
        )
        return "failed after" in haystack and "attempt" in haystack


@dataclass(slots=True)
class ReconciliationReport:
    """Summary of broker/local state reconciliation."""

    updated_account_snapshot: bool = False
    broker_open_positions: int = 0
    pending_broker_orders: int = 0
    closed_local_positions: int = 0
    created_local_positions: int = 0
    updated_local_positions: int = 0
    removed_open_entries: int = 0
    synthesized_open_entries: int = 0
    relinked_open_entries: int = 0
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_blockers(self) -> bool:
        return bool(self.blockers)


def _safe_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:  # nosec B110
        return Decimal(default)


def _direction_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").strip().lower()


def _aggregate_trade_exposure(items: list[Any]) -> dict[str, Any]:
    directions = {_direction_value(getattr(item, "direction", "")) for item in items}
    directions.discard("")
    units = sum(int(abs(getattr(item, "units", 0) or 0)) for item in items)
    average = _weighted_average(items, units=units, price_attr="entry_price", units_attr="units")
    return {"directions": directions, "units": units, "average_price": average}


def _aggregate_position_exposure(items: list[Any]) -> dict[str, Any]:
    directions = {_direction_value(getattr(item, "direction", "")) for item in items}
    directions.discard("")
    units = sum(int(abs(getattr(item, "units", 0) or 0)) for item in items)
    average = _weighted_average(items, units=units, price_attr="entry_price", units_attr="units")
    return {"directions": directions, "units": units, "average_price": average}


def _weighted_average(
    items: list[Any],
    *,
    units: int,
    price_attr: str,
    units_attr: str,
) -> Decimal | None:
    if units <= 0:
        return None
    weighted_total = sum(
        (
            _safe_decimal(getattr(item, price_attr, None))
            * Decimal(abs(int(getattr(item, units_attr, 0) or 0)))
            for item in items
        ),
        Decimal("0"),
    )
    return weighted_total / Decimal(units)


class TradingResumeReconciler:
    """Reconcile broker and local state for live trading resume."""

    def __init__(
        self,
        *,
        task: TradingTask,
        state: ExecutionState,
        retry_policy: OandaRetryPolicy | None = None,
        retry_service: OandaRetryService | None = None,
    ) -> None:
        self.task = task
        self.state = state
        self.execution_id = task.execution_id
        self.retry_policy = retry_policy or OandaRetryPolicy.from_task(task)
        self.retry_service = retry_service or OandaRetryService(
            policy=self.retry_policy,
            raise_runtime_error=True,
        )
        self.oanda_service = OandaService(
            account=task.oanda_account,
            dry_run=False,
            retry_service=OandaRetryService(policy=self.retry_policy, raise_runtime_error=False),
            task=task,
        )
        self.failure_policy = BrokerReadFailurePolicy()
        self.broker_snapshot = BrokerSnapshotLoader(
            broker_service=self.oanda_service,
            request_runner=self._oanda_call,
        )

    def _oanda_call(
        self,
        fn: Any,
        *args: Any,
        label: str,
        **kwargs: Any,
    ) -> Any:
        """Call an OANDA service method with the task-scoped retry policy."""
        try:
            return fn(*args, **kwargs)
        except OandaAPIError as exc:
            self._failure_policy().raise_for(label=label, exc=exc)

    def _failure_policy(self) -> BrokerReadFailurePolicy:
        policy = getattr(self, "failure_policy", None)
        if isinstance(policy, BrokerReadFailurePolicy):
            return policy
        self.failure_policy = BrokerReadFailurePolicy()
        return self.failure_policy

    def _snapshot_loader(self) -> BrokerSnapshotLoader:
        loader = getattr(self, "broker_snapshot", None)
        if isinstance(loader, BrokerSnapshotLoader):
            return loader
        self.broker_snapshot = BrokerSnapshotLoader(
            broker_service=self.oanda_service,
            request_runner=self._oanda_call,
        )
        return self.broker_snapshot

    def reconcile(self, *, resumed: bool) -> ReconciliationReport:
        """Run full reconciliation and return a summary report."""
        report = ReconciliationReport()
        self._sync_account_snapshot(report)
        self._check_pending_orders(report)
        open_positions = self._sync_positions_with_broker(report)
        self._sync_strategy_state_with_positions(open_positions, report)
        self._validate_safety(report=report, resumed=resumed)
        self._record_reconciliation_metadata(report=report)
        self._persist_state()
        return report

    def detect_runtime_drift(self) -> ReconciliationReport:
        """Detect broker/local drift without mutating local state.

        This is used while a live trading task is actively running. Any mismatch
        is treated as unsafe because continuing would make strategy decisions on
        stale broker exposure.
        """
        report = ReconciliationReport()
        self._check_pending_orders(report)

        broker_trades = self._snapshot_loader().open_trades_for(
            instrument=self.task.instrument,
            label="Fetch open trades (drift check)",
        )
        report.broker_open_positions = len(broker_trades)

        if self._strategy_type() == "snowball_net":
            self._detect_snowball_net_runtime_drift(
                report=report,
                broker_trades=broker_trades,
            )
            return report

        local_open_positions = list(
            Position.objects.filter(
                task_type=TaskType.TRADING,
                task_id=self.task.pk,
                execution_id=self.execution_id,
                instrument=self.task.instrument,
                is_open=True,
            ).order_by("entry_time", "created_at")
        )
        if any(not position.oanda_trade_id for position in local_open_positions):
            report.blockers.append(
                "Found local open position(s) without OANDA trade ids while live trading is "
                "running. Broker drift detection cannot verify exposure safely."
            )

        broker_by_trade_id = {trade.trade_id: trade for trade in broker_trades if trade.trade_id}
        local_by_trade_id = {
            str(position.oanda_trade_id): position
            for position in local_open_positions
            if position.oanda_trade_id
        }

        for trade_id, local_position in local_by_trade_id.items():
            broker_trade = broker_by_trade_id.get(trade_id)
            if broker_trade is None:
                report.blockers.append(
                    f"OANDA trade {trade_id} for local position {local_position.pk} is no longer "
                    "open while the trading task is running."
                )
                continue

            broker_direction = (
                Direction.LONG if broker_trade.direction == OrderDirection.LONG else Direction.SHORT
            )
            broker_units = int(abs(broker_trade.units))
            local_units = int(abs(local_position.units))

            if local_position.direction != broker_direction:
                report.blockers.append(
                    f"OANDA trade {trade_id} direction changed from local "
                    f"{local_position.direction} to broker {broker_direction.value} while the "
                    "trading task is running."
                )

            if local_units != broker_units:
                report.blockers.append(
                    f"OANDA trade {trade_id} units changed from local {local_units} to broker "
                    f"{broker_units} while the trading task is running."
                )

        for trade_id, broker_trade in broker_by_trade_id.items():
            if trade_id in local_by_trade_id:
                continue
            report.blockers.append(
                f"OANDA trade {trade_id} for {broker_trade.instrument} is open at the broker "
                "but is not tracked locally while the trading task is running."
            )

        return report

    def _strategy_type(self) -> str:
        return str(getattr(self.task.config, "strategy_type", "") or "").strip().lower()

    def _detect_snowball_net_runtime_drift(
        self,
        *,
        report: ReconciliationReport,
        broker_trades: list[Any],
    ) -> None:
        """Detect SnowballNet drift by logical net exposure, not trade IDs."""
        local_open_positions = list(
            Position.objects.filter(
                task_type=TaskType.TRADING,
                task_id=self.task.pk,
                execution_id=self.execution_id,
                instrument=self.task.instrument,
                is_open=True,
            ).order_by("entry_time", "created_at")
        )

        broker = _aggregate_trade_exposure(broker_trades)
        local = _aggregate_position_exposure(local_open_positions)
        broker_units = int(broker["units"])
        local_units = int(local["units"])

        if broker_units > 0 and len(broker["directions"]) != 1:
            report.blockers.append(
                "OANDA SnowballNet exposure does not have a single valid direction while the "
                "trading task is running."
            )
            return
        if local_units > 0 and len(local["directions"]) != 1:
            report.blockers.append(
                "Local SnowballNet exposure does not have a single valid direction while the "
                "trading task is running."
            )
            return

        if broker_units != local_units:
            report.blockers.append(
                "SnowballNet net units changed while the trading task is running "
                f"(local={local_units}, broker={broker_units})."
            )
            return

        if broker_units <= 0:
            return

        broker_direction = next(iter(broker["directions"]))
        local_direction = next(iter(local["directions"])) if local["directions"] else ""
        if broker_direction != local_direction:
            report.blockers.append(
                "SnowballNet net direction changed while the trading task is running "
                f"(local={local_direction or 'none'}, broker={broker_direction})."
            )
            return

        strategy_state = (
            self.state.strategy_state if isinstance(self.state.strategy_state, dict) else {}
        )
        state_units = int(_safe_decimal(strategy_state.get("net_units")))
        if state_units != broker_units:
            report.blockers.append(
                "SnowballNet strategy state units diverged from OANDA while the trading task "
                f"is running (state={state_units}, broker={broker_units})."
            )
            return

        state_average = _safe_decimal(strategy_state.get("average_price"))
        broker_average = broker["average_price"]
        pip_size = _safe_decimal(getattr(self.task, "pip_size", None), "0.0001")
        tolerance = pip_size / Decimal("10") if pip_size > 0 else Decimal("0.00001")
        if broker_average is not None and abs(state_average - broker_average) > tolerance:
            report.blockers.append(
                "SnowballNet strategy average price diverged from OANDA while the trading task "
                f"is running (state={state_average}, broker={broker_average})."
            )

    def _sync_account_snapshot(self, report: ReconciliationReport) -> None:
        details = self._snapshot_loader().account_details(
            label="Fetch account snapshot",
        )

        account = self.task.oanda_account
        account.currency = details.currency
        account.balance = details.balance
        account.margin_used = details.margin_used
        account.margin_available = details.margin_available
        account.unrealized_pnl = details.unrealized_pl
        account.save(
            update_fields=[
                "currency",
                "balance",
                "margin_used",
                "margin_available",
                "unrealized_pnl",
                "updated_at",
            ]
        )

        self.state.current_balance = details.balance
        self.state.current_balance_currency = str(details.currency or "").strip().upper()
        report.updated_account_snapshot = True

    def _check_pending_orders(self, report: ReconciliationReport) -> None:
        pending_orders = self._snapshot_loader().pending_orders_for(
            instrument=self.task.instrument,
            label="Fetch pending orders",
        )

        report.pending_broker_orders = len(pending_orders)
        if pending_orders:
            report.blockers.append(
                f"OANDA account has {len(pending_orders)} pending order(s) for "
                f"{self.task.instrument}. Automatic trading is blocked until the "
                "account is reconciled manually."
            )

    def _sync_positions_with_broker(self, report: ReconciliationReport) -> list[Position]:
        broker_trades = self._snapshot_loader().open_trades_for(
            instrument=self.task.instrument,
            label="Fetch open trades (position sync)",
        )
        report.broker_open_positions = len(broker_trades)

        local_open_positions = list(
            Position.objects.filter(
                task_type=TaskType.TRADING,
                task_id=self.task.pk,
                execution_id=self.execution_id,
                instrument=self.task.instrument,
                is_open=True,
            ).order_by("entry_time", "created_at")
        )
        if any(not position.oanda_trade_id for position in local_open_positions):
            report.blockers.append(
                "Found local open position(s) without OANDA trade ids. Automatic resume "
                "cannot safely reconcile broker exposure."
            )

        broker_by_trade_id = {trade.trade_id: trade for trade in broker_trades if trade.trade_id}
        local_by_trade_id = {
            str(position.oanda_trade_id): position
            for position in local_open_positions
            if position.oanda_trade_id
        }

        for trade_id, local_position in local_by_trade_id.items():
            broker_trade = broker_by_trade_id.get(trade_id)
            if broker_trade is None:
                report.closed_local_positions += 1
                report.blockers.append(
                    f"OANDA trade {trade_id} for local position {local_position.pk} is no longer "
                    "open. Automatic close reconciliation is blocked to avoid losing "
                    "realized PnL or strategy state."
                )
                continue

            updated_fields: list[str] = []
            expected_units = int(abs(broker_trade.units))
            signed_units = (
                expected_units if local_position.direction == Direction.LONG else -expected_units
            )
            if local_position.units != signed_units:
                local_position.units = signed_units
                updated_fields.append("units")

            if local_position.entry_price != broker_trade.entry_price:
                local_position.entry_price = broker_trade.entry_price
                updated_fields.append("entry_price")

            if local_position.unrealized_pnl != broker_trade.unrealized_pnl:
                local_position.unrealized_pnl = broker_trade.unrealized_pnl
                updated_fields.append("unrealized_pnl")
            quote_currency = Instrument(local_position.instrument).quote_currency
            if quote_currency and local_position.unrealized_pnl_currency != quote_currency:
                local_position.unrealized_pnl_currency = quote_currency
                updated_fields.append("unrealized_pnl_currency")

            if self._strategy_type() == "snowball_net":
                if local_position.layer_index != 1:
                    local_position.layer_index = 1
                    updated_fields.append("layer_index")
                if local_position.retracement_count is None:
                    local_position.retracement_count = 0
                    updated_fields.append("retracement_count")

            if updated_fields:
                updated_fields.append("updated_at")
                local_position.save(update_fields=updated_fields)
                report.updated_local_positions += 1
                report.warnings.append(
                    f"Updated local position {local_position.pk} to match OANDA trade {trade_id}."
                )

        for trade_id, broker_trade in broker_by_trade_id.items():
            if trade_id in local_by_trade_id:
                continue

            direction = (
                Direction.LONG if broker_trade.direction == OrderDirection.LONG else Direction.SHORT
            )
            units_abs = int(abs(broker_trade.units))
            signed_units = units_abs if direction == Direction.LONG else -units_abs
            entry_time = broker_trade.open_time or dj_timezone.now()

            Position.objects.create(
                task_type=TaskType.TRADING,
                task_id=self.task.pk,
                execution_id=self.execution_id,
                instrument=broker_trade.instrument,
                direction=direction,
                units=signed_units,
                entry_price=broker_trade.entry_price,
                entry_time=entry_time,
                is_open=True,
                oanda_trade_id=broker_trade.trade_id,
                unrealized_pnl=broker_trade.unrealized_pnl,
                unrealized_pnl_currency=Instrument(broker_trade.instrument).quote_currency,
                layer_index=1 if self._strategy_type() == "snowball_net" else None,
                retracement_count=0 if self._strategy_type() == "snowball_net" else None,
            )
            report.created_local_positions += 1
            report.warnings.append(
                f"Created a missing local position for OANDA trade {trade_id} during reconciliation."
            )

        refreshed_open_positions = list(
            Position.objects.filter(
                task_type=TaskType.TRADING,
                task_id=self.task.pk,
                execution_id=self.execution_id,
                instrument=self.task.instrument,
                is_open=True,
            ).order_by("entry_time", "created_at")
        )

        return refreshed_open_positions

    def _validate_safety(self, *, report: ReconciliationReport, resumed: bool) -> None:
        strategy_type = self._strategy_type()
        strategy_state = (
            self.state.strategy_state if isinstance(self.state.strategy_state, dict) else {}
        )
        from apps.trading.strategies.registry import registry

        supports_stateful_reconciliation = registry.is_registered(
            strategy_type
        ) and registry.supports_stateful_broker_reconciliation(strategy_type)

        if not resumed:
            if report.broker_open_positions > 0:
                report.warnings.append(
                    f"OANDA account has {report.broker_open_positions} existing open trade(s) for "
                    f"{self.task.instrument}. Fresh start will adopt the broker exposure into the "
                    "new execution instead of blocking the restart."
                )
            return

        # Block unsupported strategy types that had broker-side changes.
        if not supports_stateful_reconciliation and (
            report.created_local_positions > 0
            or report.updated_local_positions > 0
            or report.closed_local_positions > 0
        ):
            report.blockers.append(
                "Automatic broker reconciliation is not state-aware for this strategy. "
                f"Task strategy '{strategy_type or 'unknown'}' requires manual review before resume."
            )

        # Positions disappeared from the broker while the task was stopped.
        # The strategy cannot safely continue without them.
        if report.closed_local_positions > 0 or report.removed_open_entries > 0:
            report.blockers.append(
                "Broker exposure changed while the task was stopped. "
                f"{report.closed_local_positions} local position(s) were closed and "
                f"{report.removed_open_entries} strategy entry/entries could not be matched. "
                "Use restart to begin a fresh execution."
            )

        if report.broker_open_positions > 0 and not strategy_state:
            report.blockers.append(
                "Broker open trades exist but no persisted strategy state was found for this "
                "execution. Automatic resume is unsafe."
            )

    def _record_reconciliation_metadata(self, *, report: ReconciliationReport) -> None:
        unrealized_total = sum(
            (
                _safe_decimal(position.unrealized_pnl)
                for position in Position.objects.filter(
                    task_type=TaskType.TRADING,
                    task_id=self.task.pk,
                    execution_id=self.execution_id,
                    instrument=self.task.instrument,
                    is_open=True,
                )
            ),
            Decimal("0"),
        )
        strategy_state = (
            self.state.strategy_state if isinstance(self.state.strategy_state, dict) else {}
        )
        strategy_state["broker_reconciled_at"] = dj_timezone.now().isoformat()
        strategy_state["broker_reconciliation_status"] = (
            "blocked" if report.blockers else "warning" if report.warnings else "ok"
        )
        strategy_state["broker_unrealized_pnl"] = str(unrealized_total)
        strategy_state["broker_open_trade_count"] = report.broker_open_positions
        strategy_state["broker_pending_order_count"] = report.pending_broker_orders
        if report.warnings:
            strategy_state["broker_reconciliation_warnings"] = report.warnings
        if report.blockers:
            strategy_state["broker_reconciliation_blockers"] = report.blockers
        self.state.strategy_state = strategy_state

    def _persist_state(self) -> None:
        if self._try_persist_state() == 1:
            self.state.state_version += 1
            return

        if self._refresh_state_for_metadata_retry():
            if self._try_persist_state() == 1:
                self.state.state_version += 1
                logger.info(
                    "Retried broker reconciliation state persistence after benign "
                    "state_version conflict - task_id=%s, execution_id=%s, state_version=%s",
                    self.task.pk,
                    self.execution_id,
                    self.state.state_version,
                )
                return

        raise TradingSafetyError(
            "Execution state changed during broker reconciliation. Retry resume after refresh."
        )

    def _try_persist_state(self) -> int:
        now = dj_timezone.now()
        return ExecutionState.objects.filter(
            pk=self.state.pk,
            state_version=self.state.state_version,
        ).update(
            strategy_state=self.state.strategy_state,
            current_balance=self.state.current_balance,
            current_balance_currency=self.state.current_balance_currency,
            ticks_processed=self.state.ticks_processed,
            last_tick_timestamp=self.state.last_tick_timestamp,
            resume_cursor_timestamp=(
                self.state.resume_cursor_timestamp or self.state.last_tick_timestamp
            ),
            last_tick_price=self.state.last_tick_price,
            last_tick_bid=self.state.last_tick_bid,
            last_tick_ask=self.state.last_tick_ask,
            updated_at=now,
            state_version=F("state_version") + 1,
        )

    def _refresh_state_for_metadata_retry(self) -> bool:
        """Refresh after a benign metadata-only optimistic-lock conflict.

        Resume reconciliation can overlap with a redundant recovery/resume attempt
        around deploys. If another writer only saved reconciliation metadata for
        the same tick cursor, merge our broker metadata into the latest row and
        retry once. If tick progress changed, trading may already be active and
        continuing this reconciliation would risk overwriting live state.
        """
        latest = ExecutionState.objects.get(pk=self.state.pk)
        progress_fields = (
            "ticks_processed",
            "last_tick_timestamp",
            "resume_cursor_timestamp",
            "last_tick_price",
            "last_tick_bid",
            "last_tick_ask",
        )
        if any(
            getattr(latest, progress_field) != getattr(self.state, progress_field)
            for progress_field in progress_fields
        ):
            return False

        latest_strategy_state = (
            dict(latest.strategy_state) if isinstance(latest.strategy_state, dict) else {}
        )
        pending_strategy_state = (
            self.state.strategy_state if isinstance(self.state.strategy_state, dict) else {}
        )
        latest_strategy_state.update(pending_strategy_state)
        self.state.strategy_state = latest_strategy_state

        for progress_field in progress_fields:
            setattr(self.state, progress_field, getattr(latest, progress_field))
        self.state.state_version = latest.state_version
        return True

    def _sync_strategy_state_with_positions(
        self,
        open_positions: list[Position],
        report: ReconciliationReport,
    ) -> None:
        strategy_type = str(getattr(self.task.config, "strategy_type", "") or "").strip().lower()

        from apps.trading.strategies.registry import registry

        if not registry.is_registered(strategy_type):
            return
        registry.reconcile_broker_positions(
            identifier=strategy_type,
            state=self.state,
            open_positions=open_positions,
            report=report,
            strategy_config=self.task.config,
        )
