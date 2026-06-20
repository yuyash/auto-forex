"""Per-cycle orchestration for the Snowball strategy."""

from __future__ import annotations

from dataclasses import dataclass, field
from logging import Logger, getLogger
from typing import Protocol

from apps.trading.dataclasses.tick import Tick
from apps.trading.enums import Direction
from apps.trading.events import StrategyEvent
from apps.trading.strategies.snowball.config import SnowballStrategyConfig
from apps.trading.strategies.snowball.decision_trace import (
    DisabledSnowballDecisionTrace,
    SnowballDecisionTrace,
    SnowballDecisionTraceRecorder,
)
from apps.trading.strategies.snowball.enums import CycleStatus
from apps.trading.strategies.snowball.cycle_state import SnowballCycle, SnowballStrategyState

logger = getLogger(__name__)


class CycleOrchestratorStrategy(Protocol):
    config: SnowballStrategyConfig
    _close_order_violation: str | None
    _grid_order_violation: str | None
    _hedging_enabled: bool

    def _process_stop_loss_rebuilds(
        self,
        ss: SnowballStrategyState,
        tick: Tick,
        cycle: SnowballCycle,
        *,
        max_rebuilds: int | None = None,
        max_retracement_count: int | None = None,
    ) -> list[StrategyEvent]: ...

    def _process_cycle_counter_closes(
        self,
        ss: SnowballStrategyState,
        tick: Tick,
        cycle: SnowballCycle,
    ) -> list[StrategyEvent]: ...

    def _process_cycle_tp(
        self,
        ss: SnowballStrategyState,
        tick: Tick,
        cycle: SnowballCycle,
        *,
        allow_reentry: bool,
    ) -> list[StrategyEvent]: ...

    def _process_stop_loss_closes(
        self,
        ss: SnowballStrategyState,
        tick: Tick,
        cycle: SnowballCycle,
    ) -> list[StrategyEvent]: ...

    def _process_cycle_counter_adds(
        self,
        ss: SnowballStrategyState,
        tick: Tick,
        cycle: SnowballCycle,
        *,
        max_retracement_count: int | None = None,
    ) -> list[StrategyEvent]: ...

    def _validate_grid_ordering(self, cycle: SnowballCycle) -> None: ...

    def _create_cycle(
        self,
        ss: SnowballStrategyState,
        tick: Tick,
        direction: Direction,
    ) -> tuple[list[StrategyEvent], SnowballCycle]: ...


@dataclass
class CycleProcessingResult:
    events: list[StrategyEvent] = field(default_factory=list)
    stop_reason: str | None = None
    is_error: bool = False
    rebuild_count: int = 0


class SnowballCycleStatusRefresher:
    """Update a cycle status after grid mutations have settled."""

    def __init__(self, *, logger_: Logger | None = None) -> None:
        self.logger = logger_ or logger

    def refresh(self, cycle: SnowballCycle) -> None:
        """Move a cycle between active, pending, and completed states."""
        if not cycle.is_active and not cycle.is_pending:
            return

        has_open = not cycle.grid.is_empty()
        has_pending = cycle.grid.has_pending_rebuilds()
        if has_open:
            if cycle.is_pending:
                cycle.status = CycleStatus.ACTIVE
        elif has_pending:
            if cycle.is_active:
                cycle.status = CycleStatus.PENDING
        else:
            cycle.status = CycleStatus.COMPLETED
            if cycle.realized_pnl < 0:
                self.logger.warning(
                    "Cycle %d (%s) completed with negative realised P/L: %s",
                    cycle.cycle_id,
                    cycle.direction.value.upper(),
                    cycle.realized_pnl,
                )


