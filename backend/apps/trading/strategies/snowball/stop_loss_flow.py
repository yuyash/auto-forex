"""Stop-loss close and rebuild flow for the Snowball strategy."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from logging import Logger, getLogger
from typing import Protocol

from apps.trading.dataclasses.tick import Tick
from apps.trading.enums import Direction
from apps.trading.events import StrategyEvent
from apps.trading.strategies.snowball.calculators import (
    SnowballCalculatorProvider,
    SnowballFormulaCalculator,
    round_to_step,
)
from apps.trading.strategies.snowball.config import SnowballStrategyConfig
from apps.trading.strategies.snowball.enums import CycleStatus
from apps.trading.strategies.snowball.events import SNOWBALL_EVENTS
from apps.trading.strategies.snowball.grid_policy import SNOWBALL_GRID_POLICY, SnowballGridPolicy
from apps.trading.strategies.snowball.cycle_state import SnowballCycle, SnowballStrategyState
from apps.trading.strategies.snowball.entries import Entry, StopLossClosedEntry
from apps.trading.strategies.snowball.grid_models import Layer, Slot
from apps.trading.strategies.snowball.pricing import SNOWBALL_PRICING, PlannedExitPriceBound

logger = getLogger(__name__)


class StopLossFlowStrategy(Protocol):
    """Runtime surface needed by stop-loss flow collaborators."""

    config: SnowballStrategyConfig
    pip_size: Decimal
    calculator: SnowballFormulaCalculator

    def counter_interval_pips(self, step: int) -> Decimal: ...


@dataclass(frozen=True, slots=True)
class StopLossCloseCandidate:
    """A slot whose stop-loss should close on the current tick."""

    slot: Slot
    entry: Entry
    layer: Layer


@dataclass(frozen=True, slots=True)
class StopLossRebuildPlan:
    """Computed prices and description text for one stop-loss rebuild."""

    trigger_price: Decimal
    close_price: Decimal
    planned_exit_price_bound: Decimal | None = None
    planned_exit_price_bound_mode: str = ""


class StopLossAssigner:
    """Assign normal, automatic, configured, and rebuild stop-loss prices."""

    def __init__(
        self,
        *,
        calculator_provider: SnowballCalculatorProvider | None = None,
        logger_: Logger | None = None,
    ) -> None:
        self.calculator_provider = calculator_provider or SnowballCalculatorProvider()
        self.logger = logger_ or logger

    def assign(
        self,
        strategy: StopLossFlowStrategy,
        entry: Entry,
        sl_pips: Decimal,
    ) -> None:
        """Compute and assign a stop-loss price to an entry."""
        if sl_pips <= 0:
            return
        if entry.is_long:
            stop_loss_price = entry.entry_price - sl_pips * strategy.pip_size
        else:
            stop_loss_price = entry.entry_price + sl_pips * strategy.pip_size
        entry.stop_loss_price = stop_loss_price
        self.logger.debug(
            "SL assigned: entry_id=%d L%d/R%d, SL=%.5f (sl_pips=%.1f)",
            entry.entry_id,
            entry.layer_number,
            entry.retracement_count,
            stop_loss_price,
            sl_pips,
        )

    def assign_auto(
        self,
        strategy: StopLossFlowStrategy,
        entry: Entry,
        next_interval_pips: Decimal,
    ) -> None:
        """Apply interval-based stop-loss placement."""
        tp_pips = abs(entry.close_price - entry.entry_price) / strategy.pip_size
        if entry.is_long:
            next_entry_price = entry.entry_price - next_interval_pips * strategy.pip_size
            if entry.retracement_count == 0 or tp_pips < next_interval_pips:
                stop_loss_price = next_entry_price
            else:
                stop_loss_price = next_entry_price - next_interval_pips * strategy.pip_size
        else:
            next_entry_price = entry.entry_price + next_interval_pips * strategy.pip_size
            if entry.retracement_count == 0 or tp_pips < next_interval_pips:
                stop_loss_price = next_entry_price
            else:
                stop_loss_price = next_entry_price + next_interval_pips * strategy.pip_size
        entry.stop_loss_price = stop_loss_price
        self.logger.debug(
            "Auto SL assigned: entry_id=%d L%d/R%d, SL=%.5f (tp_pips=%.1f, next_interval=%.1f)",
            entry.entry_id,
            entry.layer_number,
            entry.retracement_count,
            stop_loss_price,
            tp_pips,
            next_interval_pips,
        )

    def assign_configured(
        self,
        strategy: StopLossFlowStrategy,
        entry: Entry,
        slot_number: int,
    ) -> None:
        """Assign stop-loss using the configured mode for a 1-based slot number."""
        calculator = self.calculator_provider.for_strategy(strategy)
        if strategy.config.stop_loss_mode == "auto":
            interval_method = getattr(strategy, "counter_interval_pips", None)
            next_interval = (
                interval_method(slot_number)
                if callable(interval_method)
                else calculator.counter_interval_pips(slot_number)
            )
            if next_interval > 0:
                self.assign_auto(strategy, entry, next_interval)
            return

        sl_pips = calculator.stop_loss_pips(slot_number)
        if sl_pips > 0:
            self.assign(strategy, entry, sl_pips)

    def assign_rebuild(
        self,
        strategy: StopLossFlowStrategy,
        entry: Entry,
        pending: StopLossClosedEntry,
    ) -> None:
        """Assign stop-loss to a rebuilt entry using rebuild-specific settings."""
        if not strategy.config.stop_loss_enabled:
            return

        if strategy.config.rebuild_stop_loss_mode == "same":
            if pending.stop_loss_price is not None:
                projected = self._same_mode_stop_loss(entry, pending)
                if projected is not None:
                    entry.stop_loss_price = projected
                else:
                    self._assign_fallback_configured(strategy, entry, pending)
            return

        if strategy.config.rebuild_stop_loss_mode == "same_pips":
            projected = SNOWBALL_PRICING.reproject_stop_loss(
                direction=entry.direction,
                entry_price=entry.entry_price,
                source_entry_price=pending.entry_price,
                source_stop_loss_price=pending.stop_loss_price,
            )
            if projected is None:
                self._assign_fallback_configured(strategy, entry, pending)
                return
            entry.stop_loss_price = projected
            return

        values = strategy.config.rebuild_stop_loss_manual_pips
        if not values:
            return
        idx = min(max(pending.retracement_count, 0), len(values) - 1)
        sl_pips = round_to_step(values[idx], strategy.config.round_step_pips)
        if sl_pips > 0:
            self.assign(strategy, entry, sl_pips)

    def _same_mode_stop_loss(
        self,
        entry: Entry,
        pending: StopLossClosedEntry,
    ) -> Decimal | None:
        stop_loss_price = pending.stop_loss_price
        if SNOWBALL_PRICING.is_stop_loss_on_loss_side(
            direction=entry.direction,
            entry_price=entry.entry_price,
            stop_loss_price=stop_loss_price,
        ):
            return stop_loss_price

        projected = SNOWBALL_PRICING.reproject_stop_loss(
            direction=entry.direction,
            entry_price=entry.entry_price,
            source_entry_price=pending.entry_price,
            source_stop_loss_price=stop_loss_price,
        )
        if projected is not None and SNOWBALL_PRICING.is_stop_loss_on_loss_side(
            direction=entry.direction,
            entry_price=entry.entry_price,
            stop_loss_price=projected,
        ):
            self.logger.warning(
                "Rebuild SL reprojected to preserve loss-side placement: "
                "L%d/R%d %s original_entry=%.5f copied_sl=%s rebuilt_entry=%.5f "
                "projected_sl=%.5f",
                pending.layer_number,
                pending.retracement_count,
                pending.direction.value.upper(),
                pending.entry_price,
                stop_loss_price,
                entry.entry_price,
                projected,
            )
            return projected

        self.logger.warning(
            "Rebuild SL could not reuse copied price; falling back to configured SL: "
            "L%d/R%d %s original_entry=%.5f copied_sl=%s rebuilt_entry=%.5f",
            pending.layer_number,
            pending.retracement_count,
            pending.direction.value.upper(),
            pending.entry_price,
            stop_loss_price,
            entry.entry_price,
        )
        return None

    def _assign_fallback_configured(
        self,
        strategy: StopLossFlowStrategy,
        entry: Entry,
        pending: StopLossClosedEntry,
    ) -> None:
        slot_number = max(pending.retracement_count + 1, 1)
        self.assign_configured(strategy, entry, slot_number)


class StopLossProtectionPolicy:
    """Decide whether a stop-loss is active and hit on the current tick."""

    def temporarily_protected(
        self,
        config: SnowballStrategyConfig,
        layer: Layer,
        entry: Entry,
    ) -> bool:
        """Return True when the layer's highest live R should ignore stop-loss."""
        if not config.preserve_highest_retracement_enabled:
            return False
        threshold = config.preserve_highest_r_from
        highest = layer.highest_occupied_slot()
        if highest is None or highest.entry is None:
            return False
        if highest.index == 0 or highest.index < threshold:
            return False
        return highest.entry.entry_id == entry.entry_id

    def hit(self, entry: Entry, tick: Tick) -> bool:
        """Return True when the tick has crossed the entry's stop-loss price."""
        if not entry.can_close_on_tick(tick):
            return False
        stop_loss_price = entry.stop_loss_price
        if stop_loss_price is None:
            return False
        return bool(
            (entry.is_long and tick.bid <= stop_loss_price)
            or (entry.is_short and tick.ask >= stop_loss_price)
        )


