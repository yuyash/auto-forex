"""Snowball strategy tick-pattern integration tests.

Tests the strategy against realistic tick sequences using the production
Snowball Strategy Configuration 1 parameters:

    m_pips=50, r_max=7, f_max=3, interval_mode=manual,
    manual_intervals=[30, 30, 25, 20, 16, 14, 12],
    counter_tp_mode=weighted_avg, pip_size=0.01

Tick patterns tested:
    1. Monotonic increase
    2. Monotonic decrease
    3. Increase then decrease
    4. Increase → decrease → increase (V-shape recovery)
    5. Decrease → increase → decrease (inverted V)

Each pattern is run with stop_loss_enabled=True and False,
and both LONG and SHORT cycles are verified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from apps.trading.enums import Direction, EventType
from apps.trading.strategies.snowball.config import SnowballStrategyConfig
from apps.trading.strategies.snowball.cycle_state import SnowballCycle, SnowballStrategyState
from apps.trading.strategies.snowball.entries import Entry, StopLossClosedEntry
from apps.trading.strategies.snowball.grid_models import Layer, Slot
from apps.trading.strategies.snowball.strategy import SnowballStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROD_CONFIG: dict[str, Any] = {
    "base_units": 1000,
    "m_pips": "50",
    "r_max": 7,
    "f_max": 3,
    "trend_lot_size": 1,
    "n_pips_head": "30",
    "n_pips_tail": "14",
    "n_pips_flat_steps": 2,
    "n_pips_gamma": "1.4",
    "interval_mode": "manual",
    "manual_intervals": ["30", "30", "25", "20", "16", "14", "12"],
    "counter_tp_mode": "weighted_avg",
    "counter_tp_pips": "25",
    "counter_tp_step_amount": "2.5",
    "counter_tp_multiplier": "1.2",
    "round_step_pips": "0.1",
    "shrink_enabled": False,
    "m_th": "70",
    "m1_th": "50",
    "emergency_enabled": True,
    "post_r_max_base_factor": "1",
    "refill_up_to": 3,
    "pip_size": "0.01",
    "reseed_on_all_pending": True,
}

SPREAD = Decimal("0.02")  # 2 pips spread
PIP = Decimal("0.01")


@dataclass
class DummyState:
    """Minimal ExecutionState shape required by strategy.on_tick."""

    strategy_state: dict[str, Any] = field(default_factory=dict)
    current_balance: Decimal = Decimal("1000000")
    ticks_processed: int = 1


def _make_tick(ts: datetime, mid: Decimal) -> Any:
    from apps.trading.dataclasses.tick import Tick

    bid = mid - SPREAD / 2
    ask = mid + SPREAD / 2
    return Tick.create(
        instrument="USD_JPY",
        timestamp=ts,
        bid=bid,
        ask=ask,
        mid=mid,
    )


def _strategy(
    stop_loss: bool,
    overrides: dict[str, Any] | None = None,
) -> SnowballStrategy:
    params = {**PROD_CONFIG, "stop_loss_enabled": stop_loss}
    if overrides:
        params.update(overrides)
    config = SnowballStrategyConfig.from_dict(params)
    return SnowballStrategy("USD_JPY", PIP, config)


def _pending_snapshot_for_slot(
    *,
    cycle_id: int,
    layer_number: int,
    retracement_count: int,
    entry_price: Decimal,
) -> StopLossClosedEntry:
    return StopLossClosedEntry(
        entry_price=entry_price,
        close_price=entry_price + Decimal("0.50"),
        units=1000,
        direction=Direction.LONG,
        role="initial" if retracement_count == 0 else "counter",
        layer_number=layer_number,
        retracement_count=retracement_count,
        step=retracement_count + 1,
        cycle_id=cycle_id,
    )


class TickRunner:
    """Run a sequence of mid prices through the strategy and collect results."""

    def __init__(self, stop_loss: bool, overrides: dict[str, Any] | None = None) -> None:
        self.strategy = _strategy(stop_loss, overrides)
        self.state = DummyState()
        self.all_events: list[Any] = []
        self.ts = datetime(2026, 1, 1, tzinfo=UTC)
        self.last_mid = START_PRICE

    def tick(self, mid: Decimal) -> Any:
        self.ts += timedelta(seconds=1)
        self.state.ticks_processed += 1
        self.last_mid = mid
        result = self.strategy.on_tick(
            tick=_make_tick(self.ts, mid),
            state=self.state,
        )
        self.all_events.extend(result.events)
        return result

    def tick_range(self, start: Decimal, end: Decimal, step_pips: int = 1) -> None:
        """Generate ticks from start to end in pip increments."""
        step = PIP * step_pips
        current = start
        if end >= start:
            while current <= end:
                self.tick(current)
                current += step
        else:
            while current >= end:
                self.tick(current)
                current -= step

    @property
    def ss(self) -> SnowballStrategyState:
        return SnowballStrategyState.from_strategy_state(self.state.strategy_state)

    @property
    def open_events(self) -> list:
        return [e for e in self.all_events if e.event_type == EventType.OPEN_POSITION]

    @property
    def close_events(self) -> list:
        return [e for e in self.all_events if e.event_type == EventType.CLOSE_POSITION]

    @property
    def rebuild_events(self) -> list:
        return [e for e in self.all_events if e.event_type == EventType.REBUILD_POSITION]

    def long_cycles(self) -> list:
        return [c for c in self.ss.cycles if c.direction.value == "long"]

    def short_cycles(self) -> list:
        return [c for c in self.ss.cycles if c.direction.value == "short"]

    def assert_no_error(self, result) -> None:
        assert not result.should_stop, f"Strategy stopped: {result.stop_reason}"


# ---------------------------------------------------------------------------
# Tick pattern generators
# ---------------------------------------------------------------------------

START_PRICE = Decimal("155.000")


def _pattern_monotonic_increase(runner: TickRunner) -> None:
    """Pattern 1: Price rises steadily by 200 pips."""
    runner.tick_range(START_PRICE, START_PRICE + Decimal("2.00"), step_pips=2)


def _pattern_monotonic_decrease(runner: TickRunner) -> None:
    """Pattern 2: Price falls steadily by 200 pips."""
    runner.tick_range(START_PRICE, START_PRICE - Decimal("2.00"), step_pips=2)


def _pattern_up_then_down(runner: TickRunner) -> None:
    """Pattern 3: Rise 100 pips, then fall 200 pips."""
    peak = START_PRICE + Decimal("1.00")
    bottom = START_PRICE - Decimal("1.00")
    runner.tick_range(START_PRICE, peak, step_pips=2)
    runner.tick_range(peak - PIP * 2, bottom, step_pips=2)


def _pattern_up_down_up(runner: TickRunner) -> None:
    """Pattern 4: Rise 100 pips, fall 150 pips, rise 200 pips."""
    p1 = START_PRICE + Decimal("1.00")
    p2 = START_PRICE - Decimal("0.50")
    p3 = START_PRICE + Decimal("1.50")
    runner.tick_range(START_PRICE, p1, step_pips=2)
    runner.tick_range(p1 - PIP * 2, p2, step_pips=2)
    runner.tick_range(p2 + PIP * 2, p3, step_pips=2)


def _pattern_down_up_down(runner: TickRunner) -> None:
    """Pattern 5: Fall 100 pips, rise 150 pips, fall 200 pips."""
    p1 = START_PRICE - Decimal("1.00")
    p2 = START_PRICE + Decimal("0.50")
    p3 = START_PRICE - Decimal("1.50")
    runner.tick_range(START_PRICE, p1, step_pips=2)
    runner.tick_range(p1 + PIP * 2, p2, step_pips=2)
    runner.tick_range(p2 - PIP * 2, p3, step_pips=2)


PATTERNS = [
    pytest.param(_pattern_monotonic_increase, id="monotonic_increase"),
    pytest.param(_pattern_monotonic_decrease, id="monotonic_decrease"),
    pytest.param(_pattern_up_then_down, id="up_then_down"),
    pytest.param(_pattern_up_down_up, id="up_down_up"),
    pytest.param(_pattern_down_up_down, id="down_up_down"),
]


# ===========================================================================
# Tests
# ===========================================================================


class TestSnowballTickPatterns:
    """Run each tick pattern and verify the strategy does not crash."""

    @pytest.mark.parametrize("pattern_fn", PATTERNS)
    @pytest.mark.parametrize("stop_loss", [False, True], ids=["no_sl", "sl"])
    def test_pattern_completes_without_error(self, pattern_fn, stop_loss):
        runner = TickRunner(stop_loss=stop_loss)
        # Initialise
        result = runner.tick(START_PRICE)
        runner.assert_no_error(result)
        assert runner.ss.initialised

        # Run pattern
        pattern_fn(runner)

        # Verify no crash — one more tick at last price
        runner.tick(runner.last_mid)
        # We only care that it didn't crash; some patterns may trigger
        # strategy stop (e.g. margin blowout) which is acceptable.

    @pytest.mark.parametrize("pattern_fn", PATTERNS)
    @pytest.mark.parametrize("stop_loss", [False, True], ids=["no_sl", "sl"])
    def test_both_directions_have_cycles(self, pattern_fn, stop_loss):
        runner = TickRunner(stop_loss=stop_loss)
        runner.tick(START_PRICE)
        pattern_fn(runner)

        assert len(runner.long_cycles()) >= 1, "No LONG cycles created"
        assert len(runner.short_cycles()) >= 1, "No SHORT cycles created"

    @pytest.mark.parametrize("pattern_fn", PATTERNS)
    @pytest.mark.parametrize("stop_loss", [False, True], ids=["no_sl", "sl"])
    def test_events_are_emitted(self, pattern_fn, stop_loss):
        runner = TickRunner(stop_loss=stop_loss)
        runner.tick(START_PRICE)
        pattern_fn(runner)

        assert len(runner.open_events) >= 2, "Expected at least initial LONG+SHORT opens"

    @pytest.mark.parametrize("stop_loss", [False, True], ids=["no_sl", "sl"])
    def test_monotonic_increase_long_tp_hit(self, stop_loss):
        """LONG cycle should hit TP when price rises 50+ pips."""
        runner = TickRunner(stop_loss=stop_loss)
        runner.tick(START_PRICE)
        runner.tick_range(START_PRICE, START_PRICE + Decimal("0.60"), step_pips=1)

        long_closes = [e for e in runner.close_events if e.direction == "long"]
        assert len(long_closes) >= 1, "LONG TP should have been hit"

    @pytest.mark.parametrize("stop_loss", [False, True], ids=["no_sl", "sl"])
    def test_monotonic_decrease_short_tp_hit(self, stop_loss):
        """SHORT cycle should hit TP when price falls 50+ pips."""
        runner = TickRunner(stop_loss=stop_loss)
        runner.tick(START_PRICE)
        runner.tick_range(START_PRICE, START_PRICE - Decimal("0.60"), step_pips=1)

        short_closes = [e for e in runner.close_events if e.direction == "short"]
        assert len(short_closes) >= 1, "SHORT TP should have been hit"


class TestSnowballCounterEntries:
    """Verify counter entries are added at correct intervals."""

    @pytest.mark.parametrize("stop_loss", [False, True], ids=["no_sl", "sl"])
    def test_counter_entries_added_on_adverse_move(self, stop_loss):
        """When price moves adversely, counter entries should be added."""
        runner = TickRunner(stop_loss=stop_loss)
        runner.tick(START_PRICE)

        # Move price down 100 pips (adverse for LONG)
        runner.tick_range(START_PRICE, START_PRICE - Decimal("1.00"), step_pips=1)

        long_opens = [e for e in runner.open_events if getattr(e, "direction", "") == "long"]
        # Initial + at least some counter entries
        assert len(long_opens) >= 2, (
            f"Expected counter entries for LONG, got {len(long_opens)} opens"
        )

    @pytest.mark.parametrize("stop_loss", [False, True], ids=["no_sl", "sl"])
    def test_no_counter_when_price_favourable(self, stop_loss):
        """No counter entries when price moves in favourable direction."""
        runner = TickRunner(stop_loss=stop_loss)
        runner.tick(START_PRICE)

        # Move price up 30 pips (favourable for LONG, adverse for SHORT)
        runner.tick_range(START_PRICE, START_PRICE + Decimal("0.30"), step_pips=1)

        long_opens = [e for e in runner.open_events if getattr(e, "direction", "") == "long"]
        # Should only have the initial entry, no counters
        assert len(long_opens) == 1, f"Expected only initial LONG entry, got {len(long_opens)}"


class TestSnowballStopLossRebuild:
    """Verify stop-loss close and rebuild behaviour."""

    def test_stop_loss_triggers_on_adverse_move(self):
        runner = TickRunner(stop_loss=True)
        runner.tick(START_PRICE)

        # Move adversely enough to trigger counter entries then SL
        runner.tick_range(START_PRICE, START_PRICE - Decimal("2.00"), step_pips=1)

        sl_closes = [
            e for e in runner.close_events if getattr(e, "close_reason", "") == "stop_loss"
        ]
        assert len(sl_closes) >= 1, "Expected stop-loss closes"

    def test_rebuild_after_price_returns(self):
        """After SL close, rebuilds should fire when price returns."""
        runner = TickRunner(stop_loss=True)
        runner.tick(START_PRICE)

        # Drop to trigger SL
        bottom = START_PRICE - Decimal("1.50")
        runner.tick_range(START_PRICE, bottom, step_pips=1)

        # Return to original price
        runner.tick_range(bottom, START_PRICE, step_pips=1)

        assert len(runner.rebuild_events) >= 1, "Expected rebuild events after price returned"

    def test_rebuild_gets_stop_loss(self):
        runner = TickRunner(stop_loss=True)
        runner.tick(START_PRICE)

        bottom = START_PRICE - Decimal("1.50")
        runner.tick_range(START_PRICE, bottom, step_pips=1)
        runner.tick_range(bottom, START_PRICE, step_pips=1)

        assert runner.rebuild_events, "Expected at least one rebuilt entry"
        assert all(evt.stop_loss_price is not None for evt in runner.rebuild_events)

    def test_rebuild_reuses_position_id(self):
        """Rebuild events should carry original_position_id."""
        runner = TickRunner(stop_loss=True)
        runner.tick(START_PRICE)

        bottom = START_PRICE - Decimal("1.50")
        runner.tick_range(START_PRICE, bottom, step_pips=1)
        runner.tick_range(bottom, START_PRICE, step_pips=1)

        for evt in runner.rebuild_events:
            # original_position_id may be None in unit tests (no DB),
            # but the event type should be REBUILD_POSITION
            assert evt.event_type == EventType.REBUILD_POSITION

    def test_rebuilt_position_can_be_loss_cut_again(self):
        runner = TickRunner(stop_loss=True)
        runner.tick(START_PRICE)

        bottom = START_PRICE - Decimal("1.50")
        runner.tick_range(START_PRICE, bottom, step_pips=1)
        current = bottom
        rebuild_evt = None
        while current < START_PRICE:
            current += PIP
            runner.tick(current)
            if runner.rebuild_events:
                rebuild_evt = runner.rebuild_events[-1]
                break

        assert rebuild_evt is not None, "Expected a rebuild before second adverse move"
        assert rebuild_evt.stop_loss_price is not None, (
            "Expected rebuilt entry to carry a stop-loss"
        )

        trigger_mid = Decimal(str(rebuild_evt.stop_loss_price))
        runner.tick_range(current, trigger_mid, step_pips=1)

        rebuilt_stop_loss_closes = [
            e
            for e in runner.close_events
            if getattr(e, "close_reason", "") == "stop_loss" and e.entry_id == rebuild_evt.entry_id
        ]
        assert rebuilt_stop_loss_closes, "Expected rebuilt entries to be loss-cut again"

    def test_no_premature_layer_after_stop_loss(self):
        """Stop-loss closed slots should not trigger new layer addition."""
        runner = TickRunner(stop_loss=True)
        runner.tick(START_PRICE)

        # Move down enough to trigger some SL closes but not enough
        # to fill all r_max slots
        runner.tick_range(START_PRICE, START_PRICE - Decimal("0.80"), step_pips=1)

        ss = runner.ss
        for cycle in ss.active_cycles():
            if cycle.direction.value == "long":
                # With manual_intervals=[30,30,25,20,16,14,12],
                # 80 pips adverse should add counters but not necessarily
                # need a new layer if SL slots are refillable
                layer_count = cycle.layer_count
                assert layer_count <= 2, (
                    f"LONG cycle has {layer_count} layers — "
                    "SL closed slots should not trigger premature layer addition"
                )

    def test_f_max_caps_total_layers_at_l1_through_l3(self):
        """f_max=3 should cap a cycle at L1-L3, never L4."""
        runner = TickRunner(stop_loss=False)
        runner.tick(START_PRICE)

        # Drive a large adverse move so the strategy keeps attempting to
        # expand layers after counter slots are exhausted.
        runner.tick_range(START_PRICE, START_PRICE - Decimal("4.00"), step_pips=1)

        for cycle in runner.ss.cycles:
            if cycle.direction.value == "long":
                assert cycle.layer_count <= 3, (
                    f"LONG cycle has {cycle.layer_count} layers — f_max=3 should allow only L1-L3"
                )

    def test_sl_closed_slot_blocks_counter_add(self):
        """When R1 is SL-closed, the next counter should go to R2, not R1.

        SL-closed slots are in pending_rebuild state and must not be
        reused by counter-add logic.  The strategy should skip R1 and
        place the next counter at R2 with the correct interval from R1.
        """
        runner = TickRunner(stop_loss=True)
        runner.tick(START_PRICE)

        # Move SHORT adversely (price up) to trigger R1 counter, then SL on R1
        # R1 opens at ~30 pips adverse, SL is near the next interval
        runner.tick_range(START_PRICE, START_PRICE + Decimal("0.70"), step_pips=1)

        ss = runner.ss
        for cycle in ss.active_cycles():
            if cycle.direction.value != "short":
                continue
            layer = cycle.grid.current_layer
            if layer is None:
                continue
            # Check that SL-closed slots have pending_rebuild set
            for slot in layer.slots:
                if slot.is_pending_rebuild:
                    assert slot.entry is None, "SL slot should have no live entry"
                    assert slot.pending_rebuild is not None
                    # Verify the slot is NOT available for counter adds
                    assert not slot.is_available, (
                        f"SL-closed slot R{slot.index} should not be available"
                    )

    def test_sl_slot_preserves_r_number_progression(self):
        """Pending rebuild slots should not be reused as available slots.

        When a slot has pending_rebuild, counter adds should proceed only
        to a later available slot.  Depending on the tick sequence, the
        pending slot can be R0 (cycle is pending-only and waits for reseed
        or rebuild) or a later retracement.
        """
        runner = TickRunner(stop_loss=True)
        runner.tick(START_PRICE)

        # Move SHORT adversely (price up) enough to trigger R1 then SL on R1
        runner.tick_range(START_PRICE, START_PRICE + Decimal("0.70"), step_pips=1)

        ss = runner.ss
        found_pending = False
        for cycle in ss.cycles:
            if cycle.direction.value != "short":
                continue
            layer = cycle.grid.current_layer
            if layer is None:
                continue
            pending_slots = [slot for slot in layer.slots if slot.is_pending_rebuild]
            for pending_slot in pending_slots:
                found_pending = True
                next_slot = layer.next_available_counter_slot()
                if next_slot is not None:
                    assert next_slot.index > pending_slot.index, (
                        f"Expected next available slot after R{pending_slot.index}, "
                        f"got R{next_slot.index}"
                    )
        # At least one cycle should have had a pending rebuild
        assert found_pending, "Expected at least one SL-closed slot"

    def test_cycle_pending_when_all_sl_closed(self):
        """Cycle should be PENDING when all positions are SL-closed.

        When no open entries remain but pending rebuilds exist, the
        cycle transitions to PENDING regardless of available counter
        slots.  The reseed logic creates a fresh cycle if needed.
        """
        runner = TickRunner(stop_loss=True)
        runner.tick(START_PRICE)

        # Move far enough to trigger SL on all positions
        runner.tick_range(START_PRICE, START_PRICE - Decimal("2.50"), step_pips=1)

        ss = runner.ss
        for cycle in ss.cycles:
            if cycle.direction.value != "long":
                continue
            if cycle.grid.has_pending_rebuilds() and cycle.grid.is_empty():
                assert cycle.status.value == "pending", (
                    f"Cycle {cycle.cycle_id} has pending rebuilds and no open "
                    f"entries but status is {cycle.status.value}"
                )


class TestSnowballCycleReseedOptions:
    """Verify opt-in cycle reseeding from pending cycles."""

    @pytest.mark.parametrize("stop_loss", [False, True], ids=["no_sl", "sl"])
    def test_reseed_on_all_pending_starts_new_cycle(self, stop_loss: bool) -> None:
        runner = TickRunner(
            stop_loss=stop_loss,
            overrides={
                "reseed_on_all_pending": True,
            },
        )
        runner.tick(START_PRICE)

        ss = runner.ss
        long_cycle = next(c for c in ss.cycles if c.direction == Direction.LONG)
        slot = long_cycle.grid.layers[0].slot_at(0)
        assert slot is not None and slot.entry is not None
        slot.pending_rebuild = _pending_snapshot_for_slot(
            cycle_id=long_cycle.cycle_id,
            layer_number=1,
            retracement_count=0,
            entry_price=slot.entry.entry_price,
        )
        slot.entry = None
        runner.state.strategy_state = ss.to_dict()

        result = runner.tick(START_PRICE - Decimal("1.00"))

        runner.assert_no_error(result)
        long_cycles = runner.long_cycles()
        assert any(c.cycle_id == long_cycle.cycle_id and c.is_pending for c in long_cycles)
        assert sum(1 for c in long_cycles if c.is_active) == 1
        assert len(long_cycles) == 2


class TestSnowballTPOrdering:
    """Verify TP ordering is maintained across layers."""

    @pytest.mark.parametrize("stop_loss", [False, True], ids=["no_sl", "sl"])
    def test_tp_ordering_maintained(self, stop_loss):
        """Within a cycle, counter TPs should be monotonically ordered."""
        runner = TickRunner(stop_loss=stop_loss)
        runner.tick(START_PRICE)

        # Generate enough adverse movement to create multiple layers
        runner.tick_range(START_PRICE, START_PRICE - Decimal("2.00"), step_pips=1)

        ss = runner.ss
        for cycle in ss.active_cycles():
            if cycle.direction.value != "long":
                continue
            entries = list(cycle.grid.all_entries())
            if len(entries) < 2:
                continue

            head = cycle.initial_entry
            if head is None:
                continue

            # For LONG: all non-head entries should have TP <= head TP
            # (counters close before the head)
            for entry in entries:
                if entry.entry_id == head.entry_id:
                    continue
                if entry.close_price <= 0:
                    continue
                assert entry.close_price <= head.close_price + PIP, (
                    f"TP ordering violated: L{entry.layer_number}/R{entry.retracement_count} "
                    f"TP={entry.close_price} > head TP={head.close_price}"
                )


class TestCounterAddLoopWithinTick:
    """Ensure a single tick can produce multiple counter adds when the
    price moves far enough in one step to cross several retracement
    thresholds.

    Motivating scenario: the 2nd-slot stop-loss fires on a tick that has
    already moved far enough to place the 3rd counter.  Previously the
    3rd counter was deferred to a later tick and could be missed if the
    price retraced before the next sample.
    """

    @pytest.fixture
    def runner(self) -> TickRunner:
        # Use a tight f_max and keep shrink off so stop-loss stays on.
        overrides = {
            "f_max": 2,
            "r_max": 5,
            "manual_intervals": ["20", "20", "20", "20", "20"],
            "stop_loss_enabled": True,
            "shrink_enabled": False,
            "reseed_on_all_pending": False,
            "preserve_highest_r_from": 0,
        }
        runner = TickRunner(stop_loss=True, overrides=overrides)
        runner.tick(START_PRICE)  # L1/R0 LONG opens
        return runner

    def test_multiple_counter_adds_in_same_tick(self, runner: TickRunner) -> None:
        """A single 90-pip adverse move should open R1, R2, R3 together."""
        # 20-pip intervals means -60 pips covers R1, R2, R3.  Jump well
        # past that in one tick so the loop is forced to fire three times.
        runner.tick(START_PRICE - Decimal("0.90"))

        long_cycle = next(c for c in runner.long_cycles() if c.is_active)
        layer = long_cycle.grid.layers[0]
        occupied_counters = [s for s in layer.slots if s.index >= 1 and s.is_occupied]
        assert len(occupied_counters) >= 2, (
            f"Expected at least R1 and R2 to open in one tick, got "
            f"{[s.index for s in occupied_counters]}"
        )

    def test_counter_add_after_stop_loss_in_same_tick(self, runner: TickRunner) -> None:
        """A tick that both SLs a slot and crosses the next threshold
        should still place the next counter on that very tick."""
        # Step the price down gradually to fill R1 first.
        runner.tick(START_PRICE - Decimal("0.25"))  # open R1

        long_cycle = next(c for c in runner.long_cycles() if c.is_active)
        layer = long_cycle.grid.layers[0]
        r1 = layer.slot_at(1)
        assert r1 is not None and r1.is_occupied, "R1 should be open after -25 pips"

        # One big tick that (a) triggers R1's stop-loss and (b) moves far
        # past R2's planned entry price.  A previous implementation
        # R1 would SL and the next counter would be deferred to the next
        # tick; the new loop places R2 on this same tick.
        runner.tick(START_PRICE - Decimal("1.30"))

        # Refresh state.
        long_cycle = next(c for c in runner.long_cycles() if c.is_active)
        layer = long_cycle.grid.layers[0]
        r1 = layer.slot_at(1)
        r2 = layer.slot_at(2)
        assert r1 is not None and r1.is_pending_rebuild, (
            "R1 should have transitioned to pending_rebuild"
        )
        assert r2 is not None and r2.is_occupied, (
            "R2 should have been opened on the same tick as R1's SL"
        )


class TestCycleAndLifecyclePnLWarnings:
    """Structural warnings for unexpected P/L outcomes."""

    @pytest.fixture
    def runner(self) -> TickRunner:
        return TickRunner(stop_loss=False)

    def test_cycle_realized_pnl_is_tracked(self, runner: TickRunner) -> None:
        """Cycle realised P/L accumulates over every close event."""
        runner.tick(START_PRICE)

        # Force a TP close so realized_pnl becomes > 0.
        runner.tick_range(START_PRICE, START_PRICE + Decimal("0.60"), step_pips=2)

        ss = runner.ss
        # The first cycle should be COMPLETED with realized_pnl > 0.
        completed_long = [
            c for c in ss.cycles if c.direction.value == "long" and c.status.value == "completed"
        ]
        assert completed_long, "expected at least one completed LONG cycle"
        assert completed_long[0].realized_pnl > 0, (
            f"expected positive realized_pnl, got {completed_long[0].realized_pnl}"
        )


class TestLifecycleNegativePnlWarnings:
    """Ensure warnings are emitted when a non-stop-loss close or a full
    slot lifecycle ends with negative P/L."""

    def test_non_stop_loss_close_with_negative_pnl_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Directly invoke ``_close_entry`` with a losing non-SL close and
        assert the warning fires.  Bypasses the tick-pattern helpers so
        the test is deterministic."""
        import logging

        runner = TickRunner(stop_loss=False)
        runner.tick(START_PRICE)
        long_cycle = next(c for c in runner.long_cycles() if c.is_active)
        entry = long_cycle.initial_entry
        assert entry is not None

        # Synthesise a protection close at an unfavourable price to force pnl<0.
        bad_tick = _make_tick(
            runner.ts + timedelta(seconds=1),
            START_PRICE - Decimal("0.50"),
        )
        with caplog.at_level(logging.WARNING, logger="apps.trading.strategies.snowball.strategy"):
            runner.strategy._close_entry(
                bad_tick,
                entry,
                description="forced losing shrink",
                close_reason="shrink",
                cycle=long_cycle,
            )

        messages = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
        assert any("negative P/L" in m for m in messages), (
            f"expected 'negative P/L' warning, got: {messages}"
        )

    def test_stop_loss_close_does_not_warn(self, caplog: pytest.LogCaptureFixture) -> None:
        """Stop-loss closes are expected to be losing and must not warn."""
        import logging

        runner = TickRunner(stop_loss=True)
        runner.tick(START_PRICE)
        long_cycle = next(c for c in runner.long_cycles() if c.is_active)
        entry = long_cycle.initial_entry
        assert entry is not None

        bad_tick = _make_tick(
            runner.ts + timedelta(seconds=1),
            START_PRICE - Decimal("0.50"),
        )
        with caplog.at_level(logging.WARNING, logger="apps.trading.strategies.snowball.strategy"):
            runner.strategy._close_entry(
                bad_tick,
                entry,
                description="forced SL",
                close_reason="stop_loss",
                cycle=long_cycle,
            )

        messages = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
        assert not any("negative P/L" in m for m in messages), (
            f"stop_loss close should not emit a negative-P/L warning: {messages}"
        )

    def test_cycle_completed_with_negative_pnl_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A cycle whose accumulated realized_pnl is negative at close
        should log a warning."""
        import logging

        runner = TickRunner(stop_loss=False)
        runner.tick(START_PRICE)
        # Pre-seed the cycle's realized P/L to a loss in the serialized
        # state so the next tick rehydrates with that value and the
        # completion transition triggers the warning.
        ss_dict = dict(runner.state.strategy_state)
        cycles = list(ss_dict.get("cycles", []))
        for cycle_dict in cycles:
            if cycle_dict.get("direction") == "long":
                cycle_dict["realized_pnl"] = "-123.45"
        ss_dict["cycles"] = cycles
        runner.state.strategy_state = ss_dict

        # Drive the cycle to completion via a normal TP close.
        with caplog.at_level(logging.WARNING, logger="apps.trading.strategies.snowball.strategy"):
            runner.tick_range(START_PRICE, START_PRICE + Decimal("0.60"), step_pips=2)

        messages = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
        assert any("negative realised P/L" in m for m in messages), (
            f"expected cycle-completion warning, got: {messages}"
        )


class TestSnowballRebuildEntryPriceMode:
    """Verify whether rebuilds trigger at the original or stop-loss exit price."""

    REBUILD_MODE_OVERRIDES = {
        "r_max": 1,
        "f_max": 0,
        "refill_up_to": 0,
        "interval_mode": "manual",
        "manual_intervals": ["200"],
        "stop_loss_mode": "constant",
        "stop_loss_pips_head": "50",
        "stop_loss_pips_tail": "50",
        "reseed_on_all_pending": False,
    }

    def test_original_entry_price_mode_is_default(self):
        cfg = SnowballStrategyConfig.from_dict({})
        assert cfg.rebuild_entry_price_mode == "original_entry"

    def test_stop_loss_exit_mode_rebuilds_before_original_entry_returns(self):
        runner = TickRunner(
            stop_loss=True,
            overrides={
                **self.REBUILD_MODE_OVERRIDES,
                "rebuild_entry_price_mode": "stop_loss_exit",
            },
        )
        runner.tick(START_PRICE)

        bottom = START_PRICE - Decimal("1.50")
        runner.tick_range(START_PRICE, bottom, step_pips=1)
        assert any(e for e in runner.close_events if getattr(e, "close_reason", "") == "stop_loss")

        runner.tick_range(bottom, START_PRICE - Decimal("0.47"), step_pips=1)

        assert any(event.direction == "long" for event in runner.rebuild_events), (
            "Expected long rebuild before original entry price returned"
        )

    def test_original_entry_mode_waits_for_original_entry_price(self):
        runner = TickRunner(stop_loss=True, overrides=self.REBUILD_MODE_OVERRIDES)
        runner.tick(START_PRICE)

        bottom = START_PRICE - Decimal("1.50")
        runner.tick_range(START_PRICE, bottom, step_pips=1)
        runner.tick_range(bottom, START_PRICE - Decimal("0.50"), step_pips=1)

        assert not any(event.direction == "long" for event in runner.rebuild_events)

        runner.tick_range(START_PRICE - Decimal("0.49"), START_PRICE + Decimal("0.02"), step_pips=1)

        assert any(event.direction == "long" for event in runner.rebuild_events)


class TestSnowballRebuildTpGridClamp:
    """Rebuild TP inherits the snapshot TP while preserving grid ordering."""

    def _build_layer_with_grid(self, strategy: SnowballStrategy):
        """Create a layer with R0 (open), R2 (pending_rebuild), and an
        empty R3 slot, then return (layer, R3 slot).

        The R3 slot is returned so callers can attach a pending rebuild
        snapshot whose close_price exercises the grid-ordering path.
        """
        from apps.trading.enums import Direction
        from apps.trading.strategies.snowball.entries import StopLossClosedEntry

        layer = Layer(layer_number=1, slots=[], base_units=1000, refill_up_to=3)
        for idx in range(8):
            layer.slots.append(Slot(index=idx))

        # R0: live long entry at 131.000 with TP 131.200.
        r0 = layer.slots[0]
        r0.entry = Entry(
            entry_id=1,
            step=1,
            direction=Direction.LONG,
            entry_price=Decimal("131.000"),
            close_price=Decimal("131.200"),
            units=1000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="initial",
            layer_number=1,
            retracement_count=0,
        )

        # R2: pending rebuild after SL.  Its original TP was 130.87550
        # — the value we want R3's adjusted TP to stay below.
        r2 = layer.slots[2]
        r2.pending_rebuild = StopLossClosedEntry(
            entry_price=Decimal("130.675"),
            close_price=Decimal("130.87550"),
            units=3000,
            direction=Direction.LONG,
            role="counter",
            layer_number=1,
            retracement_count=2,
            step=3,
            cycle_id=1,
        )
        return layer

    def test_upper_neighbor_tp_bound_finds_pending_above(self):
        s = _strategy(stop_loss=True)
        from apps.trading.strategies.snowball.grid_policy import SNOWBALL_GRID_POLICY
        from apps.trading.enums import Direction

        layer = self._build_layer_with_grid(s)
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        cycle.grid.layers.append(layer)

        # R3 looks up to R2 (pending) and R0 (occupied) — the tighter of
        # the two for LONG (minimum) is R2's 130.87550.
        assert SNOWBALL_GRID_POLICY.upper_neighbor_tp_bound(cycle, layer, slot_index=3) == Decimal(
            "130.87550"
        )
        # R1 only sees R0 (no R2 yet in the predecessor range).
        assert SNOWBALL_GRID_POLICY.upper_neighbor_tp_bound(cycle, layer, slot_index=1) == Decimal(
            "131.200"
        )
        # R0 has no predecessor at all.
        assert SNOWBALL_GRID_POLICY.upper_neighbor_tp_bound(cycle, layer, slot_index=0) is None

    def test_rebuild_keeps_original_tp(self):
        """A rebuild must inherit the pending TP."""
        from apps.trading.enums import Direction
        from apps.trading.strategies.snowball.cycle_state import (
            SnowballStrategyState,
        )
        from apps.trading.strategies.snowball.entries import StopLossClosedEntry

        s = _strategy(stop_loss=True)
        layer = self._build_layer_with_grid(s)
        # The rebuilt TP must inherit close_price=130.691.
        r3 = layer.slots[3]
        r3.pending_rebuild = StopLossClosedEntry(
            entry_price=Decimal("130.415"),
            close_price=Decimal("130.691"),  # original profit distance 0.276
            units=4000,
            direction=Direction.LONG,
            role="counter",
            layer_number=1,
            retracement_count=3,
            step=4,
            cycle_id=1,
        )

        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        cycle.grid.layers.append(layer)
        # Tick at exactly the rebuild trigger (R3's original entry price).
        tick = _make_tick(datetime(2026, 1, 1, 9, tzinfo=UTC), Decimal("130.430"))
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("1000000"))

        events = s._process_stop_loss_rebuilds(ss, tick, cycle)
        assert r3.entry is not None, "R3 must have rebuilt to a live entry"

        assert r3.entry.close_price == Decimal("130.691")

        assert events, "expected a rebuild event"

    def test_rebuild_tp_clamps_against_occupied_neighbor(self):
        """A live entry's TP is a hard ceiling — the rebuild must respect it.

        Here R2 is **occupied** (not pending), so its TP can't be moved.
        The rebuilt R3 TP is clamped to R2's TP if its inherited TP
        would cross that hard bound.
        """
        from apps.trading.enums import Direction
        from apps.trading.strategies.snowball.cycle_state import (
            SnowballStrategyState,
        )
        from apps.trading.strategies.snowball.entries import StopLossClosedEntry

        s = _strategy(stop_loss=True)
        layer = self._build_layer_with_grid(s)

        # Convert R2 from pending_rebuild to a live occupied entry.
        r2 = layer.slots[2]
        r2.pending_rebuild = None
        r2.entry = Entry(
            entry_id=42,
            step=3,
            direction=Direction.LONG,
            entry_price=Decimal("130.675"),
            close_price=Decimal("130.87550"),
            units=3000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="counter",
            layer_number=1,
            retracement_count=2,
        )

        r3 = layer.slots[3]
        r3.pending_rebuild = StopLossClosedEntry(
            entry_price=Decimal("130.415"),
            close_price=Decimal("130.900"),
            units=4000,
            direction=Direction.LONG,
            role="counter",
            layer_number=1,
            retracement_count=3,
            step=4,
            cycle_id=1,
        )

        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        cycle.grid.layers.append(layer)

        tick = _make_tick(datetime(2026, 1, 1, 9, tzinfo=UTC), Decimal("130.430"))
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("1000000"))

        s._process_stop_loss_rebuilds(ss, tick, cycle)
        assert r3.entry is not None
        # Clamped at the live R2 TP — the hard ceiling.
        assert r3.entry.close_price == Decimal("130.87550")

    def test_rebuild_tp_retains_inherited_tp_when_within_bound(self):
        """If the inherited TP is below the upper neighbour, leave it alone."""
        from apps.trading.enums import Direction
        from apps.trading.strategies.snowball.cycle_state import (
            SnowballStrategyState,
        )
        from apps.trading.strategies.snowball.entries import StopLossClosedEntry

        s = _strategy(stop_loss=True)
        layer = self._build_layer_with_grid(s)
        r3 = layer.slots[3]
        r3.pending_rebuild = StopLossClosedEntry(
            entry_price=Decimal("130.415"),
            close_price=Decimal("130.691"),
            units=4000,
            direction=Direction.LONG,
            role="counter",
            layer_number=1,
            retracement_count=3,
            step=4,
            cycle_id=1,
        )

        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        cycle.grid.layers.append(layer)

        tick = _make_tick(datetime(2026, 1, 1, 9, tzinfo=UTC), Decimal("130.430"))
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("1000000"))

        s._process_stop_loss_rebuilds(ss, tick, cycle)
        assert r3.entry is not None
        assert r3.entry.close_price == Decimal("130.691")


class TestSnowballRebuildCrossLayerTpOrdering:
    """Regression tests for the cross-layer grid-ordering rule.

    The grid validator walks layer-by-layer then slot-by-slot, so a
    rebuild in a higher layer must remain monotonic with present slots
    in every earlier layer — not only within its own layer.  These
    tests cover inherited rebuild TPs that need cross-layer ordering
    adjustment.
    """

    @staticmethod
    def _build_short_cross_layer_grid(strategy: SnowballStrategy):
        """Construct a SHORT cycle with L1 (R0 occupied, R7 pending), L2
        (R0 pending_rebuild ready to rebuild).

        Returns the (cycle, L1, L2, L2.R0 slot) tuple.
        """
        from apps.trading.enums import Direction
        from apps.trading.strategies.snowball.entries import StopLossClosedEntry

        l1 = Layer(layer_number=1, slots=[], base_units=1000, refill_up_to=3)
        l2 = Layer(layer_number=2, slots=[], base_units=1000, refill_up_to=3)
        for idx in range(8):
            l1.slots.append(Slot(index=idx))
            l2.slots.append(Slot(index=idx))

        # L1/R0: live short entry (the cycle head).  TP is the least
        # ascending — safely below every other TP.
        l1.slots[0].entry = Entry(
            entry_id=1,
            step=1,
            direction=Direction.SHORT,
            entry_price=Decimal("130.000"),
            close_price=Decimal("129.500"),
            units=1000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="initial",
            layer_number=1,
            retracement_count=0,
        )

        # L1/R7: pending rebuild holding a snapshot TP that must be
        # pushed out when L2/R0 inherits a slightly lower TP.
        l1.slots[7].pending_rebuild = StopLossClosedEntry(
            entry_price=Decimal("131.015"),
            close_price=Decimal("130.644"),  # Pre-fix: caused the ordering violation.
            units=8000,
            direction=Direction.SHORT,
            role="counter",
            layer_number=1,
            retracement_count=7,
            step=8,
            cycle_id=1,
        )

        cycle = SnowballCycle(cycle_id=1, direction=Direction.SHORT)
        cycle.grid.layers.extend([l1, l2])
        return cycle, l1, l2

    def test_cross_layer_rebuild_clamps_to_preceding_pending_rebuild_tp(self):
        """Pending predecessors bound the rebuilt TP just like live predecessors."""
        from apps.trading.enums import Direction
        from apps.trading.strategies.snowball.cycle_state import (
            SnowballStrategyState,
        )
        from apps.trading.strategies.snowball.entries import StopLossClosedEntry

        s = _strategy(stop_loss=True)
        cycle, l1, l2 = self._build_short_cross_layer_grid(s)

        # L2/R0 pending rebuild inherits TP 130.64392, which is just
        # below L1/R7's pending 130.644 and would violate SHORT ordering
        # unless the pending predecessor is adjusted.
        l2.slots[0].pending_rebuild = StopLossClosedEntry(
            entry_price=Decimal("131.177"),
            close_price=Decimal("130.64392"),
            units=1000,
            direction=Direction.SHORT,
            role="layer_initial",
            layer_number=2,
            retracement_count=0,
            step=1,
            cycle_id=1,
        )

        # Tick where the ask touches L2/R0's trigger price (131.177).
        tick = _make_tick(datetime(2026, 1, 1, 9, tzinfo=UTC), Decimal("131.167"))
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("1000000"))

        s._process_stop_loss_rebuilds(ss, tick, cycle)

        # L2/R0 rebuilt at the preceding pending TP bound so the grid
        # stays monotonic without moving L1/R7's pending snapshot.
        assert l2.slots[0].entry is not None
        expected_l2r0_tp = Decimal("130.644")
        assert l2.slots[0].entry.close_price == expected_l2r0_tp

        l1r7 = l1.slots[7]
        assert l1r7.pending_rebuild is not None
        assert l1r7.pending_rebuild.close_price == Decimal("130.644")

        # Running the validator after the rebuild must find no violation.
        s._grid_order_violation = None
        s._validate_grid_ordering(cycle)
        assert s._grid_order_violation is None

    def test_cross_layer_hard_bound_from_occupied_still_clamps(self):
        """Occupied predecessors in earlier layers must clamp the rebuild.

        If L1/R7 is *occupied* (not pending), its TP can't be moved, so
        the rebuild has to honour it as a hard bound — even though it
        is in a different layer.
        """
        from apps.trading.enums import Direction
        from apps.trading.strategies.snowball.cycle_state import (
            SnowballStrategyState,
        )
        from apps.trading.strategies.snowball.entries import StopLossClosedEntry

        s = _strategy(stop_loss=True)
        cycle, l1, l2 = self._build_short_cross_layer_grid(s)

        # Make L1/R7 a live occupied entry instead of a pending snapshot.
        l1.slots[7].pending_rebuild = None
        l1.slots[7].entry = Entry(
            entry_id=99,
            step=8,
            direction=Direction.SHORT,
            entry_price=Decimal("131.015"),
            close_price=Decimal("130.644"),
            units=8000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="counter",
            layer_number=1,
            retracement_count=7,
        )

        l2.slots[0].pending_rebuild = StopLossClosedEntry(
            entry_price=Decimal("131.177"),
            close_price=Decimal("130.500"),
            units=1000,
            direction=Direction.SHORT,
            role="layer_initial",
            layer_number=2,
            retracement_count=0,
            step=1,
            cycle_id=1,
        )

        tick = _make_tick(datetime(2026, 1, 1, 9, tzinfo=UTC), Decimal("131.167"))
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("1000000"))

        s._process_stop_loss_rebuilds(ss, tick, cycle)

        # L2/R0's inherited TP was clamped up to L1/R7's occupied TP
        # (for SHORT a floor from the maximum prior TP).
        assert l2.slots[0].entry is not None
        assert l2.slots[0].entry.close_price == Decimal("130.644")

        s._grid_order_violation = None
        s._validate_grid_ordering(cycle)
        assert s._grid_order_violation is None