class SnowballActiveCycleProcessor:
    """Process live Snowball cycles in explicit close, rebuild, add phases."""

    def __init__(
        self,
        *,
        status_refresher: SnowballCycleStatusRefresher | None = None,
        decision_trace_recorder: SnowballDecisionTraceRecorder | None = None,
        logger_: Logger | None = None,
    ) -> None:
        self.status_refresher = status_refresher or SnowballCycleStatusRefresher()
        self.decision_trace_recorder = decision_trace_recorder or SnowballDecisionTraceRecorder()
        self.logger = logger_ or logger

    def process(
        self,
        strategy: CycleOrchestratorStrategy,
        ss: SnowballStrategyState,
        tick: Tick,
        *,
        allow_new_positions: bool,
        allow_rebuilds: bool,
        new_position_limit: int | None = None,
        max_retracement_count: int | None = None,
        rebuild_limit_per_tick: int | None = None,
        blocked_counter_add_directions: set[Direction] | None = None,
    ) -> CycleProcessingResult:
        """Process every active Snowball cycle for the current tick."""
        events: list[StrategyEvent] = []
        trace = self.decision_trace_recorder.start_tick(tick=tick)
        remaining_rebuild_limit = rebuild_limit_per_tick
        blocked_counter_add_directions = blocked_counter_add_directions or set()
        for cycle in list(ss.iter_active_cycles()):
            result = self._process_cycle(
                strategy=strategy,
                ss=ss,
                tick=tick,
                cycle=cycle,
                allow_new_positions=allow_new_positions,
                allow_rebuilds=allow_rebuilds,
                new_position_limit=new_position_limit,
                max_retracement_count=max_retracement_count,
                rebuild_limit_per_tick=remaining_rebuild_limit,
                blocked_counter_add_directions=blocked_counter_add_directions,
                trace=trace,
            )
            events.extend(result.events)
            remaining_rebuild_limit = self._consume_rebuild_limit(
                remaining_rebuild_limit,
                result.rebuild_count,
            )
            if result.stop_reason:
                self.decision_trace_recorder.persist(ss=ss, trace=trace)
                return CycleProcessingResult(
                    events=events,
                    stop_reason=result.stop_reason,
                    is_error=result.is_error,
                    rebuild_count=(
                        0
                        if rebuild_limit_per_tick is None
                        else rebuild_limit_per_tick - (remaining_rebuild_limit or 0)
                    ),
                )

        self.decision_trace_recorder.persist(ss=ss, trace=trace)
        return CycleProcessingResult(
            events=events,
            rebuild_count=(
                0
                if rebuild_limit_per_tick is None
                else rebuild_limit_per_tick - (remaining_rebuild_limit or 0)
            ),
        )

    def _process_cycle(
        self,
        *,
        strategy: CycleOrchestratorStrategy,
        ss: SnowballStrategyState,
        tick: Tick,
        cycle: SnowballCycle,
        allow_new_positions: bool,
        allow_rebuilds: bool,
        new_position_limit: int | None,
        max_retracement_count: int | None,
        rebuild_limit_per_tick: int | None,
        blocked_counter_add_directions: set[Direction],
        trace: SnowballDecisionTrace | DisabledSnowballDecisionTrace,
    ) -> CycleProcessingResult:
        events: list[StrategyEvent] = []
        remaining_rebuild_limit = rebuild_limit_per_tick
        rebuild_count = 0
        if cycle.grid.is_empty() and cycle.grid.has_pending_rebuilds():
            cycle.status = CycleStatus.PENDING
            if allow_rebuilds and self._can_open_new_position(ss, new_position_limit):
                rebuild_events = strategy._process_stop_loss_rebuilds(
                    ss,
                    tick,
                    cycle,
                    max_rebuilds=self._remaining_rebuild_capacity(
                        ss,
                        new_position_limit,
                        remaining_rebuild_limit,
                    ),
                    max_retracement_count=max_retracement_count,
                )
                rebuild_count += len(rebuild_events)
                remaining_rebuild_limit = self._consume_rebuild_limit(
                    remaining_rebuild_limit,
                    len(rebuild_events),
                )
                trace.record_events(
                    phase="pending_rebuild",
                    cycle=cycle,
                    events=rebuild_events,
                    no_event_reason="pending_rebuild_trigger_not_hit",
                )
                events.extend(rebuild_events)
            else:
                trace.record(
                    phase="pending_rebuild",
                    outcome="skipped",
                    reason="rebuilds_not_allowed",
                    cycle=cycle,
                )
            if cycle.grid.is_empty():
                if strategy.config.reseed_on_all_pending:
                    # The operator opted into reseeding fully-pending cycles, so
                    # leave this one PENDING and let ``SnowballCycleReseeder``
                    # spawn a fresh cycle instead of averaging deeper into the
                    # underwater one.  This preserves the historical
                    # reseed-driven recovery path.
                    strategy._validate_grid_ordering(cycle)
                    trace.record(
                        phase="cycle",
                        outcome="skipped",
                        reason="pending_rebuilds_remain_without_live_entries",
                        cycle=cycle,
                    )
                    return CycleProcessingResult(events=events, rebuild_count=rebuild_count)
                # Otherwise keep the cycle averaging from its pending-rebuild
                # head.  This branch used to ``return`` unconditionally, which
                # froze a PENDING cycle: it would only ever retry rebuilds of
                # its existing pending slots (which fire when price returns to
                # their original entry prices) and never open the next counter
                # or layer as price kept moving adversely (production backtest
                # DN/TEST3, cycle 686).  We now fall through to the normal
                # phases so the counter-add phase can refill a take-profit'd
                # counter slot (when refill is enabled) or open the next layer's
                # R0 (when it is not).  The counter-close, cycle-TP, and
                # stop-loss-close phases are no-ops without live entries, and
                # the trailing stop-loss-rebuild pass cannot fire because this
                # tick's rebuild trigger was already missed above.
                # ``status_refresher`` flips the cycle back to ACTIVE if a new
                # entry is opened, or leaves it PENDING otherwise.
                trace.record(
                    phase="cycle",
                    outcome="continued",
                    reason="pending_cycle_counter_add_attempt",
                    cycle=cycle,
                )
            else:
                cycle.status = CycleStatus.ACTIVE

        counter_close_events = strategy._process_cycle_counter_closes(ss, tick, cycle)
        trace.record_events(
            phase="counter_close",
            cycle=cycle,
            events=counter_close_events,
            no_event_reason="no_counter_take_profit_hit",
        )
        events.extend(counter_close_events)

        cycle_tp_events = strategy._process_cycle_tp(
            ss,
            tick,
            cycle,
            allow_reentry=allow_new_positions
            and self._can_open_new_position(ss, new_position_limit),
        )
        trace.record_events(
            phase="cycle_take_profit",
            cycle=cycle,
            events=cycle_tp_events,
            no_event_reason="cycle_head_take_profit_not_hit",
        )
        events.extend(cycle_tp_events)

        if (
            cycle_tp_events
            and cycle.grid.is_empty()
            and cycle.grid.has_pending_rebuilds()
            and strategy.config.reseed_on_all_pending
        ):
            self.status_refresher.refresh(cycle)
            trace.record(
                phase="cycle",
                outcome="skipped",
                reason="pending_after_tp_waiting_for_reseed",
                cycle=cycle,
            )
            return CycleProcessingResult(events=events, rebuild_count=rebuild_count)

        if strategy._close_order_violation:
            trace.record(
                phase="close_order",
                outcome="stop",
                reason="close_order_violation",
                cycle=cycle,
            )
            return CycleProcessingResult(
                events=events,
                stop_reason=f"Close order violation: {strategy._close_order_violation}",
                is_error=True,
                rebuild_count=rebuild_count,
            )

        stop_loss_events = strategy._process_stop_loss_closes(ss, tick, cycle)
        trace.record_events(
            phase="stop_loss_close",
            cycle=cycle,
            events=stop_loss_events,
            no_event_reason="no_stop_loss_hit",
        )
        events.extend(stop_loss_events)

        if allow_rebuilds and self._can_open_new_position(ss, new_position_limit):
            rebuild_events = strategy._process_stop_loss_rebuilds(
                ss,
                tick,
                cycle,
                max_rebuilds=self._remaining_rebuild_capacity(
                    ss,
                    new_position_limit,
                    remaining_rebuild_limit,
                ),
                max_retracement_count=max_retracement_count,
            )
            rebuild_count += len(rebuild_events)
            remaining_rebuild_limit = self._consume_rebuild_limit(
                remaining_rebuild_limit,
                len(rebuild_events),
            )
            trace.record_events(
                phase="stop_loss_rebuild",
                cycle=cycle,
                events=rebuild_events,
                no_event_reason="no_rebuild_trigger_hit",
            )
            events.extend(rebuild_events)
        else:
            trace.record(
                phase="stop_loss_rebuild",
                outcome="skipped",
                reason="rebuilds_not_allowed",
                cycle=cycle,
            )

        order_checked_without_new_mutations = False
        if (
            allow_new_positions
            and self._can_open_new_position(ss, new_position_limit)
            and not counter_close_events
        ):
            if cycle.direction in blocked_counter_add_directions:
                trace.record(
                    phase="counter_add",
                    outcome="skipped",
                    reason="trend_guard",
                    cycle=cycle,
                )
                order_checked_without_new_mutations = True
            else:
                strategy._validate_grid_ordering(cycle)
            if strategy._grid_order_violation:
                self.logger.debug(
                    "Skipping Snowball counter adds while grid ordering is violated: %s",
                    strategy._grid_order_violation,
                )
                trace.record(
                    phase="counter_add",
                    outcome="skipped",
                    reason="grid_ordering_violation",
                    cycle=cycle,
                )
                strategy._grid_order_violation = None
                order_checked_without_new_mutations = True
            elif cycle.direction not in blocked_counter_add_directions:
                max_iterations = max(1, strategy.config.f_max * (strategy.config.r_max + 1))
                opened_new_position = False
                for _ in range(max_iterations):
                    if not self._can_open_new_position(ss, new_position_limit):
                        break
                    add_events = strategy._process_cycle_counter_adds(
                        ss,
                        tick,
                        cycle,
                        max_retracement_count=max_retracement_count,
                    )
                    if not add_events:
                        break
                    opened_new_position = True
                    trace.record_events(
                        phase="counter_add",
                        cycle=cycle,
                        events=add_events,
                        no_event_reason="counter_add_threshold_not_met",
                    )
                    events.extend(add_events)
                if not opened_new_position:
                    trace.record(
                        phase="counter_add",
                        outcome="skipped",
                        reason="counter_add_threshold_not_met",
                        cycle=cycle,
                    )
                order_checked_without_new_mutations = not opened_new_position
        elif not allow_new_positions:
            trace.record(
                phase="counter_add",
                outcome="skipped",
                reason="new_positions_not_allowed",
                cycle=cycle,
            )

        if not order_checked_without_new_mutations:
            strategy._validate_grid_ordering(cycle)
        if strategy._grid_order_violation:
            strategy._grid_order_violation = None

        self.status_refresher.refresh(cycle)
        return CycleProcessingResult(events=events, rebuild_count=rebuild_count)

    def _can_open_new_position(
        self,
        ss: SnowballStrategyState,
        new_position_limit: int | None,
    ) -> bool:
        return new_position_limit is None or ss.entry_count() < new_position_limit

    def _remaining_rebuild_capacity(
        self,
        ss: SnowballStrategyState,
        new_position_limit: int | None,
        rebuild_limit_per_tick: int | None,
    ) -> int | None:
        position_capacity = (
            None if new_position_limit is None else max(0, new_position_limit - ss.entry_count())
        )
        capacities = [
            value for value in (position_capacity, rebuild_limit_per_tick) if value is not None
        ]
        if not capacities:
            return None
        return min(capacities)

    def _consume_rebuild_limit(
        self,
        rebuild_limit_per_tick: int | None,
        count: int,
    ) -> int | None:
        if rebuild_limit_per_tick is None:
            return None
        return max(0, rebuild_limit_per_tick - count)