class StopLossSnapshotFactory:
    """Create pending-rebuild snapshots from stop-loss-closed entries."""

    def snapshot(
        self,
        entry: Entry,
        cycle: SnowballCycle,
        pips_lost: Decimal,
        *,
        exit_price: Decimal,
        closed_at: datetime,
    ) -> StopLossClosedEntry:
        """Return the pending rebuild record for a stop-loss close."""
        return StopLossClosedEntry(
            entry_price=entry.entry_price,
            close_price=entry.close_price,
            units=entry.units,
            direction=entry.direction,
            role=entry.role,
            layer_number=entry.layer_number,
            retracement_count=entry.retracement_count,
            step=entry.step,
            root_entry_id=entry.root_entry_id,
            parent_entry_id=entry.parent_entry_id,
            cycle_id=cycle.cycle_id,
            position_id=entry.position_id,
            stop_loss_price=entry.stop_loss_price,
            stop_loss_exit_price=exit_price,
            closed_at=closed_at,
            lifecycle_realized_pnl=entry.lifecycle_realized_pnl,
            lifecycle_stop_loss_count=entry.lifecycle_stop_loss_count,
            stop_loss_loss_pips=pips_lost,
        )


class StopLossCloseProcessor:
    """Close entries whose stop-loss price has been hit."""

    def __init__(
        self,
        *,
        protection_policy: StopLossProtectionPolicy | None = None,
        snapshot_factory: StopLossSnapshotFactory | None = None,
        logger_: Logger | None = None,
    ) -> None:
        self.protection_policy = protection_policy or StopLossProtectionPolicy()
        self.snapshot_factory = snapshot_factory or StopLossSnapshotFactory()
        self.logger = logger_ or logger

    def process(
        self,
        strategy: StopLossFlowStrategy,
        ss: SnowballStrategyState,
        tick: Tick,
        cycle: SnowballCycle,
        *,
        close_entry: Callable[..., StrategyEvent],
    ) -> list[StrategyEvent]:
        """Close all stop-loss-hit entries in the cycle."""
        if not strategy.config.stop_loss_enabled:
            return []

        events: list[StrategyEvent] = []
        for candidate in self._candidates(strategy=strategy, tick=tick, cycle=cycle):
            events.append(
                self._close_candidate(
                    strategy=strategy,
                    tick=tick,
                    cycle=cycle,
                    candidate=candidate,
                    close_entry=close_entry,
                )
            )
            ss.invalidate_entry_cache()
        return events

    def _candidates(
        self,
        *,
        strategy: StopLossFlowStrategy,
        tick: Tick,
        cycle: SnowballCycle,
    ) -> list[StopLossCloseCandidate]:
        candidates: list[StopLossCloseCandidate] = []
        for layer in cycle.grid.layers:
            for slot in layer.slots:
                entry = slot.entry
                if entry is None or entry.stop_loss_price is None:
                    continue
                if entry.is_hedge:
                    continue
                if self.protection_policy.temporarily_protected(
                    strategy.config,
                    layer,
                    entry,
                ):
                    continue
                if self.protection_policy.hit(entry, tick):
                    candidates.append(StopLossCloseCandidate(slot=slot, entry=entry, layer=layer))
        return candidates

    def _close_candidate(
        self,
        *,
        strategy: StopLossFlowStrategy,
        tick: Tick,
        cycle: SnowballCycle,
        candidate: StopLossCloseCandidate,
        close_entry: Callable[..., StrategyEvent],
    ) -> StrategyEvent:
        entry = candidate.entry
        exit_price = entry.exit_price(tick)
        pips_lost = abs(exit_price - entry.entry_price) / strategy.pip_size

        self.logger.info(
            "Stop-loss hit (%s): L%d/R%d, entry=%.5f, SL=%.5f, exit=%.5f, -%.1f pips",
            entry.direction.value.upper(),
            entry.layer_number,
            entry.retracement_count,
            entry.entry_price,
            entry.stop_loss_price,
            exit_price,
            pips_lost,
        )

        close_event = close_entry(
            tick,
            entry,
            description=(
                f"[PROTECTION] Stop-loss ({entry.direction.value.upper()}) | "
                f"L{entry.layer_number}/R{entry.retracement_count}, "
                f"entry={entry.entry_price:.5f}, SL={entry.stop_loss_price:.5f}, "
                f"exit={exit_price:.5f}, -{pips_lost:.1f} pips"
            ),
            close_reason="stop_loss",
            validation_status="warn",
            cycle=cycle,
        )

        entry.lifecycle_stop_loss_count += 1
        cycle.stop_loss_count += 1
        if strategy.config.rebuild_enabled:
            candidate.slot.close_for_stop_loss(
                self.snapshot_factory.snapshot(
                    entry,
                    cycle,
                    pips_lost,
                    exit_price=exit_price,
                    closed_at=tick.timestamp,
                )
            )
        else:
            candidate.slot.close(refillable=False)
        return close_event


