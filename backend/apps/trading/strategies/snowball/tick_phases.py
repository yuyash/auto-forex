"""Object-oriented tick pipeline for the Snowball strategy."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from apps.trading.dataclasses import StrategyResult
from apps.trading.dataclasses.tick import Tick
from apps.trading.enums import Direction
from apps.trading.events import StrategyEvent
from apps.trading.strategies.snowball.config import SnowballStrategyConfig
from apps.trading.strategies.snowball.accounting import SnowballAccountMetricsUpdater
from apps.trading.strategies.snowball.cycle_orchestrator import (
    CycleOrchestratorStrategy,
    SnowballActiveCycleProcessor,
    SnowballCycleReseeder,
)
from apps.trading.strategies.snowball.cycle_state import SnowballCycle, SnowballStrategyState
from apps.trading.strategies.snowball.enums import ProtectionLevel
from apps.trading.strategies.snowball.protection import SNOWBALL_PROTECTION, ProtectionStrategy
from apps.trading.strategies.snowball.warmup import (
    SnowballWarmupDecision,
    SnowballWarmupPolicy,
)

ARCHIVED_COMPLETED_CYCLES_KEY = "archived_completed_cycles"
SNOWBALL_DEFERRED_RUNTIME_METRIC_KEYS = frozenset(
    {
        "current_base_units",
        "snowball_current_base_units",
    }
)


class SnowballTickStrategy(CycleOrchestratorStrategy, ProtectionStrategy, Protocol):
    """Runtime surface the tick pipeline needs from SnowballStrategy."""

    instrument: str
    account_currency: str
    config: SnowballStrategyConfig
    pip_size: Decimal
    _hedging_enabled: bool
    _grid_order_violation: str | None
    _close_order_violation: str | None
    decision_engine: Any

    def _create_cycle(
        self,
        ss: SnowballStrategyState,
        tick: Tick,
        direction: Direction,
    ) -> tuple[list[StrategyEvent], Any]: ...

    def _effective_base_units(self, ss: SnowballStrategyState) -> int: ...

    def _close_entry(self, *args: Any, **kwargs: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class SnowballExecutionStateBoundary:
    """Typed adapter around ExecutionState.strategy_state."""

    state: Any

    def load(self) -> SnowballStrategyState:
        """Convert raw persisted state into the Snowball domain model."""
        cached = getattr(self.state, "_snowball_strategy_state_cache", None)
        if isinstance(cached, SnowballStrategyState):
            return cached
        snowball_state = SnowballStrategyState.from_strategy_state(self.raw_strategy_state())
        if self._defer_serialization:
            self._set_cached_state(snowball_state)
        return snowball_state

    def persist(self, snowball_state: SnowballStrategyState) -> None:
        """Write the Snowball domain model back to the execution state."""
        if self._defer_serialization:
            self._set_cached_state(snowball_state)
            if not self._defer_runtime_view_updates:
                strategy_state = self._hot_strategy_state(snowball_state)
                self._merge_runtime_view(strategy_state)
            return
        strategy_state = self._hot_strategy_state(snowball_state)
        self.state.strategy_state = strategy_state

    def raw_strategy_state(self) -> dict[str, Any]:
        """Return the raw strategy_state dict, tolerating malformed persisted values."""
        raw = getattr(self.state, "strategy_state", {})
        if isinstance(raw, dict):
            return raw
        return {}

    @property
    def _defer_serialization(self) -> bool:
        return bool(getattr(self.state, "_defer_snowball_state_serialization", False))

    @property
    def _defer_runtime_view_updates(self) -> bool:
        return bool(getattr(self.state, "_defer_snowball_runtime_view_updates", False))

    def _set_cached_state(self, snowball_state: SnowballStrategyState) -> None:
        setattr(self.state, "_snowball_strategy_state_cache", snowball_state)
        setattr(self.state, "_strategy_state_materializer", self.materialize)

    def _merge_runtime_view(self, hot_state: dict[str, Any]) -> None:
        """Keep cheap scalar/metrics fields visible without serializing grids."""
        strategy_state = dict(self.raw_strategy_state())
        strategy_state.pop("cycles", None)
        for key in (
            "protection_level",
            "initialised",
            "next_entry_id",
            "last_bid",
            "last_ask",
            "last_mid",
            "account_balance",
            "account_nav",
            ARCHIVED_COMPLETED_CYCLES_KEY,
            "warmup_started_at",
            "warmup_completed_at",
            "warmup_tick_count",
            "warmup_tp_closes",
            "warmup_phase",
            "warmup_last_log_state",
            "warmup_mid_history",
        ):
            if key in hot_state:
                strategy_state[key] = hot_state[key]
        metrics = (
            dict(strategy_state.get("metrics", {}))
            if isinstance(strategy_state.get("metrics"), dict)
            else {}
        )
        hot_metrics = hot_state.get("metrics")
        if isinstance(hot_metrics, dict):
            metrics.update(hot_metrics)
        strategy_state["metrics"] = metrics
        self.state.strategy_state = strategy_state

    def materialize(self) -> None:
        """Serialize the cached Snowball state before durable persistence."""
        cached = getattr(self.state, "_snowball_strategy_state_cache", None)
        if not isinstance(cached, SnowballStrategyState):
            return
        cached.flush_deferred_metrics()
        runtime_state = self.raw_strategy_state()
        runtime_metrics = runtime_state.get("metrics", {})
        if isinstance(runtime_metrics, dict):
            merged_metrics = dict(cached.metrics)
            merged_metrics.update(runtime_metrics)
            for key in SNOWBALL_DEFERRED_RUNTIME_METRIC_KEYS:
                if key in cached.metrics:
                    merged_metrics[key] = cached.metrics[key]
            cached.metrics = merged_metrics
        strategy_state = self._hot_strategy_state(cached)
        for key, value in runtime_state.items():
            if key not in strategy_state:
                strategy_state[key] = value
        self.state.strategy_state = strategy_state

    def _hot_strategy_state(self, snowball_state: SnowballStrategyState) -> dict[str, Any]:
        """Return the persistence payload without completed trade-backed cycles.

        Completed cycles are already represented by Trade/Position/Event rows,
        which power the strategy tab history and PnL views.  Keeping every
        completed grid in the hot ExecutionState JSON makes each tick and state
        save progressively more expensive, so we retain only cycles that can
        still affect future decisions.
        """
        retained, archived_delta = _split_hot_cycles(snowball_state.cycles)
        if archived_delta:
            snowball_state.cycles = retained

        snowball_state.flush_deferred_metrics()
        strategy_state = snowball_state.to_dict()
        archived_total = _archived_completed_cycles(self.raw_strategy_state()) + archived_delta
        if archived_total:
            strategy_state[ARCHIVED_COMPLETED_CYCLES_KEY] = archived_total
        return strategy_state


def _split_hot_cycles(cycles: list[SnowballCycle]) -> tuple[list[SnowballCycle], int]:
    retained: list[SnowballCycle] = []
    archived = 0
    for cycle in cycles:
        if cycle.completed and not _must_keep_completed_cycle_in_state(cycle):
            archived += 1
            continue
        retained.append(cycle)
    return retained, archived


def _must_keep_completed_cycle_in_state(cycle: SnowballCycle) -> bool:
    """Preserve completed cycles that cannot be rebuilt from the Trade ledger."""
    return not cycle.trade_cycle_id


def _archived_completed_cycles(strategy_state: dict[str, Any]) -> int:
    try:
        return max(0, int(strategy_state.get(ARCHIVED_COMPLETED_CYCLES_KEY, 0) or 0))
    except (TypeError, ValueError):
        return 0


@dataclass
class SnowballTickContext:
    """Mutable execution context shared by Snowball tick phases."""

    strategy: SnowballTickStrategy
    state: Any
    tick: Tick
    state_boundary: SnowballExecutionStateBoundary
    snowball_state: SnowballStrategyState
    events: list[StrategyEvent] = field(default_factory=list)
    ratio: Decimal = Decimal("0")
    allow_new_positions: bool = True
    allow_rebuilds: bool = True
    new_position_limit: int | None = None
    rebuild_limit_per_tick: int | None = None
    blocked_counter_add_directions: set[Direction] = field(default_factory=set)
    warmup_decision: SnowballWarmupDecision | None = None
    defer_metric_strings: bool = False
    previous_mid: Decimal | None = None

    def set_metric(self, key: str, value: str | int | float | Decimal) -> None:
        self.snowball_state.set_metric(key, value, defer=self.defer_metric_strings)


@dataclass(frozen=True, slots=True)
class SnowballTickPhaseOutcome:
    """Result returned by a pipeline phase."""

    result: StrategyResult | None = None

    @property
    def completed(self) -> bool:
        """Return True when the pipeline should stop."""
        return self.result is not None


NOOP_PHASE_OUTCOME = SnowballTickPhaseOutcome()

CANDLE_GRANULARITY_SECONDS: dict[str, int] = {
    "S5": 5,
    "S10": 10,
    "S15": 15,
    "S30": 30,
    "M1": 60,
    "M2": 120,
    "M4": 240,
    "M5": 300,
    "M10": 600,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H2": 7200,
    "H3": 10800,
    "H4": 14400,
    "H6": 21600,
    "H8": 28800,
    "H12": 43200,
    "D": 86400,
}


@dataclass(frozen=True, slots=True)
class SnowballCompletedCandle:
    """Completed mid-price candle built from the task tick stream."""

    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    previous_close: Decimal | None


class SnowballTickStateSerializer:
    """Persist SnowballStrategyState back into the task state object."""

    def persist(self, context: SnowballTickContext) -> None:
        """Write the Snowball state dictionary to the execution state."""
        context.state_boundary.persist(context.snowball_state)

    def result(
        self,
        context: SnowballTickContext,
        *,
        events: list[StrategyEvent] | None = None,
        should_stop: bool = False,
        stop_reason: str | None = None,
        is_error: bool = False,
    ) -> StrategyResult:
        """Persist context and build a StrategyResult."""
        self.persist(context)
        return StrategyResult(
            state=context.state,
            events=context.events if events is None else events,
            should_stop=should_stop,
            stop_reason=stop_reason or "",
            is_error=is_error,
        )


class SnowballInitialInvariantPhase:
    """Stop before mutations when the loaded state is structurally invalid."""

    def __init__(self, *, serializer: SnowballTickStateSerializer | None = None) -> None:
        self.serializer = serializer or SnowballTickStateSerializer()

    def run(self, context: SnowballTickContext) -> SnowballTickPhaseOutcome:
        """Evaluate the pre-tick invariant decision."""
        decision = context.strategy.decision_engine.invariant_decision(context.snowball_state)
        if not decision.should_stop:
            return NOOP_PHASE_OUTCOME
        return SnowballTickPhaseOutcome(
            result=self.serializer.result(
                context,
                should_stop=True,
                stop_reason=decision.stop_reason,
                is_error=decision.is_error,
            )
        )


class SnowballAccountMetricsPhase:
    """Refresh account metrics before protection logic runs."""

    def __init__(
        self,
        *,
        updater: SnowballAccountMetricsUpdater | None = None,
    ) -> None:
        self.updater = updater or SnowballAccountMetricsUpdater()

    def run(self, context: SnowballTickContext) -> SnowballTickPhaseOutcome:
        """Update metrics and store the protection ratio on the context."""
        context.ratio = self.updater.update(
            state=context.state,
            ss=context.snowball_state,
            tick=context.tick,
            instrument=context.strategy.instrument,
            account_currency=context.strategy.account_currency,
        )
        current_base_units = context.strategy.config.effective_base_units(
            context.snowball_state.account_balance
        )
        context.set_metric("active_cycles", len(context.snowball_state.active_cycles()))
        context.set_metric("current_base_units", current_base_units)
        context.set_metric("snowball_current_base_units", current_base_units)
        return NOOP_PHASE_OUTCOME


class SnowballWarmupPhase:
    """Apply Snowball cold-start warmup controls."""

    def __init__(self, *, policy: SnowballWarmupPolicy | None = None) -> None:
        self.policy = policy or SnowballWarmupPolicy()

    def run(self, context: SnowballTickContext) -> SnowballTickPhaseOutcome:
        """Evaluate warmup gates and runtime limits for this tick."""
        decision = self.policy.evaluate(
            config=context.strategy.config,
            state=context.snowball_state,
            tick=context.tick,
            pip_size=context.strategy.pip_size,
        )
        context.warmup_decision = decision
        context.allow_new_positions = decision.allow_new_positions
        context.allow_rebuilds = decision.allow_new_positions
        context.new_position_limit = decision.new_position_limit
        context.rebuild_limit_per_tick = decision.rebuild_limit_per_tick
        current_base_units = context.strategy.config.warmup_scaled_base_units(
            context.snowball_state.account_balance,
            ratio_pct=decision.unit_ratio_pct,
        )
        context.set_metric("active_cycles", len(context.snowball_state.active_cycles()))
        context.set_metric("current_base_units", current_base_units)
        context.set_metric("snowball_current_base_units", current_base_units)
        return NOOP_PHASE_OUTCOME


class SnowballRiskGuardPhase:
    """Apply runtime add/rebuild guards and adaptive interval multipliers."""

    def run(self, context: SnowballTickContext) -> SnowballTickPhaseOutcome:
        """Update risk indicators and gate this tick's opening decisions."""
        cfg = context.strategy.config
        self._reset_runtime_multipliers(context)

        trend_blocked = self._apply_trend_guard(context)
        if trend_blocked:
            context.blocked_counter_add_directions.update(trend_blocked)

        counter_multiplier = self._adaptive_multiplier(
            context,
            prefix="snowball_adaptive_counter_interval",
            config=cfg.adaptive_counter_interval,
        )
        trend_multiplier = self._adaptive_multiplier(
            context,
            prefix="snowball_adaptive_trend_interval",
            config=cfg.adaptive_trend_interval,
        )
        setattr(
            context.strategy, "_snowball_adaptive_counter_interval_multiplier", counter_multiplier
        )
        setattr(context.strategy, "_snowball_adaptive_trend_interval_multiplier", trend_multiplier)
        context.set_metric("snowball_adaptive_counter_interval_multiplier", counter_multiplier)
        context.set_metric("snowball_adaptive_trend_interval_multiplier", trend_multiplier)

        block_reasons: list[str] = []
        rebuild_block_reasons: list[str] = []

        if cfg.add_margin_guard_enabled and context.ratio >= cfg.add_margin_guard_max_pct:
            block_reasons.append("margin")
            if cfg.add_margin_guard_scope == "adds_and_rebuilds":
                rebuild_block_reasons.append("margin")

        volatility_block_active = False
        if cfg.volatility_guard_enabled:
            volatility_block_active = self._volatility_guard_block_active(context)
        else:
            context.snowball_state.volatility_guard_cooldown_until = None
            self._write_volatility_cooldown_metrics(context, None)

        if volatility_block_active:
            if cfg.volatility_guard_target in {
                "new_positions",
                "new_positions_and_rebuilds",
            }:
                block_reasons.append("volatility")
            if cfg.volatility_guard_target in {"rebuilds", "new_positions_and_rebuilds"}:
                rebuild_block_reasons.append("volatility")

        if block_reasons:
            context.allow_new_positions = False
        if rebuild_block_reasons:
            context.allow_rebuilds = False

        context.set_metric("snowball_add_block_reason", ",".join(block_reasons))
        context.set_metric("snowball_rebuild_block_reason", ",".join(rebuild_block_reasons))
        context.set_metric("snowball_allow_new_positions", int(context.allow_new_positions))
        context.set_metric("snowball_allow_rebuilds", int(context.allow_rebuilds))
        if context.blocked_counter_add_directions:
            context.set_metric(
                "snowball_trend_blocked_directions",
                ",".join(
                    sorted(direction.value for direction in context.blocked_counter_add_directions)
                ),
            )
        else:
            context.set_metric("snowball_trend_blocked_directions", "")
        return NOOP_PHASE_OUTCOME

    def _volatility_guard_block_active(self, context: SnowballTickContext) -> bool:
        cfg = context.strategy.config
        exceeded = self._volatility_exceeded(
            context,
            prefix="snowball_volatility_guard",
            source=cfg.volatility_guard_source,
            candle_granularity=cfg.volatility_guard_candle_granularity,
            atr_period=cfg.volatility_guard_atr_period,
            baseline_period=cfg.volatility_guard_baseline_period,
            candle_ema_period=cfg.volatility_guard_candle_ema_period,
            max_pips=cfg.volatility_guard_max_pips,
            max_multiplier=cfg.volatility_guard_max_multiplier,
        )
        now = self._aware_datetime(context.tick.timestamp)
        cooldown_until = self._parse_datetime(
            context.snowball_state.volatility_guard_cooldown_until
        )
        if exceeded:
            cooldown_until = self._extend_volatility_cooldown(context, now)
            self._write_volatility_cooldown_metrics(context, cooldown_until)
            return True
        if cooldown_until is not None and now < cooldown_until:
            self._write_volatility_cooldown_metrics(context, cooldown_until)
            return True
        context.snowball_state.volatility_guard_cooldown_until = None
        self._write_volatility_cooldown_metrics(context, None)
        return False

    def _extend_volatility_cooldown(
        self,
        context: SnowballTickContext,
        now: datetime,
    ) -> datetime | None:
        cooldown_minutes = context.strategy.config.volatility_guard_cooldown_minutes
        if cooldown_minutes <= 0:
            context.snowball_state.volatility_guard_cooldown_until = None
            return None
        cooldown_until = now + timedelta(minutes=cooldown_minutes)
        context.snowball_state.volatility_guard_cooldown_until = cooldown_until.isoformat()
        return cooldown_until

    def _write_volatility_cooldown_metrics(
        self,
        context: SnowballTickContext,
        cooldown_until: datetime | None,
    ) -> None:
        if cooldown_until is None:
            context.set_metric("snowball_volatility_guard_cooldown_until", "")
            context.set_metric("snowball_volatility_guard_cooldown_remaining_minutes", 0)
            return
        now = self._aware_datetime(context.tick.timestamp)
        remaining_seconds = max(0, int((cooldown_until - now).total_seconds()))
        remaining_minutes = (remaining_seconds + 59) // 60
        context.set_metric(
            "snowball_volatility_guard_cooldown_until",
            cooldown_until.isoformat(),
        )
        context.set_metric(
            "snowball_volatility_guard_cooldown_remaining_minutes",
            remaining_minutes,
        )

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        raw = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            return self._aware_datetime(datetime.fromisoformat(raw))
        except ValueError:
            return None

    def _aware_datetime(self, value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    def _reset_runtime_multipliers(self, context: SnowballTickContext) -> None:
        setattr(context.strategy, "_snowball_adaptive_counter_interval_multiplier", Decimal("1"))
        setattr(context.strategy, "_snowball_adaptive_trend_interval_multiplier", Decimal("1"))

    def _apply_trend_guard(self, context: SnowballTickContext) -> set[Direction]:
        cfg = context.strategy.config
        prefix = "snowball_trend_guard"
        completed_candle = _update_candle_state(
            context,
            prefix=prefix,
            granularity=cfg.add_trend_candle_granularity,
        )
        previous_ema = _decimal_metric(context.snowball_state.metrics, "snowball_trend_guard_ema")
        trend_ema = previous_ema
        slope_pips = _decimal_metric(
            context.snowball_state.metrics, "snowball_trend_guard_slope_pips"
        ) or Decimal("0")
        if completed_candle is not None:
            trend_ema = _ema_next(
                current=previous_ema,
                price=completed_candle.close,
                period=cfg.add_trend_ema_period,
            )
            slope_pips = Decimal("0")
            if previous_ema is not None:
                slope_pips = (trend_ema - previous_ema) / context.strategy.pip_size
            context.set_metric("snowball_trend_guard_ema", trend_ema)
            context.set_metric("snowball_trend_guard_slope_pips", slope_pips)

        if trend_ema is None:
            context.set_metric("snowball_trend_guard_deviation_pips", Decimal("0"))
            context.set_metric("snowball_trend_guard_slope_pips", slope_pips)
            return set()

        deviation_pips = (context.tick.mid - trend_ema) / context.strategy.pip_size
        context.set_metric("snowball_trend_guard_deviation_pips", deviation_pips)
        context.set_metric("snowball_trend_guard_slope_pips", slope_pips)

        if not cfg.add_trend_guard_enabled:
            return set()

        blocked: set[Direction] = set()
        if deviation_pips <= -cfg.add_trend_max_opposite_deviation_pips:
            blocked.add(Direction.LONG)
        if deviation_pips >= cfg.add_trend_max_opposite_deviation_pips:
            blocked.add(Direction.SHORT)

        slope_threshold = cfg.add_trend_max_opposite_slope_pips
        if slope_threshold > 0:
            if slope_pips <= -slope_threshold:
                blocked.add(Direction.LONG)
            if slope_pips >= slope_threshold:
                blocked.add(Direction.SHORT)
        return blocked

    def _adaptive_multiplier(
        self,
        context: SnowballTickContext,
        *,
        prefix: str,
        config: Any,
    ) -> Decimal:
        if not config.enabled:
            return Decimal("1")
        volatility, _baseline, reference_baseline = self._volatility_value(
            context,
            prefix=prefix,
            source=config.source,
            candle_granularity=config.candle_granularity,
            atr_period=config.atr_period,
            baseline_period=config.baseline_period,
            candle_ema_period=config.candle_ema_period,
        )
        reference = (
            reference_baseline
            if reference_baseline is not None and reference_baseline > 0
            else config.reference_pips
        )
        if volatility is None or volatility <= 0 or reference <= 0:
            return Decimal("1")
        multiplier = volatility / reference
        multiplier = max(config.min_multiplier, multiplier)
        multiplier = min(config.max_multiplier, multiplier)
        return multiplier

    def _volatility_exceeded(
        self,
        context: SnowballTickContext,
        *,
        prefix: str,
        source: str,
        candle_granularity: str,
        atr_period: int,
        baseline_period: int,
        candle_ema_period: int,
        max_pips: Decimal,
        max_multiplier: Decimal,
    ) -> bool:
        volatility, _baseline, reference_baseline = self._volatility_value(
            context,
            prefix=prefix,
            source=source,
            candle_granularity=candle_granularity,
            atr_period=atr_period,
            baseline_period=baseline_period,
            candle_ema_period=candle_ema_period,
        )
        if volatility is None or volatility <= 0:
            return False
        if volatility > max_pips:
            return True
        return (
            reference_baseline is not None
            and reference_baseline > 0
            and volatility > reference_baseline * max_multiplier
        )

    def _volatility_value(
        self,
        context: SnowballTickContext,
        *,
        prefix: str,
        source: str,
        candle_granularity: str,
        atr_period: int,
        baseline_period: int,
        candle_ema_period: int,
    ) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
        completed_candle = _update_candle_state(
            context,
            prefix=prefix,
            granularity=candle_granularity,
        )
        if source == "candle_ema":
            current_key = f"{prefix}_candle_ema_pips"
            period = candle_ema_period
            sample_pips = _candle_close_change_pips(completed_candle, context.strategy.pip_size)
        else:
            current_key = f"{prefix}_atr_pips"
            period = atr_period
            sample_pips = _candle_true_range_pips(completed_candle, context.strategy.pip_size)
        baseline_key = f"{prefix}_baseline_pips"

        current = _decimal_metric(context.snowball_state.metrics, current_key)
        baseline = _decimal_metric(context.snowball_state.metrics, baseline_key)
        reference_baseline = baseline
        if sample_pips is not None:
            current = _ema_next(current=current, price=sample_pips, period=period)
            baseline = _ema_next(current=baseline, price=current, period=baseline_period)
            context.set_metric(current_key, current)
            context.set_metric(baseline_key, baseline)
        context.set_metric(f"{prefix}_source", source)
        context.set_metric(f"{prefix}_candle_granularity", candle_granularity)
        context.set_metric(f"{prefix}_current_pips", current or Decimal("0"))
        context.set_metric(f"{prefix}_baseline_current_pips", baseline or Decimal("0"))
        return current, baseline, reference_baseline


class SnowballProtectionPhase:
    """Apply emergency and shrink protection."""

    def __init__(self, *, serializer: SnowballTickStateSerializer | None = None) -> None:
        self.serializer = serializer or SnowballTickStateSerializer()

    def run(self, context: SnowballTickContext) -> SnowballTickPhaseOutcome:
        """Run the protection ladder for the current tick."""
        emergency = SNOWBALL_PROTECTION.handle_emergency(
            strategy=context.strategy,
            ss=context.snowball_state,
            tick=context.tick,
            ratio=context.ratio,
        )
        if emergency is not None:
            emergency_events, stop_reason = emergency
            return SnowballTickPhaseOutcome(
                result=self.serializer.result(
                    context,
                    events=emergency_events,
                    should_stop=True,
                    stop_reason=stop_reason,
                    is_error=True,
                )
            )

        shrink_result = self._handle_shrink(context)
        if shrink_result.completed:
            return shrink_result

        if context.snowball_state.protection_level != ProtectionLevel.NORMAL:
            context.snowball_state.protection_level = ProtectionLevel.NORMAL
        return NOOP_PHASE_OUTCOME

    def _handle_shrink(self, context: SnowballTickContext) -> SnowballTickPhaseOutcome:
        shrink_events = SNOWBALL_PROTECTION.handle_shrink(
            strategy=context.strategy,
            close_entry=context.strategy._close_entry,
            state=context.state,
            ss=context.snowball_state,
            tick=context.tick,
            ratio=context.ratio,
        )
        if shrink_events is None:
            return NOOP_PHASE_OUTCOME

        context.events.extend(shrink_events.events)
        if shrink_events.close_order_violation:
            context.strategy._close_order_violation = shrink_events.close_order_violation
            return SnowballTickPhaseOutcome(
                result=self.serializer.result(
                    context,
                    should_stop=True,
                    stop_reason=(f"Close order violation: {shrink_events.close_order_violation}"),
                    is_error=True,
                )
            )
        return SnowballTickPhaseOutcome(result=self.serializer.result(context))


class SnowballInitialisationPhase:
    """Create first long and optional short cycles."""

    def __init__(self, *, serializer: SnowballTickStateSerializer | None = None) -> None:
        self.serializer = serializer or SnowballTickStateSerializer()

    def run(self, context: SnowballTickContext) -> SnowballTickPhaseOutcome:
        """Initialise the strategy once and complete the tick."""
        if context.snowball_state.initialised:
            return NOOP_PHASE_OUTCOME

        if not _can_open_new_position(context):
            return SnowballTickPhaseOutcome(result=self.serializer.result(context))

        init_events, _ = context.strategy._create_cycle(
            context.snowball_state,
            context.tick,
            Direction.LONG,
        )
        context.events.extend(init_events)
        if context.strategy._hedging_enabled and _can_open_new_position(context):
            short_events, _ = context.strategy._create_cycle(
                context.snowball_state,
                context.tick,
                Direction.SHORT,
            )
            context.events.extend(short_events)
        context.snowball_state.initialised = True
        return SnowballTickPhaseOutcome(result=self.serializer.result(context))


class SnowballActiveCyclePhase:
    """Delegate active cycle processing to a cycle processor object."""

    def __init__(
        self,
        *,
        processor: SnowballActiveCycleProcessor | None = None,
        serializer: SnowballTickStateSerializer | None = None,
    ) -> None:
        self.processor = processor or SnowballActiveCycleProcessor()
        self.serializer = serializer or SnowballTickStateSerializer()

    def run(self, context: SnowballTickContext) -> SnowballTickPhaseOutcome:
        """Process existing active cycles."""
        cycle_result = self.processor.process(
            context.strategy,
            context.snowball_state,
            context.tick,
            allow_new_positions=context.allow_new_positions,
            allow_rebuilds=context.allow_rebuilds,
            new_position_limit=context.new_position_limit,
            rebuild_limit_per_tick=context.rebuild_limit_per_tick,
            blocked_counter_add_directions=context.blocked_counter_add_directions,
        )
        context.events.extend(cycle_result.events)
        if not cycle_result.stop_reason:
            return NOOP_PHASE_OUTCOME
        return SnowballTickPhaseOutcome(
            result=self.serializer.result(
                context,
                should_stop=True,
                stop_reason=cycle_result.stop_reason,
                is_error=cycle_result.is_error,
            )
        )


class SnowballReseedPhase:
    """Reseed long or short directions after all active cycle work."""

    def __init__(self, *, reseeder: SnowballCycleReseeder | None = None) -> None:
        self.reseeder = reseeder or SnowballCycleReseeder()

    def run(self, context: SnowballTickContext) -> SnowballTickPhaseOutcome:
        """Create new cycles when configured conditions are met."""
        context.events.extend(
            self.reseeder.reseed(
                context.strategy,
                context.snowball_state,
                context.tick,
                allow_new_positions=context.allow_new_positions,
                new_position_limit=context.new_position_limit,
            )
        )
        return NOOP_PHASE_OUTCOME


class SnowballWarmupEventAccountingPhase:
    """Update warmup counters after tick events have been produced."""

    def __init__(self, *, policy: SnowballWarmupPolicy | None = None) -> None:
        self.policy = policy or SnowballWarmupPolicy()

    def run(self, context: SnowballTickContext) -> SnowballTickPhaseOutcome:
        self.policy.record_events(context.snowball_state, context.events)
        return NOOP_PHASE_OUTCOME


class SnowballFinalInvariantPhase:
    """Validate the post-tick Snowball state before returning."""

    def __init__(self, *, serializer: SnowballTickStateSerializer | None = None) -> None:
        self.serializer = serializer or SnowballTickStateSerializer()

    def run(self, context: SnowballTickContext) -> SnowballTickPhaseOutcome:
        """Persist the state and stop if post-mutation invariants are invalid."""
        self.serializer.persist(context)
        decision = context.strategy.decision_engine.invariant_decision(context.snowball_state)
        if not decision.should_stop:
            return NOOP_PHASE_OUTCOME
        return SnowballTickPhaseOutcome(
            result=StrategyResult(
                state=context.state,
                events=context.events,
                should_stop=True,
                stop_reason=decision.stop_reason,
                is_error=decision.is_error,
            )
        )


class SnowballTickPipeline:
    """Run Snowball tick processing as named, testable phase objects."""

    def __init__(self, *, serializer: SnowballTickStateSerializer | None = None) -> None:
        serializer = serializer or SnowballTickStateSerializer()
        self.serializer = serializer
        self.phases = (
            SnowballInitialInvariantPhase(serializer=serializer),
            SnowballAccountMetricsPhase(),
            SnowballWarmupPhase(),
            SnowballRiskGuardPhase(),
            SnowballProtectionPhase(serializer=serializer),
            SnowballInitialisationPhase(serializer=serializer),
            SnowballActiveCyclePhase(serializer=serializer),
            SnowballReseedPhase(),
            SnowballWarmupEventAccountingPhase(),
            SnowballFinalInvariantPhase(serializer=serializer),
        )

    def run(
        self,
        *,
        strategy: SnowballTickStrategy,
        tick: Tick,
        state: Any,
    ) -> StrategyResult:
        """Process a single tick through the Snowball phase pipeline."""
        strategy._grid_order_violation = None
        strategy._close_order_violation = None
        context = self._context(strategy=strategy, tick=tick, state=state)
        for phase in self.phases:
            outcome = phase.run(context)
            if outcome.result is not None:
                return outcome.result
        return self.serializer.result(context)

    def _context(
        self,
        *,
        strategy: SnowballTickStrategy,
        tick: Tick,
        state: Any,
    ) -> SnowballTickContext:
        state_boundary = SnowballExecutionStateBoundary(state=state)
        snowball_state = state_boundary.load()
        previous_mid = snowball_state.last_mid
        snowball_state.last_bid = tick.bid
        snowball_state.last_ask = tick.ask
        snowball_state.last_mid = tick.mid
        setattr(
            snowball_state,
            "_defer_metric_strings",
            bool(getattr(state, "_defer_snowball_runtime_view_updates", False)),
        )
        return SnowballTickContext(
            strategy=strategy,
            state=state,
            tick=tick,
            state_boundary=state_boundary,
            snowball_state=snowball_state,
            defer_metric_strings=bool(
                getattr(state, "_defer_snowball_runtime_view_updates", False)
            ),
            previous_mid=previous_mid,
        )


def _can_open_new_position(context: SnowballTickContext) -> bool:
    if not context.allow_new_positions:
        return False
    if context.new_position_limit is None:
        return True
    return context.snowball_state.entry_count() < context.new_position_limit


def _decimal_metric(metrics: dict[str, Any], key: str) -> Decimal | None:
    raw = metrics.get(key)
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _int_metric(metrics: dict[str, Any], key: str) -> int | None:
    raw = metrics.get(key)
    if raw in (None, ""):
        return None
    try:
        return int(str(raw))
    except (TypeError, ValueError):
        return None


def _ema_next(*, current: Decimal | None, price: Decimal, period: int) -> Decimal:
    if current is None:
        return price
    alpha = Decimal("2") / Decimal(max(1, period) + 1)
    return current + (price - current) * alpha


def _update_candle_state(
    context: SnowballTickContext,
    *,
    prefix: str,
    granularity: str,
) -> SnowballCompletedCandle | None:
    seconds = CANDLE_GRANULARITY_SECONDS.get(granularity, 60)
    bucket_epoch = _candle_bucket_epoch(context.tick.timestamp, seconds)
    metrics = context.snowball_state.metrics
    bucket_key = f"{prefix}_active_candle_bucket"
    open_key = f"{prefix}_active_candle_open"
    high_key = f"{prefix}_active_candle_high"
    low_key = f"{prefix}_active_candle_low"
    close_key = f"{prefix}_active_candle_close"
    previous_close_key = f"{prefix}_previous_candle_close"

    context.set_metric(f"{prefix}_candle_granularity", granularity)

    active_bucket = _int_metric(metrics, bucket_key)
    active_open = _decimal_metric(metrics, open_key)
    active_high = _decimal_metric(metrics, high_key)
    active_low = _decimal_metric(metrics, low_key)
    active_close = _decimal_metric(metrics, close_key)
    price = context.tick.mid

    if (
        active_bucket is None
        or active_open is None
        or active_high is None
        or active_low is None
        or active_close is None
    ):
        _start_candle(context, prefix=prefix, bucket_epoch=bucket_epoch, price=price)
        return None

    if bucket_epoch == active_bucket:
        context.set_metric(high_key, max(active_high, price))
        context.set_metric(low_key, min(active_low, price))
        context.set_metric(close_key, price)
        return None

    if bucket_epoch < active_bucket:
        return None

    previous_close = _decimal_metric(metrics, previous_close_key)
    completed = SnowballCompletedCandle(
        open=active_open,
        high=active_high,
        low=active_low,
        close=active_close,
        previous_close=previous_close,
    )
    context.set_metric(f"{prefix}_last_candle_open", completed.open)
    context.set_metric(f"{prefix}_last_candle_high", completed.high)
    context.set_metric(f"{prefix}_last_candle_low", completed.low)
    context.set_metric(f"{prefix}_last_candle_close", completed.close)
    context.set_metric(f"{prefix}_last_candle_bucket", active_bucket)
    context.set_metric(previous_close_key, completed.close)
    _start_candle(context, prefix=prefix, bucket_epoch=bucket_epoch, price=price)
    return completed


def _start_candle(
    context: SnowballTickContext,
    *,
    prefix: str,
    bucket_epoch: int,
    price: Decimal,
) -> None:
    context.set_metric(f"{prefix}_active_candle_bucket", bucket_epoch)
    context.set_metric(f"{prefix}_active_candle_open", price)
    context.set_metric(f"{prefix}_active_candle_high", price)
    context.set_metric(f"{prefix}_active_candle_low", price)
    context.set_metric(f"{prefix}_active_candle_close", price)


def _candle_bucket_epoch(timestamp: datetime, seconds: int) -> int:
    ts = timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=UTC)
    epoch = int(ts.astimezone(UTC).timestamp())
    return epoch - (epoch % seconds)


def _candle_true_range_pips(
    candle: SnowballCompletedCandle | None,
    pip_size: Decimal,
) -> Decimal | None:
    if candle is None or pip_size <= 0:
        return None
    high_low = candle.high - candle.low
    if candle.previous_close is None:
        true_range = high_low
    else:
        true_range = max(
            high_low,
            abs(candle.high - candle.previous_close),
            abs(candle.low - candle.previous_close),
        )
    return abs(true_range) / pip_size


def _candle_close_change_pips(
    candle: SnowballCompletedCandle | None,
    pip_size: Decimal,
) -> Decimal | None:
    if candle is None or pip_size <= 0:
        return None
    if candle.previous_close is None:
        return abs(candle.close - candle.open) / pip_size
    return abs(candle.close - candle.previous_close) / pip_size
