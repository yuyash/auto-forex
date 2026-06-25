"""Snowball price adjustment service."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from collections.abc import Iterator
from typing import Literal

from apps.trading.enums import Direction
from apps.trading.strategies.snowball.calculators import SnowballCalculator
from apps.trading.strategies.snowball.config import SnowballStrategyConfig
from apps.trading.strategies.snowball.entries import Entry, StopLossClosedEntry
from apps.trading.strategies.snowball.grid_models import Layer


@dataclass(frozen=True, slots=True)
class PlannedExitPriceBound:
    """A hard boundary applied after planned-exit price adjustments."""

    mode: Literal["min", "max"]
    price: Decimal

    def apply(self, price: Decimal) -> Decimal:
        """Return price clamped to this boundary."""
        if self.mode == "min":
            return min(price, self.price)
        return max(price, self.price)

    @classmethod
    def from_values(
        cls,
        *,
        mode: str | None,
        price: Decimal | str | None,
    ) -> "PlannedExitPriceBound | None":
        """Build a bound from event or execution-binding fields."""
        if price is None:
            return None
        mode_value = str(mode or "").strip().lower()
        if mode_value == "min":
            return cls(mode="min", price=Decimal(str(price)))
        if mode_value == "max":
            return cls(mode="max", price=Decimal(str(price)))
        raise ValueError("planned_exit_price_bound_mode must be 'min' or 'max'")


@dataclass(frozen=True, slots=True)
class LayerInitialClosePrice:
    """Close-price plan for a layer-initial entry."""

    close_price: Decimal
    formula: str
    bound: PlannedExitPriceBound | None = None

    def __iter__(self) -> Iterator[Decimal | str]:
        """Keep tuple unpacking compatibility for existing callers."""
        yield self.close_price
        yield self.formula


class SnowballPricingService:
    """Own Snowball entry/exit price calculations and fill-price synchronization."""

    def rebuild_take_profit_price(
        self,
        *,
        pending: StopLossClosedEntry,
        entry_price: Decimal,
        pip_size: Decimal,
        config: SnowballStrategyConfig,
    ) -> Decimal:
        """Return the take-profit price for a rebuilt entry."""
        if config.rebuild_take_profit_mode == "same":
            return pending.close_price
        if config.rebuild_take_profit_mode == "same_pips":
            if pip_size <= 0:
                return pending.close_price
            tp_pips = self._take_profit_distance_pips(pending, pip_size)
        else:
            tp_pips = SnowballCalculator(config).rebuild_take_profit_pips(
                pending.retracement_count + 1
            )
        return self._take_profit_price(
            direction=pending.direction,
            entry_price=entry_price,
            tp_pips=tp_pips,
            pip_size=pip_size,
        )

    def _take_profit_distance_pips(
        self,
        pending: StopLossClosedEntry,
        pip_size: Decimal,
    ) -> Decimal:
        """Return the original absolute TP distance in pips."""
        return abs(pending.close_price - pending.entry_price) / pip_size

    def weighted_avg_close_price(
        self,
        layer: Layer,
        *,
        new_price: Decimal,
        new_units: int,
        include_ref: Entry | None = None,
    ) -> tuple[Decimal, str]:
        """Compute weighted-average close price for a new entry in a layer."""
        total_cost = new_price * Decimal(str(new_units))
        total_units = new_units
        parts = [f"{new_price} * {new_units}"]

        for slot in layer.slots:
            if slot.entry is not None and not slot.entry.is_hedge:
                total_cost += slot.entry.entry_price * Decimal(str(slot.entry.units))
                total_units += slot.entry.units
                parts.append(f"{slot.entry.entry_price} * {slot.entry.units}")
            elif slot.pending_rebuild is not None:
                pending = slot.pending_rebuild
                total_cost += pending.entry_price * Decimal(str(pending.units))
                total_units += pending.units
                parts.append(f"{pending.entry_price} * {pending.units}")

        if include_ref is not None:
            ref_units = abs(include_ref.units)
            if ref_units > 0:
                total_cost += include_ref.entry_price * Decimal(str(ref_units))
                total_units += ref_units
                parts.append(f"{include_ref.entry_price} * {ref_units}")

        close_price = total_cost / Decimal(str(total_units)) if total_units > 0 else new_price
        return close_price, f"({' + '.join(parts)}) / {total_units}"

    def current_weighted_avg_close_price(self, layer: Layer) -> tuple[Decimal, str] | None:
        """Compute weighted-average close price from the layer's current state."""
        total_cost = Decimal("0")
        total_units = 0
        parts: list[str] = []

        for slot in layer.slots:
            if slot.entry is not None and not slot.entry.is_hedge:
                total_cost += slot.entry.entry_price * Decimal(str(slot.entry.units))
                total_units += slot.entry.units
                parts.append(f"{slot.entry.entry_price} * {slot.entry.units}")
            elif slot.pending_rebuild is not None:
                pending = slot.pending_rebuild
                total_cost += pending.entry_price * Decimal(str(pending.units))
                total_units += pending.units
                parts.append(f"{pending.entry_price} * {pending.units}")

        if total_units <= 0:
            return None

        close_price = total_cost / Decimal(str(total_units))
        return close_price, f"({' + '.join(parts)}) / {total_units}"

    def layer_initial_close_price(
        self,
        *,
        new_price: Decimal,
        prev_layer: Layer,
        direction: Direction,
        pip_size: Decimal,
        m_pips: Decimal,
    ) -> LayerInitialClosePrice:
        """Compute close price for a layer-initial entry.

        The layer initial normally uses the same fixed TP distance as L1/R0.
        The previous layer's last present TP is only a boundary: crossing it
        would invert the grid TP order, so clamp to that previous TP.
        """
        if direction == Direction.LONG:
            close_price = new_price + m_pips * pip_size
            formula = f"{new_price} + {m_pips} * {pip_size}"
        else:
            close_price = new_price - m_pips * pip_size
            formula = f"{new_price} - {m_pips} * {pip_size}"

        highest = prev_layer.highest_present_slot()
        if highest is None:
            return LayerInitialClosePrice(close_price=close_price, formula=formula)

        previous_close_price: Decimal | None = None
        if highest.entry is not None:
            previous_close_price = highest.entry.close_price
        elif highest.pending_rebuild is not None:
            previous_close_price = highest.pending_rebuild.close_price

        if previous_close_price is None:
            return LayerInitialClosePrice(close_price=close_price, formula=formula)

        bound = PlannedExitPriceBound(
            mode="min" if direction == Direction.LONG else "max",
            price=previous_close_price,
        )
        if direction == Direction.LONG and close_price > previous_close_price:
            return LayerInitialClosePrice(
                close_price=previous_close_price,
                formula=f"min({formula}, {previous_close_price:.5f})",
                bound=bound,
            )
        if direction == Direction.SHORT and close_price < previous_close_price:
            return LayerInitialClosePrice(
                close_price=previous_close_price,
                formula=f"max({formula}, {previous_close_price:.5f})",
                bound=bound,
            )

        return LayerInitialClosePrice(close_price=close_price, formula=formula, bound=bound)

    def sync_weighted_average_counter_take_profits(self, layer: Layer) -> Decimal | None:
        """Recompute weighted-average TP and apply it to all live counters in a layer."""
        weighted = self.current_weighted_avg_close_price(layer)
        if weighted is None:
            return None

        close_price = weighted[0]
        for slot in layer.slots:
            if slot.entry is not None and slot.entry.role == "counter":
                slot.entry.close_price = close_price
        return close_price

    def sync_entry_fill_price(
        self,
        *,
        entry: Entry,
        layer: Layer | None,
        fill_price: Decimal | None,
        counter_tp_mode: str,
        planned_exit_price_bound: Decimal | str | None = None,
        planned_exit_price_bound_mode: str | None = None,
    ) -> None:
        """Align entry pricing with a broker fill price and refresh dependent exits."""
        if fill_price is None:
            return

        bound = PlannedExitPriceBound.from_values(
            mode=planned_exit_price_bound_mode,
            price=planned_exit_price_bound,
        )
        fill_price = Decimal(str(fill_price))
        original_entry_price = entry.entry_price
        original_stop_loss_price = entry.stop_loss_price
        delta = fill_price - original_entry_price
        if delta == 0:
            if bound is not None:
                entry.close_price = bound.apply(entry.close_price)
            return

        entry.entry_price = fill_price

        if entry.stop_loss_price is not None:
            entry.stop_loss_price += delta
            entry.stop_loss_price = self.ensure_stop_loss_on_loss_side(
                direction=entry.direction,
                entry_price=entry.entry_price,
                stop_loss_price=entry.stop_loss_price,
                source_entry_price=original_entry_price,
                source_stop_loss_price=original_stop_loss_price,
            )

        if layer is not None and entry.role == "counter" and counter_tp_mode == "weighted_avg":
            self.sync_weighted_average_counter_take_profits(layer)
            if bound is not None:
                entry.close_price = bound.apply(entry.close_price)
            return

        entry.close_price += delta
        if bound is not None:
            entry.close_price = bound.apply(entry.close_price)

    def is_stop_loss_on_loss_side(
        self,
        *,
        direction: Direction,
        entry_price: Decimal,
        stop_loss_price: Decimal | None,
    ) -> bool:
        """Return whether a stop-loss is positive and on the loss side."""
        if stop_loss_price is None:
            return True
        if stop_loss_price <= 0:
            return False
        if direction == Direction.LONG:
            return stop_loss_price < entry_price
        return stop_loss_price > entry_price

    def stop_loss_from_distance(
        self,
        *,
        direction: Direction,
        entry_price: Decimal,
        distance: Decimal,
    ) -> Decimal | None:
        """Project an absolute stop-loss distance from an entry price."""
        if distance <= 0:
            return None
        if direction == Direction.LONG:
            stop_loss_price = entry_price - distance
        else:
            stop_loss_price = entry_price + distance
        if stop_loss_price <= 0:
            return None
        return stop_loss_price

    def reproject_stop_loss(
        self,
        *,
        direction: Direction,
        entry_price: Decimal,
        source_entry_price: Decimal | None,
        source_stop_loss_price: Decimal | None,
    ) -> Decimal | None:
        """Rebuild a stop-loss from a prior entry/SL distance."""
        if source_entry_price is None or source_stop_loss_price is None:
            return None
        if source_entry_price <= 0 or source_stop_loss_price <= 0:
            return None
        return self.stop_loss_from_distance(
            direction=direction,
            entry_price=entry_price,
            distance=abs(source_entry_price - source_stop_loss_price),
        )

    def ensure_stop_loss_on_loss_side(
        self,
        *,
        direction: Direction,
        entry_price: Decimal,
        stop_loss_price: Decimal | None,
        source_entry_price: Decimal | None = None,
        source_stop_loss_price: Decimal | None = None,
    ) -> Decimal | None:
        """Return a valid stop-loss or raise when it cannot be repaired."""
        if self.is_stop_loss_on_loss_side(
            direction=direction,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
        ):
            return stop_loss_price

        repaired = self.reproject_stop_loss(
            direction=direction,
            entry_price=entry_price,
            source_entry_price=source_entry_price,
            source_stop_loss_price=source_stop_loss_price,
        )
        if repaired is not None and self.is_stop_loss_on_loss_side(
            direction=direction,
            entry_price=entry_price,
            stop_loss_price=repaired,
        ):
            return repaired

        raise ValueError("Stop-loss price must be positive and on the loss side of entry price")

    def _take_profit_price(
        self,
        *,
        direction: Direction,
        entry_price: Decimal,
        tp_pips: Decimal,
        pip_size: Decimal,
    ) -> Decimal:
        if direction == Direction.LONG:
            return entry_price + tp_pips * pip_size
        return entry_price - tp_pips * pip_size


SNOWBALL_PRICING = SnowballPricingService()