class StopLossRebuildPricePlanner:
    """Compute rebuild trigger and take-profit prices while preserving grid order."""

    def __init__(
        self,
        *,
        grid_policy: SnowballGridPolicy | None = None,
        logger_: Logger | None = None,
    ) -> None:
        self.grid_policy = grid_policy or SNOWBALL_GRID_POLICY
        self.logger = logger_ or logger

    def plan(
        self,
        *,
        strategy: StopLossFlowStrategy,
        tick: Tick,
        cycle: SnowballCycle,
        layer: Layer,
        slot: Slot,
        pending: StopLossClosedEntry,
    ) -> StopLossRebuildPlan | None:
        """Return a rebuild plan when the trigger price has been reached."""
        if pending.closed_at is not None and tick.timestamp <= pending.closed_at:
            return None

        trigger_price = self.rebuild_trigger_price(
            strategy=strategy,
            cycle=cycle,
            layer=layer,
            slot=slot,
            pending=pending,
        )
        if self.cycle_rebuild_guard_blocks(
            strategy=strategy,
            tick=tick,
            cycle=cycle,
            pending=pending,
            trigger_price=trigger_price,
        ):
            return None
        if not self.cooldown_elapsed(
            pending=pending,
            tick=tick,
            cooldown_seconds=strategy.config.rebuild_cooldown_seconds,
        ):
            return None

        if not self.trigger_hit(pending, tick, trigger_price):
            return None

        close_price, planned_exit_bound = self.take_profit_price(
            strategy=strategy,
            cycle=cycle,
            layer=layer,
            slot=slot,
            pending=pending,
            trigger_price=trigger_price,
        )
        projected_close_price = self.projected_close_price_after_fill(
            pending=pending,
            tick=tick,
            trigger_price=trigger_price,
            close_price=close_price,
            planned_exit_bound=planned_exit_bound,
        )
        fill_price = self.entry_side_fill_price(pending, tick)
        if not self.planned_exit_on_profit_side(
            pending=pending,
            fill_price=fill_price,
            planned_exit_price=projected_close_price,
        ):
            repaired_close_price = self.repair_take_profit_for_fill(
                strategy=strategy,
                pending=pending,
                fill_price=fill_price,
                trigger_price=trigger_price,
                planned_exit_bound=planned_exit_bound,
            )
            if repaired_close_price is None:
                self.logger.info(
                    "Skipping stop-loss rebuild until planned exit is on profit side: "
                    "L%d/R%d, fill=%.5f, planned_exit=%.5f, trigger=%.5f",
                    pending.layer_number,
                    pending.retracement_count,
                    fill_price,
                    projected_close_price,
                    trigger_price,
                )
                return None
            self.logger.info(
                "Adjusted stop-loss rebuild TP to stay on profit side after fill: "
                "L%d/R%d, fill=%.5f, old_projected=%.5f, repaired_projected=%.5f, "
                "trigger=%.5f",
                pending.layer_number,
                pending.retracement_count,
                fill_price,
                projected_close_price,
                repaired_close_price,
                trigger_price,
            )
            close_price = self.pre_fill_close_price(
                fill_price=fill_price,
                trigger_price=trigger_price,
                projected_close_price=repaired_close_price,
            )

        self.propagate_take_profit(cycle, layer, slot, pending, close_price)
        return StopLossRebuildPlan(
            trigger_price=trigger_price,
            close_price=close_price,
            planned_exit_price_bound=planned_exit_bound.price
            if planned_exit_bound is not None
            else None,
            planned_exit_price_bound_mode=planned_exit_bound.mode
            if planned_exit_bound is not None
            else "",
        )

    def rebuild_trigger_price(
        self,
        *,
        strategy: StopLossFlowStrategy,
        cycle: SnowballCycle,
        layer: Layer,
        slot: Slot,
        pending: StopLossClosedEntry,
    ) -> Decimal:
        """Return the effective trigger price for rebuilding a pending slot."""
        trigger_price = self.trigger_price(pending, strategy.config.rebuild_entry_price_mode)
        trigger_price = self.apply_entry_buffer(
            pending=pending,
            trigger_price=trigger_price,
            entry_price_mode=strategy.config.rebuild_entry_price_mode,
            buffer_pips=strategy.config.rebuild_entry_buffer_pips,
            pip_size=strategy.pip_size,
        )
        return self.clamp_entry_price(cycle, layer, slot, pending, trigger_price)

    def cycle_rebuild_guard_blocks(
        self,
        *,
        strategy: StopLossFlowStrategy,
        tick: Tick,
        cycle: SnowballCycle,
        pending: StopLossClosedEntry,
        trigger_price: Decimal,
    ) -> bool:
        """Return True when repeated stop-losses should pause this pending rebuild."""
        cfg = strategy.config
        if not cfg.cycle_rebuild_guard_enabled:
            return False
        if cycle.stop_loss_count < cfg.cycle_rebuild_guard_stop_count:
            return False

        loss_threshold = -cfg.cycle_rebuild_guard_min_loss
        if cycle.realized_pnl >= loss_threshold:
            return False
        if self.pending_rebuild_price_recovered(
            strategy=strategy,
            tick=tick,
            pending=pending,
            trigger_price=trigger_price,
        ):
            return False
        return True

    def pending_rebuild_price_recovered(
        self,
        *,
        strategy: StopLossFlowStrategy,
        tick: Tick,
        pending: StopLossClosedEntry,
        trigger_price: Decimal,
    ) -> bool:
        """Return True when price has recovered to this slot's rebuild trigger."""
        recovery = strategy.config.cycle_rebuild_guard_recovery_pips
        offset = recovery * strategy.pip_size
        if pending.direction == Direction.LONG:
            return tick.bid >= trigger_price + offset
        return tick.ask <= trigger_price - offset

    def cooldown_elapsed(
        self,
        *,
        pending: StopLossClosedEntry,
        tick: Tick,
        cooldown_seconds: Decimal,
    ) -> bool:
        """Return True when the post-stop-loss cooldown has elapsed."""
        if cooldown_seconds <= 0:
            return True
        if pending.closed_at is None:
            return True
        elapsed = tick.timestamp - pending.closed_at
        return elapsed.total_seconds() >= float(cooldown_seconds)

    def trigger_price(
        self,
        pending: StopLossClosedEntry,
        entry_price_mode: str,
    ) -> Decimal:
        """Return the price that must be reached to rebuild the entry.

        In ``stop_loss_exit`` mode the trigger is anchored on the previous
        stop-loss price level, NOT the actual fill price.  Anchoring on the
        fill price made every rebuild round drift the trigger by one
        slippage step in the adverse direction.  Historically, that drift
        could combine with ``rebuild_stop_loss_mode='same'`` and place the
        rebuilt SL on the profit side of the new entry.  Anchoring on the SL
        level keeps the trigger stationary across rounds.
        """
        if entry_price_mode == "stop_loss_exit":
            return pending.stop_loss_price or pending.stop_loss_exit_price or pending.entry_price
        return pending.entry_price

    def apply_entry_buffer(
        self,
        *,
        pending: StopLossClosedEntry,
        trigger_price: Decimal,
        entry_price_mode: str,
        buffer_pips: Decimal,
        pip_size: Decimal,
    ) -> Decimal:
        """Push the trigger further into the favorable direction by ``buffer_pips``.

        Only meaningful in ``stop_loss_exit`` mode: in ``original_entry``
        mode the rebuild always lands on the original entry price, so an
        additional buffer would push the rebuild past the original
        position, which is not the intended behaviour.
        """
        if entry_price_mode != "stop_loss_exit":
            return trigger_price
        if buffer_pips <= 0 or pip_size <= 0:
            return trigger_price
        offset = buffer_pips * pip_size
        if pending.direction == Direction.LONG:
            return trigger_price + offset
        return trigger_price - offset

    def clamp_entry_price(
        self,
        cycle: SnowballCycle,
        layer: Layer,
        slot: Slot,
        pending: StopLossClosedEntry,
        trigger_price: Decimal,
    ) -> Decimal:
        """Clamp rebuild entry price against preceding grid entry bounds."""
        entry_bound = self.grid_policy.preceding_entry_bound(cycle, layer, slot.index)
        if entry_bound is None:
            return trigger_price
        if pending.direction == Direction.LONG and trigger_price > entry_bound:
            return self._clamped_entry_price(pending, trigger_price, entry_bound)
        if pending.direction == Direction.SHORT and trigger_price < entry_bound:
            return self._clamped_entry_price(pending, trigger_price, entry_bound)
        return trigger_price

    def trigger_hit(
        self,
        pending: StopLossClosedEntry,
        tick: Tick,
        trigger_price: Decimal,
    ) -> bool:
        """Return True when current price permits rebuilding the pending entry."""
        if pending.direction == Direction.LONG:
            return tick.bid >= trigger_price
        return tick.ask <= trigger_price

    def take_profit_price(
        self,
        *,
        strategy: StopLossFlowStrategy,
        cycle: SnowballCycle,
        layer: Layer,
        slot: Slot,
        pending: StopLossClosedEntry,
        trigger_price: Decimal,
    ) -> tuple[Decimal, PlannedExitPriceBound | None]:
        """Return adjusted and clamped rebuild take-profit price with grid bound."""
        close_price = SNOWBALL_PRICING.rebuild_take_profit_price(
            pending=pending,
            entry_price=trigger_price,
            pip_size=strategy.pip_size,
            config=strategy.config,
        )
        close_price, planned_exit_bound = self.clamp_take_profit(
            cycle,
            layer,
            slot,
            pending,
            close_price,
        )
        return close_price, planned_exit_bound

    def projected_close_price_after_fill(
        self,
        *,
        pending: StopLossClosedEntry,
        tick: Tick,
        trigger_price: Decimal,
        close_price: Decimal,
        planned_exit_bound: PlannedExitPriceBound | None,
    ) -> Decimal:
        """Return the planned exit price that order execution will validate.

        Rebuild events carry ``trigger_price`` as the planned entry, but dry-run
        execution fills at the current entry-side tick price.  The execution
        handler shifts TP by that fill delta and reapplies any grid-order bound.
        Mirror that here so an invalid rebuild stays pending instead of creating
        an unfillable strategy entry.
        """
        projected = close_price + (self.entry_side_fill_price(pending, tick) - trigger_price)
        if planned_exit_bound is not None:
            return planned_exit_bound.apply(projected)
        return projected

    def repair_take_profit_for_fill(
        self,
        *,
        strategy: StopLossFlowStrategy,
        pending: StopLossClosedEntry,
        fill_price: Decimal,
        trigger_price: Decimal,
        planned_exit_bound: PlannedExitPriceBound | None,
    ) -> Decimal | None:
        """Return a fill-based projected TP when the original TP is invalid."""
        distance = self.repair_take_profit_distance(
            strategy=strategy,
            pending=pending,
        )
        if distance <= 0:
            return None

        if pending.direction == Direction.LONG:
            projected = fill_price + distance
        else:
            projected = fill_price - distance

        if planned_exit_bound is not None:
            projected = planned_exit_bound.apply(projected)

        if not self.planned_exit_on_profit_side(
            pending=pending,
            fill_price=fill_price,
            planned_exit_price=projected,
        ):
            return None
        return projected

    def repair_take_profit_distance(
        self,
        *,
        strategy: StopLossFlowStrategy,
        pending: StopLossClosedEntry,
    ) -> Decimal:
        """Return the TP distance to use when a persisted TP is unusable."""
        original_distance = abs(pending.close_price - pending.entry_price)
        if original_distance > 0:
            return original_distance

        configured_pips = strategy.calculator.rebuild_take_profit_pips(
            pending.retracement_count + 1
        )
        if configured_pips <= 0 or strategy.pip_size <= 0:
            return Decimal("0")
        return configured_pips * strategy.pip_size

    @staticmethod
    def pre_fill_close_price(
        *,
        fill_price: Decimal,
        trigger_price: Decimal,
        projected_close_price: Decimal,
    ) -> Decimal:
        """Convert a desired post-fill TP into the planned pre-fill TP."""
        return projected_close_price - (fill_price - trigger_price)

    @staticmethod
    def entry_side_fill_price(pending: StopLossClosedEntry, tick: Tick) -> Decimal:
        """Return the dry-run fill side used for a rebuild entry."""
        return tick.ask if pending.direction == Direction.LONG else tick.bid

    @staticmethod
    def planned_exit_on_profit_side(
        *,
        pending: StopLossClosedEntry,
        fill_price: Decimal,
        planned_exit_price: Decimal,
    ) -> bool:
        """Return True when the projected TP is reachable as profit after fill."""
        if pending.direction == Direction.LONG:
            return planned_exit_price > fill_price
        return planned_exit_price < fill_price

    def clamp_take_profit(
        self,
        cycle: SnowballCycle,
        layer: Layer,
        slot: Slot,
        pending: StopLossClosedEntry,
        adjusted_close_price: Decimal,
    ) -> tuple[Decimal, PlannedExitPriceBound | None]:
        """Clamp rebuild TP against preceding occupied or pending slots."""
        neighbor_bound = self.grid_policy.upper_neighbor_tp_bound(cycle, layer, slot.index)
        if neighbor_bound is None:
            return adjusted_close_price, None
        bound = PlannedExitPriceBound(
            mode="min" if pending.direction == Direction.LONG else "max",
            price=neighbor_bound,
        )
        if pending.direction == Direction.LONG and adjusted_close_price > neighbor_bound:
            return self._clamped_take_profit(pending, adjusted_close_price, neighbor_bound), bound
        if pending.direction == Direction.SHORT and adjusted_close_price < neighbor_bound:
            return self._clamped_take_profit(pending, adjusted_close_price, neighbor_bound), bound
        return adjusted_close_price, bound

    def propagate_take_profit(
        self,
        cycle: SnowballCycle,
        layer: Layer,
        slot: Slot,
        pending: StopLossClosedEntry,
        adjusted_close_price: Decimal,
    ) -> None:
        """Extend preceding pending rebuild TPs so rebuilt grids stay monotonic."""
        propagated = self.grid_policy.propagate_pending_rebuild_tp(
            cycle, layer, slot.index, adjusted_close_price
        )
        for layer_number, slot_index, old_tp, new_tp in propagated:
            self.logger.info(
                "Pending-rebuild TP extended to preserve ordering: "
                "L%d/R%d, old_tp=%.5f, new_tp=%.5f "
                "(triggered by L%d/R%d rebuild @ TP=%.5f)",
                layer_number,
                slot_index,
                old_tp,
                new_tp,
                pending.layer_number,
                pending.retracement_count,
                adjusted_close_price,
            )

    def _clamped_entry_price(
        self,
        pending: StopLossClosedEntry,
        trigger_price: Decimal,
        entry_bound: Decimal,
    ) -> Decimal:
        self.logger.info(
            "Rebuild entry clamped to preserve grid ordering: "
            "L%d/R%d, trigger=%.5f, bound=%.5f, clamped_to=%.5f",
            pending.layer_number,
            pending.retracement_count,
            trigger_price,
            entry_bound,
            entry_bound,
        )
        return entry_bound

    def _clamped_take_profit(
        self,
        pending: StopLossClosedEntry,
        adjusted_close_price: Decimal,
        neighbor_bound: Decimal,
    ) -> Decimal:
        self.logger.info(
            "Rebuild TP clamped to upper neighbor: "
            "L%d/R%d, pending_tp=%.5f, computed_adj=%.5f, clamped_to=%.5f",
            pending.layer_number,
            pending.retracement_count,
            pending.close_price,
            adjusted_close_price,
            neighbor_bound,
        )
        return neighbor_bound


