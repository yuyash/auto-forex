"""Object-oriented tick pipeline for the Snowball strategy."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
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
    new_position_limit: int | None = None
    rebuild_limit_per_tick: int | None = None
    warmup_decision: SnowballWarmupDecision | None = None
    defer_metric_strings: bool = False

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
        context.new_position_limit = decision.new_position_limit
        context.rebuild_limit_per_tick = decision.rebuild_limit_per_tick
        current_base_units = context.strategy.config.warmup_scaled_base_units(
            context.snowball_state.account_balance,
            ratio_pct=decision.unit_ratio_pct,
        )
        context.set_metric("current_base_units", current_base_units)
        context.set_metric("snowball_current_base_units", current_base_units)
        return NOOP_PHASE_OUTCOME


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
            new_position_limit=context.new_position_limit,
            rebuild_limit_per_tick=context.rebuild_limit_per_tick,
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
        )


def _can_open_new_position(context: SnowballTickContext) -> bool:
    if not context.allow_new_positions:
        return False
    if context.new_position_limit is None:
        return True
    return context.snowball_state.entry_count() < context.new_position_limit
