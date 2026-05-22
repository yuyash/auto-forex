"""Counter-entry open/close flow for the Snowball strategy."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal
from logging import Logger, getLogger
from typing import Protocol

from apps.trading.dataclasses.tick import Tick
from apps.trading.enums import Direction
from apps.trading.events import StrategyEvent
from apps.trading.strategies.snowball.calculators import (
    SnowballCalculatorProvider,
    SnowballFormulaCalculator,
)
from apps.trading.strategies.snowball.config import SnowballStrategyConfig
from apps.trading.strategies.snowball.events import SNOWBALL_EVENTS
from apps.trading.strategies.snowball.grid_policy import SNOWBALL_GRID_POLICY, SnowballGridPolicy
from apps.trading.strategies.snowball.cycle_state import SnowballCycle, SnowballStrategyState
from apps.trading.strategies.snowball.entries import Entry
from apps.trading.strategies.snowball.grid_models import Layer, Slot
from apps.trading.strategies.snowball.pricing import SNOWBALL_PRICING

logger = getLogger(__name__)


class CounterFlowStrategy(Protocol):
    """Runtime surface needed by counter-flow collaborators."""

    config: SnowballStrategyConfig
    pip_size: Decimal
    calculator: SnowballFormulaCalculator


@dataclass(frozen=True, slots=True)
class CounterHeadContext:
    """Effective cycle head used for add-distance checks."""

    entry: Entry | None
    entry_price: Decimal | None
    entry_id: int | None
    direction: Direction


@dataclass(frozen=True, slots=True)
class CounterAdverseInterval:
    """Measured adverse movement and required interval for a counter slot."""

    adverse: Decimal
    interval: Decimal


class CounterPriceService:
    """Resolve executable prices and pip distances for counter flows."""

    def entry_side_price(self, direction: Direction, tick: Tick) -> Decimal:
        """Return the executable entry-side price for a direction."""
        return tick.ask if direction == Direction.LONG else tick.bid

    def exit_side_price(self, direction: Direction, tick: Tick) -> Decimal:
        """Return the executable exit-side price for a direction."""
        return tick.bid if direction == Direction.LONG else tick.ask

    def slot_reference_price(self, slot: Slot) -> Decimal | None:
        """Return a live or pending-rebuild reference price for a slot."""
        if slot.entry is not None:
            return slot.entry.entry_price
        if slot.pending_rebuild is not None:
            return slot.pending_rebuild.entry_price
        return None

    def layer_r0_reference_price(self, layer: Layer) -> Decimal | None:
        """Return the layer R0 live or pending-rebuild reference price."""
        r0 = layer.slot_at(0)
        if r0 is None:
            return None
        return self.slot_reference_price(r0)

    def adverse_pips(
        self,
        *,
        direction: Direction,
        ref_price: Decimal,
        current_entry_price: Decimal,
        pip_size: Decimal,
    ) -> Decimal:
        """Return adverse pips from ref_price to current_entry_price."""
        if direction == Direction.LONG:
            return (ref_price - current_entry_price) / pip_size
        return (current_entry_price - ref_price) / pip_size


class CounterTakeProfitPolicy:
    """Determine whether a counter entry's take-profit is executable."""

    def hit(self, entry: Entry, tick: Tick) -> bool:
        """Return True when the tick reaches the entry's close price."""
        if entry.close_price <= 0:
            return False
        if entry.is_long:
            return tick.bid >= entry.close_price
        return tick.ask <= entry.close_price


class CounterSlotClassifier:
    """Classify grid slots for counter-flow decisions."""

    def is_layer_initial_slot(self, layer: Layer, slot: Slot, entry: Entry) -> bool:
        """Return True when the slot is a non-L1 layer initial entry."""
        return layer.layer_number > 1 and slot.index == 0 and entry.is_layer_initial