class StopLossRebuildEntryFactory:
    """Create rebuilt entries and their strategy events."""

    def __init__(
        self,
        *,
        assigner: StopLossAssigner | None = None,
        logger_: Logger | None = None,
    ) -> None:
        self.assigner = assigner or StopLossAssigner()
        self.logger = logger_ or logger

    def rebuild_entry(
        self,
        *,
        strategy: StopLossFlowStrategy,
        ss: SnowballStrategyState,
        tick: Tick,
        pending: StopLossClosedEntry,
        plan: StopLossRebuildPlan,
    ) -> Entry:
        """Create and configure the rebuilt entry."""
        entry = Entry.open(
            state=ss,
            tick=tick,
            direction=pending.direction,
            units=pending.units,
            step=pending.step,
            close_price=plan.close_price,
            role=pending.role,
            layer_number=pending.layer_number,
            retracement_count=pending.retracement_count,
            root_entry_id=pending.root_entry_id,
            parent_entry_id=pending.parent_entry_id,
        )
        entry.entry_price = plan.trigger_price
        entry.validation_status = "pass"
        entry.is_rebuild = True
        entry.lifecycle_realized_pnl = pending.lifecycle_realized_pnl
        entry.lifecycle_stop_loss_count = pending.lifecycle_stop_loss_count
        self.assigner.assign_rebuild(strategy, entry, pending)
        return entry

    def rebuild_event(
        self,
        *,
        entry: Entry,
        tick: Tick,
        pending: StopLossClosedEntry,
        plan: StopLossRebuildPlan,
    ) -> StrategyEvent:
        """Return the strategy event for a rebuilt entry."""
        stop_loss_note = (
            f", SL={entry.stop_loss_price:.3f}" if entry.stop_loss_price is not None else ""
        )
        entry_note = (
            f", entry={plan.trigger_price:.5f}" if plan.trigger_price != pending.entry_price else ""
        )
        return SNOWBALL_EVENTS.entry_rebuild_event(
            entry,
            timestamp=tick.timestamp,
            execution_price=self._entry_side_price(entry.direction, tick),
            original_position_id=pending.position_id,
            planned_exit_price_bound=plan.planned_exit_price_bound,
            planned_exit_price_bound_mode=plan.planned_exit_price_bound_mode,
            description=(
                f"Stop-loss rebuild ({pending.direction.value.upper()}) | "
                f"L{pending.layer_number}/R{pending.retracement_count}, "
                f"units={pending.units}, TP={plan.close_price:.5f}"
                f"{entry_note}{stop_loss_note}"
            ),
        )

    @staticmethod
    def _entry_side_price(direction: Direction, tick: Tick) -> Decimal:
        return tick.ask if direction == Direction.LONG else tick.bid

    def log_rebuild(self, pending: StopLossClosedEntry, plan: StopLossRebuildPlan) -> None:
        """Log the rebuilt entry details."""
        self.logger.info(
            "Stop-loss rebuild (%s): L%d/R%d, entry=%.5f, TP=%.5f, units=%d",
            pending.direction.value.upper(),
            pending.layer_number,
            pending.retracement_count,
            plan.trigger_price,
            plan.close_price,
            pending.units,
        )


