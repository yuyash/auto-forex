"""Object collaborators for per-tick executor processing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from time import monotonic
from logging import Logger, getLogger
from typing import TYPE_CHECKING, Any

from apps.trading.dataclasses import StrategyResult
from apps.trading.enums import TaskStatus, TaskType
from apps.trading.tasks.execution_dtos import LiveTickDeliveryState

if TYPE_CHECKING:
    from apps.trading.models.state import ExecutionState
    from apps.trading.tasks.executor import ExecutionLoopState, TaskExecutor

logger: Logger = getLogger(name=__name__)


@dataclass(frozen=True, slots=True)
class RuntimeMetricTickSnapshot:
    """Minimal tick snapshot retained until metrics are materialized."""

    timestamp: datetime
    bid: Decimal
    ask: Decimal
    mid: Decimal
    current_balance: Decimal
    ticks_processed: int


class ExecutionTickProcessor:
    """Coordinate all policy decisions for one delivered tick."""

    def __init__(self, executor: "TaskExecutor") -> None:
        """Bind the processor to one executor instance."""
        self.executor = executor

    def process(self, loop: "ExecutionLoopState", tick) -> bool:
        """Process one tick; return True when execution should stop."""
        executor = self.executor
        tick_ts = executor._coerce_tick_timestamp(tick.timestamp)

        if executor.task_type == TaskType.TRADING:
            executor._trading_idle_tick_policy.refresh_market_state(loop=loop)

        if self._skip_resume_duplicate_tick(loop=loop, tick=tick, tick_ts=tick_ts):
            return False

        if executor._trading_idle_tick_policy.handle_if_idle(
            loop=loop,
            tick=tick,
            tick_ts=tick_ts,
        ):
            return False

        if executor._handle_live_tick_delivery(loop=loop, tick=tick, tick_ts=tick_ts):
            return loop.stopped_early

        if executor._backtest_gap_guard.stop_for_gap(loop=loop, tick_ts=tick_ts):
            return True

        executor._runtime_metric_recorder.materialize_if_tick_enters_new_bucket(
            loop.state,
            tick_ts,
        )
        if executor._backtest_idle_policy.handle_if_idle(loop=loop, tick=tick, tick_ts=tick_ts):
            return False

        live_tick_delivery = executor._current_live_tick_delivery_state(loop.state)
        result: StrategyResult = executor.engine.on_tick(tick=tick, state=loop.state)
        loop.state = result.state
        if live_tick_delivery is not None:
            executor._merge_live_tick_delivery_state(loop.state, live_tick_delivery)
        self._attach_tick_snapshot(result.events, tick)
        events: list[Any] = executor.save_events(result.events)

        if executor.task_type == TaskType.TRADING and events:
            executor.save_state(loop.state)

        if events:
            executor.handle_events(loop.state, events)

        if result.should_stop:
            logger.warning(
                "Strategy requested stop: %s - ticks_processed=%d",
                result.stop_reason,
                loop.state.ticks_processed,
            )
            executor._record_processed_tick(loop, tick)
            loop.stopped_early = True
            loop.stop_reason = result.stop_reason
            loop.is_error = result.is_error
            return True

        executor._record_processed_tick(loop, tick)
        return False

    @staticmethod
    def _attach_tick_snapshot(events: list[Any], tick) -> None:
        """Persist executable tick prices on events before order handling."""
        for event in events:
            if getattr(event, "tick_bid", None) is None:
                event.tick_bid = Decimal(str(tick.bid))
            if getattr(event, "tick_ask", None) is None:
                event.tick_ask = Decimal(str(tick.ask))
            if getattr(event, "tick_mid", None) is None:
                event.tick_mid = Decimal(str(tick.mid))

    def _skip_resume_duplicate_tick(
        self,
        *,
        loop: "ExecutionLoopState",
        tick,
        tick_ts: datetime,
    ) -> bool:
        """Skip ticks that were already processed before this run resumed."""
        resume_ts = loop.resume_last_tick_timestamp
        if resume_ts is None or tick_ts > resume_ts:
            return False

        executor = self.executor
        executor._runtime_metrics._record_tick(
            timestamp=tick_ts,
            mid=Decimal(str(tick.mid)),
        )
        if executor.task_type == TaskType.TRADING and executor.task.status == TaskStatus.IDLE:
            executor._trading_idle_tick_policy.write_waiting_delivery_state(
                loop=loop,
                tick=tick,
                tick_ts=tick_ts,
            )
        loop.last_delivered_tick_timestamp = tick_ts
        return True


class LiveTickDeliveryGuard:
    """Record live tick delivery state and keep stale ticks out of strategy code."""

    def __init__(self, executor: "TaskExecutor") -> None:
        """Bind the guard to one executor instance."""
        self.executor = executor

    def handle(
        self,
        *,
        loop: "ExecutionLoopState",
        tick,
        tick_ts: datetime,
    ) -> bool:
        """Return True when the current tick has been handled without strategy processing."""
        executor = self.executor
        if executor.task_type != TaskType.TRADING:
            return False

        now = datetime.now(UTC)
        age_seconds = max(0.0, (now - tick_ts).total_seconds())
        max_age_seconds = executor._max_live_tick_age_seconds()
        if not executor._live_tick_stale_guard_enabled():
            executor._write_live_tick_delivery_state(
                loop=loop,
                status="disabled",
                tick_ts=tick_ts,
                observed_at=now,
                age_seconds=age_seconds,
                max_age_seconds=max_age_seconds,
                message="Live tick stale guard is disabled for this task.",
            )
            self._log_status_if_due(
                loop=loop,
                tick=tick,
                tick_ts=tick_ts,
                observed_at=now,
                age_seconds=age_seconds,
                max_age_seconds=max_age_seconds,
                status="disabled",
            )
            return False

        if age_seconds > max_age_seconds:
            executor._write_live_tick_delivery_state(
                loop=loop,
                status="stale",
                tick_ts=tick_ts,
                observed_at=now,
                age_seconds=age_seconds,
                max_age_seconds=max_age_seconds,
                message=(
                    "Live tick is stale; skipped before strategy/order processing. "
                    "Waiting for the pricing stream to recover. "
                    f"age_seconds={age_seconds:.3f}, max_age_seconds={max_age_seconds}, "
                    f"tick_timestamp={tick_ts.isoformat()}"
                ),
            )
            logger.warning(
                "[EXECUTOR:LIVE_TICK_STALE] task_id=%s execution_id=%s "
                "tick_ts=%s observed_at=%s age_seconds=%.3f max_age_seconds=%d "
                "ticks_processed=%d bid=%s ask=%s mid=%s. "
                "Skipped before strategy/order processing; waiting for a fresh tick.",
                executor.task.pk,
                executor.task.execution_id,
                tick_ts.isoformat(),
                now.isoformat(),
                age_seconds,
                max_age_seconds,
                loop.state.ticks_processed,
                getattr(tick, "bid", None),
                getattr(tick, "ask", None),
                getattr(tick, "mid", None),
            )
            loop.last_live_tick_status_log_at = now
            latency_metrics = executor._maybe_update_live_tick_latency_metrics(
                loop=loop,
                tick=tick,
                tick_ts=tick_ts,
                observed_at=now,
            )
            if latency_metrics:
                executor._buffer_live_tick_latency_metrics(
                    observed_at=now,
                    latency_metrics=latency_metrics,
                )
            return True

        executor._write_live_tick_delivery_state(
            loop=loop,
            status="ok",
            tick_ts=tick_ts,
            observed_at=now,
            age_seconds=age_seconds,
            max_age_seconds=max_age_seconds,
            message="Live tick delivery is current.",
        )
        self._log_status_if_due(
            loop=loop,
            tick=tick,
            tick_ts=tick_ts,
            observed_at=now,
            age_seconds=age_seconds,
            max_age_seconds=max_age_seconds,
            status="ok",
        )
        return False

    def _log_status_if_due(
        self,
        *,
        loop: "ExecutionLoopState",
        tick,
        tick_ts: datetime,
        observed_at: datetime,
        age_seconds: float,
        max_age_seconds: int,
        status: str,
    ) -> None:
        executor = self.executor
        if not executor._should_log_live_tick_status(loop=loop, now=observed_at):
            return
        logger.info(
            "[EXECUTOR:LIVE_TICK_DELIVERY] task_id=%s execution_id=%s "
            "status=%s tick_ts=%s observed_at=%s age_seconds=%.3f "
            "max_age_seconds=%d ticks_processed=%d bid=%s ask=%s mid=%s",
            executor.task.pk,
            executor.task.execution_id,
            status,
            tick_ts.isoformat(),
            observed_at.isoformat(),
            age_seconds,
            max_age_seconds,
            loop.state.ticks_processed,
            getattr(tick, "bid", None),
            getattr(tick, "ask", None),
            getattr(tick, "mid", None),
        )
        loop.last_live_tick_status_log_at = observed_at


class BacktestGapGuard:
    """Detect suspicious gaps in replayed backtest tick streams."""

    def __init__(self, executor: "TaskExecutor") -> None:
        """Bind the guard to one executor instance."""
        self.executor = executor

    def stop_for_gap(self, *, loop: "ExecutionLoopState", tick_ts: datetime) -> bool:
        """Return True when a suspicious replay gap should stop execution."""
        executor = self.executor
        if executor.task_type != TaskType.BACKTEST or loop.last_delivered_tick_timestamp is None:
            return False
        if not self.is_suspicious(
            loop.last_delivered_tick_timestamp,
            tick_ts,
            max_gap_hours=executor._max_backtest_tick_gap_hours(),
        ):
            return False

        gap = tick_ts - loop.last_delivered_tick_timestamp
        logger.error(
            "[EXECUTOR:TICK_GAP] Suspicious tick gap detected in backtest stream - "
            "task_id=%s, execution_id=%s, previous_ts=%s, current_ts=%s, "
            "gap_seconds=%.0f, gap_hours=%.2f, ticks_processed=%d. "
            "Aborting to prevent a corrupted backtest result. "
            "Cross-reference [PUBLISHER:BATCH] / [SUBSCRIBER:BATCH] log lines "
            "covering this simulated-time window to see who dropped the batch.",
            executor.task.pk,
            executor.task.execution_id,
            loop.last_delivered_tick_timestamp.isoformat(),
            tick_ts.isoformat(),
            gap.total_seconds(),
            gap.total_seconds() / 3600,
            loop.state.ticks_processed,
        )
        loop.stopped_early = True
        loop.stop_reason = f"tick_gap:{gap.total_seconds():.0f}s"
        loop.is_error = True
        return True

    @staticmethod
    def is_suspicious(
        previous: datetime,
        current: datetime,
        *,
        max_gap_hours: int,
    ) -> bool:
        """Return true when a timestamp gap cannot be explained by market hours."""
        if current <= previous:
            return False

        gap = current - previous
        if gap <= timedelta(hours=max_gap_hours):
            return False

        if previous.weekday() == 4 and previous.hour >= 20:
            if gap < timedelta(days=3, hours=12):
                return False

        return True


class BacktestIdleTickPolicy:
    """Apply market-idle behavior to replayed backtest ticks."""

    def __init__(self, executor: "TaskExecutor") -> None:
        """Bind the policy to one executor instance."""
        self.executor = executor

    def handle_if_idle(
        self,
        *,
        loop: "ExecutionLoopState",
        tick,
        tick_ts: datetime,
    ) -> bool:
        """Return true when the tick was consumed by idle-mode handling."""
        executor = self.executor
        if executor.task_type != TaskType.BACKTEST:
            return False

        loop.last_delivered_tick_timestamp = tick_ts
        last_eval = loop.last_market_idle_eval_at
        if (
            last_eval is None
            or (tick_ts - last_eval) >= timedelta(seconds=60)
            or executor.task.status == TaskStatus.IDLE
        ):
            executor._evaluate_market_idle(loop)
            loop.last_market_idle_eval_at = tick_ts

        if executor.task.status != TaskStatus.IDLE:
            return False

        loop.state.ticks_processed += 1
        loop.state.last_tick_timestamp = tick_ts
        loop.state.resume_cursor_timestamp = tick_ts
        loop.state.last_tick_price = tick.mid
        loop.state.last_tick_bid = tick.bid
        loop.state.last_tick_ask = tick.ask
        if executor.uses_in_memory_mode:
            executor._runtime_metric_recorder.record_sparse_backtest_metrics(
                loop.state,
                tick,
                tick_ts,
            )
        else:
            executor._update_common_metrics(loop.state, tick)
            executor._buffer_tick_metrics(loop.state, tick)
        return True


class TradingIdleTickPolicy:
    """Consume live ticks without strategy/order processing while a task is IDLE."""

    def __init__(self, executor: "TaskExecutor") -> None:
        """Bind the policy to one executor instance."""
        self.executor = executor

    def refresh_market_state(self, *, loop: "ExecutionLoopState") -> None:
        """Synchronize RUNNING/IDLE before a live tick reaches freshness checks."""
        executor = self.executor
        if executor.task_type != TaskType.TRADING:
            return
        if executor.task.status not in (TaskStatus.RUNNING, TaskStatus.IDLE):
            return
        if executor.task.status == TaskStatus.IDLE and self._broker_read_outage_active(loop):
            return
        now = datetime.now(UTC)
        if (
            executor.task.status == TaskStatus.RUNNING
            and loop.last_market_idle_eval_at is not None
            and (now - loop.last_market_idle_eval_at).total_seconds() < 60
        ):
            return
        executor._evaluate_market_idle(loop)
        loop.last_market_idle_eval_at = now

    def handle_if_idle(
        self,
        *,
        loop: "ExecutionLoopState",
        tick,
        tick_ts: datetime,
    ) -> bool:
        """Return true when the live tick was consumed by idle-mode handling."""
        executor = self.executor
        if executor.task_type != TaskType.TRADING:
            return False
        if executor.task.status != TaskStatus.IDLE:
            return False

        self.write_waiting_delivery_state(loop=loop, tick=tick, tick_ts=tick_ts)
        loop.last_delivered_tick_timestamp = tick_ts
        loop.state.ticks_processed += 1
        loop.state.last_tick_timestamp = tick_ts
        loop.state.resume_cursor_timestamp = tick_ts
        loop.state.last_tick_price = tick.mid
        loop.state.last_tick_bid = tick.bid
        loop.state.last_tick_ask = tick.ask
        executor._update_common_metrics(loop.state, tick)
        executor._buffer_tick_metrics(loop.state, tick)
        return True

    def write_waiting_delivery_state(
        self,
        *,
        loop: "ExecutionLoopState",
        tick,
        tick_ts: datetime,
    ) -> None:
        """Record that a live tick was observed but trading is intentionally idle."""
        executor = self.executor
        observed_at = datetime.now(UTC)
        age_seconds = max(0.0, (observed_at - tick_ts).total_seconds())
        status = "market_closed" if self._market_is_closed(loop) else "waiting"
        executor._write_live_tick_delivery_state(
            loop=loop,
            status=status,
            tick_ts=tick_ts,
            observed_at=observed_at,
            age_seconds=age_seconds,
            max_age_seconds=executor._max_live_tick_age_seconds(),
            message=(
                "Live tick observed while task is parked in IDLE; "
                "strategy/order processing skipped."
            )
            if status == "waiting"
            else (
                "Live tick observed while forex market is closed; "
                "strategy/order processing skipped."
            ),
        )

    def _market_is_closed(self, loop: "ExecutionLoopState") -> bool:
        clock = self.executor._market_idle_clock(loop)
        if clock is None:
            return False

        from apps.trading.tasks.market_session import is_forex_market_closed

        return is_forex_market_closed(clock, config=self.executor._market_session_config())

    @staticmethod
    def _broker_read_outage_active(loop: "ExecutionLoopState") -> bool:
        strategy_state = (
            loop.state.strategy_state if isinstance(loop.state.strategy_state, dict) else {}
        )
        return isinstance(strategy_state.get("_broker_read_unavailable"), dict)


class LiveTickDeliveryStateRepository:
    """Read and write live tick delivery diagnostics on ExecutionState."""

    def write(
        self,
        *,
        loop: "ExecutionLoopState",
        status: str,
        tick_ts: datetime | None,
        observed_at: datetime,
        age_seconds: float | None,
        max_age_seconds: int,
        message: str,
    ) -> None:
        """Persist live tick delivery diagnostics."""
        LiveTickDeliveryState.from_observation(
            status=status,
            tick_ts=tick_ts,
            observed_at=observed_at,
            age_seconds=age_seconds,
            max_age_seconds=max_age_seconds,
            message=message,
        ).apply_to(loop.state)

    def current(self, state: "ExecutionState") -> dict[str, object] | None:
        """Return current delivery diagnostics as a JSON-compatible dict."""
        delivery = LiveTickDeliveryState.from_state(state)
        return delivery.to_dict() if delivery is not None else None

    def merge(self, state: "ExecutionState", delivery: dict[str, object]) -> None:
        """Merge a previously captured delivery payload into a state."""
        strategy_state = (
            dict(state.strategy_state) if isinstance(state.strategy_state, dict) else {}
        )
        strategy_state["live_tick_delivery"] = delivery
        state.strategy_state = strategy_state


class RuntimeMetricsRecorder:
    """Record runtime metrics and tick progress for an executor."""

    def __init__(self, executor: "TaskExecutor") -> None:
        """Bind the recorder to one executor instance."""
        self.executor = executor
        self._execution_started_at = monotonic()
        self._latest_metric_snapshot: RuntimeMetricTickSnapshot | None = None
        self.live_tick_latency_metric_keys = frozenset(
            {
                "oanda_tick_publish_latency_seconds",
                "trading_tick_receive_latency_seconds",
            }
        )

    def maybe_update_live_tick_latency_metrics(
        self,
        *,
        loop: "ExecutionLoopState",
        tick,
        tick_ts: datetime,
        observed_at: datetime,
    ) -> dict[str, float] | None:
        """Store sampled live tick latency metrics in strategy_state.metrics."""
        executor = self.executor
        if executor.task_type != TaskType.TRADING:
            return None

        interval_seconds = executor._live_tick_latency_metric_interval_seconds()
        if interval_seconds <= 0:
            return None

        last = loop.last_live_tick_latency_metric_at
        if last is not None and (observed_at - last).total_seconds() < interval_seconds:
            return None

        receive_latency_seconds = max(0.0, (observed_at - tick_ts).total_seconds())
        publisher_latency = executor._coerce_latency_metric(
            getattr(tick, "oanda_tick_publish_latency_seconds", None)
        )
        latency_metrics = {
            "trading_tick_receive_latency_seconds": round(receive_latency_seconds, 6)
        }
        if publisher_latency is not None:
            latency_metrics["oanda_tick_publish_latency_seconds"] = round(publisher_latency, 6)

        strategy_state = (
            dict(loop.state.strategy_state) if isinstance(loop.state.strategy_state, dict) else {}
        )
        metrics = (
            dict(strategy_state.get("metrics", {}))
            if isinstance(strategy_state.get("metrics"), dict)
            else {}
        )
        metrics.update(latency_metrics)
        strategy_state["metrics"] = metrics
        loop.state.strategy_state = strategy_state
        loop.last_live_tick_latency_metric_at = observed_at

        logger.debug(
            "[EXECUTOR:TICK_LATENCY_METRIC] task_id=%s execution_id=%s "
            "tick_ts=%s observed_at=%s oanda_tick_publish_latency_seconds=%s "
            "trading_tick_receive_latency_seconds=%.6f interval_seconds=%d "
            "ticks_processed=%d",
            executor.task.pk,
            executor.task.execution_id,
            tick_ts.isoformat(),
            observed_at.isoformat(),
            f"{publisher_latency:.6f}" if publisher_latency is not None else "n/a",
            receive_latency_seconds,
            interval_seconds,
            loop.state.ticks_processed,
        )
        return latency_metrics

    def update_common_metrics(
        self,
        state: "ExecutionState",
        tick,
        *,
        record_tick: bool = True,
    ) -> None:
        """Merge strategy-agnostic runtime metrics into state.strategy_state.metrics."""
        timestamp = self.executor._coerce_tick_timestamp(tick.timestamp)
        strategy_state = state.strategy_state if isinstance(state.strategy_state, dict) else {}
        existing_metrics = (
            dict(strategy_state.get("metrics", {}))
            if isinstance(strategy_state.get("metrics"), dict)
            else {}
        )
        try:
            current_balance = Decimal(str(state.current_balance))
        except (InvalidOperation, TypeError, ValueError):
            current_balance = Decimal("0")
        common_metrics = self.executor._runtime_metrics.build_metrics(
            timestamp=timestamp,
            bid=Decimal(str(tick.bid)),
            ask=Decimal(str(tick.ask)),
            mid=Decimal(str(tick.mid)),
            current_balance=current_balance,
            ticks_processed=state.ticks_processed,
            execution_elapsed_seconds=self._execution_elapsed_seconds(),
            record_tick=record_tick,
        )
        existing_metrics.update(common_metrics)
        strategy_state["metrics"] = existing_metrics
        state.strategy_state = strategy_state

    def _execution_elapsed_seconds(self) -> float:
        return max(monotonic() - self._execution_started_at, 0.000001)

    def buffer_tick_metrics(self, state: "ExecutionState", tick) -> None:
        """Record strategy metrics into the minute-level aggregator."""
        metrics = (state.strategy_state or {}).get("metrics", {})
        if not metrics:
            return
        if self.executor.task_type == TaskType.TRADING:
            metrics = {
                key: value
                for key, value in metrics.items()
                if key not in self.live_tick_latency_metric_keys
            }
            if not metrics:
                return
        self.executor._metrics_aggregator.record(
            self.executor._coerce_tick_timestamp(tick.timestamp), metrics
        )

    def buffer_live_tick_latency_metrics(
        self,
        *,
        observed_at: datetime,
        latency_metrics: dict[str, float],
    ) -> None:
        """Record live latency metrics by wall-clock observation time."""
        if not latency_metrics:
            return
        self.executor._metrics_aggregator.record(observed_at, latency_metrics)

    def record_processed_tick(self, loop: "ExecutionLoopState", tick) -> None:
        """Persist tick progress and metrics after strategy processing."""
        tick_timestamp = self.executor._coerce_tick_timestamp(tick.timestamp)
        loop.state.ticks_processed += 1
        loop.state.last_tick_timestamp = tick_timestamp
        loop.state.resume_cursor_timestamp = tick_timestamp
        loop.state.last_tick_price = tick.mid
        loop.state.last_tick_bid = tick.bid
        loop.state.last_tick_ask = tick.ask
        loop.last_delivered_tick_timestamp = tick_timestamp
        if getattr(self.executor, "uses_in_memory_mode", False) is True:
            self.record_sparse_backtest_metrics(loop.state, tick, tick_timestamp)
            return

        self.update_common_metrics(loop.state, tick)
        observed_at = datetime.now(UTC)
        latency_metrics = self.maybe_update_live_tick_latency_metrics(
            loop=loop,
            tick=tick,
            tick_ts=tick_timestamp,
            observed_at=observed_at,
        )
        self.buffer_tick_metrics(loop.state, tick)
        if latency_metrics:
            self.buffer_live_tick_latency_metrics(
                observed_at=observed_at,
                latency_metrics=latency_metrics,
            )

    def record_sparse_backtest_metrics(
        self,
        state: "ExecutionState",
        tick,
        tick_timestamp: datetime,
    ) -> None:
        """Observe every tick but materialize common metrics sparsely."""
        previous = self._latest_metric_snapshot
        current = self._snapshot_for(state=state, tick=tick, tick_timestamp=tick_timestamp)

        self.executor._runtime_metrics.observe_tick(timestamp=current.timestamp, mid=current.mid)
        self._latest_metric_snapshot = current

        if previous is None:
            self._materialize_snapshot(state, current)
            self._buffer_state_metrics_at(current.timestamp, state)

    def materialize_if_tick_enters_new_bucket(
        self,
        state: "ExecutionState",
        tick_timestamp: datetime,
    ) -> None:
        """Finalize the previous minute before a newer tick mutates state."""
        if getattr(self.executor, "uses_in_memory_mode", False) is not True:
            return
        snapshot = self._latest_metric_snapshot
        if snapshot is None:
            return
        if self._bucket(snapshot.timestamp) == self._bucket(tick_timestamp):
            return
        self._materialize_snapshot(state, snapshot)
        self._buffer_state_metrics_at(snapshot.timestamp, state)

    def materialize_latest(self, state: "ExecutionState") -> None:
        """Materialize the latest sparse metrics before state/metric flushes."""
        if getattr(self.executor, "uses_in_memory_mode", False) is not True:
            return
        snapshot = self._latest_metric_snapshot
        if snapshot is None:
            return
        self._materialize_snapshot(state, snapshot)
        self._buffer_state_metrics_at(snapshot.timestamp, state)

    def _snapshot_for(
        self,
        *,
        state: "ExecutionState",
        tick,
        tick_timestamp: datetime,
    ) -> RuntimeMetricTickSnapshot:
        try:
            current_balance = Decimal(str(state.current_balance))
        except (InvalidOperation, TypeError, ValueError):
            current_balance = Decimal("0")
        return RuntimeMetricTickSnapshot(
            timestamp=tick_timestamp,
            bid=Decimal(str(tick.bid)),
            ask=Decimal(str(tick.ask)),
            mid=Decimal(str(tick.mid)),
            current_balance=current_balance,
            ticks_processed=state.ticks_processed,
        )

    def _materialize_snapshot(
        self,
        state: "ExecutionState",
        snapshot: RuntimeMetricTickSnapshot,
    ) -> None:
        materializer = getattr(state, "_strategy_state_materializer", None)
        if callable(materializer):
            materializer()
        strategy_state = state.strategy_state if isinstance(state.strategy_state, dict) else {}
        existing_metrics = (
            dict(strategy_state.get("metrics", {}))
            if isinstance(strategy_state.get("metrics"), dict)
            else {}
        )
        common_metrics = self.executor._runtime_metrics.build_metrics(
            timestamp=snapshot.timestamp,
            bid=snapshot.bid,
            ask=snapshot.ask,
            mid=snapshot.mid,
            current_balance=snapshot.current_balance,
            ticks_processed=snapshot.ticks_processed,
            execution_elapsed_seconds=self._execution_elapsed_seconds(),
            record_tick=False,
        )
        existing_metrics.update(common_metrics)
        strategy_state["metrics"] = existing_metrics
        state.strategy_state = strategy_state

    def _buffer_state_metrics_at(self, timestamp: datetime, state: "ExecutionState") -> None:
        metrics = (state.strategy_state or {}).get("metrics", {})
        if not metrics:
            return
        self.executor._metrics_aggregator.record(timestamp, metrics)

    @staticmethod
    def _bucket(timestamp: datetime) -> datetime:
        return timestamp.replace(second=0, microsecond=0)
