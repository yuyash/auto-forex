"""Task execution engine for backtests and live trading.

This module provides the core execution engine that processes ticks through
strategies, manages state, and handles lifecycle events.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from logging import Logger, getLogger
from typing import Any, List, cast

from apps.trading.dataclasses import EventContext, StrategyResult
from apps.trading.engine import TradingEngine
from apps.trading.enums import StopMode, TaskStatus, TaskType
from apps.trading.events import StrategyEvent
from apps.trading.events.handler import EventHandler as _EventHandlerCompat
from apps.trading.events.handler import CycleResolutionError  # noqa: F401 — used in handle_events
from apps.trading.logging import flush_task_log_handlers
from apps.trading.models import BacktestTask, TradingEvent, TradingTask
from apps.trading.models.state import ExecutionState
from apps.trading.order import OrderService
from apps.trading.services.runtime_metrics import (
    RuntimeMetricsTracker,
    config_decimal,
    config_int,
)
from apps.trading.services.unrealized_pnl import update_unrealized_pnl
from apps.trading.tasks.broker_read_outage import BrokerReadOutageCoordinator
from apps.trading.tasks.diagnostics import ExecutionDiagnostics
from apps.trading.tasks.drain import TaskDrainCoordinator, record_final_stop_metrics
from apps.trading.tasks.event_processor import TaskEventProcessor
from apps.trading.tasks.event_replay import (
    EventReplayExecutor,
    classify_replay_event,
    event_already_applied,
    mark_event_processed,
    mark_event_processing_error,
)
from apps.trading.tasks.execution_collaborators import (
    ExecutionEventDispatcher,
    ExecutionStateRepository,
    ExecutionTickLoop,
)
from apps.trading.tasks.execution_tick_processing import (
    BacktestGapGuard,
    BacktestIdleTickPolicy,
    ExecutionTickProcessor,
    LiveTickDeliveryGuard,
    LiveTickDeliveryStateRepository,
    RuntimeMetricsRecorder,
    TradingIdleTickPolicy,
)
from apps.trading.tasks.execution_state_store import (
    ExecutionStateConflict,
    ExecutionStateStore,
)
from apps.trading.tasks.market_idle import MarketIdleCoordinator
from apps.trading.tasks.market_session import is_forex_market_closed
from apps.trading.tasks.metric_resume import (
    RuntimeMetricResumeCoordinator,
    to_decimal_metric,
    to_int_metric,
)
from apps.trading.tasks.progress_flush import ProgressFlushPolicy
from apps.trading.tasks.source import TickDataSource
from apps.trading.tasks.state import StateManager
from apps.trading.utils import Instrument, format_money, pip_size_for_instrument

logger: Logger = getLogger(name=__name__)

# Backward-compatible export for tests patching this symbol.
EventHandler = _EventHandlerCompat


class StrategyError(Exception):
    """Raised when a strategy signals an error stop.

    This exception is raised by the executor when a strategy returns
    ``should_stop=True`` with ``is_error=True``.  Task runners should
    catch this to transition the task to FAILED with the error message.
    """


@dataclass(slots=True)
class ExecutionLoopState:
    """Mutable loop state for executor runtime."""

    state: ExecutionState
    batch_count: int = 0
    no_tick_batches: int = 0
    max_no_tick_batches: int = 60
    stopped_early: bool = False
    paused_early: bool = False
    stop_mode: StopMode | None = None
    stop_reason: str = ""
    is_error: bool = False
    resume_last_tick_timestamp: datetime | None = None
    # Last delivered tick timestamp used for runtime gap detection.  Unlike
    # ``state.last_tick_timestamp`` (which only advances for ticks that were
    # actually processed), this is written *before* we decide whether to
    # process or skip, so it reflects the real cadence of the tick stream.
    last_delivered_tick_timestamp: datetime | None = None
    # Last timestamp at which the market-idle state was evaluated.  For
    # backtests we re-evaluate only when the replayed clock advances by a
    # threshold so we don't pay the DB-refresh cost on every tick.
    last_market_idle_eval_at: datetime | None = None
    # Wall-clock throttles for live tick diagnostics and broker drift checks.
    last_live_tick_status_log_at: datetime | None = None
    last_live_tick_latency_metric_at: datetime | None = None
    last_runtime_drift_check_at: datetime | None = None
    market_closed_empty_batch_logged: bool = False


class TaskExecutor:
    """Abstract base class for task execution.

    This class provides the core execution loop for processing ticks through
    a trading engine, managing state, handling lifecycle events, and coordinating
    task execution via Redis.
    """

    def __init__(
        self,
        *,
        task: BacktestTask | TradingTask,
        engine: TradingEngine,
        data_source: TickDataSource,
        event_context: EventContext,
        order_service: OrderService,
        state_manager: StateManager,
    ) -> None:
        """Initialize the executor.

        Args:
            task: Task instance (BacktestTask or TradingTask)
            engine: Trading engine instance
            data_source: Tick data source
            event_context: Context for event emission
            order_service: Service for executing orders
            state_manager: State manager for Redis coordination
        """
        self.task: TradingTask | BacktestTask = task
        self.logger = logger
        self.engine = engine
        self.data_source = data_source
        self.event_context = event_context
        self.order_service = order_service
        self.state_manager = state_manager
        self.state_store = ExecutionStateStore()

        # Extract properties from task
        self.instrument = task.instrument
        self.pip_size = task.pip_size or pip_size_for_instrument(task.instrument)
        self.initial_balance = self._get_initial_balance()
        self.account_currency = self._get_account_currency()

        self.event_handler = self.engine.create_event_handler(
            order_service=order_service,
            instrument=self.instrument,
        )
        self.event_processor = TaskEventProcessor(self)
        self._event_dispatcher = ExecutionEventDispatcher(self)
        self._state_repository = ExecutionStateRepository(self)
        self._tick_loop = ExecutionTickLoop(self)
        self._progress_flush_policy = ProgressFlushPolicy.for_task_type(
            self.task_type,
            in_memory_mode=self.uses_in_memory_mode,
        )
        self._batch_control_check_interval = self._control_check_tick_interval()

        from apps.trading.services.metrics_aggregator import MetricsAggregator

        self._metrics_aggregator = MetricsAggregator(
            task_type=self.task_type.value,
            task_id=str(task.pk),
            execution_id=str(task.execution_id) if task.execution_id else None,
        )
        self._runtime_metrics = self._create_runtime_metrics_tracker()
        self._live_tick_delivery_state_repository = LiveTickDeliveryStateRepository()
        self._live_tick_delivery_guard = LiveTickDeliveryGuard(self)
        self._backtest_gap_guard = BacktestGapGuard(self)
        self._backtest_idle_policy = BacktestIdleTickPolicy(self)
        self._trading_idle_tick_policy = TradingIdleTickPolicy(self)
        self._runtime_metric_recorder = RuntimeMetricsRecorder(self)
        self._tick_processor = ExecutionTickProcessor(self)
        self._broker_read_outage = BrokerReadOutageCoordinator(
            task=task,
            task_type=self.task_type,
            state_manager=state_manager,
            logger=logger,
        )

        # --- Debug: memory profiling ---
        debug_opts = getattr(task, "debug_options", None) or {}
        self._tracemalloc_enabled = bool(debug_opts.get("tracemalloc"))
        self._diagnostics = ExecutionDiagnostics(
            task=task,
            tracemalloc_enabled=self._tracemalloc_enabled,
        )
        self._market_idle = MarketIdleCoordinator(task=task, task_type=self.task_type)
        self._drain = TaskDrainCoordinator(self)
        self._metric_resume = RuntimeMetricResumeCoordinator(self)

        logger.info(
            "TaskExecutor initialized: instrument=%s, pip_size=%s, initial_balance=%s",
            self.instrument,
            self.pip_size,
            self.initial_balance,
        )

    def _get_initial_balance(self) -> Decimal:
        """Get initial balance from task.

        Returns:
            Initial balance for the task
        """
        from apps.trading.models import BacktestTask

        if isinstance(self.task, BacktestTask):
            return self.task.initial_balance
        else:
            # For trading tasks, fetch live balance from OANDA API.
            # The DB-stored balance may be stale (default 0).
            #
            # Use the short retry policy here rather than the task-level
            # policy: this is a one-shot startup probe, the DB fallback is
            # safe, and we don't want to block executor construction for the
            # full transient-outage budget on this single request.
            try:
                from apps.market.services.oanda import OandaService
                from apps.market.services.oanda_retry import OandaRetryPolicy

                client = OandaService(
                    self.task.oanda_account,
                    retry_policy=OandaRetryPolicy.short_default(),
                )
                details = client.get_account_details()
                return details.balance
            except Exception as e:
                logger.warning(
                    "Failed to fetch live balance from OANDA for account %s, "
                    "falling back to DB value: %s",
                    self.task.oanda_account.account_id,
                    e,
                )
                return self.task.oanda_account.balance

    @property
    def task_type(self) -> TaskType:
        """Determine task type from task instance.

        Returns:
            TaskType enum value
        """
        from apps.trading.models import BacktestTask

        if isinstance(self.task, BacktestTask):
            return TaskType.BACKTEST
        return TaskType.TRADING

    @property
    def uses_in_memory_mode(self) -> bool:
        """Return whether this executor should skip execution-row persistence."""
        return bool(
            self.task_type == TaskType.BACKTEST
            and getattr(self.task, "in_memory_mode", False) is True
        )

    def _create_runtime_metrics_tracker(self) -> RuntimeMetricsTracker:
        """Create a tracker for strategy-agnostic runtime metrics."""
        task_config = getattr(self.task, "config", None)
        raw_config_dict = getattr(task_config, "config_dict", {}) or {}
        config_dict = raw_config_dict if isinstance(raw_config_dict, dict) else {}
        strategy_type = str(getattr(task_config, "strategy_type", "") or "")
        account_currency = self.account_currency
        atr_period = config_int(config_dict, "atr_period", 14)
        snowball_net_atr_periods = self._snowball_net_atr_periods(
            strategy_type=strategy_type,
            config_dict=config_dict,
        )
        snowball_net_atr_baseline_periods = self._snowball_net_atr_baseline_periods(
            strategy_type=strategy_type,
            config_dict=config_dict,
        )

        return RuntimeMetricsTracker(
            instrument=self.instrument,
            pip_size=Decimal(str(self.pip_size)),
            account_currency=str(account_currency or ""),
            margin_rate=config_decimal(config_dict, "margin_rate", "0.04") or Decimal("0.04"),
            atr_period=atr_period,
            atr_baseline_period=(
                config_int(config_dict, "atr_baseline_period", 0)
                if "atr_baseline_period" in config_dict
                else (
                    config_int(config_dict, "atr_baseline_lookback", 0)
                    if "atr_baseline_lookback" in config_dict
                    else None
                )
            ),
            atr_periods=snowball_net_atr_periods,
            atr_baseline_periods=snowball_net_atr_baseline_periods,
            volatility_lock_multiplier=config_decimal(config_dict, "volatility_lock_multiplier"),
            initial_balance=self.initial_balance,
        )

    def _get_account_currency(self) -> str:
        """Return the currency code for account-denominated execution values."""
        return str(
            getattr(self.task, "account_currency", "")
            or getattr(getattr(self.task, "oanda_account", None), "currency", "")
            or ""
        ).upper()

    @staticmethod
    def _uses_snowball_net_atr_config(*, strategy_type: str, config_dict: dict[str, Any]) -> bool:
        return strategy_type == "snowball_net" or any(
            key.startswith(
                (
                    "adaptive_interval_atr_",
                    "volatility_guard_atr_",
                    "auto_direction_atr_",
                )
            )
            for key in config_dict
        )

    @classmethod
    def _snowball_net_atr_periods(
        cls, *, strategy_type: str, config_dict: dict[str, Any]
    ) -> dict[str, int]:
        if not cls._uses_snowball_net_atr_config(
            strategy_type=strategy_type,
            config_dict=config_dict,
        ):
            return {}

        legacy_period = config_int(config_dict, "atr_period", 14)
        return {
            "snowball_net_adaptive_interval": config_int(
                config_dict,
                "adaptive_interval_atr_period",
                legacy_period,
            ),
            "snowball_net_volatility_guard": config_int(
                config_dict,
                "volatility_guard_atr_period",
                legacy_period,
            ),
            "snowball_net_auto_direction": config_int(
                config_dict,
                "auto_direction_atr_period",
                legacy_period,
            ),
        }

    @classmethod
    def _snowball_net_atr_baseline_periods(
        cls, *, strategy_type: str, config_dict: dict[str, Any]
    ) -> dict[str, int]:
        if not cls._uses_snowball_net_atr_config(
            strategy_type=strategy_type,
            config_dict=config_dict,
        ):
            return {}

        legacy_period = config_int(config_dict, "atr_baseline_period", 96)
        return {
            "snowball_net_adaptive_interval": config_int(
                config_dict,
                "adaptive_interval_atr_baseline_period",
                legacy_period,
            ),
            "snowball_net_volatility_guard": config_int(
                config_dict,
                "volatility_guard_atr_baseline_period",
                legacy_period,
            ),
            "snowball_net_auto_direction": config_int(
                config_dict,
                "auto_direction_atr_baseline_period",
                legacy_period,
            ),
        }

    def handle_events(
        self,
        state: ExecutionState,
        events: List[Any],
        *,
        replaying: bool = False,
    ) -> None:
        """Handle events from strategy execution.

        Args:
            events: List of TradingEvent instances that were saved
        """
        self._event_dispatcher.process(state, events, replaying=replaying)

    def load_state(self) -> ExecutionState:
        """Load execution state from ExecutionState model.

        Returns:
            ExecutionState: Current execution state
        """
        return self._state_repository.load()

    def _load_state_with_metadata(self) -> tuple[ExecutionState, bool]:
        """Load state and indicate whether this execution is a resume."""
        return self._state_repository.load_with_metadata()

    def save_state(self, state: ExecutionState) -> None:
        """Save execution state to ExecutionState model.

        Args:
            state: Execution state to save
        """
        self._state_repository.save(state)

    def _flush_metrics(self, state: ExecutionState) -> None:
        """Flush completed minute-level metric buckets to the database."""
        self._metrics_aggregator.flush()

    def save_events(self, events: List[StrategyEvent]) -> List[Any]:
        """Save strategy events to database.

        Args:
            events: List of events to save
        """
        return self._event_dispatcher.persist(events)

    def execute(self) -> None:
        """Execute the task."""
        if self._tracemalloc_enabled:
            self._start_tracemalloc()
        try:
            state, resumed = self._start_execution()
            loop = ExecutionLoopState(
                state=state,
                resume_last_tick_timestamp=(state.last_tick_timestamp if resumed else None),
            )
            # Market-aware idle gate: if the task is a live trading task and
            # the forex market is currently closed, switch to IDLE before
            # waiting for ticks. This gives the user an immediate visual
            # signal that the task is parked rather than showing RUNNING
            # while the tick source is quiet.
            self._maybe_enter_market_idle_at_start(loop)
            self._run_tick_loop(loop)
            self._finalize_execution(loop)
        except Exception as e:
            self._handle_execution_failure(e)
            raise
        finally:
            if self._diagnostics.tracemalloc_started:
                self._stop_tracemalloc()
            self._cleanup_execution()

    def _maybe_enter_market_idle_at_start(self, loop: ExecutionLoopState) -> None:
        """Switch to IDLE right after start if the market is already closed.

        Only applies to live trading tasks. This is a cheap pre-flight check:
        the tick loop will maintain the RUNNING ↔ IDLE transitions on its
        own once batches start arriving.
        """
        if self.task_type != TaskType.TRADING:
            return
        if not is_forex_market_closed():
            return
        # Reuse the shared entry helper so the status change and the
        # in-state ``_idle_entered_at`` marker stay consistent with what
        # happens later in the tick loop.
        self._maybe_enter_market_idle(loop)

    def prepare_state_for_execution(
        self,
        *,
        state: ExecutionState,
        resumed: bool,
    ) -> ExecutionState:
        """Hook for executor-specific state preparation before start/resume."""
        _ = resumed
        return state

    def _run_start_hook(
        self,
        *,
        state: ExecutionState,
        resumed: bool,
    ) -> StrategyResult:
        if resumed:
            return self.engine.on_resume(state=state)
        return self.engine.on_start(state=state)

    def _start_execution(self) -> tuple[ExecutionState, bool]:
        """Initialize coordinator/state and run strategy start hook.

        Returns:
            Tuple of (state, resumed) where resumed indicates whether this
            execution is continuing from a previous run.

        IMPORTANT — Resume state preservation contract:
            When ``resumed`` is True the following invariants MUST hold:

            1. ``execution_id`` is unchanged from the previous run.
            2. ``ExecutionState`` (balance, strategy_state, ticks_processed,
               positions, orders) is loaded from the database — NOT recreated.
            3. Cumulative metric counters (realized_pnl, total_trades, …) are
               restored via ``_restore_metric_counters`` so dashboard values
               do not jump back to zero.
            4. The strategy receives ``on_resume`` (not ``on_start``).

            Breaking any of these causes the user-visible symptom of "state
            reset on resume". See ``TestResumeLifecycle`` for regression tests.
        """
        logger.info("Starting task execution")
        celery_task_id = getattr(self.task, "celery_task_id", None)
        self.state_manager.start(
            celery_task_id=str(celery_task_id) if celery_task_id else None,
            meta={
                "execution_id": str(self.task.execution_id) if self.task.execution_id else None,
                "celery_task_id": str(celery_task_id) if celery_task_id else None,
            },
        )

        state, resumed = self._load_state_with_metadata()
        state = self.prepare_state_for_execution(state=state, resumed=resumed)
        logger.info(
            "State loaded: balance=%s, ticks_processed=%d, resumed=%s",
            state.current_balance,
            state.ticks_processed,
            resumed,
        )

        if resumed and self.task_type == TaskType.TRADING:
            self._replay_unprocessed_events(state)

        logger.info("Starting trading engine lifecycle hook...")
        result = self._run_start_hook(state=state, resumed=resumed)
        state = result.state
        self.save_events(result.events)
        self.save_state(state)
        self._refresh_open_positions_cache()

        # Restore cumulative metric counters from DB when resuming a live
        # trading task.  Backtest restarts always start fresh — the caller
        # allocates a new execution_id and the task is expected to replay
        # from ``task.start_time``, so there is nothing to restore.
        if resumed:
            self._validate_resume_metrics_continuity(state=state)
            self._restore_metric_counters(state=state)

        logger.info("Engine started, events_count=%d", len(result.events))
        self._persist_config_snapshot()
        return state, resumed

    def _run_tick_loop(self, loop: ExecutionLoopState) -> None:
        """Run batch/tick processing loop."""
        self._tick_loop.run(loop)

    def _should_stop_before_batch(self, loop: ExecutionLoopState) -> bool:
        """Check external stop signal before processing a batch."""
        control = self.state_manager.check_control()
        should_stop = getattr(control, "should_stop", False) is True
        should_pause = getattr(control, "should_pause", False) is True
        if should_stop:
            self._record_requested_stop_mode(loop, control)
            logger.info("Stop signal received - ticks_processed=%d", loop.state.ticks_processed)
            loop.stopped_early = True
            return True

        if not should_pause:
            return False

        logger.info("Pause signal received - ticks_processed=%d", loop.state.ticks_processed)
        loop.paused_early = True
        return True

    def _control_check_tick_interval(self) -> int:
        if self.uses_in_memory_mode:
            from django.conf import settings as _settings

            return max(
                1,
                int(getattr(_settings, "TRADING_IN_MEMORY_CONTROL_CHECK_TICKS", 1000)),
            )
        return 100

    def _after_batch_processed(self, loop: ExecutionLoopState) -> None:
        """Hook for executor-specific checks after each processed batch."""
        _ = loop

    def _flush_task_logs(self) -> None:
        """Make task logs visible to polling clients during long executions."""
        flush_task_log_handlers(self.task)

    def _handle_empty_batch(self, loop: ExecutionLoopState) -> bool:
        """Handle empty tick batch; return True when loop should terminate."""
        if self.task_type == TaskType.TRADING and is_forex_market_closed():
            if not loop.market_closed_empty_batch_logged:
                logger.debug("Market is closed, tolerating empty batches")
                loop.market_closed_empty_batch_logged = True
            loop.no_tick_batches = 0
            self._evaluate_market_idle(loop)
            return False

        loop.market_closed_empty_batch_logged = False
        loop.no_tick_batches += 1
        if self.task_type == TaskType.TRADING:
            # Market is open — re-evaluate whether we should be idling
            # (e.g. within the pre-close window) or transitioning back
            # to RUNNING after the configured resume delay.
            self._evaluate_market_idle(loop)
            if loop.no_tick_batches == loop.max_no_tick_batches:
                logger.warning(
                    "No ticks received for %d consecutive batches on live trading task. "
                    "Keeping task alive and waiting for the market data stream to resume.",
                    loop.no_tick_batches,
                )
            elif (
                loop.no_tick_batches > loop.max_no_tick_batches
                and loop.no_tick_batches % loop.max_no_tick_batches == 0
            ):
                logger.warning(
                    "Still waiting for live ticks after %d consecutive empty batches.",
                    loop.no_tick_batches,
                )
            return False

        if loop.no_tick_batches < loop.max_no_tick_batches:
            return False

        logger.warning(
            "No ticks received for %d consecutive batches. Data source may have ended without EOF signal.",
            loop.no_tick_batches,
        )
        return True

    def _process_tick_batch(self, loop: ExecutionLoopState, tick_batch: list) -> None:
        """Process one non-empty batch."""
        # Drain-on-stop integration: when the task is DRAINING, inspect open
        # positions and close any at breakeven-or-better *before* feeding
        # ticks into the strategy, so that closed positions are reflected in
        # the same batch instead of the next one.  This also lets us exit
        # the loop as soon as the drain is complete.
        if self._handle_drain_pre_batch(loop):
            return
        control_check_interval = self._batch_control_check_interval
        for tick_idx, tick in enumerate(tick_batch):
            if tick_idx % control_check_interval == 0 and self._should_stop_during_batch(
                loop, tick_idx
            ):
                break
            if self._process_single_tick(loop, tick):
                break

    # ------------------------------------------------------------------
    # Drain-on-stop
    # ------------------------------------------------------------------

    def _handle_drain_pre_batch(self, loop: ExecutionLoopState) -> bool:
        return self._drain.handle_pre_batch(loop)

    def _close_position_during_drain(self, position_id: str) -> None:
        self._drain.close_position_during_drain(position_id)

    def _close_all_positions_on_stop_if_requested(self, loop: ExecutionLoopState) -> None:
        self._drain.close_all_positions_on_stop_if_requested(loop)

    def _record_final_stop_metrics(self, loop: ExecutionLoopState) -> None:
        record_final_stop_metrics(self, loop)

    def _record_drain_marker(self, loop: ExecutionLoopState, started_at: datetime | None) -> None:
        self._drain.record_drain_marker(loop, started_at)

    def _read_drain_marker(self, loop: ExecutionLoopState) -> datetime | None:
        return self._drain.read_drain_marker(loop)

    def _read_drain_duration_minutes_override(self, loop: ExecutionLoopState) -> int | None:
        return self._drain.read_drain_duration_minutes_override(loop)

    def _clear_drain_duration_minutes_override(self, loop: ExecutionLoopState) -> None:
        self._drain.clear_drain_duration_minutes_override(loop)

    # ------------------------------------------------------------------
    # Market-aware idle (trading + backtest)
    # ------------------------------------------------------------------

    def _market_idle_clock(self, loop: ExecutionLoopState) -> datetime | None:
        """Return the reference time for market-idle decisions.

        Live trading uses wall-clock time. Backtests use the most recent
        tick timestamp so that a fast replay still crosses the market
        open/close thresholds at the right point in the replayed clock.
        Returns ``None`` for backtests that have not yet delivered a
        tick — callers should treat that as "skip the evaluation".
        """
        return self._market_idle.clock(loop)

    def _market_session_config(self):
        """Build a MarketSessionConfig from the task's fields.

        Trading tasks always use the default forex schedule (the model
        doesn't expose overrides for them). Backtest tasks honour the
        per-task ``market_close_*`` fields so users can disable the
        weekly close or point it at a different weekday/hour pair.
        """
        return self._market_idle.session_config()

    def _evaluate_market_idle(self, loop: ExecutionLoopState) -> None:
        """Flip the task between RUNNING and IDLE based on the market clock.

        Triggers on three conditions:

        * Market currently closed (weekend).
        * Within ``market_idle_pre_close_minutes`` of the upcoming close.
        * Inside the post-open resume delay window.

        Safe to call repeatedly: the helper is idempotent and short-circuits
        when the task is in any state other than RUNNING/IDLE (so draining
        or stopping tasks are left alone).
        """
        self._market_idle.evaluate(loop)

    def _enter_market_idle(
        self,
        loop: ExecutionLoopState,
        *,
        now: datetime,
        reason: str,
    ) -> None:
        self._market_idle.enter(loop, now=now, reason=reason)

    def _exit_market_idle(self, loop: ExecutionLoopState) -> None:
        self._market_idle.exit(loop)

    # Backwards-compatible wrappers so existing call sites keep working.
    def _maybe_enter_market_idle(self, loop: ExecutionLoopState) -> None:
        self._evaluate_market_idle(loop)

    def _maybe_exit_market_idle(self, loop: ExecutionLoopState) -> None:
        self._evaluate_market_idle(loop)

    def _record_idle_marker(self, loop: ExecutionLoopState, entered_at: datetime | None) -> None:
        """Persist the idle-start timestamp into ExecutionState."""
        self._market_idle.record_marker(loop, entered_at)

    def _read_idle_marker(self, loop: ExecutionLoopState) -> datetime | None:
        return self._market_idle.read_marker(loop)

    def _should_stop_during_batch(self, loop: ExecutionLoopState, tick_idx: int) -> bool:
        """Check stop signal during long batch processing."""
        control = self.state_manager.check_control()
        should_stop = getattr(control, "should_stop", False) is True
        should_pause = getattr(control, "should_pause", False) is True
        if should_stop:
            self._record_requested_stop_mode(loop, control)
            logger.info(
                "Stop signal received during batch processing - task_id=%s, task_type=%s, ticks_processed=%d, tick_idx=%d",
                self.task.pk,
                self.task_type.value,
                loop.state.ticks_processed,
                tick_idx,
            )
            loop.stopped_early = True
            return True

        if not should_pause:
            return False

        logger.info(
            "Pause signal received during batch processing - task_id=%s, task_type=%s, ticks_processed=%d, tick_idx=%d",
            self.task.pk,
            self.task_type.value,
            loop.state.ticks_processed,
            tick_idx,
        )
        loop.paused_early = True
        return True

    @staticmethod
    def _record_requested_stop_mode(loop: ExecutionLoopState, control: object) -> None:
        raw_mode = getattr(control, "stop_mode", None)
        if raw_mode in (None, ""):
            return
        try:
            loop.stop_mode = StopMode(str(raw_mode))
        except ValueError:
            logger.warning("Ignoring unknown stop mode from control signal: %s", raw_mode)

    def _process_single_tick(self, loop: ExecutionLoopState, tick) -> bool:
        """Process one tick; return True when execution should stop."""
        return self._tick_processor.process(loop=loop, tick=tick)

    def _handle_live_tick_delivery(
        self,
        *,
        loop: ExecutionLoopState,
        tick,
        tick_ts: datetime,
    ) -> bool:
        """Record live tick delivery and stop before strategy code on stale ticks."""
        return self._live_tick_delivery_guard.handle(
            loop=loop,
            tick=tick,
            tick_ts=tick_ts,
        )

    def _write_live_tick_delivery_state(
        self,
        *,
        loop: ExecutionLoopState,
        status: str,
        tick_ts: datetime | None,
        observed_at: datetime,
        age_seconds: float | None,
        max_age_seconds: int,
        message: str,
    ) -> None:
        self._live_tick_delivery_state_repository.write(
            loop=loop,
            status=status,
            tick_ts=tick_ts,
            observed_at=observed_at,
            age_seconds=age_seconds,
            max_age_seconds=max_age_seconds,
            message=message,
        )

    def _current_live_tick_delivery_state(self, state: ExecutionState) -> dict[str, object] | None:
        return self._live_tick_delivery_state_repository.current(state)

    def _merge_live_tick_delivery_state(
        self,
        state: ExecutionState,
        delivery: dict[str, object],
    ) -> None:
        self._live_tick_delivery_state_repository.merge(state, delivery)

    def _should_log_live_tick_status(self, *, loop: ExecutionLoopState, now: datetime) -> bool:
        interval_seconds = self._live_tick_status_log_interval_seconds()
        if interval_seconds <= 0:
            return False
        last = loop.last_live_tick_status_log_at
        return last is None or (now - last).total_seconds() >= interval_seconds

    def _maybe_update_live_tick_latency_metrics(
        self,
        *,
        loop: ExecutionLoopState,
        tick,
        tick_ts: datetime,
        observed_at: datetime,
    ) -> dict[str, float] | None:
        """Store sampled live tick latency metrics in strategy_state.metrics."""
        return self._runtime_metric_recorder.maybe_update_live_tick_latency_metrics(
            loop=loop,
            tick=tick,
            tick_ts=tick_ts,
            observed_at=observed_at,
        )

    @staticmethod
    def _coerce_latency_metric(value: object) -> float | None:
        if value in (None, ""):
            return None
        try:
            return max(0.0, float(Decimal(str(value))))
        except (InvalidOperation, TypeError, ValueError):
            return None

    @staticmethod
    def _positive_int(value: object, *, default: int) -> int:
        try:
            if isinstance(value, int):
                return max(0, value)
            if isinstance(value, str):
                return max(0, int(value))
        except (TypeError, ValueError):
            return default
        return default

    def _live_tick_stale_guard_enabled(self) -> bool:
        return bool(getattr(self.task, "live_tick_stale_guard_enabled", True))

    def _max_live_tick_age_seconds(self) -> int:
        value = self._positive_int(
            getattr(self.task, "live_tick_max_age_seconds", 30),
            default=30,
        )
        return value if value > 0 else 30

    def _live_tick_status_log_interval_seconds(self) -> int:
        return self._positive_int(
            getattr(self.task, "live_tick_status_log_interval_seconds", 60),
            default=60,
        )

    def _live_tick_latency_metric_interval_seconds(self) -> int:
        account = getattr(self.task, "oanda_account", None)
        raw_value = getattr(account, "live_tick_latency_metric_interval_seconds", 60)
        if not isinstance(raw_value, (int, str)):
            raw_value = 60
        return self._positive_int(raw_value, default=60)

    @staticmethod
    def _coerce_tick_timestamp(value) -> datetime:
        """Normalize tick timestamps to timezone-aware datetimes."""
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

        timestamp_str = str(value).strip()
        if timestamp_str.endswith("Z"):
            timestamp_str = timestamp_str[:-1] + "+00:00"
        parsed = datetime.fromisoformat(timestamp_str)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed

    def _max_backtest_tick_gap_hours(self) -> int:
        """Return the configured backtest tick-gap threshold in hours."""
        from django.conf import settings as _settings

        task_value = getattr(self.task, "max_tick_gap_hours", None)
        if task_value is not None:
            return int(task_value)

        return int(getattr(_settings, "MARKET_BACKTEST_MAX_TICK_GAP_HOURS", 120))

    @staticmethod
    def _is_suspicious_tick_gap(
        previous: datetime,
        current: datetime,
        *,
        max_gap_hours: int | None = None,
    ) -> bool:
        """Return True when ``current`` jumps forward from ``previous`` by an
        amount that cannot be explained by forex market hours.

        The threshold is configured by task ``max_tick_gap_hours`` and falls
        back to ``settings.MARKET_BACKTEST_MAX_TICK_GAP_HOURS`` (default 120 hours).
        The regular weekend close (Fri 21:00 → Sun 21:00 UTC) is always
        considered acceptable.
        """
        from django.conf import settings as _settings

        if max_gap_hours is None:
            max_gap_hours = int(getattr(_settings, "MARKET_BACKTEST_MAX_TICK_GAP_HOURS", 120))
        return BacktestGapGuard.is_suspicious(
            previous,
            current,
            max_gap_hours=max_gap_hours,
        )

    def _refresh_open_positions_cache(self) -> None:
        """Refresh cached open positions used by common metric calculation."""
        positions = self.order_service.get_open_positions(instrument=self.instrument)
        self._runtime_metrics.sync_open_positions(positions)

    def _restore_metric_counters(self, *, state: ExecutionState) -> None:
        self._metric_resume.restore_counters(state=state)

    def _validate_resume_metrics_continuity(self, *, state: ExecutionState) -> None:
        self._metric_resume.validate_continuity(state=state)

    @staticmethod
    def _to_decimal_metric(value: object) -> Decimal:
        return to_decimal_metric(value)

    @staticmethod
    def _to_int_metric(value: object) -> int:
        return to_int_metric(value)

    def _update_common_metrics(self, state: ExecutionState, tick) -> None:
        """Merge strategy-agnostic runtime metrics into state.strategy_state.metrics."""
        self._runtime_metric_recorder.update_common_metrics(state, tick)

    def _replay_unprocessed_events(self, state: ExecutionState) -> None:
        """Replay pending events that were persisted before a crash."""
        pending_events = list(
            TradingEvent.objects.filter(
                task_type=self.task_type.value,
                task_id=self.task.pk,
                execution_id=self.task.execution_id,
                is_processed=False,
            ).order_by("created_at", "id")
        )

        if not pending_events:
            return

        logger.warning(
            "Replaying %d unprocessed event(s) before resume - task_id=%s",
            len(pending_events),
            self.task.pk,
        )
        self.handle_events(state, pending_events, replaying=True)
        self.save_state(state)

    @staticmethod
    def _classify_replay_event(trading_event: TradingEvent) -> str:
        return classify_replay_event(trading_event)

    def _event_already_applied(
        self,
        *,
        trading_event: TradingEvent,
        state: ExecutionState,
    ) -> bool:
        return event_already_applied(
            cast(EventReplayExecutor, self),
            trading_event=trading_event,
            state=state,
        )

    @staticmethod
    def _mark_event_processed(trading_event: TradingEvent) -> None:
        if getattr(trading_event, "_in_memory", False):
            from django.utils import timezone as dj_timezone

            trading_event.is_processed = True
            trading_event.processed_at = dj_timezone.now()
            trading_event.processing_error = ""
            return
        mark_event_processed(trading_event)

    @staticmethod
    def _mark_event_processing_error(trading_event: TradingEvent, message: str) -> None:
        if getattr(trading_event, "_in_memory", False):
            trading_event.processing_error = str(message)[:4000]
            return
        mark_event_processing_error(trading_event, message)

    def _buffer_tick_metrics(self, state: ExecutionState, tick) -> None:
        """Record strategy metrics into the minute-level aggregator."""
        self._runtime_metric_recorder.buffer_tick_metrics(state, tick)

    def _buffer_live_tick_latency_metrics(
        self,
        *,
        observed_at: datetime,
        latency_metrics: dict[str, float],
    ) -> None:
        """Record live latency metrics by wall-clock observation time."""
        self._runtime_metric_recorder.buffer_live_tick_latency_metrics(
            observed_at=observed_at,
            latency_metrics=latency_metrics,
        )

    def _record_processed_tick(self, loop: ExecutionLoopState, tick) -> None:
        """Persist tick progress and metrics after strategy processing."""
        self._runtime_metric_recorder.record_processed_tick(loop, tick)

    def _persist_batch_progress(self, loop: ExecutionLoopState) -> None:
        """Persist state/metrics and emit periodic telemetry."""
        if not self._progress_flush_policy.should_flush(batch_count=loop.batch_count):
            self._emit_batch_telemetry(loop)
            if self._tracemalloc_enabled:
                self._check_memory(loop)
            return
        self._runtime_metric_recorder.materialize_latest(loop.state)
        logger.debug(
            "Saving state after batch - task_id=%s, batch_count=%d, ticks_processed=%d",
            self.task.pk,
            loop.batch_count,
            loop.state.ticks_processed,
        )
        self.save_state(loop.state)
        self._flush_metrics(loop.state)
        self._update_unrealized_pnl(loop.state)
        self._emit_batch_telemetry(loop)
        if self._tracemalloc_enabled:
            self._check_memory(loop)

    def _update_unrealized_pnl(self, state: ExecutionState) -> None:
        """Recalculate unrealized pnl for open positions from latest tick."""
        if self.uses_in_memory_mode:
            return
        if state.last_tick_bid is None or state.last_tick_ask is None:
            return

        update_unrealized_pnl(
            task_type=self.task_type.value,
            task_id=str(self.task.pk),
            bid_price=Decimal(str(state.last_tick_bid)),
            ask_price=Decimal(str(state.last_tick_ask)),
            execution_id=self.task.execution_id,
            pnl_currency=Instrument(self.instrument).quote_currency,
        )

    def _emit_batch_telemetry(self, loop: ExecutionLoopState) -> None:
        """Emit periodic progress logs and heartbeat updates."""
        if loop.batch_count % 50 == 0:
            logger.debug(
                "Metrics progress - task_id=%s, batch=%d, ticks_processed=%d, pending_buckets=%d, last_tick_ts=%s",
                self.task.pk,
                loop.batch_count,
                loop.state.ticks_processed,
                len(self._metrics_aggregator._buckets),
                loop.state.last_tick_timestamp,
            )

        if loop.batch_count % 10 == 0:
            logger.debug(
                "Sending heartbeat - task_id=%s, batch_count=%d, ticks_processed=%d",
                self.task.pk,
                loop.batch_count,
                loop.state.ticks_processed,
            )
            self.state_manager.heartbeat(
                status_message=f"Processed {loop.state.ticks_processed} ticks"
            )

    # ------------------------------------------------------------------
    # Debug: memory profiling (opt-in via task.debug_options.tracemalloc)
    # ------------------------------------------------------------------

    def _start_tracemalloc(self) -> None:
        self._diagnostics.start_tracemalloc()

    def _stop_tracemalloc(self) -> None:
        self._diagnostics.stop_tracemalloc()

    def _check_memory(self, loop: ExecutionLoopState) -> None:
        self._diagnostics.check_memory(
            batch_count=loop.batch_count,
            ticks_processed=loop.state.ticks_processed,
        )

    def _log_tracemalloc_snapshot(self, label: str) -> None:
        self._diagnostics.log_tracemalloc_snapshot(label)

    def _finalize_execution(self, loop: ExecutionLoopState) -> None:
        """Run stop hook and persist final stop state."""
        # If the user asked for "Close All Positions" at stop time, close
        # them here before the strategy's on_stop hook runs so that the
        # final balance and metrics reflect the closed positions.  Applies
        # to both live trading and backtest tasks.
        if not loop.paused_early:
            self._close_all_positions_on_stop_if_requested(loop)
        logger.info("Calling engine.on_stop")
        result = self.engine.on_stop(state=loop.state)
        loop.state = result.state
        self.save_events(result.events)
        self._runtime_metric_recorder.materialize_latest(loop.state)
        self.save_state(loop.state)
        # Flush any remaining metrics (including the last partial minute)
        self._metrics_aggregator.flush(final=True)
        logger.info("Engine stopped, events_count=%d", len(result.events))

        self._raise_if_failed_stop(loop)

        if loop.paused_early:
            logger.info(
                "Execution paused - ticks_processed=%d, final_balance=%s",
                loop.state.ticks_processed,
                loop.state.current_balance,
            )
            type(self.task).objects.filter(
                pk=self.task.pk,
                status__in=(TaskStatus.RUNNING, TaskStatus.PAUSED),
            ).update(
                status=TaskStatus.PAUSED,
                completed_at=None,
            )
            self.task.refresh_from_db()
            self.state_manager.pause(status_message="Execution paused")
            return

        if loop.stopped_early:
            logger.info(
                "Execution stopped by external signal - ticks_processed=%d, final_balance=%s",
                loop.state.ticks_processed,
                loop.state.current_balance,
            )
            self.state_manager.stop(status_message="Execution stopped by external signal")
            return

        logger.info(
            "Execution completed successfully - ticks_processed=%d, final_balance=%s",
            loop.state.ticks_processed,
            loop.state.current_balance,
        )
        self.state_manager.stop(status_message="Execution completed successfully", completed=True)

    def _raise_if_failed_stop(self, loop: ExecutionLoopState) -> None:
        """Persist failed stop state and surface the strategy error."""
        if not (loop.stopped_early and loop.is_error):
            return

        logger.error(
            "Execution failed: %s — ticks_processed=%d, final_balance=%s",
            loop.stop_reason,
            loop.state.ticks_processed,
            format_money(loop.state.current_balance),
        )
        self.state_manager.stop(
            status_message=f"Execution failed: {loop.stop_reason}",
        )
        raise StrategyError(loop.stop_reason)

    def _handle_execution_failure(self, error: Exception) -> None:
        """Record failed execution outcome."""
        if isinstance(error, ExecutionStateConflict):
            logger.error("Execution state conflict during execution: %s", error, exc_info=True)
            self.state_manager.stop(
                status_message=(
                    "Execution stopped because persisted state changed concurrently. "
                    "Review recovery diagnostics before resuming."
                ),
                failed=True,
            )
            return

        logger.error("Execution failed: %s", error, exc_info=True)
        self.state_manager.stop(status_message=f"Execution failed: {error}", failed=True)

    def _persist_config_snapshot(self) -> None:
        """Save task and strategy config into the execution snapshot early.

        Called at execution start so the config is captured even if the
        execution fails before reaching the finalization step.
        """
        from apps.trading.models import TaskExecutionSnapshot

        execution_id = getattr(self.task, "execution_id", None)
        if execution_id is None:
            return
        try:
            from apps.trading.services.resume_config import (
                build_config_snapshot_defaults,
                log_effective_start_configuration,
            )

            snapshot = TaskExecutionSnapshot.objects.filter(
                task_type=self.task_type.value,
                task_id=self.task.pk,
                execution_id=execution_id,
            ).first()
            defaults = {
                **build_config_snapshot_defaults(snapshot=snapshot, task=self.task),
                "completed_at": None,
                "summary": {},
                "metrics": {},
            }
            TaskExecutionSnapshot.objects.update_or_create(
                task_type=self.task_type.value,
                task_id=self.task.pk,
                execution_id=execution_id,
                defaults=defaults,
            )
            log_effective_start_configuration(logger=logger, task=self.task)
        except Exception:
            logger.warning("Failed to persist config snapshot", exc_info=True)

    def _cleanup_execution(self) -> None:
        """Release runtime resources."""
        if self.uses_in_memory_mode:
            try:
                self.event_handler.clear_positions()
            except Exception:
                logger.debug("Failed to clear in-memory event handler state", exc_info=True)
        try:
            self.data_source.close()
        except Exception as e:
            logger.warning("Failed to close data source: %s", e)
        self.state_manager.cleanup()


class BacktestExecutor(TaskExecutor):
    """Executor for backtest tasks."""

    def __init__(
        self,
        *,
        task: BacktestTask,
        engine: TradingEngine,
        data_source: TickDataSource,
    ) -> None:
        """Initialize the backtest executor.

        Args:
            task: Backtest task instance
            engine: Trading engine instance
            data_source: Tick data source
        """
        # Create event context
        event_context = EventContext(
            user=task.user,
            account=None,  # No account for backtests
            instrument=task.instrument,
            task_id=task.pk,
            execution_id=task.execution_id,
            task_type=TaskType.BACKTEST,
        )

        # Create OrderService with dry_run=True for simulation.
        # In-memory mode swaps ORM repositories for transient execution state.
        if task.in_memory_mode is True:
            from apps.trading.in_memory_execution import InMemoryOrderService

            order_service = InMemoryOrderService(
                account=None,
                task=task,
                dry_run=True,
            )
        else:
            order_service = OrderService(
                account=None,  # Backtests don't need a real OANDA account
                task=task,
                dry_run=True,  # Backtest mode - simulate orders
            )

        # Create state manager
        state_manager = StateManager(
            task_name="trading.tasks.run_backtest_task",
            instance_key=f"{task.pk}:{task.execution_id}",
            task_id=str(task.pk),
        )

        super().__init__(
            task=task,
            engine=engine,
            data_source=data_source,
            event_context=event_context,
            order_service=order_service,
            state_manager=state_manager,
        )
        if task.in_memory_mode is True:
            from apps.trading.in_memory_execution import InMemoryEventHandler

            self.event_handler = InMemoryEventHandler(
                order_service=order_service,
                instrument=self.instrument,
            )

    def prepare_state_for_execution(
        self,
        *,
        state: ExecutionState,
        resumed: bool,
    ) -> ExecutionState:
        """Enable Snowball's cached state path for high-volume backtests."""
        _ = resumed
        if str(getattr(self.task.config, "strategy_type", "")) == "snowball":
            setattr(state, "_defer_snowball_state_serialization", True)
            if getattr(self.task, "in_memory_mode", False) is True:
                setattr(state, "_defer_snowball_runtime_view_updates", True)
        return state


class TradingExecutor(TaskExecutor):
    """Executor for live trading tasks."""

    def _after_batch_processed(self, loop: ExecutionLoopState) -> None:
        super()._after_batch_processed(loop)
        trading_task = cast(TradingTask, self.task)
        if getattr(trading_task, "dry_run", False):
            return
        if loop.stopped_early or loop.paused_early:
            return
        interval_seconds = self._runtime_drift_check_interval_seconds()
        if interval_seconds <= 0:
            return
        now = datetime.now(UTC)
        last = loop.last_runtime_drift_check_at
        if last is None:
            loop.last_runtime_drift_check_at = now
            return
        if (now - last).total_seconds() < interval_seconds:
            return
        loop.last_runtime_drift_check_at = now
        self._assert_runtime_broker_sync(state=loop.state)

    def _runtime_drift_check_interval_seconds(self) -> int:
        return self._positive_int(
            getattr(self.task, "broker_drift_check_interval_seconds", 60),
            default=60,
        )

    def _assert_runtime_broker_sync(self, *, state: ExecutionState) -> None:
        """Fail fast when broker exposure drifts during a live execution."""
        trading_task = cast(TradingTask, self.task)
        from apps.trading.services.reconciliation import (
            BrokerReadUnavailableError,
            TradingResumeReconciler,
            TradingSafetyError,
        )

        reconciler = TradingResumeReconciler(
            task=trading_task,
            state=state,
        )
        try:
            report = reconciler.detect_runtime_drift()
        except BrokerReadUnavailableError as exc:
            self._broker_read_outage.park(state=state, reason=str(exc))
            return
        if not report.has_blockers:
            return

        for blocker in report.blockers:
            logger.error(
                "Live broker drift detected - task_id=%s, execution_id=%s, blocker=%s",
                self.task.pk,
                self.task.execution_id,
                blocker,
            )
        raise TradingSafetyError(
            "Trading task stopped because broker state drift was detected while it was running. "
            "Review task logs and reconcile the OANDA account before restarting."
        )

    def prepare_state_for_execution(
        self,
        *,
        state: ExecutionState,
        resumed: bool,
    ) -> ExecutionState:
        """Reconcile broker/local state before live trading starts or resumes."""
        trading_task = cast(TradingTask, self.task)
        if getattr(trading_task, "dry_run", False):
            return state

        from apps.trading.services.reconciliation import TradingResumeReconciler, TradingSafetyError

        reconciler = TradingResumeReconciler(
            task=trading_task,
            state=state,
        )
        report = reconciler.reconcile(resumed=resumed)
        if report.has_blockers:
            for blocker in report.blockers:
                logger.error(
                    "Trading safety blocker - task_id=%s, execution_id=%s, blocker=%s",
                    self.task.pk,
                    self.task.execution_id,
                    blocker,
                )
            raise TradingSafetyError(
                "Trading task blocked by broker reconciliation safety checks. "
                "Review task logs and reconcile the OANDA account before restarting."
            )

        lifecycle = "resume" if resumed else "start"
        logger.info(
            "Trading %s reconciliation complete - task_id=%s, execution_id=%s, "
            "open_trades=%d, pending_orders=%d, closed_local=%d, created_local=%d, "
            "updated_local=%d, removed_entries=%d, synthesized_entries=%d, relinked_entries=%d",
            lifecycle,
            self.task.pk,
            self.task.execution_id,
            report.broker_open_positions,
            report.pending_broker_orders,
            report.closed_local_positions,
            report.created_local_positions,
            report.updated_local_positions,
            report.removed_open_entries,
            report.synthesized_open_entries,
            report.relinked_open_entries,
        )
        return state

    def __init__(
        self,
        *,
        task: TradingTask,
        engine: TradingEngine,
        data_source: TickDataSource,
        dry_run: bool = False,
    ) -> None:
        """Initialize the trading executor.

        Args:
            task: Trading task instance
            engine: Trading engine instance
            data_source: Tick data source
            dry_run: If True, simulate orders without placing real orders on OANDA
        """
        # Create event context
        event_context = EventContext(
            user=task.user,
            account=task.oanda_account,
            instrument=task.instrument,
            task_id=task.pk,
            execution_id=task.execution_id,
            task_type=TaskType.TRADING,
        )

        # Create OrderService (respect dry_run flag)
        order_service = OrderService(
            account=task.oanda_account,
            task=task,
            dry_run=dry_run,
        )

        # Create state manager
        state_manager = StateManager(
            task_name="trading.tasks.run_trading_task",
            instance_key=f"{task.pk}:{task.execution_id}",
            task_id=str(task.pk),
        )

        super().__init__(
            task=task,
            engine=engine,
            data_source=data_source,
            event_context=event_context,
            order_service=order_service,
            state_manager=state_manager,
        )