class StopLossRebuildProcessor:
    """Rebuild positions that were closed by stop-loss when price returns."""

    def __init__(
        self,
        *,
        price_planner: StopLossRebuildPricePlanner | None = None,
        entry_factory: StopLossRebuildEntryFactory | None = None,
        logger_: Logger | None = None,
    ) -> None:
        self.price_planner = price_planner or StopLossRebuildPricePlanner()
        self.entry_factory = entry_factory or StopLossRebuildEntryFactory()
        self.logger = logger_ or logger

    def process(
        self,
        strategy: StopLossFlowStrategy,
        ss: SnowballStrategyState,
        tick: Tick,
        cycle: SnowballCycle,
        *,
        max_rebuilds: int | None = None,
        max_retracement_count: int | None = None,
    ) -> list[StrategyEvent]:
        """Rebuild all pending slots that have reached their trigger price."""
        if not strategy.config.stop_loss_enabled or not strategy.config.rebuild_enabled:
            return []
        if max_rebuilds is not None and max_rebuilds <= 0:
            return []

        events: list[StrategyEvent] = []

        for layer in cycle.grid.layers:
            for slot in layer.slots:
                if max_rebuilds is not None and len(events) >= max_rebuilds:
                    break
                pending = slot.pending_rebuild
                if pending is None:
                    continue
                if (
                    max_retracement_count is not None
                    and pending.retracement_count > max_retracement_count
                ):
                    continue
                plan = self.price_planner.plan(
                    strategy=strategy,
                    tick=tick,
                    cycle=cycle,
                    layer=layer,
                    slot=slot,
                    pending=pending,
                )
                if plan is None:
                    continue
                entry = self.entry_factory.rebuild_entry(
                    strategy=strategy,
                    ss=ss,
                    tick=tick,
                    pending=pending,
                    plan=plan,
                )
                slot.complete_rebuild(entry)
                ss.invalidate_entry_cache()
                self.entry_factory.log_rebuild(pending, plan)
                events.append(
                    self.entry_factory.rebuild_event(
                        entry=entry,
                        tick=tick,
                        pending=pending,
                        plan=plan,
                    )
                )
            if max_rebuilds is not None and len(events) >= max_rebuilds:
                break

        if events and cycle.is_pending:
            cycle.status = CycleStatus.ACTIVE
            self.logger.info(
                "Cycle %d (%s) reactivated after stop-loss rebuild",
                cycle.cycle_id,
                cycle.direction.value.upper(),
            )

        return events