class CounterGridEntryFormatter:
    """Format entries for diagnostic log messages."""

    def format(self, entry: Entry) -> str:
        """Return a compact grid entry label."""
        return (
            f"L{entry.layer_number}/R{entry.retracement_count}"
            f"(entry={entry.entry_price:.5f},tp={entry.close_price:.5f})"
        )


class CounterCloseCandidateFinder:
    """Find the next counter or layer-initial slot eligible for TP close."""

    def __init__(
        self,
        *,
        take_profit_policy: CounterTakeProfitPolicy | None = None,
        slot_classifier: CounterSlotClassifier | None = None,
        entry_formatter: CounterGridEntryFormatter | None = None,
        logger_: Logger | None = None,
    ) -> None:
        self.take_profit_policy = take_profit_policy or CounterTakeProfitPolicy()
        self.slot_classifier = slot_classifier or CounterSlotClassifier()
        self.entry_formatter = entry_formatter or CounterGridEntryFormatter()
        self.logger = logger_ or logger

    def next_candidate(
        self,
        *,
        cycle: SnowballCycle,
        tick: Tick,
    ) -> tuple[Layer, Slot, list[str]] | None:
        """Return the newest TP-hit non-head slot, even if newer slots are not hit."""
        head = cycle.initial_entry
        head_entry_id = head.entry_id if head is not None else None
        blocked_newer: list[str] = []

        for layer in reversed(cycle.grid.layers):
            candidate = self._candidate_in_layer(
                cycle=cycle,
                tick=tick,
                layer=layer,
                head_entry_id=head_entry_id,
                blocked_newer=blocked_newer,
            )
            if candidate is not None:
                return candidate
        return None

    def _candidate_in_layer(
        self,
        *,
        cycle: SnowballCycle,
        tick: Tick,
        layer: Layer,
        head_entry_id: int | None,
        blocked_newer: list[str],
    ) -> tuple[Layer, Slot, list[str]] | None:
        occupied_count = layer.entry_count()
        for slot in reversed(layer.slots):
            entry = slot.entry
            if entry is None or entry.entry_id == head_entry_id:
                continue
            if self._layer_initial_blocked_by_counters(
                cycle=cycle,
                tick=tick,
                layer=layer,
                slot=slot,
                entry=entry,
                occupied_count=occupied_count,
            ):
                blocked_newer.append(self.entry_formatter.format(entry))
                continue
            if self.take_profit_policy.hit(entry, tick):
                return layer, slot, blocked_newer
            blocked_newer.append(self.entry_formatter.format(entry))
        return None

    def _layer_initial_blocked_by_counters(
        self,
        *,
        cycle: SnowballCycle,
        tick: Tick,
        layer: Layer,
        slot: Slot,
        entry: Entry,
        occupied_count: int,
    ) -> bool:
        if not self.slot_classifier.is_layer_initial_slot(layer, slot, entry):
            return False
        if occupied_count == 1:
            return False
        if self.take_profit_policy.hit(entry, tick):
            self.logger.warning(
                "Layer initial TP reached before its layer counters closed; "
                "waiting for counters: cycle_id=%d, L%d/R%d",
                cycle.cycle_id,
                entry.layer_number,
                entry.retracement_count,
            )
        return True


