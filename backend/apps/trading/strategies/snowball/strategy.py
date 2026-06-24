"""Trading engine for Snowball strategy.

Implements a cycle-based hedging strategy:
- Each cycle starts with an initial entry and tracks its own counter entries
- Hedging mode: LONG and SHORT cycles run independently in parallel
- Non-hedging mode: a single LONG cycle
- Multi-level margin protection (shrink → lock → emergency)

Position grid
-------------
All positions (including the cycle's first entry) live in a unified
``PositionGrid``.  The grid is addressed as L(layer)/R(index) where both
are 0-based.  R0 of each layer is the layer-initial position.

Close ordering:
- Normal TP: newest → oldest (back of grid first)
- Shrink protection: oldest → newest (front of grid first)
- Cycle head (whose TP ends the cycle): dynamically the oldest surviving
  position — ``grid.head_entry()``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from logging import Logger, getLogger
from typing import Any, cast

from apps.trading.dataclasses import EventExecutionResult, StrategyResult
from apps.trading.dataclasses.tick import Tick
from apps.trading.enums import Direction, StrategyType
from apps.trading.events import (
    ClosePositionEvent,
    StrategyEvent,
)
from apps.trading.models.state import ExecutionState
from apps.trading.strategies.base import Strategy
from apps.trading.strategies.registry import register_strategy
from apps.trading.strategies.snowball.calculators import SnowballCalculator
from apps.trading.strategies.snowball.calculators import round_to_step
from apps.trading.strategies.snowball.config import SnowballStrategyConfig
from apps.trading.strategies.snowball.counter_flow import (
    CounterPriceService,
    CounterTakeProfitPolicy,
    SnowballCounterAddDescription,
    SnowballCounterAddProcessor,
    SnowballCounterCloseProcessor,
)
from apps.trading.strategies.snowball.decisions import SnowballDecisionEngine
from apps.trading.strategies.snowball.entry_lifecycle import SNOWBALL_ENTRY_LIFECYCLE
from apps.trading.strategies.snowball.events import SNOWBALL_EVENTS
from apps.trading.strategies.snowball.execution_binding import (
    apply_event_execution_result as apply_snowball_execution_result,
)
from apps.trading.strategies.snowball.grid_policy import SNOWBALL_GRID_POLICY
from apps.trading.strategies.snowball.invariants import SnowballInvariantValidator
from apps.trading.strategies.snowball.cycle_state import SnowballCycle, SnowballStrategyState
from apps.trading.strategies.snowball.cycle_lifecycle import (
    CycleLifecycleStrategy,
    SnowballCycleFactory,
    SnowballLayerInitialPlanner,
)
from apps.trading.strategies.snowball.entries import Entry, StopLossClosedEntry
from apps.trading.strategies.snowball.grid_models import Layer, Slot
from apps.trading.strategies.snowball.parameters import SNOWBALL_PARAMETER_SERVICE
from apps.trading.strategies.snowball.pricing import SNOWBALL_PRICING
from apps.trading.strategies.snowball.protection import SNOWBALL_PROTECTION
from apps.trading.strategies.snowball.stop_loss_flow import (
    StopLossAssigner,
    StopLossCloseProcessor,
    StopLossProtectionPolicy,
    StopLossRebuildPricePlanner,
    StopLossRebuildProcessor,
)
from apps.trading.strategies.snowball.tick_phases import (
    SnowballExecutionStateBoundary,
    SnowballTickPipeline,
)

logger: Logger = getLogger(__name__)
__all__ = ["SNOWBALL_PROTECTION", "SnowballStrategy"]


class SnowballResumeParameterCompatibility:
    """Validate Snowball resume compatibility between parameter sets."""

    def validate(
        self,
        *,
        previous_params: dict[str, Any],
        current_params: dict[str, Any],
    ) -> None:
        """Reject resume attempts that shrink the persisted grid."""
        previous_r_max = self._optional_int(previous_params.get("r_max"))
        current_r_max = self._optional_int(current_params.get("r_max"))
        if previous_r_max is None or current_r_max is None:
            return
        if current_r_max < previous_r_max:
            raise ValueError(
                "Cannot resume Snowball after decreasing r_max. "
                "Restart the task to apply a smaller grid."
            )

    def _optional_int(self, value: Any) -> int | None:
        if value is None:
            return None
        return int(value)


@dataclass(frozen=True, slots=True)
class SnowballRegistryFacade:
    """Own Snowball's Strategy registry-facing adapters."""

    parameter_service: Any = SNOWBALL_PARAMETER_SERVICE
    resume_compatibility: SnowballResumeParameterCompatibility = (
        SnowballResumeParameterCompatibility()
    )

    def parse_config(self, strategy_config: Any) -> SnowballStrategyConfig:
        """Parse persisted strategy configuration."""
        return self.parameter_service.parse_config(strategy_config)

    def config_to_parameters(self, config: SnowballStrategyConfig) -> dict[str, Any]:
        """Return persisted parameters for a config."""
        return self.parameter_service.config_to_parameters(config)

    def normalize_parameters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Normalize strategy parameters."""
        return self.parameter_service.normalize_parameters(parameters)

    def default_parameters(self) -> dict[str, Any]:
        """Return strategy defaults."""
        return self.parameter_service.default_parameters()

    def validate_parameters(
        self,
        *,
        parameters: dict[str, Any],
        config_schema: dict[str, Any] | None = None,
    ) -> None:
        """Validate strategy parameters."""
        self.parameter_service.validate_parameters(
            parameters=parameters,
            config_schema=config_schema,
        )

    def reconcile_broker_positions(
        self,
        *,
        state: ExecutionState,
        open_positions: list[Any],
        report: Any,
        strategy_config: Any | None = None,
    ) -> None:
        """Reconcile persisted Snowball state with broker positions."""
        from apps.trading.strategies.snowball.reconciliation import SNOWBALL_RECONCILER

        SNOWBALL_RECONCILER.reconcile(
            state=state,
            open_positions=open_positions,
            report=report,
            strategy_config=strategy_config,
        )

    def build_cycle_grid_state_map(
        self,
        *,
        strategy_state: dict[str, Any] | None,
    ) -> dict[str, dict[str, Any]]:
        """Build cycle grid visualization payloads."""
        from apps.trading.strategies.snowball.visualization import SNOWBALL_VISUALIZATION

        return SNOWBALL_VISUALIZATION.cycle_grid_state_map(strategy_state=strategy_state)

    def build_cycle_status_map(
        self,
        *,
        strategy_state: dict[str, Any] | None,
    ) -> dict[str, str]:
        """Build cycle status visualization payloads."""
        from apps.trading.strategies.snowball.visualization import SNOWBALL_VISUALIZATION

        return SNOWBALL_VISUALIZATION.cycle_status_map(strategy_state=strategy_state)

    def validate_resume_parameter_compatibility(
        self,
        *,
        previous_params: dict[str, Any],
        current_params: dict[str, Any],
    ) -> None:
        """Validate Snowball resume compatibility."""
        self.resume_compatibility.validate(
            previous_params=previous_params,
            current_params=current_params,
        )


SNOWBALL_REGISTRY_FACADE = SnowballRegistryFacade()


@register_strategy(
    id="snowball",
    schema="trading/schemas/snowball.json",
    display_name="Snowball Strategy",
    description=(
        "Cycle-based hedging strategy: rotational profit-taking on initial entries "
        "and averaging-down with step-based partial closes on counter entries."
    ),
)
class SnowballStrategy(Strategy):
    """Main trading engine for Snowball strategy."""

    config: SnowballStrategyConfig

    def __init__(
        self,
        instrument: str,
        pip_size: Decimal,
        config: SnowballStrategyConfig,
    ) -> None:
        super().__init__(instrument, pip_size, config)
        self.calculator = SnowballCalculator(config)
        self._hedging_enabled: bool = True
        self._close_order_violation: str | None = None
        self._grid_order_violation: str | None = None
        self._last_tolerated_grid_order_violation: str | None = None
        self._snowball_adaptive_counter_interval_multiplier = Decimal("1")
        self._snowball_adaptive_trend_interval_multiplier = Decimal("1")
        self.grid_policy = SNOWBALL_GRID_POLICY
        self.decision_engine = SnowballDecisionEngine(
            invariant_validator=SnowballInvariantValidator(config=config),
        )
        self.tick_pipeline = SnowballTickPipeline()
        self.counter_price_service = CounterPriceService()
        self.counter_take_profit_policy = CounterTakeProfitPolicy()
        self.counter_close_processor = SnowballCounterCloseProcessor(
            take_profit_policy=self.counter_take_profit_policy,
        )
        self.counter_add_processor = SnowballCounterAddProcessor(
            price_service=self.counter_price_service,
            grid_policy=self.grid_policy,
        )
        self.cycle_factory = SnowballCycleFactory()
        self.layer_initial_planner = SnowballLayerInitialPlanner()
        self.counter_add_description = SnowballCounterAddDescription()
        self.entry_lifecycle = SNOWBALL_ENTRY_LIFECYCLE
        self.stop_loss_assigner = StopLossAssigner()
        self.stop_loss_protection_policy = StopLossProtectionPolicy()
        self.stop_loss_close_processor = StopLossCloseProcessor(
            protection_policy=self.stop_loss_protection_policy,
        )
        self.stop_loss_rebuild_processor = StopLossRebuildProcessor(
            price_planner=StopLossRebuildPricePlanner(grid_policy=self.grid_policy),
        )
        logger.info(
            "Initialised Snowball engine: instrument=%s, pip_size=%s",
            instrument,
            pip_size,
        )

    def counter_interval_pips(self, step: int) -> Decimal:
        """Return the runtime counter-side interval after adaptive adjustment."""
        base = self.calculator.counter_interval_pips(step)
        multiplier = self._snowball_adaptive_counter_interval_multiplier
        return round_to_step(base * multiplier, self.config.round_step_pips)

    def trend_take_profit_pips(self) -> Decimal:
        """Return the runtime trend-side take-profit distance."""
        multiplier = self._snowball_adaptive_trend_interval_multiplier
        return round_to_step(self.config.m_pips * multiplier, self.config.round_step_pips)

    # ------------------------------------------------------------------
    # Registry interface
    # ------------------------------------------------------------------

    @staticmethod
    def parse_config(strategy_config: Any) -> SnowballStrategyConfig:
        return SNOWBALL_REGISTRY_FACADE.parse_config(strategy_config)

    @staticmethod
    def _config_to_parameters(config: SnowballStrategyConfig) -> dict[str, Any]:
        return SNOWBALL_REGISTRY_FACADE.config_to_parameters(config)

    @classmethod
    def normalize_parameters(cls, parameters: dict[str, Any]) -> dict[str, Any]:
        return SNOWBALL_REGISTRY_FACADE.normalize_parameters(parameters)

    @classmethod
    def default_parameters(cls) -> dict[str, Any]:
        return SNOWBALL_REGISTRY_FACADE.default_parameters()

    @classmethod
    def validate_parameters(
        cls,
        *,
        parameters: dict[str, Any],
        config_schema: dict[str, Any] | None = None,
    ) -> None:
        SNOWBALL_REGISTRY_FACADE.validate_parameters(
            parameters=parameters,
            config_schema=config_schema,
        )

    @property
    def strategy_type(self) -> StrategyType:
        return StrategyType.SNOWBALL

    def on_start(self, *, state: ExecutionState) -> StrategyResult:
        result = super().on_start(state=state)
        self._persist_loaded_strategy_state(state)
        result.state = state
        return result

    def on_resume(self, *, state: ExecutionState) -> StrategyResult:
        result = super().on_resume(state=state)
        self._persist_loaded_strategy_state(state)
        result.state = state
        return result

    @staticmethod
    def _persist_loaded_strategy_state(state: ExecutionState) -> None:
        snowball_state = SnowballStrategyState.from_strategy_state(state.strategy_state)
        SnowballExecutionStateBoundary(state=state).persist(snowball_state)

    @classmethod
    def supports_stateful_broker_reconciliation(cls) -> bool:
        return True

    @classmethod
    def capabilities(cls) -> dict[str, Any]:
        return {
            "runtime": {
                "hedging": True,
            },
            "visualization": {
                "kind": "cycle_grid",
                "cycle_statuses": True,
                "grid": True,
            },
            "events": {
                "close_reason_labels": {
                    "tp": "Take profit",
                    "close_position": "Manual close",
                    "stop_loss": "Stop-loss protection",
                    "shrink": "Shrink protection",
                    "volatility_lock": "Volatility lock protection",
                    "margin_protection": "Margin protection",
                    "counter_tp": "Counter-trend take profit",
                    "layer_initial_tp": "Layer initial take profit",
                },
                "strategy_event_labels": {
                    "snowball_shrink": "Snowball shrink",
                },
            },
            "resume": {
                "stateful_broker_reconciliation": True,
            },
        }

    @classmethod
    def reconcile_broker_positions(
        cls,
        *,
        state: ExecutionState,
        open_positions: list[Any],
        report: Any,
        strategy_config: Any | None = None,
    ) -> None:
        SNOWBALL_REGISTRY_FACADE.reconcile_broker_positions(
            state=state,
            open_positions=open_positions,
            report=report,
            strategy_config=strategy_config,
        )

    @classmethod
    def build_cycle_grid_state_map(
        cls,
        *,
        strategy_state: dict[str, Any] | None,
    ) -> dict[str, dict[str, Any]]:
        return SNOWBALL_REGISTRY_FACADE.build_cycle_grid_state_map(strategy_state=strategy_state)

    @classmethod
    def build_cycle_status_map(
        cls,
        *,
        strategy_state: dict[str, Any] | None,
    ) -> dict[str, str]:
        return SNOWBALL_REGISTRY_FACADE.build_cycle_status_map(strategy_state=strategy_state)

    @classmethod
    def validate_resume_parameter_compatibility(
        cls,
        *,
        previous_params: dict[str, Any],
        current_params: dict[str, Any],
    ) -> None:
        SNOWBALL_REGISTRY_FACADE.validate_resume_parameter_compatibility(
            previous_params=previous_params,
            current_params=current_params,
        )

    def configure_runtime(self, *, account_currency: str, hedging_enabled: bool) -> None:
        super().configure_runtime(
            account_currency=account_currency,
            hedging_enabled=hedging_enabled,
        )
        self._hedging_enabled = hedging_enabled

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _close_entry(
        self,
        tick: Tick,
        entry: Entry,
        *,
        description: str = "",
        close_reason: str = "",
        actual_tp_pips: Decimal | None = None,
        validation_status: str = "",
        margin_ratio: Decimal | None = None,
        cycle: SnowballCycle | None = None,
    ) -> ClosePositionEvent:
        return self.entry_lifecycle.close(
            self,
            logger,
            tick,
            entry,
            description=description,
            close_reason=close_reason,
            actual_tp_pips=actual_tp_pips,
            validation_status=validation_status,
            margin_ratio=margin_ratio,
            cycle=cycle,
        )

    # ------------------------------------------------------------------
    # Cycle lifecycle
    # ------------------------------------------------------------------

    def _create_cycle(
        self,
        ss: SnowballStrategyState,
        tick: Tick,
        direction: Direction,
    ) -> tuple[list[StrategyEvent], SnowballCycle]:
        """Create a new cycle with an initial entry at L0/R0."""
        return self.cycle_factory.create(
            strategy=cast(CycleLifecycleStrategy, self),
            state=ss,
            tick=tick,
            direction=direction,
        )

    def _effective_base_units(self, ss: SnowballStrategyState) -> int:
        """Return the current base units after balance and warmup scaling."""
        try:
            ratio = Decimal(str(ss.metrics.get("warmup_unit_ratio_pct", "100") or "100"))
        except Exception:  # noqa: BLE001
            ratio = Decimal("100")
        return self.config.warmup_scaled_base_units(ss.account_balance, ratio_pct=ratio)

    def _tp_reentry_block_reason(
        self,
        ss: SnowballStrategyState,
        cycle: SnowballCycle,
    ) -> str:
        """Return why TP re-entry must not create a replacement cycle."""
        if cycle.grid.has_pending_rebuilds():
            return "pending rebuilds remain"
        if not cycle.grid.is_empty():
            return "live entries remain"
        has_same_direction_cycle = any(
            other.cycle_id != cycle.cycle_id
            and other.direction == cycle.direction
            and not other.completed
            for other in ss.iter_active_cycles()
        )
        if has_same_direction_cycle:
            return "other active/pending cycle(s) exist"
        return ""

    def _close_and_reenter(
        self,
        ss: SnowballStrategyState,
        tick: Tick,
        cycle: SnowballCycle,
        *,
        allow_reentry: bool = True,
        entry: Entry | None = None,
    ) -> list[StrategyEvent]:
        """Close the cycle head (TP hit) and create a new cycle.

        This is only called when the dynamic head's active close target is
        reached and the head is a live entry.  Rebuilt head slots can carry a
        close target beyond the
        initial ``entry ± m_pips`` target.  The cycle transitions to COMPLETED
        via the unified status check in on_tick.
        """
        entry = entry or cycle.initial_entry
        if entry is None:
            return []

        slot_ref = cycle.grid.slot_for_entry(entry.entry_id)
        if slot_ref is None:
            return []
        layer, slot = slot_ref
        remaining_entries = [
            other for other in cycle.grid.iter_entries() if other.entry_id != entry.entry_id
        ]
        if remaining_entries:
            logger.warning(
                "Cycle head close blocked because other live entries remain: "
                "cycle_id=%d, head=L%d/R%d, remaining=[%s]",
                cycle.cycle_id,
                entry.layer_number,
                entry.retracement_count,
                ", ".join(
                    f"L{other.layer_number}/R{other.retracement_count}"
                    for other in remaining_entries
                ),
            )
            return []

        direction = cycle.direction
        exit_price = entry.exit_price(tick)
        pips_gained = abs(exit_price - entry.entry_price) / self.pip_size

        events: list[StrategyEvent] = []
        logger.info(
            "TP hit (%s): entry=%s, exit=%s, +%.1f pips, units=%s",
            direction.value.upper(),
            entry.entry_price,
            exit_price,
            pips_gained,
            entry.units,
        )
        events.append(
            self._close_entry(
                tick,
                entry,
                description=(
                    f"TP ({direction.value.upper()}) | entry={entry.entry_price:.3f}, "
                    f"exit={exit_price:.3f}, +{pips_gained:.1f} pips"
                ),
                close_reason="tp",
                actual_tp_pips=pips_gained,
                validation_status="pass",
                cycle=cycle,
            )
        )

        # R0/layer-initial heads still seal, but counter heads must follow the
        # layer refill policy so pending-rebuild cycles can reuse allowed slots.
        layer.close_slot(slot.index)
        ss.invalidate_entry_cache()

        # If closing this head emptied a non-L1 layer (no live entries and no
        # pending rebuilds left), remove it so it does not linger as a "ghost"
        # top layer.  A ghost current layer breaks head resolution for fully
        # pending cycles: its R0 is sealed (not pending), so the cycle would
        # freeze instead of resuming counter adds in the layer below.  L1 is
        # always preserved.
        if layer.layer_number > 1 and not layer.has_present_entries():
            cycle.grid.layers.remove(layer)
            ss.invalidate_entry_cache()

        # Do NOT clear pending rebuilds here.  If other slots have
        # pending rebuilds, the cycle status update in on_tick will
        # transition the cycle to PENDING (not COMPLETED).  Those
        # rebuilds will eventually restore positions and close them
        # normally, at which point the cycle will finally complete.

        # Only create a replacement when this close genuinely exhausted the
        # direction.  Pending-rebuild cycles are still live recovery state:
        # ``reseed_on_all_pending`` owns whether they may spawn a fresh cycle.
        if not allow_reentry:
            logger.info(
                "TP (%s) cycle %d — skipping re-entry while new opens are blocked",
                direction.value.upper(),
                cycle.cycle_id,
            )
            return events

        block_reason = self._tp_reentry_block_reason(ss, cycle)
        if block_reason:
            logger.info(
                "TP (%s) cycle %d — skipping re-entry, %s",
                direction.value.upper(),
                cycle.cycle_id,
                block_reason,
            )
            return events

        new_events, _new_cycle = self._create_cycle(ss, tick, direction)
        logger.info(
            "Re-entry (%s) after TP: new cycle_id=%d",
            direction.value.upper(),
            _new_cycle.cycle_id,
        )
        events.extend(new_events)

        return events

    def _fail_close_order_violation(
        self,
        ss: SnowballStrategyState,
        tick: Tick,
        cycle: SnowballCycle,
    ) -> list[StrategyEvent]:
        """Build a stop event when a close-order violation is detected."""
        open_entries = []
        for e in cycle.grid.iter_entries():
            open_entries.append(
                f"L{e.layer_number}/R{e.retracement_count} "
                f"entry={e.entry_price:.3f} tp={e.close_price:.3f}"
            )
        head = cycle.initial_entry
        head_price = f"{head.entry_price:.3f}" if head else "None"
        head_tp = f"{head.close_price:.3f}" if head else "None"
        detail = (
            f"cycle_id={cycle.cycle_id}, direction={cycle.direction.value}, "
            f"head_entry={head_price}, head_tp={head_tp}, "
            f"open_entries=[{', '.join(open_entries)}], "
            f"tick_bid={tick.bid}, tick_ask={tick.ask}"
        )
        logger.error("Close order violation detail: %s", detail)
        self._close_order_violation = detail
        return []

    def _validate_grid_ordering(self, cycle: SnowballCycle) -> None:
        """Ensure present slots preserve monotonic entry/TP ordering."""
        manual_rebuild_take_profit_active = (
            self.config.stop_loss_enabled
            and self.config.rebuild_enabled
            and self.config.rebuild_take_profit_mode == "manual"
        )
        if not manual_rebuild_take_profit_active:
            repaired = self._repair_layer_initial_take_profit_bounds(cycle)
            if repaired:
                logger.info(
                    "Repaired %d layer-initial take-profit bound(s) before grid validation",
                    repaired,
                )
        self._grid_order_violation = self.grid_policy.validate_ordering(
            cycle,
            check_take_profit=not manual_rebuild_take_profit_active,
        )
        if not self._grid_order_violation:
            self._last_tolerated_grid_order_violation = None
            return

        if self._grid_order_violation == self._last_tolerated_grid_order_violation:
            logger.debug(
                "Grid ordering violation still present: %s",
                self._grid_order_violation,
            )
            return

        self._last_tolerated_grid_order_violation = self._grid_order_violation
        logger.info(
            "Grid ordering violation detected; pausing counter adds until ordering recovers: %s",
            self._grid_order_violation,
        )

    def _repair_layer_initial_take_profit_bounds(self, cycle: SnowballCycle) -> int:
        """Clamp legacy layer-initial TPs that crossed their preceding hard bound."""
        repaired = 0
        for layer in cycle.grid.layers:
            if layer.layer_number <= 1:
                continue
            slot = layer.slot_at(0)
            if slot is None:
                continue
            target = slot.entry if slot.entry is not None else slot.pending_rebuild
            if target is None or target.role != "layer_initial":
                continue
            hard_bound, _soft_bound = self.grid_policy.tp_bounds(cycle, layer, slot.index)
            if hard_bound is None:
                continue

            current = Decimal(str(target.close_price))
            entry_price = Decimal(str(target.entry_price))
            if cycle.direction == Direction.LONG:
                if current <= hard_bound or hard_bound <= entry_price:
                    continue
            elif current >= hard_bound or hard_bound >= entry_price:
                continue

            target.close_price = hard_bound
            repaired += 1
        return repaired

    # ------------------------------------------------------------------
    # Per-cycle tick processing
    # ------------------------------------------------------------------

    def _entry_side_price(self, direction: Direction, tick: Tick) -> Decimal:
        """Return the executable entry-side price for a direction."""
        return self.counter_price_service.entry_side_price(direction, tick)

    def _exit_side_price(self, direction: Direction, tick: Tick) -> Decimal:
        """Return the executable exit-side price for a direction."""
        return self.counter_price_service.exit_side_price(direction, tick)

    def _process_cycle_tp(
        self,
        ss: SnowballStrategyState,
        tick: Tick,
        cycle: SnowballCycle,
        *,
        allow_reentry: bool = True,
    ) -> list[StrategyEvent]:
        """Check if the cycle head's TP target is hit.

        The cycle TP follows the dynamic head's current close target. For ordinary entries
        this is ``R0.entry_price ± m_pips * pip_size``; for rebuilt entries it
        may be pushed farther out to recover prior stop-losses.

        The head position can only close when no other entries remain open
        in the grid.  If counter entries are still present, their TPs
        should be reached first (they are closer to the current price).
        """
        if cycle.completed:
            return []

        direction = cycle.direction
        # Determine the dynamic head and its close target.  Shrink and
        # out-of-order closes can move the cycle head away from L1/R0.
        head_entry = cycle.initial_entry
        if head_entry is None:
            return []
        if not head_entry.can_close_on_tick(tick):
            return []

        head_close_price = head_entry.close_price
        if head_close_price <= 0:
            tp_pips = self.trend_take_profit_pips()
            if direction == Direction.LONG:
                head_close_price = head_entry.entry_price + tp_pips * self.pip_size
            else:
                head_close_price = head_entry.entry_price - tp_pips * self.pip_size

        # Check if cycle TP is hit based on the head's active close target.
        hit = False
        if direction == Direction.LONG and tick.bid >= head_close_price:
            hit = True
        elif direction == Direction.SHORT and tick.ask <= head_close_price:
            hit = True

        if not hit:
            return []

        if not cycle.grid.has_counter_entries():
            return self._close_and_reenter(
                ss,
                tick,
                cycle,
                allow_reentry=allow_reentry,
                entry=head_entry,
            )

        # Counter entries are still open while the head TP is hit.
        # Check whether every remaining counter's TP is also reached
        # on this tick.  If so, flush them all and proceed normally.
        all_counters_tp_hit = True
        for e in cycle.grid.iter_entries():
            if e.entry_id == head_entry.entry_id:
                continue
            if not self._entry_take_profit_hit(e, tick):
                all_counters_tp_hit = False
                break

        if not all_counters_tp_hit:
            logger.warning(
                "Head TP reached while some counter TPs are not yet hit — "
                "waiting instead of force-closing remaining entries. "
                "cycle_id=%d, direction=%s.",
                cycle.cycle_id,
                direction.value,
            )
            return []

        # Flush all remaining counter entries only after their own TP targets
        # are also executable.  This preserves planned_exit_price as a hard
        # accounting boundary; otherwise a recovered R0 could close a cycle
        # while counter slots are still short of their planned exits.
        events: list[StrategyEvent] = []
        for layer_iter in reversed(cycle.grid.layers):
            for slot in reversed(layer_iter.slots):
                counter = slot.entry
                if counter is None or counter.entry_id == head_entry.entry_id:
                    continue
                exit_price = counter.exit_price(tick)
                pips_gained = abs(exit_price - counter.entry_price) / self.pip_size
                label = "Counter TP flush"
                logger.info(
                    "%s (%s): L%s/R%s, %.1f pips",
                    label,
                    counter.direction.value.upper(),
                    counter.layer_number,
                    counter.retracement_count,
                    pips_gained,
                )
                layer_iter.close_slot(slot.index)
                ss.invalidate_entry_cache()
                cycle.counter_close_count += 1
                events.append(
                    self._close_entry(
                        tick,
                        counter,
                        description=(
                            f"{label} ({counter.direction.value.upper()}) | "
                            f"L{counter.layer_number}/R{counter.retracement_count}, "
                            f"entry={counter.entry_price:.3f}, "
                            f"exit={exit_price:.3f}, +{pips_gained:.1f} pips"
                        ),
                        close_reason="counter_tp",
                        actual_tp_pips=pips_gained,
                        validation_status="pass",
                        cycle=cycle,
                    )
                )
            # Remove empty non-L1 layers
            if layer_iter.layer_number > 1 and not layer_iter.has_present_entries():
                cycle.grid.layers.remove(layer_iter)

        events.extend(
            self._close_and_reenter(
                ss,
                tick,
                cycle,
                allow_reentry=allow_reentry,
                entry=head_entry,
            )
        )
        return events

    def _process_cycle_counter_closes(
        self,
        ss: SnowballStrategyState,
        tick: Tick,
        cycle: SnowballCycle,
    ) -> list[StrategyEvent]:
        return self.counter_close_processor.process(
            self,
            ss,
            tick,
            cycle,
            close_entry=self._close_entry,
        )

    def _entry_take_profit_hit(self, entry: Entry, tick: Tick) -> bool:
        return self.counter_take_profit_policy.hit(entry, tick)

    def _process_cycle_counter_adds(
        self,
        ss: SnowballStrategyState,
        tick: Tick,
        cycle: SnowballCycle,
        *,
        max_retracement_count: int | None = None,
    ) -> list[StrategyEvent]:
        return self.counter_add_processor.process(
            self,
            ss,
            tick,
            cycle,
            open_layer_initial=self._open_layer_initial,
            assign_configured_stop_loss=self._assign_configured_stop_loss,
            max_retracement_count=max_retracement_count,
        )

    def _format_counter_add_description(
        self,
        *,
        direction: Direction,
        layer: Layer,
        slot: Slot,
        units: int,
        adverse: Decimal,
        close_price: Decimal,
        stop_loss_price: Decimal | None,
    ) -> str:
        return self.counter_add_description.format(
            direction=direction,
            layer=layer,
            slot=slot,
            units=units,
            adverse=adverse,
            close_price=close_price,
            stop_loss_price=stop_loss_price,
        )

    def _open_layer_initial(
        self,
        ss: SnowballStrategyState,
        tick: Tick,
        cycle: SnowballCycle,
    ) -> list[StrategyEvent]:
        """Open a layer-initial entry (R0) for a new layer."""
        cfg = self.config
        head = cycle.initial_entry
        head_entry_price, head_entry_id = cycle.effective_head()
        if head_entry_price is None:
            return []

        # Gate: head (or its SL snapshot) must be losing
        if head is not None:
            if (
                head.unrealised_loss_pips(
                    self._exit_side_price(head.direction, tick),
                    self.pip_size,
                )
                <= 0
            ):
                return []
        else:
            if cycle.direction == Direction.LONG:
                if (
                    head_entry_price - self._exit_side_price(cycle.direction, tick)
                ) / self.pip_size <= 0:
                    return []
            else:
                if (
                    self._exit_side_price(cycle.direction, tick) - head_entry_price
                ) / self.pip_size <= 0:
                    return []

        direction = cycle.direction
        prev_layer = cycle.current_layer
        assert prev_layer is not None
        new_layer_number = prev_layer.layer_number + 1
        new_base_units = int(
            Decimal(str(self._effective_base_units(ss))) * cfg.post_r_max_base_factor
        )
        layer = Layer.create(
            new_layer_number,
            cfg.r_max,
            new_base_units,
            cfg.effective_refill_up_to,
        )
        cycle.add_layer(layer)
        ss.invalidate_entry_cache()

        # The new layer's R0 is placed at the position where the previous
        # layer's *next* retracement slot would have been: anchor = highest
        # present slot's entry price, offset by the next-slot interval in
        # the adverse direction.  This snaps L_new/R0 onto the grid rather
        # than accepting whatever market price happened to trigger the
        # layer-interval gate — so the resulting grid stays monotonic and
        # interval-consistent across layers.  If the live market has moved
        # further adverse than the anchor the broker will fill past it and
        # ``sync_entry_fill_price`` will shift entry/SL/TP by the delta.
        market_price = tick.ask if direction == Direction.LONG else tick.bid
        price = self._layer_initial_anchor_price(
            prev_layer=prev_layer,
            direction=direction,
            market_price=market_price,
        )

        # Guard: the new layer's entry must not violate the monotonic
        # grid ordering.  For LONG grids, entries are descending so the
        # new entry must be ≤ every occupied entry in earlier layers.
        # This can fail when intermediate layers were emptied by shrink
        # or stop-loss and the market has since moved past the stuck
        # entries in even earlier layers.  In that case we skip the
        # layer creation — the strategy will retry on a later tick.
        for earlier_layer in cycle.grid.layers:
            if earlier_layer.layer_number >= layer.layer_number:
                continue
            for s in earlier_layer.slots:
                if s.entry is None:
                    continue
                if direction == Direction.LONG and price > s.entry.entry_price:
                    logger.info(
                        "Skipping layer initial L%d/R0: entry %.5f would exceed "
                        "L%d/R%d entry %.5f (grid ordering)",
                        layer.layer_number,
                        price,
                        s.entry.layer_number,
                        s.entry.retracement_count,
                        s.entry.entry_price,
                    )
                    cycle.grid.layers.remove(layer)
                    return []
                if direction == Direction.SHORT and price < s.entry.entry_price:
                    logger.info(
                        "Skipping layer initial L%d/R0: entry %.5f would be below "
                        "L%d/R%d entry %.5f (grid ordering)",
                        layer.layer_number,
                        price,
                        s.entry.layer_number,
                        s.entry.retracement_count,
                        s.entry.entry_price,
                    )
                    cycle.grid.layers.remove(layer)
                    return []

        close_plan = SNOWBALL_PRICING.layer_initial_close_price(
            new_price=price,
            prev_layer=prev_layer,
            direction=direction,
            pip_size=self.pip_size,
            m_pips=self.trend_take_profit_pips(),
        )
        close_price = close_plan.close_price
        formula = close_plan.formula

        effective_close_price = close_price + (market_price - price)
        if close_plan.bound is not None:
            effective_close_price = close_plan.bound.apply(effective_close_price)
        if not self._planned_exit_on_profit_side(
            direction=direction,
            entry_price=market_price,
            planned_exit_price=effective_close_price,
        ):
            logger.info(
                "Skipping layer initial L%d/R0: planned exit %.5f would not remain "
                "on the profit side after fill price %.5f",
                layer.layer_number,
                effective_close_price,
                market_price,
            )
            cycle.grid.layers.remove(layer)
            return []

        layer_entry = Entry.open(
            state=ss,
            tick=tick,
            direction=direction,
            units=cfg.trend_lot_size * layer.base_units,
            step=1,
            close_price=Decimal("0"),
            role="layer_initial",
            layer_number=layer.layer_number,
            retracement_count=0,
            root_entry_id=head_entry_id,
            parent_entry_id=head_entry_id,
        )
        # ``Entry.open`` seeds entry_price from the live tick; override with
        # the grid-snapped anchor so the planned price matches where the
        # layer-interval gate said it should sit.  If the broker fills at
        # a different price, ``sync_entry_fill_price`` will shift entry/SL/
        # TP together, then reapply the cross-layer TP boundary when one
        # was needed to preserve grid ordering.
        layer_entry.entry_price = price

        layer_entry.close_price = close_price
        tp_pips = abs(close_price - layer_entry.entry_price) / self.pip_size
        layer_entry.expected_tp_pips = tp_pips
        layer_entry.validation_status = "pass"

        highest = prev_layer.highest_present_slot()
        if highest is not None:
            highest_price = (
                highest.entry.entry_price
                if highest.entry is not None
                else highest.pending_rebuild.entry_price
                if highest.pending_rebuild is not None
                else None
            )
            if highest_price is not None:
                layer_entry.actual_interval_pips = abs(highest_price - price) / self.pip_size

        # Compute stop-loss for this entry at creation time
        if cfg.stop_loss_enabled:
            self._assign_configured_stop_loss(layer_entry, 1)

        logger.info(
            "Layer initial L%d/R0 in cycle %d, TP=%.3f",
            layer.layer_number,
            cycle.cycle_id,
            close_price,
        )

        evt = SNOWBALL_EVENTS.entry_open_event(
            layer_entry,
            timestamp=tick.timestamp,
            execution_price=market_price,
            planned_exit_price_formula=formula,
            planned_exit_price_bound=close_plan.bound.price
            if close_plan.bound is not None
            else None,
            planned_exit_price_bound_mode=close_plan.bound.mode
            if close_plan.bound is not None
            else "",
            description=(
                f"Layer initial entry ({direction.value.upper()}) | "
                f"L{layer.layer_number}/R0, units={layer_entry.units}, TP={close_price:.3f}"
                + (
                    f", SL={layer_entry.stop_loss_price:.3f}"
                    if layer_entry.stop_loss_price is not None
                    else ""
                )
            ),
        )
        # Place in R0 of the new layer
        slot0 = layer.slot_at(0)
        assert slot0 is not None  # noqa: S101
        slot0.fill(layer_entry)
        ss.invalidate_entry_cache()

        return [evt]

    def _layer_initial_anchor_price(
        self,
        *,
        prev_layer: Layer,
        direction: Direction,
        market_price: Decimal,
    ) -> Decimal:
        """Return the planned entry price for the next layer's R0.

        The anchor is the previous layer's highest present slot (live
        entry or pending rebuild) offset by ``counter_interval_pips`` for
        the would-be next retracement.  This lines up the new layer's R0
        with the position where the prev layer's next R slot would have
        opened, so grids stay monotonic and interval-consistent across
        layers.

        If the previous layer has no present slot (no entry and no pending
        rebuild), fall back to the current market price — there is no
        anchor to snap to.
        """
        # Interval that the gate uses for "the next slot past ``highest``":
        # ``counter_interval_pips(k)`` is 1-based, k == highest.index + 1
        # advances into the next retracement slot.
        highest = prev_layer.highest_present_slot()
        if highest is None:
            return market_price
        interval = self.counter_interval_pips(highest.index + 1)
        return self.layer_initial_planner.anchor_price(
            prev_layer=prev_layer,
            direction=direction,
            market_price=market_price,
            interval_pips=interval,
            pip_size=self.pip_size,
        )

    @staticmethod
    def _planned_exit_on_profit_side(
        *,
        direction: Direction,
        entry_price: Decimal,
        planned_exit_price: Decimal,
    ) -> bool:
        if direction == Direction.LONG:
            return planned_exit_price > entry_price
        return planned_exit_price < entry_price

    # ------------------------------------------------------------------
    # Stop-loss protection
    # ------------------------------------------------------------------

    def _assign_stop_loss(
        self,
        entry: Entry,
        sl_pips: Decimal,
    ) -> None:
        self.stop_loss_assigner.assign(self, entry, sl_pips)

    def _assign_auto_stop_loss(
        self,
        entry: Entry,
        next_interval_pips: Decimal,
    ) -> None:
        self.stop_loss_assigner.assign_auto(self, entry, next_interval_pips)

    def _assign_configured_stop_loss(
        self,
        entry: Entry,
        slot_number: int,
    ) -> None:
        self.stop_loss_assigner.assign_configured(self, entry, slot_number)

    def _assign_rebuild_stop_loss(
        self,
        entry: Entry,
        pending: StopLossClosedEntry,
    ) -> None:
        self.stop_loss_assigner.assign_rebuild(self, entry, pending)

    def _is_stop_loss_temporarily_protected(self, layer: Layer, entry: Entry) -> bool:
        return self.stop_loss_protection_policy.temporarily_protected(
            self.config,
            layer,
            entry,
        )

    def _process_stop_loss_closes(
        self,
        ss: SnowballStrategyState,
        tick: Tick,
        cycle: SnowballCycle,
    ) -> list[StrategyEvent]:
        return self.stop_loss_close_processor.process(
            self,
            ss,
            tick,
            cycle,
            close_entry=self._close_entry,
        )

    def _process_stop_loss_rebuilds(
        self,
        ss: SnowballStrategyState,
        tick: Tick,
        cycle: SnowballCycle,
        *,
        max_rebuilds: int | None = None,
        max_retracement_count: int | None = None,
    ) -> list[StrategyEvent]:
        return self.stop_loss_rebuild_processor.process(
            self,
            ss,
            tick,
            cycle,
            max_rebuilds=max_rebuilds,
            max_retracement_count=max_retracement_count,
        )

    # ------------------------------------------------------------------
    # Core tick processing
    # ------------------------------------------------------------------

    def on_tick(self, *, tick: Tick, state: ExecutionState) -> StrategyResult:
        """Process a single tick."""
        return self.tick_pipeline.run(strategy=self, tick=tick, state=state)

    # ------------------------------------------------------------------
    # State serialisation
    # ------------------------------------------------------------------

    def apply_event_execution_result(
        self,
        *,
        state: ExecutionState,
        execution_result: EventExecutionResult,
    ) -> None:
        apply_snowball_execution_result(
            self,
            state=state,
            execution_result=execution_result,
        )
