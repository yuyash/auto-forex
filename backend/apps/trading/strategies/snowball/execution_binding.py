"""Apply broker execution bindings to Snowball state."""

from __future__ import annotations

from typing import Protocol

from apps.trading.dataclasses import EventExecutionResult
from apps.trading.models.state import ExecutionState
from apps.trading.strategies.snowball.config import SnowballStrategyConfig
from apps.trading.strategies.snowball.pricing import SNOWBALL_PRICING
from apps.trading.strategies.snowball.tick_phases import SnowballExecutionStateBoundary


class ExecutionBindingStrategy(Protocol):
    config: SnowballStrategyConfig


def apply_event_execution_result(
    strategy: ExecutionBindingStrategy,
    *,
    state: ExecutionState,
    execution_result: EventExecutionResult,
) -> None:
    """Apply order execution feedback (position IDs, cycle IDs) to state."""
    state_boundary = SnowballExecutionStateBoundary(state=state)
    ss = state_boundary.load()
    if not execution_result:
        return

    binding = execution_result.entry_binding
    if binding is None:
        return
    eid = binding.entry_id
    position_id = binding.position_id
    if eid is None or position_id is None:
        return

    for cycle in ss.cycles:
        for layer in cycle.grid.layers:
            for slot in layer.slots:
                if slot.entry is not None and slot.entry.entry_id == eid:
                    slot.entry.position_id = str(position_id)
                    SNOWBALL_PRICING.sync_entry_fill_price(
                        entry=slot.entry,
                        layer=layer,
                        fill_price=binding.fill_price,
                        counter_tp_mode=strategy.config.counter_tp_mode,
                        planned_exit_price_bound=binding.planned_exit_price_bound,
                        planned_exit_price_bound_mode=binding.planned_exit_price_bound_mode,
                    )
                    if binding.cycle_id and cycle.cycle_id == eid and cycle.trade_cycle_id is None:
                        cycle.trade_cycle_id = binding.cycle_id
        for entry in cycle.hedge_entries:
            if entry.entry_id == eid:
                entry.position_id = str(position_id)
                SNOWBALL_PRICING.sync_entry_fill_price(
                    entry=entry,
                    layer=None,
                    fill_price=binding.fill_price,
                    counter_tp_mode=strategy.config.counter_tp_mode,
                    planned_exit_price_bound=binding.planned_exit_price_bound,
                    planned_exit_price_bound_mode=binding.planned_exit_price_bound_mode,
                )

    state_boundary.persist(ss)