class SnowballCounterCloseProcessor:
    """Close TP-hit non-head entries, preferring the newest hit slot first."""

    def __init__(
        self,
        *,
        candidate_finder: CounterCloseCandidateFinder | None = None,
        slot_classifier: CounterSlotClassifier | None = None,
        take_profit_policy: CounterTakeProfitPolicy | None = None,
        logger_: Logger | None = None,
    ) -> None:
        candidate_policy = take_profit_policy or CounterTakeProfitPolicy()
        candidate_classifier = slot_classifier or CounterSlotClassifier()
        self.candidate_finder = candidate_finder or CounterCloseCandidateFinder(
            take_profit_policy=candidate_policy,
            slot_classifier=candidate_classifier,
        )
        self.slot_classifier = slot_classifier or self.candidate_finder.slot_classifier
        self.take_profit_policy = take_profit_policy or self.candidate_finder.take_profit_policy
        self.logger = logger_ or logger

    def process(
        self,
        strategy: CounterFlowStrategy,
        ss: SnowballStrategyState,
        tick: Tick,
        cycle: SnowballCycle,
        *,
        close_entry: Callable[..., StrategyEvent],
    ) -> list[StrategyEvent]:
        """Close all currently executable counter take-profits."""
        if cycle.completed:
            return []

        events: list[StrategyEvent] = []
        while True:
            candidate = self.candidate_finder.next_candidate(cycle=cycle, tick=tick)
            if candidate is None:
                return events
            layer, slot, blocked_newer = candidate
            entry = slot.entry
            if entry is None:
                return events

            self._log_blocked_newer(cycle=cycle, entry=entry, blocked_newer=blocked_newer)
            if self.slot_classifier.is_layer_initial_slot(layer, slot, entry):
                self._close_layer_initial_slot(
                    strategy=strategy,
                    tick=tick,
                    cycle=cycle,
                    layer=layer,
                    slot=slot,
                    events=events,
                    close_entry=close_entry,
                )
                ss.invalidate_entry_cache()
                if layer.layer_number > 1 and not layer.has_present_entries():
                    cycle.grid.layers.remove(layer)
                    ss.invalidate_entry_cache()
                continue

            self._close_counter_slot(
                strategy=strategy,
                tick=tick,
                cycle=cycle,
                layer=layer,
                slot=slot,
                events=events,
                close_entry=close_entry,
            )
            ss.invalidate_entry_cache()
            if layer.layer_number > 1:
                self._close_layer_initial_if_ready(
                    strategy=strategy,
                    tick=tick,
                    cycle=cycle,
                    layer=layer,
                    events=events,
                    close_entry=close_entry,
                )
                ss.invalidate_entry_cache()
                if not layer.has_present_entries():
                    cycle.grid.layers.remove(layer)
                    ss.invalidate_entry_cache()

    def _log_blocked_newer(
        self,
        *,
        cycle: SnowballCycle,
        entry: Entry,
        blocked_newer: list[str],
    ) -> None:
        if not blocked_newer:
            return
        self.logger.warning(
            "Grid close-order violation: closing TP-hit L%d/R%d while newer "
            "entries remain open or are not at TP; cycle_id=%d, blocked_newer=[%s]",
            entry.layer_number,
            entry.retracement_count,
            cycle.cycle_id,
            ", ".join(blocked_newer),
        )

    def _close_counter_slot(
        self,
        *,
        strategy: CounterFlowStrategy,
        tick: Tick,
        cycle: SnowballCycle,
        layer: Layer,
        slot: Slot,
        events: list[StrategyEvent],
        close_entry: Callable[..., StrategyEvent],
    ) -> None:
        entry = slot.entry
        if entry is None:
            return

        exit_price = entry.exit_price(tick)
        pips_gained = abs(exit_price - entry.entry_price) / strategy.pip_size
        self.logger.info(
            "Counter TP (%s): L%s/R%s, +%.1f pips",
            entry.direction.value.upper(),
            entry.layer_number,
            entry.retracement_count,
            pips_gained,
        )
        layer.close_slot(slot.index)
        cycle.counter_close_count += 1
        events.append(
            close_entry(
                tick,
                entry,
                description=(
                    f"Counter TP ({entry.direction.value.upper()}) | "
                    f"L{entry.layer_number}/R{entry.retracement_count}, "
                    f"entry={entry.entry_price:.3f}, "
                    f"exit={exit_price:.3f}, +{pips_gained:.1f} pips"
                ),
                close_reason="counter_tp",
                actual_tp_pips=pips_gained,
                validation_status="pass",
                cycle=cycle,
            )
        )

    def _close_layer_initial_if_ready(
        self,
        *,
        strategy: CounterFlowStrategy,
        tick: Tick,
        cycle: SnowballCycle,
        layer: Layer,
        events: list[StrategyEvent],
        close_entry: Callable[..., StrategyEvent],
    ) -> None:
        if layer.entry_count() != 1:
            return
        r0_slot = layer.lowest_occupied_slot()
        if r0_slot is None or r0_slot.index != 0:
            return
        r0_entry = r0_slot.entry
        if r0_entry is None or not self.take_profit_policy.hit(r0_entry, tick):
            return

        self._close_layer_initial_slot(
            strategy=strategy,
            tick=tick,
            cycle=cycle,
            layer=layer,
            slot=r0_slot,
            events=events,
            close_entry=close_entry,
        )

    def _close_layer_initial_slot(
        self,
        *,
        strategy: CounterFlowStrategy,
        tick: Tick,
        cycle: SnowballCycle,
        layer: Layer,
        slot: Slot,
        events: list[StrategyEvent],
        close_entry: Callable[..., StrategyEvent],
    ) -> None:
        r0_entry = slot.entry
        if r0_entry is None:
            return

        r0_exit = r0_entry.exit_price(tick)
        r0_pips = abs(r0_exit - r0_entry.entry_price) / strategy.pip_size
        self.logger.info(
            "Layer initial TP (%s): L%s, +%.1f pips; removing layer",
            r0_entry.direction.value.upper(),
            layer.layer_number,
            r0_pips,
        )
        layer.close_slot(slot.index, refillable=False)
        events.append(
            close_entry(
                tick,
                r0_entry,
                description=(
                    f"Layer initial TP ({r0_entry.direction.value.upper()}) | "
                    f"L{layer.layer_number}, entry={r0_entry.entry_price:.3f}, "
                    f"exit={r0_exit:.3f}, +{r0_pips:.1f} pips"
                ),
                close_reason="layer_initial_tp",
                actual_tp_pips=r0_pips,
                validation_status="pass",
                cycle=cycle,
            )
        )


