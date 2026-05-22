"""Cycle creation and layer-entry planning for Snowball."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from apps.trading.dataclasses.tick import Tick
from apps.trading.enums import Direction
from apps.trading.events import StrategyEvent
from apps.trading.strategies.snowball.config import SnowballStrategyConfig
from apps.trading.strategies.snowball.cycle_state import SnowballCycle, SnowballStrategyState
from apps.trading.strategies.snowball.entries import Entry
from apps.trading.strategies.snowball.events import SNOWBALL_EVENTS
from apps.trading.strategies.snowball.grid_models import Layer


class CycleLifecycleStrategy(Protocol):
    """Strategy surface needed by cycle lifecycle collaborators."""

    config: SnowballStrategyConfig
    pip_size: Decimal

    def _effective_base_units(self, state: SnowballStrategyState) -> int: ...

    def _assign_configured_stop_loss(self, entry: Entry, slot_number: int) -> None: ...


@dataclass(frozen=True, slots=True)
class SnowballCycleFactory:
    """Create Snowball cycles and their root entry events."""

    def create(
        self,
        *,
        strategy: CycleLifecycleStrategy,
        state: SnowballStrategyState,
        tick: Tick,
        direction: Direction,
    ) -> tuple[list[StrategyEvent], SnowballCycle]:
        """Create a new cycle with an initial L1/R0 entry."""
        cfg = strategy.config
        base_units = strategy._effective_base_units(state)
        units = cfg.trend_lot_size * base_units
        price = tick.ask if direction == Direction.LONG else tick.bid
        if direction == Direction.LONG:
            close_price = price + cfg.m_pips * strategy.pip_size
            formula = f"{price} + {cfg.m_pips} * {strategy.pip_size}"
        else:
            close_price = price - cfg.m_pips * strategy.pip_size
            formula = f"{price} - {cfg.m_pips} * {strategy.pip_size}"

        entry = Entry.open(
            state=state,
            tick=tick,
            direction=direction,
            units=units,
            step=1,
            close_price=close_price,
            role="initial",
            layer_number=1,
            retracement_count=0,
        )
        entry.expected_tp_pips = cfg.m_pips
        entry.validation_status = "pass"
        if cfg.stop_loss_enabled:
            strategy._assign_configured_stop_loss(entry, 1)

        event = SNOWBALL_EVENTS.entry_open_event(
            entry,
            timestamp=tick.timestamp,
            planned_exit_price_formula=formula,
            description=(
                f"Initial entry ({direction.value.upper()}) | units={units}, TP={close_price:.3f}"
                + (f", SL={entry.stop_loss_price:.3f}" if entry.stop_loss_price is not None else "")
            ),
        )

        cycle = SnowballCycle(cycle_id=entry.entry_id, direction=direction)
        layer = Layer.create(1, cfg.r_max, base_units, cfg.effective_refill_up_to)
        slot = layer.slot_at(0)
        assert slot is not None  # noqa: S101
        slot.fill(entry)
        cycle.add_layer(layer)
        state.cycles.append(cycle)
        state.invalidate_entry_cache()
        return [event], cycle


@dataclass(frozen=True, slots=True)
class SnowballLayerInitialPlanner:
    """Plan grid-snapped layer-initial entry prices."""

    def anchor_price(
        self,
        *,
        prev_layer: Layer,
        direction: Direction,
        market_price: Decimal,
        interval_pips: Decimal,
        pip_size: Decimal,
    ) -> Decimal:
        """Return the planned entry price for the next layer's R0."""
        highest = prev_layer.highest_present_slot()
        if highest is None:
            return market_price

        if highest.entry is not None:
            ref_price = highest.entry.entry_price
        elif highest.pending_rebuild is not None:
            ref_price = highest.pending_rebuild.entry_price
        else:
            return market_price

        offset = interval_pips * pip_size
        if direction == Direction.LONG:
            return ref_price - offset
        return ref_price + offset