class SnowballCycleReseeder:
    """Create fresh cycles for directions that no longer have a tradable cycle."""

    def __init__(self, *, logger_: Logger | None = None) -> None:
        self.logger = logger_ or logger

    def reseed(
        self,
        strategy: CycleOrchestratorStrategy,
        ss: SnowballStrategyState,
        tick: Tick,
        *,
        allow_new_positions: bool,
        new_position_limit: int | None = None,
    ) -> list[StrategyEvent]:
        """Create fresh cycles for missing, pending-only, or exhausted directions."""
        events: list[StrategyEvent] = []
        active = list(ss.iter_active_cycles())
        for direction in (Direction.LONG, Direction.SHORT):
            if not allow_new_positions:
                break
            if new_position_limit is not None and ss.entry_count() >= new_position_limit:
                break
            if not strategy._hedging_enabled and direction == Direction.SHORT:
                continue
            dir_cycles = [cycle for cycle in active if cycle.direction == direction]
            events.extend(
                self._reseed_direction(
                    strategy=strategy,
                    ss=ss,
                    tick=tick,
                    direction=direction,
                    dir_cycles=dir_cycles,
                )
            )
        return events

    def _reseed_direction(
        self,
        *,
        strategy: CycleOrchestratorStrategy,
        ss: SnowballStrategyState,
        tick: Tick,
        direction: Direction,
        dir_cycles: list[SnowballCycle],
    ) -> list[StrategyEvent]:
        if not dir_cycles:
            self.logger.info("No active %s cycle; creating new cycle", direction.value.upper())
            new_events, _ = strategy._create_cycle(ss, tick, direction)
            return new_events
        if strategy.config.reseed_on_all_pending and all(cycle.is_pending for cycle in dir_cycles):
            self.logger.info(
                "All %s cycles pending; creating new cycle (reseed_on_all_pending)",
                direction.value.upper(),
            )
            new_events, _ = strategy._create_cycle(ss, tick, direction)
            return new_events
        return []