class SnowballCounterAddDescription:
    """Build user-facing descriptions for counter-add events."""

    def format(
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
        """Return the counter-add event description."""
        description = (
            f"Counter add ({direction.value.upper()}) | "
            f"L{layer.layer_number}/R{slot.index}, units={units}, "
            f"adverse={adverse:.1f} pips, TP={close_price:.3f}"
        )
        if stop_loss_price is not None:
            description += f", SL={stop_loss_price:.3f}"
        return description


class CounterSlotSelector:
    """Select and validate counter grid slots for new entries."""

    def __init__(
        self,
        *,
        calculator_provider: SnowballCalculatorProvider | None = None,
        price_service: CounterPriceService | None = None,
        grid_policy: SnowballGridPolicy | None = None,
        logger_: Logger | None = None,
    ) -> None:
        self.calculator_provider = calculator_provider or SnowballCalculatorProvider()
        self.price_service = price_service or CounterPriceService()
        self.grid_policy = grid_policy or SNOWBALL_GRID_POLICY
        self.logger = logger_ or logger

    def head_context(self, *, cycle: SnowballCycle, layer: Layer) -> CounterHeadContext | None:
        """Return live or pending-rebuild head context for a cycle."""
        head = cycle.initial_entry
        if head is not None:
            return CounterHeadContext(
                entry=head,
                entry_price=head.entry_price,
                entry_id=head.entry_id,
                direction=head.direction,
            )
        r0 = layer.slot_at(0)
        if r0 is None or r0.pending_rebuild is None:
            return None
        return CounterHeadContext(
            entry=None,
            entry_price=r0.pending_rebuild.entry_price,
            entry_id=r0.pending_rebuild.root_entry_id,
            direction=cycle.direction,
        )

    def head_losing(
        self,
        *,
        strategy: CounterFlowStrategy,
        tick: Tick,
        head_context: CounterHeadContext,
    ) -> bool:
        """Return True when the effective cycle head is currently losing."""
        if head_context.entry is not None:
            exit_price = self.price_service.exit_side_price(head_context.entry.direction, tick)
            return head_context.entry.unrealised_loss_pips(exit_price, strategy.pip_size) > Decimal(
                "0"
            )
        if head_context.entry_price is None:
            return False
        exit_price = self.price_service.exit_side_price(head_context.direction, tick)
        if head_context.direction == Direction.LONG:
            return (head_context.entry_price - exit_price) / strategy.pip_size > Decimal("0")
        return (exit_price - head_context.entry_price) / strategy.pip_size > Decimal("0")

    def new_layer_interval_hit(
        self,
        *,
        strategy: CounterFlowStrategy,
        tick: Tick,
        cycle: SnowballCycle,
        layer: Layer,
    ) -> bool:
        """Return True when the newest slot has moved enough to create a layer."""
        highest = layer.highest_present_slot()
        if highest is None:
            return True
        ref_price = self.price_service.slot_reference_price(highest)
        if ref_price is None:
            return True

        direction = cycle.direction
        current_entry_price = self.price_service.entry_side_price(direction, tick)
        if self._same_tick_layer_interval_hit(
            strategy=strategy,
            tick=tick,
            layer=layer,
            highest=highest,
            current_entry_price=current_entry_price,
        ):
            return True

        adverse = self.price_service.adverse_pips(
            direction=direction,
            ref_price=ref_price,
            current_entry_price=current_entry_price,
            pip_size=strategy.pip_size,
        )
        interval = self._counter_interval(strategy, highest.index + 1)
        return adverse >= interval

    def counter_slot_adverse_interval(
        self,
        *,
        strategy: CounterFlowStrategy,
        tick: Tick,
        cycle: SnowballCycle,
        layer: Layer,
        slot: Slot,
        head_entry_price: Decimal | None,
    ) -> CounterAdverseInterval | None:
        """Return adverse/required pips for a counter slot."""
        direction = cycle.direction
        current_entry_price = self.price_service.entry_side_price(direction, tick)
        previous_slot = layer.previous_present_slot(slot.index)

        same_tick_interval = self._same_tick_counter_slot_interval(
            strategy=strategy,
            tick=tick,
            layer=layer,
            slot=slot,
            previous_slot=previous_slot,
            current_entry_price=current_entry_price,
            head_entry_price=head_entry_price,
        )
        if same_tick_interval is not None:
            return same_tick_interval

        if previous_slot is not None:
            ref_price = self.price_service.slot_reference_price(previous_slot)
        else:
            ref_price = self.price_service.layer_r0_reference_price(layer) or head_entry_price
        if ref_price is None:
            return None

        adverse = self.price_service.adverse_pips(
            direction=direction,
            ref_price=ref_price,
            current_entry_price=current_entry_price,
            pip_size=strategy.pip_size,
        )
        interval = self._counter_interval(strategy, slot.index)
        return CounterAdverseInterval(adverse=adverse, interval=interval)

    def violates_preceding_entry_bound(
        self,
        *,
        cycle: SnowballCycle,
        layer: Layer,
        slot: Slot,
        new_price: Decimal,
    ) -> bool:
        """Return True when opening at new_price would break cross-layer order."""
        bound = self.grid_policy.preceding_entry_bound(cycle, layer, slot.index)
        if bound is None:
            return False
        if cycle.direction == Direction.LONG:
            if new_price > bound:
                self._log_preceding_bound_skip(
                    layer=layer,
                    slot=slot,
                    new_price=new_price,
                    bound=bound,
                    comparator="exceed",
                )
                return True
            return False
        if new_price < bound:
            self._log_preceding_bound_skip(
                layer=layer,
                slot=slot,
                new_price=new_price,
                bound=bound,
                comparator="be below",
            )
            return True
        return False

    def _same_tick_layer_interval_hit(
        self,
        *,
        strategy: CounterFlowStrategy,
        tick: Tick,
        layer: Layer,
        highest: Slot,
        current_entry_price: Decimal,
    ) -> bool:
        if highest.entry is None or highest.entry.opened_at != tick.timestamp:
            return False
        r0_ref_price = self.price_service.layer_r0_reference_price(layer)
        if r0_ref_price is None:
            return True
        cumulative_interval = self._cumulative_counter_intervals(
            strategy,
            range(1, highest.index + 2),
        )
        adverse = self.price_service.adverse_pips(
            direction=highest.entry.direction,
            ref_price=r0_ref_price,
            current_entry_price=current_entry_price,
            pip_size=strategy.pip_size,
        )
        return adverse >= cumulative_interval

    def _same_tick_counter_slot_interval(
        self,
        *,
        strategy: CounterFlowStrategy,
        tick: Tick,
        layer: Layer,
        slot: Slot,
        previous_slot: Slot | None,
        current_entry_price: Decimal,
        head_entry_price: Decimal | None,
    ) -> CounterAdverseInterval | None:
        if not self._fresh_same_tick(previous_slot, tick, current_entry_price):
            return None
        assert previous_slot is not None and previous_slot.entry is not None
        r0_ref_price = self.price_service.layer_r0_reference_price(layer) or head_entry_price
        if r0_ref_price is None:
            return None
        cumulative_interval = self._cumulative_counter_intervals(strategy, range(1, slot.index + 1))
        adverse = self.price_service.adverse_pips(
            direction=previous_slot.entry.direction,
            ref_price=r0_ref_price,
            current_entry_price=current_entry_price,
            pip_size=strategy.pip_size,
        )
        return CounterAdverseInterval(adverse=adverse, interval=cumulative_interval)

    def _fresh_same_tick(
        self,
        previous_slot: Slot | None,
        tick: Tick,
        current_entry_price: Decimal,
    ) -> bool:
        return (
            previous_slot is not None
            and previous_slot.entry is not None
            and previous_slot.entry.opened_at == tick.timestamp
            and previous_slot.entry.entry_price == current_entry_price
        )

    def _counter_interval(
        self,
        strategy: CounterFlowStrategy,
        step: int,
    ) -> Decimal:
        return self.calculator_provider.for_strategy(strategy).counter_interval_pips(step)

    def _cumulative_counter_intervals(
        self,
        strategy: CounterFlowStrategy,
        steps: Iterable[int],
    ) -> Decimal:
        cumulative_interval = Decimal("0")
        calculator = self.calculator_provider.for_strategy(strategy)
        for step in steps:
            cumulative_interval += calculator.counter_interval_pips(step)
        return cumulative_interval

    def _log_preceding_bound_skip(
        self,
        *,
        layer: Layer,
        slot: Slot,
        new_price: Decimal,
        bound: Decimal,
        comparator: str,
    ) -> None:
        self.logger.info(
            "Skipping counter add L%d/R%d: entry %.5f would %s preceding-layer "
            "bound %.5f (grid ordering)",
            layer.layer_number,
            slot.index,
            new_price,
            comparator,
            bound,
        )


class CounterEntryFactory:
    """Create counter entries and their strategy-open events."""

    def __init__(
        self,
        *,
        calculator_provider: SnowballCalculatorProvider | None = None,
        price_service: CounterPriceService | None = None,
        description_builder: SnowballCounterAddDescription | None = None,
        logger_: Logger | None = None,
    ) -> None:
        self.calculator_provider = calculator_provider or SnowballCalculatorProvider()
        self.price_service = price_service or CounterPriceService()
        self.description_builder = description_builder or SnowballCounterAddDescription()
        self.logger = logger_ or logger

    def open_counter_entry(
        self,
        strategy: CounterFlowStrategy,
        ss: SnowballStrategyState,
        tick: Tick,
        cycle: SnowballCycle,
        layer: Layer,
        slot: Slot,
        adverse_interval: CounterAdverseInterval,
        head_context: CounterHeadContext,
        *,
        assign_configured_stop_loss: Callable[[Entry, int], None],
    ) -> list[StrategyEvent]:
        """Open a counter entry in the selected slot."""
        cfg = strategy.config
        direction = cycle.direction
        units = (slot.index + 1) * layer.base_units
        new_price = self.price_service.entry_side_price(direction, tick)
        close_price, formula = self._close_price_and_formula(
            strategy=strategy,
            cfg=cfg,
            direction=direction,
            layer=layer,
            slot=slot,
            units=units,
            new_price=new_price,
            head_context=head_context,
        )

        entry = Entry.open(
            state=ss,
            tick=tick,
            direction=direction,
            units=units,
            step=slot.index + 1,
            close_price=close_price,
            role="counter",
            layer_number=layer.layer_number,
            retracement_count=slot.index,
            root_entry_id=head_context.entry_id,
            parent_entry_id=head_context.entry_id,
        )
        entry.expected_interval_pips = adverse_interval.interval
        entry.actual_interval_pips = adverse_interval.adverse
        entry.validation_status = "pass"

        if cfg.stop_loss_enabled:
            assign_configured_stop_loss(entry, slot.index + 1)

        self.logger.info(
            "Counter add (%s) in cycle %d: L%d/R%d, units=%d, adverse=%.1f pips",
            direction.value.upper(),
            cycle.cycle_id,
            layer.layer_number,
            slot.index,
            units,
            adverse_interval.adverse,
        )

        event = SNOWBALL_EVENTS.entry_open_event(
            entry,
            timestamp=tick.timestamp,
            planned_exit_price_formula=formula,
            description=self.description_builder.format(
                direction=direction,
                layer=layer,
                slot=slot,
                units=units,
                adverse=adverse_interval.adverse,
                close_price=close_price,
                stop_loss_price=entry.stop_loss_price,
            ),
        )
        slot.fill(entry)
        ss.invalidate_entry_cache()
        layer.unseal_slots_above(slot.index)

        if cfg.counter_tp_mode != "weighted_avg":
            self.sync_step_counter_take_profits(strategy, direction, layer)

        return [event]

    def sync_step_counter_take_profits(
        self,
        strategy: CounterFlowStrategy,
        direction: Direction,
        layer: Layer,
    ) -> None:
        """Synchronize step TP prices for all counter slots in the layer."""
        calculator = self.calculator_provider.for_strategy(strategy)
        for slot in layer.slots:
            if slot.index == 0 or slot.entry is None or slot.entry.is_hedge:
                continue
            step_tp = calculator.counter_tp_pips(slot.index)
            if direction == Direction.LONG:
                slot.entry.close_price = slot.entry.entry_price + step_tp * strategy.pip_size
            else:
                slot.entry.close_price = slot.entry.entry_price - step_tp * strategy.pip_size

    def _close_price_and_formula(
        self,
        *,
        strategy: CounterFlowStrategy,
        cfg: SnowballStrategyConfig,
        direction: Direction,
        layer: Layer,
        slot: Slot,
        units: int,
        new_price: Decimal,
        head_context: CounterHeadContext,
    ) -> tuple[Decimal, str]:
        if cfg.counter_tp_mode == "weighted_avg":
            return SNOWBALL_PRICING.weighted_avg_close_price(
                layer,
                new_price=new_price,
                new_units=units,
                include_ref=self._layer_reference(layer=layer, head_context=head_context),
            )

        tp = self.calculator_provider.for_strategy(strategy).counter_tp_pips(slot.index)
        if direction == Direction.LONG:
            close_price = new_price + tp * strategy.pip_size
        else:
            close_price = new_price - tp * strategy.pip_size
        op = "+" if direction == Direction.LONG else "-"
        return close_price, f"{new_price} {op} {tp} * {strategy.pip_size}"

    def _layer_reference(
        self,
        *,
        layer: Layer,
        head_context: CounterHeadContext,
    ) -> Entry | None:
        r0 = layer.slot_at(0)
        if r0 is not None and (r0.entry is not None or r0.pending_rebuild is not None):
            return None
        return head_context.entry


class SnowballCounterAddProcessor:
    """Open counter entries or layer-initial entries when thresholds are met."""

    def __init__(
        self,
        *,
        slot_selector: CounterSlotSelector | None = None,
        entry_factory: CounterEntryFactory | None = None,
        price_service: CounterPriceService | None = None,
        grid_policy: SnowballGridPolicy | None = None,
    ) -> None:
        self.price_service = price_service or CounterPriceService()
        self.grid_policy = grid_policy or SNOWBALL_GRID_POLICY
        self.slot_selector = slot_selector or CounterSlotSelector(
            price_service=self.price_service,
            grid_policy=self.grid_policy,
        )
        self.entry_factory = entry_factory or CounterEntryFactory(price_service=self.price_service)

    def process(
        self,
        strategy: CounterFlowStrategy,
        ss: SnowballStrategyState,
        tick: Tick,
        cycle: SnowballCycle,
        *,
        open_layer_initial: Callable[
            [SnowballStrategyState, Tick, SnowballCycle],
            list[StrategyEvent],
        ],
        assign_configured_stop_loss: Callable[[Entry, int], None],
    ) -> list[StrategyEvent]:
        """Add a new counter entry if adverse distance threshold is met."""
        if cycle.completed:
            return []
        layer = cycle.current_layer
        if layer is None:
            return []

        head_context = self.slot_selector.head_context(cycle=cycle, layer=layer)
        if head_context is None:
            return []

        if layer.needs_new_layer:
            return self._open_new_layer_if_ready(
                strategy=strategy,
                ss=ss,
                tick=tick,
                cycle=cycle,
                layer=layer,
                head_context=head_context,
                open_layer_initial=open_layer_initial,
            )

        slot = layer.next_available_counter_slot()
        if slot is None:
            return []
        if not self.slot_selector.head_losing(
            strategy=strategy,
            tick=tick,
            head_context=head_context,
        ):
            return []

        adverse_interval = self.slot_selector.counter_slot_adverse_interval(
            strategy=strategy,
            tick=tick,
            cycle=cycle,
            layer=layer,
            slot=slot,
            head_entry_price=head_context.entry_price,
        )
        if adverse_interval is None or adverse_interval.adverse < adverse_interval.interval:
            return []

        new_price = self.price_service.entry_side_price(cycle.direction, tick)
        if self.slot_selector.violates_preceding_entry_bound(
            cycle=cycle,
            layer=layer,
            slot=slot,
            new_price=new_price,
        ):
            return []

        return self.entry_factory.open_counter_entry(
            strategy,
            ss,
            tick,
            cycle,
            layer,
            slot,
            adverse_interval,
            head_context,
            assign_configured_stop_loss=assign_configured_stop_loss,
        )

    def _open_new_layer_if_ready(
        self,
        *,
        strategy: CounterFlowStrategy,
        ss: SnowballStrategyState,
        tick: Tick,
        cycle: SnowballCycle,
        layer: Layer,
        head_context: CounterHeadContext,
        open_layer_initial: Callable[
            [SnowballStrategyState, Tick, SnowballCycle],
            list[StrategyEvent],
        ],
    ) -> list[StrategyEvent]:
        cfg = strategy.config
        if cycle.layer_count >= cfg.f_max:
            return []
        if not self.slot_selector.head_losing(
            strategy=strategy,
            tick=tick,
            head_context=head_context,
        ):
            return []
        if not self.slot_selector.new_layer_interval_hit(
            strategy=strategy,
            tick=tick,
            cycle=cycle,
            layer=layer,
        ):
            return []
        return open_layer_initial(ss, tick, cycle)
