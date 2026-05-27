"""Comprehensive unit tests for SnowballStrategy tick-driven behavior.

Covers: initialisation, trend basket rotation, counter basket adds/closes,
slot vacate after TP, layer progression, f_max exhaustion, margin
protection (shrink / emergency), spread guard, and
dynamic TP (ATR) scenarios.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import logging
from typing import Any

from apps.trading.dataclasses.tick import Tick
from apps.trading.dataclasses.execution import EntryExecutionBinding, EventExecutionResult
from apps.trading.enums import Direction
from apps.trading.events import (
    ClosePositionEvent,
    GenericStrategyEvent,
    OpenPositionEvent,
)
from apps.trading.strategies.snowball import strategy as snowball_strategy_module
from apps.trading.strategies.snowball.config import SnowballStrategyConfig
from apps.trading.strategies.snowball.cycle_state import SnowballCycle, SnowballStrategyState
from apps.trading.strategies.snowball.entries import Entry, StopLossClosedEntry
from apps.trading.strategies.snowball.grid_models import Layer
from apps.trading.strategies.snowball.strategy import SnowballStrategy

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


@dataclass
class DummyState:
    """Minimal state shape required by strategy.on_tick."""

    strategy_state: dict[str, Any] = field(default_factory=dict)
    current_balance: Decimal = Decimal("1000000")
    ticks_processed: int = 1


def _tick(ts: datetime, bid: str, ask: str) -> Tick:
    return Tick.create(
        instrument="USD_JPY",
        timestamp=ts,
        bid=Decimal(bid),
        ask=Decimal(ask),
    )


T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _strategy(**overrides) -> SnowballStrategy:
    params: dict[str, Any] = {
        "base_units": 1000,
        "m_pips": "50",
        "trend_lot_size": 1,
        "r_max": 7,
        "f_max": 3,
        "post_r_max_base_factor": "1",
        "n_pips_head": "30",
        "n_pips_tail": "14",
        "n_pips_flat_steps": 2,
        "n_pips_gamma": "1.4",
        "interval_mode": "constant",
        "counter_tp_mode": "fixed",
        "counter_tp_pips": "25",
        "counter_tp_step_amount": "2.5",
        "counter_tp_multiplier": "1.2",
        "round_step_pips": "0.1",
        "shrink_enabled": False,
        "m_th": "70",
        "pip_size": "0.01",
    }
    params.update(overrides)
    cfg = SnowballStrategyConfig.from_dict(params)
    return SnowballStrategy("USD_JPY", Decimal("0.01"), cfg)


def _open_events(result) -> list[OpenPositionEvent]:
    return [e for e in result.events if isinstance(e, OpenPositionEvent)]


def _close_events(result) -> list[ClosePositionEvent]:
    return [e for e in result.events if isinstance(e, ClosePositionEvent)]


def _signal_events(result, kind: str) -> list[GenericStrategyEvent]:
    return [
        e
        for e in result.events
        if isinstance(e, GenericStrategyEvent)
        and isinstance(e.data, dict)
        and e.data.get("kind") == kind
    ]


def test_next_available_counter_slot_blocks_refill_below_higher_present_slot():
    layer = Layer.create(3, 7, 1000, 5)
    layer.slot_at(0).fill(
        Entry(
            entry_id=1,
            step=1,
            direction=Direction.LONG,
            entry_price=Decimal("157.727"),
            close_price=Decimal("158.193"),
            units=1000,
            opened_at=T0,
            role="layer_initial",
            layer_number=3,
            retracement_count=0,
            root_entry_id=1,
        )
    )
    layer.slot_at(1).fill(
        Entry(
            entry_id=2,
            step=2,
            direction=Direction.LONG,
            entry_price=Decimal("157.427"),
            close_price=Decimal("157.738"),
            units=2000,
            opened_at=T0,
            role="counter",
            layer_number=3,
            retracement_count=1,
            root_entry_id=1,
            parent_entry_id=1,
        )
    )
    layer.slot_at(2).fill(
        Entry(
            entry_id=3,
            step=3,
            direction=Direction.LONG,
            entry_price=Decimal("157.118"),
            close_price=Decimal("157.377"),
            units=3000,
            opened_at=T0,
            role="counter",
            layer_number=3,
            retracement_count=2,
            root_entry_id=1,
            parent_entry_id=1,
        )
    )
    layer.slot_at(4).fill(
        Entry(
            entry_id=4,
            step=5,
            direction=Direction.LONG,
            entry_price=Decimal("155.380"),
            close_price=Decimal("156.157"),
            units=5000,
            opened_at=T0,
            role="counter",
            layer_number=3,
            retracement_count=4,
            root_entry_id=1,
            parent_entry_id=1,
        )
    )

    assert layer.next_available_counter_slot() is None
    assert layer.needs_new_layer is True


# ==================================================================
# 1. Initialisation
# ==================================================================


class TestInitialisation:
    def test_first_tick_creates_long_and_short_cycles(self):
        s = _strategy()
        state = DummyState()
        result = s.on_tick(tick=_tick(T0, "150.00", "150.02"), state=state)
        opens = _open_events(result)
        assert len(opens) == 2  # LONG + SHORT initial entries

    def test_initial_entries_are_at_l1_r0(self):
        s = _strategy()
        state = DummyState()
        s.on_tick(tick=_tick(T0, "150.00", "150.02"), state=state)
        from apps.trading.strategies.snowball.cycle_state import SnowballStrategyState

        ss = SnowballStrategyState.from_strategy_state(state.strategy_state)
        for cycle in ss.active_cycles():
            head = cycle.initial_entry
            assert head is not None
            assert head.layer_number == 1
            assert head.retracement_count == 0

    def test_second_tick_does_not_reinitialise(self):
        s = _strategy()
        state = DummyState()
        s.on_tick(tick=_tick(T0, "150.00", "150.02"), state=state)
        state.ticks_processed += 1
        result = s.on_tick(tick=_tick(T0 + timedelta(seconds=1), "150.00", "150.02"), state=state)
        opens = _open_events(result)
        assert len(opens) == 0

    def test_auto_base_units_uses_balance_for_new_initial_cycles(self):
        s = _strategy(
            base_units=9999,
            base_units_auto_adjust_enabled=True,
            base_units_balance_ratio="1000",
            base_units_step=100,
        )
        state = DummyState(current_balance=Decimal("1000000"))

        result = s.on_tick(tick=_tick(T0, "150.00", "150.02"), state=state)

        opens = _open_events(result)
        assert {event.units for event in opens} == {1000}
        ss = SnowballStrategyState.from_strategy_state(state.strategy_state)
        assert {cycle.current_layer.base_units for cycle in ss.active_cycles()} == {1000}
        assert ss.metrics["current_base_units"] == "1000"
        assert ss.metrics["snowball_current_base_units"] == "1000"

    def test_auto_base_units_preserves_existing_layer_units_after_balance_changes(self):
        s = _strategy(
            base_units=9999,
            base_units_auto_adjust_enabled=True,
            base_units_balance_ratio="1000",
            base_units_step=100,
            n_pips_head="30",
        )
        state = DummyState(current_balance=Decimal("1000000"))
        s.on_tick(tick=_tick(T0, "150.00", "150.02"), state=state)

        state.current_balance = Decimal("2000000")
        state.ticks_processed += 1
        result = s.on_tick(tick=_tick(T0 + timedelta(minutes=1), "150.32", "150.34"), state=state)

        counter_opens = [event for event in _open_events(result) if event.retracement_count == 1]
        assert counter_opens
        assert {event.units for event in counter_opens} == {2000}
        ss = SnowballStrategyState.from_strategy_state(state.strategy_state)
        assert ss.metrics["current_base_units"] == "2000"

    def test_auto_base_units_scales_future_reentry_cycles_after_balance_changes(self):
        s = _strategy(
            base_units=9999,
            base_units_auto_adjust_enabled=True,
            base_units_balance_ratio="1000",
            base_units_step=100,
        )
        s.configure_runtime(account_currency="JPY", hedging_enabled=False)
        state = DummyState(current_balance=Decimal("1000000"))
        s.on_tick(tick=_tick(T0, "150.00", "150.02"), state=state)

        state.current_balance = Decimal("2000000")
        state.ticks_processed += 1
        result = s.on_tick(tick=_tick(T0 + timedelta(minutes=1), "150.60", "150.62"), state=state)

        opens = _open_events(result)
        assert [event.units for event in opens] == [2000]
        ss = SnowballStrategyState.from_strategy_state(state.strategy_state)
        active_cycles = ss.active_cycles()
        assert len(active_cycles) == 1
        assert active_cycles[0].initial_entry.units == 2000


class TestSnowballWarmup:
    def test_start_gate_blocks_initial_entries_until_spread_is_acceptable(self, caplog):
        caplog.set_level(
            logging.INFO,
            logger="apps.trading.strategies.snowball.warmup",
        )
        s = _strategy(
            warmup_enabled=True,
            warmup_gate_max_spread_pips="1",
            warmup_position_limit_enabled=False,
        )
        state = DummyState()

        blocked = s.on_tick(tick=_tick(T0, "150.00", "150.02"), state=state)

        ss = SnowballStrategyState.from_strategy_state(state.strategy_state)
        assert _open_events(blocked) == []
        assert ss.initialised is False
        assert ss.metrics["warmup_status"] == "warmup"
        assert ss.metrics["warmup_block_reason"] == "spread"
        assert ss.metrics["current_base_units"] == "500"

        allowed = s.on_tick(tick=_tick(T0 + timedelta(seconds=1), "150.00", "150.005"), state=state)

        ss = SnowballStrategyState.from_strategy_state(state.strategy_state)
        assert ss.initialised is True
        assert len(_open_events(allowed)) == 2
        assert {event.units for event in _open_events(allowed)} == {500}
        assert "Snowball warmup started" in caplog.text
        assert "new entries blocked (reason=spread" in caplog.text

    def test_position_limit_caps_initial_hedged_entries(self):
        s = _strategy(
            warmup_enabled=True,
            warmup_start_gate_enabled=False,
            warmup_position_limit_enabled=True,
            warmup_max_positions=1,
        )
        state = DummyState()

        result = s.on_tick(tick=_tick(T0, "150.00", "150.02"), state=state)

        ss = SnowballStrategyState.from_strategy_state(state.strategy_state)
        opens = _open_events(result)
        assert len(opens) == 1
        assert ss.initialised is True
        assert len(ss.all_entries()) == 1
        assert ss.metrics["warmup_status"] == "warmup"

    def test_duration_transition_restores_normal_base_units(self, caplog):
        caplog.set_level(
            logging.INFO,
            logger="apps.trading.strategies.snowball.warmup",
        )
        s = _strategy(
            warmup_enabled=True,
            warmup_start_gate_enabled=False,
            warmup_position_limit_enabled=False,
            warmup_min_elapsed_minutes=1,
        )
        state = DummyState()

        first = s.on_tick(tick=_tick(T0, "150.00", "150.02"), state=state)
        assert {event.units for event in _open_events(first)} == {500}

        state.ticks_processed += 1
        s.on_tick(tick=_tick(T0 + timedelta(minutes=1), "150.00", "150.02"), state=state)

        ss = SnowballStrategyState.from_strategy_state(state.strategy_state)
        assert ss.warmup_completed_at is not None
        assert ss.metrics["warmup_status"] == "normal"
        assert ss.metrics["current_base_units"] == "1000"
        assert "Snowball warmup completed" in caplog.text

    def test_rebuild_limit_reopens_only_configured_count_per_tick(self):
        s = _strategy(
            stop_loss_enabled=True,
            rebuild_enabled=True,
            warmup_enabled=True,
            warmup_start_gate_enabled=False,
            warmup_position_limit_enabled=False,
            warmup_rebuild_limit_enabled=True,
            warmup_max_rebuilds_per_tick=1,
        )
        snowball_state = SnowballStrategyState(
            initialised=True,
            warmup_started_at=T0.isoformat(),
            warmup_phase="warmup",
        )
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        layer = Layer.create(1, 3, 1000, 2)
        for index in (1, 2):
            layer.slot_at(index).pending_rebuild = StopLossClosedEntry(
                entry_price=Decimal("149.50"),
                close_price=Decimal("150.00"),
                units=1000 * (index + 1),
                direction=Direction.LONG,
                role="counter",
                layer_number=1,
                retracement_count=index,
                step=index + 1,
                cycle_id=1,
            )
        cycle.add_layer(layer)
        snowball_state.cycles.append(cycle)
        state = DummyState(strategy_state=snowball_state.to_dict())

        result = s.on_tick(tick=_tick(T0 + timedelta(seconds=1), "149.50", "149.52"), state=state)

        rebuilds = [
            event
            for event in result.events
            if getattr(getattr(event, "event_type", None), "value", "") == "rebuild_position"
        ]
        persisted = SnowballStrategyState.from_strategy_state(state.strategy_state)
        pending_slots = [
            slot
            for cycle in persisted.active_cycles()
            for layer in cycle.layers
            for slot in layer.slots
            if slot.pending_rebuild is not None
        ]
        assert len(rebuilds) == 1
        assert len(pending_slots) == 1

    def test_warmup_max_r_blocks_rebuilds_above_limit(self):
        s = _strategy(
            stop_loss_enabled=True,
            rebuild_enabled=True,
            warmup_enabled=True,
            warmup_start_gate_enabled=False,
            warmup_position_limit_enabled=False,
            warmup_rebuild_limit_enabled=False,
            warmup_max_r=1,
        )
        snowball_state = SnowballStrategyState(
            initialised=True,
            warmup_started_at=T0.isoformat(),
            warmup_phase="warmup",
        )
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        layer = Layer.create(1, 3, 1000, 2)
        for index in (1, 2):
            layer.slot_at(index).pending_rebuild = StopLossClosedEntry(
                entry_price=Decimal("149.50"),
                close_price=Decimal("150.00"),
                units=1000 * (index + 1),
                direction=Direction.LONG,
                role="counter",
                layer_number=1,
                retracement_count=index,
                step=index + 1,
                cycle_id=1,
            )
        cycle.add_layer(layer)
        snowball_state.cycles.append(cycle)
        state = DummyState(strategy_state=snowball_state.to_dict())

        result = s.on_tick(tick=_tick(T0 + timedelta(seconds=1), "149.50", "149.52"), state=state)

        rebuilds = [
            event
            for event in result.events
            if getattr(getattr(event, "event_type", None), "value", "") == "rebuild_position"
        ]
        persisted = SnowballStrategyState.from_strategy_state(state.strategy_state)
        layer = persisted.active_cycles()[0].current_layer
        assert [event.retracement_count for event in rebuilds] == [1]
        assert layer is not None
        assert layer.slot_at(1).pending_rebuild is None
        assert layer.slot_at(2).pending_rebuild is not None


# ==================================================================
# 2. Counter adds
# ==================================================================


class TestCounterAdds:
    def test_counter_add_on_adverse_move(self):
        s = _strategy(m_pips="50", n_pips_head="30")
        state = DummyState()
        s.on_tick(tick=_tick(T0, "150.00", "150.02"), state=state)
        state.ticks_processed += 1
        # Move SHORT adverse by 30+ pips (price goes up)
        result = s.on_tick(tick=_tick(T0 + timedelta(minutes=1), "150.32", "150.34"), state=state)
        opens = _open_events(result)
        assert len(opens) >= 1
        # Should be at R1 (index 1)
        assert any(e.retracement_count == 1 for e in opens)

    def test_warmup_max_r_blocks_counter_add_above_limit(self):
        s = _strategy(
            warmup_enabled=True,
            warmup_start_gate_enabled=False,
            warmup_position_limit_enabled=False,
            warmup_max_r=1,
        )
        snowball_state = SnowballStrategyState(
            initialised=True,
            warmup_started_at=T0.isoformat(),
            warmup_phase="warmup",
        )
        cycle = SnowballCycle(cycle_id=1, direction=Direction.SHORT)
        layer = Layer.create(1, 3, 1000, 2)
        layer.slot_at(0).fill(
            Entry(
                entry_id=1,
                step=1,
                direction=Direction.SHORT,
                entry_price=Decimal("150.00"),
                close_price=Decimal("149.50"),
                units=1000,
                opened_at=T0,
                role="initial",
                layer_number=1,
                retracement_count=0,
                root_entry_id=1,
            )
        )
        layer.slot_at(1).fill(
            Entry(
                entry_id=2,
                step=2,
                direction=Direction.SHORT,
                entry_price=Decimal("150.30"),
                close_price=Decimal("150.05"),
                units=2000,
                opened_at=T0,
                role="counter",
                layer_number=1,
                retracement_count=1,
                root_entry_id=1,
                parent_entry_id=1,
            )
        )
        cycle.add_layer(layer)
        snowball_state.cycles.append(cycle)
        state = DummyState(strategy_state=snowball_state.to_dict())

        result = s.on_tick(tick=_tick(T0 + timedelta(seconds=1), "150.62", "150.64"), state=state)

        assert not any(event.retracement_count == 2 for event in _open_events(result))
        persisted = SnowballStrategyState.from_strategy_state(state.strategy_state)
        layer = persisted.active_cycles()[0].current_layer
        assert layer is not None
        assert layer.slot_at(2).entry is None

    def test_weighted_avg_counter_add_does_not_double_count_live_r0(self):
        s = _strategy(counter_tp_mode="weighted_avg", interval_mode="constant", n_pips_head="30")
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("100000"))
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)

        layer1 = Layer.create(1, 7, 1000, 3)
        layer1.slot_at(0).fill(
            Entry(
                entry_id=1,
                step=1,
                direction=Direction.LONG,
                entry_price=Decimal("161.787"),
                close_price=Decimal("162.287"),
                units=1000,
                opened_at=T0,
                role="initial",
                layer_number=1,
                retracement_count=0,
                root_entry_id=1,
            )
        )

        layer3 = Layer.create(3, 7, 1000, 3)
        layer3.slot_at(0).fill(
            Entry(
                entry_id=2,
                step=1,
                direction=Direction.LONG,
                entry_price=Decimal("157.497"),
                close_price=Decimal("158.0395"),
                units=1000,
                opened_at=T0,
                role="layer_initial",
                layer_number=3,
                retracement_count=0,
                root_entry_id=1,
                parent_entry_id=1,
            )
        )

        cycle.add_layer(layer1)
        cycle.add_layer(layer3)
        ss.cycles.append(cycle)

        tick = _tick(T0 + timedelta(minutes=1), "157.174", "157.194")
        events = s._process_cycle_counter_adds(ss, tick, cycle)

        assert len(events) == 1
        event = events[0]
        assert event.retracement_count == 1
        assert event.planned_exit_price_formula == "(157.194 * 2000 + 157.497 * 1000) / 3000"
        assert event.planned_exit_price == Decimal("157.295")

    def test_initial_r0_stop_loss_matches_r1_interval_distance(self):
        s = _strategy(m_pips="50", n_pips_head="30", stop_loss_enabled=True)
        state = DummyState()

        result = s.on_tick(tick=_tick(T0, "100.00", "100.00"), state=state)

        initial_open = _open_events(result)[0]
        assert initial_open.retracement_count == 0
        assert initial_open.stop_loss_price == Decimal("99.70")

    def test_refill_counter_is_blocked_when_higher_slot_is_still_present(self):
        s = _strategy(counter_tp_mode="fixed", counter_tp_pips="25", n_pips_head="30")
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("100000"))
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)

        layer = Layer.create(3, 7, 1000, 3)
        r0 = layer.slot_at(0)
        assert r0 is not None
        r0.fill(
            Entry(
                entry_id=1,
                step=1,
                direction=Direction.LONG,
                entry_price=Decimal("157.230"),
                close_price=Decimal("157.950"),
                units=1000,
                opened_at=T0,
                role="layer_initial",
                layer_number=3,
                retracement_count=0,
                root_entry_id=1,
            )
        )
        r3 = layer.slot_at(3)
        assert r3 is not None
        r3.fill(
            Entry(
                entry_id=2,
                step=4,
                direction=Direction.LONG,
                entry_price=Decimal("156.000"),
                close_price=Decimal("156.250"),
                units=4000,
                opened_at=T0,
                role="counter",
                layer_number=3,
                retracement_count=3,
                root_entry_id=1,
                parent_entry_id=1,
            )
        )

        cycle.add_layer(layer)
        ss.cycles.append(cycle)

        tick = _tick(T0 + timedelta(minutes=1), "156.90", "156.92")
        events = s._process_cycle_counter_adds(ss, tick, cycle)

        assert events == []

    def test_counter_add_uses_entry_side_price_not_mid(self):
        s = _strategy(counter_tp_mode="weighted_avg", interval_mode="constant", n_pips_head="30")
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("100000"))
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)

        layer = Layer.create(3, 7, 1000, 3)
        slot0 = layer.slot_at(0)
        assert slot0 is not None
        slot0.fill(
            Entry(
                entry_id=1,
                step=1,
                direction=Direction.LONG,
                entry_price=Decimal("157.230"),
                close_price=Decimal("157.95129"),
                units=1000,
                opened_at=T0,
                role="layer_initial",
                layer_number=3,
                retracement_count=0,
                root_entry_id=1,
            )
        )

        cycle.add_layer(layer)
        ss.cycles.append(cycle)

        bad_tick = Tick(
            instrument="USD_JPY",
            timestamp=T0 + timedelta(minutes=1),
            bid=Decimal("146.202"),
            ask=Decimal("163.225"),
            mid=Decimal("154.7135"),
        )

        events = s._process_cycle_counter_adds(ss, bad_tick, cycle)

        assert events == []

    def test_short_counter_add_is_skipped_when_earlier_layer_has_more_adverse_entry(self):
        """Regression: cycle 20883 from production.

        After a rebuild re-establishes an adverse entry in L1/R1 at a
        price above the current market, a new counter add in L2 must not
        be opened on the wrong side of that rebuilt entry (otherwise the
        strategy-level grid-ordering validator would stop the task).
        """
        s = _strategy(
            counter_tp_mode="weighted_avg",
            interval_mode="manual",
            manual_intervals=["30", "30", "25", "20", "16"],
            n_pips_head="30",
            n_pips_tail="14",
            f_max=5,
            r_max=5,
            refill_up_to=3,
            pip_size="0.01",
        )
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("100000"))
        cycle = SnowballCycle(cycle_id=20883, direction=Direction.SHORT)

        # L1/R0 and L1/R1 are rebuilt ghosts left over at prices above
        # the current market — this is exactly the production shape when
        # the bug fires.
        layer1 = Layer.create(1, 5, 9000, 3)
        layer1.slot_at(0).fill(
            Entry(
                entry_id=20946,
                step=1,
                direction=Direction.SHORT,
                entry_price=Decimal("142.315"),
                close_price=Decimal("141.929"),
                units=9000,
                opened_at=T0,
                role="initial",
                layer_number=1,
                retracement_count=0,
                root_entry_id=20883,
                is_rebuild=True,
            )
        )
        layer1.slot_at(1).fill(
            Entry(
                entry_id=20943,
                step=2,
                direction=Direction.SHORT,
                entry_price=Decimal("142.687"),
                close_price=Decimal("142.207"),
                units=18000,
                opened_at=T0,
                role="counter",
                layer_number=1,
                retracement_count=1,
                root_entry_id=20883,
                parent_entry_id=20883,
                is_rebuild=True,
            )
        )
        # L2/R0 is sealed (was opened then TP-closed and marked ever_closed).
        layer2 = Layer.create(2, 5, 9000, 3)
        layer2.slot_at(0).ever_closed = True
        cycle.add_layer(layer1)
        cycle.add_layer(layer2)
        ss.cycles.append(cycle)

        # Market is adverse enough against the L1/R0 fallback reference
        # (the only one the per-layer check sees once L2/R0 is sealed):
        # bid - 142.315 ≥ 30 pips.  But the new entry would sit at
        # 142.616 which is below the L1/R1 ghost at 142.687.  For a
        # SHORT grid that breaks the ascending ordering; the guard must
        # skip the open regardless.
        tick = _tick(T0 + timedelta(minutes=1), "142.616", "142.618")
        events = s._process_cycle_counter_adds(ss, tick, cycle)

        assert events == []
        # And the full on_tick path must not raise a grid-ordering
        # violation because no new entry was created.
        state = DummyState(strategy_state=ss.to_dict())
        result = s.on_tick(tick=tick, state=state)
        assert result.should_stop is False
        assert result.is_error is False

    def test_long_counter_add_is_skipped_when_earlier_layer_has_more_adverse_entry(self):
        """Mirror of the SHORT regression for LONG cycles."""
        s = _strategy(
            counter_tp_mode="weighted_avg",
            interval_mode="manual",
            manual_intervals=["30", "30", "25", "20", "16"],
            n_pips_head="30",
            n_pips_tail="14",
            f_max=5,
            r_max=5,
            refill_up_to=3,
            pip_size="0.01",
        )
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("100000"))
        cycle = SnowballCycle(cycle_id=99, direction=Direction.LONG)

        layer1 = Layer.create(1, 5, 9000, 3)
        layer1.slot_at(0).fill(
            Entry(
                entry_id=100,
                step=1,
                direction=Direction.LONG,
                entry_price=Decimal("142.687"),
                close_price=Decimal("143.067"),
                units=9000,
                opened_at=T0,
                role="initial",
                layer_number=1,
                retracement_count=0,
                root_entry_id=100,
                is_rebuild=True,
            )
        )
        layer1.slot_at(1).fill(
            Entry(
                entry_id=101,
                step=2,
                direction=Direction.LONG,
                entry_price=Decimal("142.315"),
                close_price=Decimal("142.795"),
                units=18000,
                opened_at=T0,
                role="counter",
                layer_number=1,
                retracement_count=1,
                root_entry_id=100,
                parent_entry_id=100,
                is_rebuild=True,
            )
        )
        layer2 = Layer.create(2, 5, 9000, 3)
        layer2.slot_at(0).ever_closed = True
        cycle.add_layer(layer1)
        cycle.add_layer(layer2)
        ss.cycles.append(cycle)

        # For LONG, the entry side price is tick.ask.  adverse from the
        # L1/R0 fallback (142.687) is (142.687 - ask)/0.01; using
        # ask=142.386 gives adverse=30.1 pips which clears the manual
        # interval threshold (30).  But 142.386 > 142.315, i.e. it would
        # sit above the L1/R1 ghost at 142.315 and break the descending
        # grid ordering.
        tick = _tick(T0 + timedelta(minutes=1), "142.384", "142.386")
        events = s._process_cycle_counter_adds(ss, tick, cycle)

        assert events == []

    def test_counter_add_still_opens_when_market_has_cleared_preceding_bound(self):
        """Sanity check: the guard must not block legitimate adds.

        When the market has actually moved past the most-adverse earlier
        entry, a new counter add is still permitted.
        """
        s = _strategy(
            counter_tp_mode="weighted_avg",
            interval_mode="manual",
            manual_intervals=["30", "30", "25", "20", "16"],
            n_pips_head="30",
            n_pips_tail="14",
            f_max=5,
            r_max=5,
            refill_up_to=3,
            pip_size="0.01",
        )
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("100000"))
        cycle = SnowballCycle(cycle_id=20884, direction=Direction.SHORT)

        layer1 = Layer.create(1, 5, 9000, 3)
        layer1.slot_at(0).fill(
            Entry(
                entry_id=200,
                step=1,
                direction=Direction.SHORT,
                entry_price=Decimal("142.315"),
                close_price=Decimal("141.929"),
                units=9000,
                opened_at=T0,
                role="initial",
                layer_number=1,
                retracement_count=0,
                root_entry_id=200,
            )
        )
        layer1.slot_at(1).fill(
            Entry(
                entry_id=201,
                step=2,
                direction=Direction.SHORT,
                entry_price=Decimal("142.687"),
                close_price=Decimal("142.207"),
                units=18000,
                opened_at=T0,
                role="counter",
                layer_number=1,
                retracement_count=1,
                root_entry_id=200,
                parent_entry_id=200,
            )
        )
        layer2 = Layer.create(2, 5, 9000, 3)
        layer2.slot_at(0).ever_closed = True
        cycle.add_layer(layer1)
        cycle.add_layer(layer2)
        ss.cycles.append(cycle)

        # Market has moved adversely past the L1/R1 bound: bid=142.720
        # is greater than 142.687, so the open is allowed.
        tick = _tick(T0 + timedelta(minutes=1), "142.720", "142.722")
        events = s._process_cycle_counter_adds(ss, tick, cycle)

        assert len(events) == 1
        assert isinstance(events[0], OpenPositionEvent)

    def test_layer_initial_snaps_to_prev_layer_highest_plus_next_interval_short(self):
        """L2/R0 must snap to the position the next R slot would have had.

        For a SHORT cycle with manual_intervals=[30, 30, ...] and L1/R5
        at 101.210 as the highest present slot, the next retracement
        (index 6) would sit at 101.370 (last manual interval is 16, but
        counter_interval_pips falls back to the tail entry ``16`` past
        the end of the array).  When the gate fires at a tick ahead of
        that anchor the new L2/R0 must be planted at 101.370, not at
        the market price.
        """
        s = _strategy(
            counter_tp_mode="weighted_avg",
            interval_mode="manual",
            manual_intervals=["30", "30", "25", "20", "16", "16"],
            n_pips_head="30",
            n_pips_tail="16",
            f_max=5,
            r_max=5,
            refill_up_to=3,
            pip_size="0.01",
            m_pips="50",
        )
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("100000"))
        cycle = SnowballCycle(cycle_id=1, direction=Direction.SHORT)

        layer1 = Layer.create(1, 5, 1000, 3)
        # Fill all slots R0…R5 so the layer is exhausted and promotion
        # is required on the next adverse move.
        anchor_prices = [
            ("100.000", 0),
            ("100.300", 1),
            ("100.600", 2),
            ("100.850", 3),
            ("101.050", 4),
            ("101.210", 5),
        ]
        for idx, (price, index) in enumerate(anchor_prices, start=1):
            layer1.slot_at(index).fill(
                Entry(
                    entry_id=idx,
                    step=index + 1,
                    direction=Direction.SHORT,
                    entry_price=Decimal(price),
                    close_price=Decimal("100.000"),
                    units=1000,
                    opened_at=T0 - timedelta(minutes=60 - idx),
                    role="initial" if index == 0 else "counter",
                    layer_number=1,
                    retracement_count=index,
                    root_entry_id=1,
                    parent_entry_id=1 if index > 0 else None,
                )
            )
        cycle.add_layer(layer1)
        ss.cycles.append(cycle)

        # Market has moved past the expected L2/R0 anchor (101.370).  The
        # planned entry must still snap to 101.370, regardless of where
        # the live tick is.
        tick = _tick(T0 + timedelta(minutes=1), "101.420", "101.422")
        events = s._process_cycle_counter_adds(ss, tick, cycle)

        assert len(events) == 1
        open_event = events[0]
        assert isinstance(open_event, OpenPositionEvent)
        assert open_event.layer_number == 2
        assert open_event.retracement_count == 0
        layer_entry = cycle.grid.layers[-1].slot_at(0).entry
        assert layer_entry is not None
        # The state keeps the snapped anchor; the order event must fill at tick.bid.
        assert layer_entry.entry_price == Decimal("101.370")
        assert open_event.planned_entry_price == Decimal("101.370")
        assert open_event.price == Decimal("101.420")
        # TP = anchor - m_pips * pip_size (SHORT) = 101.370 - 0.50 = 100.870
        assert open_event.planned_exit_price == Decimal("100.870")

    def test_layer_initial_snaps_to_prev_layer_highest_minus_next_interval_long(self):
        """Mirror of the SHORT snap test for LONG cycles."""
        s = _strategy(
            counter_tp_mode="weighted_avg",
            interval_mode="manual",
            manual_intervals=["30", "30", "25", "20", "16", "16"],
            n_pips_head="30",
            n_pips_tail="16",
            f_max=5,
            r_max=5,
            refill_up_to=3,
            pip_size="0.01",
            m_pips="50",
        )
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("100000"))
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)

        layer1 = Layer.create(1, 5, 1000, 3)
        anchor_prices = [
            ("101.210", 0),
            ("100.910", 1),
            ("100.610", 2),
            ("100.360", 3),
            ("100.160", 4),
            ("100.000", 5),
        ]
        for idx, (price, index) in enumerate(anchor_prices, start=1):
            layer1.slot_at(index).fill(
                Entry(
                    entry_id=idx,
                    step=index + 1,
                    direction=Direction.LONG,
                    entry_price=Decimal(price),
                    close_price=Decimal("102.000"),
                    units=1000,
                    opened_at=T0 - timedelta(minutes=60 - idx),
                    role="initial" if index == 0 else "counter",
                    layer_number=1,
                    retracement_count=index,
                    root_entry_id=1,
                    parent_entry_id=1 if index > 0 else None,
                )
            )
        cycle.add_layer(layer1)
        ss.cycles.append(cycle)

        # Market has overshot the expected L2/R0 anchor (99.840).  Snap
        # is still honoured.
        tick = _tick(T0 + timedelta(minutes=1), "99.790", "99.792")
        events = s._process_cycle_counter_adds(ss, tick, cycle)

        assert len(events) == 1
        open_event = events[0]
        assert isinstance(open_event, OpenPositionEvent)
        assert open_event.layer_number == 2
        assert open_event.retracement_count == 0
        layer_entry = cycle.grid.layers[-1].slot_at(0).entry
        assert layer_entry is not None
        # The state keeps the snapped anchor; the order event must fill at tick.ask.
        assert layer_entry.entry_price == Decimal("99.840")
        assert open_event.planned_entry_price == Decimal("99.840")
        assert open_event.price == Decimal("99.792")
        # TP = anchor + m_pips = 99.840 + 0.50 = 100.340
        assert open_event.planned_exit_price == Decimal("100.340")

    def test_layer_initial_snap_uses_pending_rebuild_anchor(self):
        """If the prev layer's highest slot is pending rebuild (no live entry),
        the snap must still anchor off its stored entry price rather than the
        live tick."""
        s = _strategy(
            counter_tp_mode="weighted_avg",
            interval_mode="manual",
            manual_intervals=["30", "30", "25", "20", "16", "16"],
            n_pips_head="30",
            n_pips_tail="16",
            f_max=5,
            r_max=5,
            refill_up_to=3,
            pip_size="0.01",
            m_pips="50",
            stop_loss_enabled=True,
            rebuild_enabled=True,
        )
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("100000"))
        cycle = SnowballCycle(cycle_id=1, direction=Direction.SHORT)

        layer1 = Layer.create(1, 5, 1000, 3)
        # R0 live, R1..R5 all pending rebuild at their original entry prices.
        # ``highest_present_slot`` returns R5 because it is present.
        layer1.slot_at(0).fill(
            Entry(
                entry_id=1,
                step=1,
                direction=Direction.SHORT,
                entry_price=Decimal("100.000"),
                close_price=Decimal("99.500"),
                units=1000,
                opened_at=T0,
                role="initial",
                layer_number=1,
                retracement_count=0,
                root_entry_id=1,
            )
        )
        pending_prices = [
            ("100.300", 1),
            ("100.600", 2),
            ("100.850", 3),
            ("101.050", 4),
            ("101.210", 5),
        ]
        for price, index in pending_prices:
            slot = layer1.slot_at(index)
            assert slot is not None
            slot.pending_rebuild = StopLossClosedEntry(
                entry_price=Decimal(price),
                close_price=Decimal("100.000"),
                units=1000,
                direction=Direction.SHORT,
                role="counter",
                layer_number=1,
                retracement_count=index,
                step=index + 1,
                root_entry_id=1,
                parent_entry_id=1,
                cycle_id=1,
                position_id="pending",
                stop_loss_price=None,
                stop_loss_loss_pips=Decimal("0"),
            )
        cycle.add_layer(layer1)
        ss.cycles.append(cycle)

        tick = _tick(T0 + timedelta(minutes=1), "101.500", "101.502")
        events = s._process_cycle_counter_adds(ss, tick, cycle)

        assert len(events) == 1
        open_event = events[0]
        assert isinstance(open_event, OpenPositionEvent)
        assert open_event.layer_number == 2
        # anchor = 101.210 + 16 pips = 101.370 regardless of current tick
        layer_entry = cycle.grid.layers[-1].slot_at(0).entry
        assert layer_entry is not None
        assert layer_entry.entry_price == Decimal("101.370")
        assert open_event.planned_entry_price == Decimal("101.370")
        assert open_event.price == Decimal("101.500")


# ==================================================================
# 3. Counter TP closes
# ==================================================================


class TestCounterCloses:
    def test_counter_tp_closes_newest_first(self):
        s = _strategy(m_pips="50", counter_tp_pips="10", n_pips_head="30")
        state = DummyState()
        s.on_tick(tick=_tick(T0, "150.00", "150.02"), state=state)
        state.ticks_processed += 1

        # Add counter for SHORT cycle (price goes up)
        s.on_tick(tick=_tick(T0 + timedelta(minutes=1), "150.32", "150.34"), state=state)
        state.ticks_processed += 1

        # Move price back down to hit counter TP
        result = s.on_tick(tick=_tick(T0 + timedelta(minutes=2), "150.20", "150.22"), state=state)
        closes = _close_events(result)
        # Should close the counter entry
        assert any(e.close_reason == "counter_tp" for e in closes)

    def test_counter_tp_closes_all_hit_counters_in_one_tick(self):
        s = _strategy(counter_tp_mode="fixed", counter_tp_pips="10")
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("100000"))
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        layer = Layer.create(1, 7, 1000)
        layer.slot_at(0).fill(
            Entry(
                entry_id=1,
                step=1,
                direction=Direction.LONG,
                entry_price=Decimal("150.00"),
                close_price=Decimal("150.50"),
                units=1000,
                opened_at=T0,
                role="initial",
                layer_number=1,
                retracement_count=0,
            )
        )
        layer.slot_at(1).fill(
            Entry(
                entry_id=2,
                step=2,
                direction=Direction.LONG,
                entry_price=Decimal("149.80"),
                close_price=Decimal("150.10"),
                units=2000,
                opened_at=T0,
                role="counter",
                layer_number=1,
                retracement_count=1,
            )
        )
        layer.slot_at(2).fill(
            Entry(
                entry_id=3,
                step=3,
                direction=Direction.LONG,
                entry_price=Decimal("149.70"),
                close_price=Decimal("150.15"),
                units=3000,
                opened_at=T0,
                role="counter",
                layer_number=1,
                retracement_count=2,
            )
        )
        cycle.add_layer(layer)
        ss.cycles.append(cycle)

        events = s._process_cycle_counter_closes(
            ss,
            _tick(T0 + timedelta(minutes=1), "150.20", "150.22"),
            cycle,
        )

        closes = [e for e in events if isinstance(e, ClosePositionEvent)]
        assert [e.entry_id for e in closes] == [3, 2]
        assert layer.slot_at(1).entry is None
        assert layer.slot_at(2).entry is None

    def test_counter_tp_does_not_close_on_open_tick(self):
        s = _strategy(counter_tp_mode="fixed", counter_tp_pips="10")
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("100000"))
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        layer = Layer.create(1, 7, 1000)
        counter = Entry(
            entry_id=2,
            step=2,
            direction=Direction.LONG,
            entry_price=Decimal("149.80"),
            close_price=Decimal("150.10"),
            units=2000,
            opened_at=T0,
            role="counter",
            layer_number=1,
            retracement_count=1,
        )
        layer.slot_at(1).fill(counter)
        cycle.add_layer(layer)
        ss.cycles.append(cycle)

        events = s._process_cycle_counter_closes(ss, _tick(T0, "150.20", "150.22"), cycle)

        assert events == []
        assert layer.slot_at(1).entry is counter

    def test_non_primary_layer_r0_close_removes_empty_layer(self):
        from apps.trading.enums import Direction
        from apps.trading.strategies.snowball.cycle_state import (
            SnowballCycle,
            SnowballStrategyState,
        )
        from apps.trading.strategies.snowball.entries import Entry
        from apps.trading.strategies.snowball.grid_models import Layer

        s = _strategy(counter_tp_mode="fixed", counter_tp_pips="25")
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("100000"))
        cycle = SnowballCycle(cycle_id=1, direction=Direction.SHORT)

        layer2 = Layer.create(2, 7, 1000)
        layer2.slot_at(5).fill(
            Entry(
                entry_id=25,
                step=6,
                direction=Direction.SHORT,
                entry_price=Decimal("143.203"),
                close_price=Decimal("142.667"),
                units=6000,
                opened_at=T0,
                role="counter",
                layer_number=2,
                retracement_count=5,
            )
        )
        layer2.slot_at(6).fill(
            Entry(
                entry_id=26,
                step=7,
                direction=Direction.SHORT,
                entry_price=Decimal("143.342"),
                close_price=Decimal("142.815"),
                units=7000,
                opened_at=T0,
                role="counter",
                layer_number=2,
                retracement_count=6,
            )
        )
        layer2.slot_at(7).fill(
            Entry(
                entry_id=27,
                step=8,
                direction=Direction.SHORT,
                entry_price=Decimal("143.471"),
                close_price=Decimal("142.946"),
                units=8000,
                opened_at=T0,
                role="counter",
                layer_number=2,
                retracement_count=7,
            )
        )

        layer3 = Layer.create(3, 7, 1000)
        layer3.slot_at(0).fill(
            Entry(
                entry_id=30,
                step=1,
                direction=Direction.SHORT,
                entry_price=Decimal("143.587"),
                close_price=Decimal("142.946"),
                units=1000,
                opened_at=T0,
                role="layer_initial",
                layer_number=3,
                retracement_count=0,
            )
        )

        cycle.add_layer(layer2)
        cycle.add_layer(layer3)
        ss.cycles.append(cycle)
        state = DummyState(strategy_state=ss.to_dict())

        result = s.on_tick(tick=_tick(T0 + timedelta(minutes=1), "142.918", "142.938"), state=state)

        closes = _close_events(result)
        assert any(e.layer_number == 3 and e.retracement_count == 0 for e in closes)

        from apps.trading.enums import Direction
        from apps.trading.strategies.snowball.cycle_state import (
            SnowballCycle,
            SnowballStrategyState,
        )
        from apps.trading.strategies.snowball.entries import Entry
        from apps.trading.strategies.snowball.grid_models import Layer

        updated = SnowballStrategyState.from_strategy_state(state.strategy_state)
        updated_cycle = updated.cycles[0]
        assert [layer.layer_number for layer in updated_cycle.grid.layers] == [2]


# ==================================================================
# 4. Trend TP (cycle head close)
# ==================================================================


class TestTrendTP:
    def test_trend_tp_closes_and_reopens(self):
        s = _strategy(m_pips="5")
        state = DummyState()
        s.on_tick(tick=_tick(T0, "150.00", "150.02"), state=state)
        state.ticks_processed += 1

        # Move price up by 5+ pips for LONG TP
        result = s.on_tick(tick=_tick(T0 + timedelta(seconds=60), "150.10", "150.12"), state=state)
        close_events = _close_events(result)
        open_events = _open_events(result)
        assert len(close_events) >= 1 or len(open_events) >= 1


class TestExecutionFillSync:
    def test_weighted_avg_counter_uses_actual_fill_before_tp_close(self):
        s = _strategy(counter_tp_mode="weighted_avg", n_pips_head="30")
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("100000"))
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        layer = Layer.create(1, 7, 1000)
        layer.slot_at(0).fill(
            Entry(
                entry_id=1,
                step=1,
                direction=Direction.LONG,
                entry_price=Decimal("158.876"),
                close_price=Decimal("159.176"),
                units=1000,
                opened_at=T0,
                role="initial",
                layer_number=1,
                retracement_count=0,
                root_entry_id=1,
            )
        )
        layer.slot_at(1).fill(
            Entry(
                entry_id=3,
                step=2,
                direction=Direction.LONG,
                entry_price=Decimal("158.576"),
                close_price=Decimal("158.676"),
                units=2000,
                opened_at=T0 + timedelta(minutes=1),
                role="counter",
                layer_number=1,
                retracement_count=1,
                root_entry_id=1,
                parent_entry_id=1,
            )
        )
        cycle.add_layer(layer)
        ss.cycles.append(cycle)
        state = DummyState(strategy_state=ss.to_dict())

        s.apply_event_execution_result(
            state=state,
            execution_result=EventExecutionResult(
                entry_binding=EntryExecutionBinding(
                    entry_id=3,
                    position_id="6adf8955-1836-4db1-aac9-ea3fbd8a67cb",
                    fill_price=Decimal("158.681"),
                )
            ),
        )

        updated = SnowballStrategyState.from_strategy_state(state.strategy_state)
        counter = updated.cycles[0].grid.layers[0].slot_at(1).entry
        assert counter is not None
        assert counter.position_id == "6adf8955-1836-4db1-aac9-ea3fbd8a67cb"
        assert counter.entry_price == Decimal("158.681")
        assert counter.close_price == Decimal("158.746")

        result = s.on_tick(
            tick=_tick(T0 + timedelta(minutes=2), "158.681", "158.701"),
            state=state,
        )

        closes = _close_events(result)
        assert not any(e.entry_id == 3 for e in closes)


# ==================================================================
# 5. Shrink mode
# ==================================================================


class TestShrinkMode:
    def test_shrink_closes_from_front(self, monkeypatch):
        """Shrink should close the oldest position (L0/R0) first."""
        s = _strategy(shrink_enabled=True, m_th="70")
        state = DummyState(current_balance=Decimal("1000000"))
        s.on_tick(tick=_tick(T0, "150.00", "150.02"), state=state)

        # Inject a counter entry via slot
        counter_entry = {
            "entry_id": 10,
            "step": 2,
            "direction": "long",
            "entry_price": "151.00",
            "close_price": "151.50",
            "units": 1000,
            "opened_at": T0.isoformat(),
            "role": "counter",
            "layer_number": 1,
            "retracement_count": 1,
            "root_entry_id": 1,
            "parent_entry_id": 1,
            "position_id": None,
            "expected_interval_pips": None,
            "actual_interval_pips": None,
            "expected_tp_pips": None,
            "validation_status": "",
            "stop_loss_price": None,
            "is_rebuild": False,
            "lifecycle_realized_pnl": "0",
            "lifecycle_stop_loss_count": 0,
        }
        layers = state.strategy_state["cycles"][0]["grid"]["layers"]
        layers[0]["slots"][1]["entry"] = counter_entry

        ratios = iter([Decimal("75"), Decimal("40")])
        monkeypatch.setattr(
            snowball_strategy_module.SNOWBALL_PROTECTION,
            "margin_ratio",
            lambda **_: next(ratios),
        )
        result = s.on_tick(tick=_tick(T0 + timedelta(seconds=60), "150.00", "150.02"), state=state)
        closes = _close_events(result)
        assert len(closes) >= 1
        shrink_signals = _signal_events(result, "snowball_shrink")
        assert len(shrink_signals) >= 1

        # The first close should be the oldest entry (L0/R0)
        first_close = closes[0]
        assert first_close.close_reason == "shrink"

    def test_shrink_head_shifts_after_close(self):
        """After shrink closes L0/R0, the cycle head should shift dynamically."""
        from apps.trading.enums import Direction
        from apps.trading.strategies.snowball.cycle_state import (
            SnowballCycle,
            SnowballStrategyState,
        )
        from apps.trading.strategies.snowball.entries import Entry
        from apps.trading.strategies.snowball.grid_models import Layer

        # Directly construct state with known entries — no on_tick needed
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("100000"))
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        l0 = Layer.create(1, 3, 1000)
        l0.slot_at(0).fill(
            Entry(
                entry_id=1,
                step=1,
                direction=Direction.LONG,
                entry_price=Decimal("150.00"),
                close_price=Decimal("150.50"),
                units=1000,
                opened_at=T0,
                role="initial",
                layer_number=1,
                retracement_count=0,
            )
        )
        l0.slot_at(1).fill(
            Entry(
                entry_id=2,
                step=2,
                direction=Direction.LONG,
                entry_price=Decimal("149.70"),
                close_price=Decimal("150.00"),
                units=2000,
                opened_at=T0,
                role="counter",
                layer_number=1,
                retracement_count=1,
            )
        )
        cycle.add_layer(l0)
        ss.cycles.append(cycle)

        # Verify head is L1/R0
        assert cycle.initial_entry.entry_id == 1

        # Simulate shrink closing L1/R0
        cycle.remove_entry(1)

        # Head should now be L1/R1
        assert cycle.initial_entry is not None
        assert cycle.initial_entry.entry_id == 2
        assert cycle.initial_entry.retracement_count == 1

    def test_shrink_preserves_existing_counter_tp(self, monkeypatch):
        """Shrink must not rewrite surviving counter TPs."""
        s = _strategy(shrink_enabled=True, m_th="70")
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("100000"))
        cycle = SnowballCycle(cycle_id=1, direction=Direction.SHORT)
        layer = Layer.create(1, 7, 1000)
        layer.slot_at(0).fill(
            Entry(
                entry_id=1,
                step=1,
                direction=Direction.SHORT,
                entry_price=Decimal("142.000"),
                close_price=Decimal("141.850"),
                units=1000,
                opened_at=T0,
                role="initial",
                layer_number=1,
                retracement_count=0,
            )
        )
        layer.slot_at(1).fill(
            Entry(
                entry_id=2,
                step=2,
                direction=Direction.SHORT,
                entry_price=Decimal("142.300"),
                close_price=Decimal("142.120"),
                units=2000,
                opened_at=T0,
                role="counter",
                layer_number=1,
                retracement_count=1,
            )
        )
        cycle.add_layer(layer)
        ss.cycles.append(cycle)

        state = DummyState(strategy_state=ss.to_dict(), current_balance=Decimal("100"))
        ratios = iter([Decimal("75"), Decimal("40")])
        monkeypatch.setattr(
            snowball_strategy_module.SNOWBALL_PROTECTION,
            "margin_ratio",
            lambda **_: next(ratios),
        )

        result = s.on_tick(tick=_tick(T0 + timedelta(seconds=60), "145.00", "145.02"), state=state)

        closes = _close_events(result)
        assert len(closes) == 1
        assert closes[0].close_reason == "shrink"
        assert closes[0].entry_id == 1

        persisted = SnowballStrategyState.from_strategy_state(state.strategy_state)
        remaining = persisted.cycles[0].grid.layers[0].slot_at(1).entry
        assert remaining is not None
        assert remaining.entry_id == 2
        assert remaining.close_price == Decimal("142.120")


# ==================================================================
# 6. Emergency stop
# ==================================================================


class TestEmergencyStop:
    def test_emergency_stop_at_95_percent(self, monkeypatch):
        s = _strategy(
            m_th="70",
            shrink_enabled=False,
        )
        state = DummyState(current_balance=Decimal("1000000"))
        s.on_tick(tick=_tick(T0, "150.00", "150.02"), state=state)
        state.ticks_processed += 1

        monkeypatch.setattr(
            snowball_strategy_module.SNOWBALL_PROTECTION,
            "margin_ratio",
            lambda **_: Decimal("96"),
        )
        result = s.on_tick(tick=_tick(T0 + timedelta(seconds=60), "150.00", "150.02"), state=state)
        assert result.should_stop is True
        assert "Emergency stop" in (result.stop_reason or "")


class TestGridOrderingValidation:
    def test_long_cycle_does_not_fail_when_entry_prices_are_not_descending(self):
        s = _strategy(counter_tp_mode="fixed", counter_tp_pips="25")
        s.configure_runtime(account_currency="JPY", hedging_enabled=False)
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("100000"))
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        layer = Layer.create(1, 7, 1000, 3)
        layer.slot_at(0).fill(
            Entry(
                entry_id=1,
                step=1,
                direction=Direction.LONG,
                entry_price=Decimal("160.000"),
                close_price=Decimal("160.500"),
                units=1000,
                opened_at=T0,
                role="initial",
                layer_number=1,
                retracement_count=0,
                root_entry_id=1,
            )
        )
        layer.slot_at(1).fill(
            Entry(
                entry_id=2,
                step=2,
                direction=Direction.LONG,
                entry_price=Decimal("160.100"),
                close_price=Decimal("160.400"),
                units=2000,
                opened_at=T0,
                role="counter",
                layer_number=1,
                retracement_count=1,
                root_entry_id=1,
                parent_entry_id=1,
            )
        )
        cycle.add_layer(layer)
        ss.cycles.append(cycle)

        state = DummyState(strategy_state=ss.to_dict())
        result = s.on_tick(tick=_tick(T0 + timedelta(minutes=1), "160.10", "160.12"), state=state)

        assert result.should_stop is False
        assert result.is_error is False
        assert result.stop_reason == ""

    def test_violation_warns_and_does_not_fail_task(self, caplog):
        s = _strategy(
            counter_tp_mode="fixed",
            counter_tp_pips="25",
        )
        s.configure_runtime(account_currency="JPY", hedging_enabled=False)
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("100000"))
        cycle = SnowballCycle(cycle_id=3, direction=Direction.LONG)
        layer = Layer.create(1, 7, 1000, 3)
        layer.slot_at(0).fill(
            Entry(
                entry_id=1,
                step=1,
                direction=Direction.LONG,
                entry_price=Decimal("160.000"),
                close_price=Decimal("160.500"),
                units=1000,
                opened_at=T0,
                role="initial",
                layer_number=1,
                retracement_count=0,
                root_entry_id=1,
            )
        )
        layer.slot_at(1).fill(
            Entry(
                entry_id=2,
                step=2,
                direction=Direction.LONG,
                entry_price=Decimal("160.100"),
                close_price=Decimal("160.400"),
                units=2000,
                opened_at=T0,
                role="counter",
                layer_number=1,
                retracement_count=1,
                root_entry_id=1,
                parent_entry_id=1,
            )
        )
        cycle.add_layer(layer)
        ss.cycles.append(cycle)

        state = DummyState(strategy_state=ss.to_dict())
        with caplog.at_level(
            logging.INFO,
            logger="apps.trading.strategies.snowball.strategy",
        ):
            result = s.on_tick(
                tick=_tick(T0 + timedelta(minutes=1), "160.10", "160.12"),
                state=state,
            )

        assert result.should_stop is False
        assert result.is_error is False
        assert result.stop_reason == ""
        assert any(
            "Grid ordering violation detected" in record.getMessage() for record in caplog.records
        )

    def test_cycle_tp_uses_dynamic_head_after_front_slot_removed(self):
        s = _strategy(
            counter_tp_mode="fixed",
            counter_tp_pips="25",
        )
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("100000"))
        cycle = SnowballCycle(cycle_id=3, direction=Direction.LONG)
        layer = Layer.create(1, 7, 1000, 3)
        layer.slot_at(0).ever_closed = True
        layer.slot_at(1).fill(
            Entry(
                entry_id=2,
                step=2,
                direction=Direction.LONG,
                entry_price=Decimal("159.500"),
                close_price=Decimal("160.000"),
                units=2000,
                opened_at=T0,
                role="counter",
                layer_number=1,
                retracement_count=1,
                root_entry_id=1,
                parent_entry_id=1,
            )
        )
        cycle.add_layer(layer)
        ss.cycles.append(cycle)

        state = DummyState(strategy_state=ss.to_dict())
        result = s.on_tick(tick=_tick(T0 + timedelta(minutes=1), "160.02", "160.04"), state=state)

        closes = _close_events(result)
        assert len(closes) == 1
        assert closes[0].entry_id == 2
        assert closes[0].close_reason == "tp"
        persisted = SnowballStrategyState.from_strategy_state(state.strategy_state)
        old_cycle = persisted.find_cycle(3)
        assert old_cycle is not None
        assert old_cycle.completed is True

    def test_tp_hit_counter_closes_when_newer_slot_is_not_hit(self, caplog):
        s = _strategy(
            counter_tp_mode="fixed",
            counter_tp_pips="25",
        )
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("100000"))
        cycle = SnowballCycle(cycle_id=4, direction=Direction.LONG)
        layer = Layer.create(1, 7, 1000, 3)
        layer.slot_at(0).fill(
            Entry(
                entry_id=1,
                step=1,
                direction=Direction.LONG,
                entry_price=Decimal("160.000"),
                close_price=Decimal("160.500"),
                units=1000,
                opened_at=T0,
                role="initial",
                layer_number=1,
                retracement_count=0,
                root_entry_id=1,
            )
        )
        layer.slot_at(1).fill(
            Entry(
                entry_id=2,
                step=2,
                direction=Direction.LONG,
                entry_price=Decimal("159.700"),
                close_price=Decimal("159.800"),
                units=2000,
                opened_at=T0,
                role="counter",
                layer_number=1,
                retracement_count=1,
                root_entry_id=1,
                parent_entry_id=1,
            )
        )
        layer.slot_at(2).fill(
            Entry(
                entry_id=3,
                step=3,
                direction=Direction.LONG,
                entry_price=Decimal("159.600"),
                close_price=Decimal("160.200"),
                units=3000,
                opened_at=T0,
                role="counter",
                layer_number=1,
                retracement_count=2,
                root_entry_id=1,
                parent_entry_id=1,
            )
        )
        cycle.add_layer(layer)
        ss.cycles.append(cycle)

        state = DummyState(strategy_state=ss.to_dict())
        with caplog.at_level(logging.WARNING):
            result = s.on_tick(
                tick=_tick(T0 + timedelta(minutes=1), "159.85", "159.87"),
                state=state,
            )

        assert result.should_stop is False
        closes = _close_events(result)
        assert [event.entry_id for event in closes] == [2]
        persisted = SnowballStrategyState.from_strategy_state(state.strategy_state)
        persisted_cycle = persisted.find_cycle(4)
        assert persisted_cycle is not None
        persisted_layer = persisted_cycle.grid.layers[0]
        assert persisted_layer.slot_at(1).entry is None
        assert persisted_layer.slot_at(2).entry is not None
        assert any("Grid close-order violation" in record.getMessage() for record in caplog.records)

    def test_lower_counter_closes_on_next_tick_after_higher_counter_closed(self):
        s = _strategy(counter_tp_mode="fixed", counter_tp_pips="25")
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("100000"))
        cycle = SnowballCycle(cycle_id=7, direction=Direction.LONG)
        layer = Layer.create(1, 7, 1000, 3)
        layer.slot_at(0).fill(
            Entry(
                entry_id=1,
                step=1,
                direction=Direction.LONG,
                entry_price=Decimal("160.000"),
                close_price=Decimal("160.500"),
                units=1000,
                opened_at=T0,
                role="initial",
                layer_number=1,
                retracement_count=0,
                root_entry_id=1,
            )
        )
        layer.slot_at(1).fill(
            Entry(
                entry_id=2,
                step=2,
                direction=Direction.LONG,
                entry_price=Decimal("159.700"),
                close_price=Decimal("160.400"),
                units=2000,
                opened_at=T0,
                role="counter",
                layer_number=1,
                retracement_count=1,
                root_entry_id=1,
                parent_entry_id=1,
            )
        )
        layer.slot_at(2).fill(
            Entry(
                entry_id=3,
                step=3,
                direction=Direction.LONG,
                entry_price=Decimal("159.600"),
                close_price=Decimal("160.200"),
                units=3000,
                opened_at=T0,
                role="counter",
                layer_number=1,
                retracement_count=2,
                root_entry_id=1,
                parent_entry_id=1,
            )
        )
        cycle.add_layer(layer)
        ss.cycles.append(cycle)

        state = DummyState(strategy_state=ss.to_dict())
        first = s.on_tick(tick=_tick(T0 + timedelta(minutes=1), "160.25", "160.27"), state=state)
        assert [event.entry_id for event in _close_events(first)] == [3]

        second = s.on_tick(tick=_tick(T0 + timedelta(minutes=2), "160.45", "160.47"), state=state)
        assert [event.entry_id for event in _close_events(second)] == [2]
        persisted = SnowballStrategyState.from_strategy_state(state.strategy_state)
        persisted_cycle = persisted.find_cycle(7)
        assert persisted_cycle is not None
        assert persisted_cycle.grid.layers[0].slot_at(0).entry is not None
        assert persisted_cycle.grid.layers[0].slot_at(1).entry is None
        assert persisted_cycle.grid.layers[0].slot_at(2).entry is None
        assert persisted_cycle.completed is False

    def test_cycle_head_tp_does_not_close_while_live_counter_remains(self):
        s = _strategy(counter_tp_mode="fixed", counter_tp_pips="25")
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("100000"))
        cycle = SnowballCycle(cycle_id=8, direction=Direction.LONG)
        layer = Layer.create(1, 7, 1000, 3)
        layer.slot_at(0).fill(
            Entry(
                entry_id=1,
                step=1,
                direction=Direction.LONG,
                entry_price=Decimal("160.000"),
                close_price=Decimal("160.500"),
                units=1000,
                opened_at=T0,
                role="initial",
                layer_number=1,
                retracement_count=0,
                root_entry_id=1,
            )
        )
        layer.slot_at(1).fill(
            Entry(
                entry_id=2,
                step=2,
                direction=Direction.LONG,
                entry_price=Decimal("159.700"),
                close_price=Decimal("160.800"),
                units=2000,
                opened_at=T0,
                role="counter",
                layer_number=1,
                retracement_count=1,
                root_entry_id=1,
                parent_entry_id=1,
            )
        )
        cycle.add_layer(layer)
        ss.cycles.append(cycle)

        state = DummyState(strategy_state=ss.to_dict())
        result = s.on_tick(tick=_tick(T0 + timedelta(minutes=1), "160.55", "160.57"), state=state)

        assert _close_events(result) == []
        persisted = SnowballStrategyState.from_strategy_state(state.strategy_state)
        persisted_cycle = persisted.find_cycle(8)
        assert persisted_cycle is not None
        assert persisted_cycle.completed is False
        assert len(persisted_cycle.grid.all_entries()) == 2

    def test_grid_violation_skips_new_counter_adds_until_order_recovers(self, caplog):
        s = _strategy(
            counter_tp_mode="fixed",
            counter_tp_pips="25",
        )
        s.configure_runtime(account_currency="JPY", hedging_enabled=False)
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("100000"))
        cycle = SnowballCycle(cycle_id=9, direction=Direction.LONG)
        layer = Layer.create(1, 7, 1000, 3)
        layer.slot_at(0).fill(
            Entry(
                entry_id=1,
                step=1,
                direction=Direction.LONG,
                entry_price=Decimal("160.000"),
                close_price=Decimal("160.500"),
                units=1000,
                opened_at=T0,
                role="initial",
                layer_number=1,
                retracement_count=0,
                root_entry_id=1,
            )
        )
        layer.slot_at(1).fill(
            Entry(
                entry_id=2,
                step=2,
                direction=Direction.LONG,
                entry_price=Decimal("160.100"),
                close_price=Decimal("160.400"),
                units=2000,
                opened_at=T0,
                role="counter",
                layer_number=1,
                retracement_count=1,
                root_entry_id=1,
                parent_entry_id=1,
            )
        )
        cycle.add_layer(layer)
        ss.cycles.append(cycle)

        state = DummyState(strategy_state=ss.to_dict())
        with caplog.at_level(logging.DEBUG):
            result = s.on_tick(
                tick=_tick(T0 + timedelta(minutes=1), "159.50", "159.52"),
                state=state,
            )

        assert result.should_stop is False
        assert _open_events(result) == []
        persisted = SnowballStrategyState.from_strategy_state(state.strategy_state)
        persisted_cycle = persisted.find_cycle(9)
        assert persisted_cycle is not None
        assert persisted_cycle.grid.layers[0].slot_at(2).entry is None
        assert any(
            "Skipping Snowball counter adds while grid ordering is violated" in record.getMessage()
            for record in caplog.records
        )
        assert not any(record.levelno >= logging.WARNING for record in caplog.records)

    def test_out_of_order_layer_closes_preserve_layer_until_present_slots_clear(self):
        s = _strategy(
            counter_tp_mode="fixed",
            counter_tp_pips="25",
        )
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("100000"))
        cycle = SnowballCycle(cycle_id=5, direction=Direction.LONG)
        l1 = Layer.create(1, 7, 1000, 3)
        l1.slot_at(0).fill(
            Entry(
                entry_id=1,
                step=1,
                direction=Direction.LONG,
                entry_price=Decimal("160.000"),
                close_price=Decimal("160.500"),
                units=1000,
                opened_at=T0,
                role="initial",
                layer_number=1,
                retracement_count=0,
                root_entry_id=1,
            )
        )
        l2 = Layer.create(2, 7, 1000, 3)
        l2.slot_at(0).fill(
            Entry(
                entry_id=2,
                step=1,
                direction=Direction.LONG,
                entry_price=Decimal("159.400"),
                close_price=Decimal("160.000"),
                units=1000,
                opened_at=T0,
                role="layer_initial",
                layer_number=2,
                retracement_count=0,
                root_entry_id=1,
                parent_entry_id=1,
            )
        )
        l2.slot_at(1).fill(
            Entry(
                entry_id=3,
                step=2,
                direction=Direction.LONG,
                entry_price=Decimal("159.200"),
                close_price=Decimal("159.800"),
                units=2000,
                opened_at=T0,
                role="counter",
                layer_number=2,
                retracement_count=1,
                root_entry_id=1,
                parent_entry_id=1,
            )
        )
        l2.slot_at(2).fill(
            Entry(
                entry_id=4,
                step=3,
                direction=Direction.LONG,
                entry_price=Decimal("159.000"),
                close_price=Decimal("160.200"),
                units=3000,
                opened_at=T0,
                role="counter",
                layer_number=2,
                retracement_count=2,
                root_entry_id=1,
                parent_entry_id=1,
            )
        )
        cycle.add_layer(l1)
        cycle.add_layer(l2)
        ss.cycles.append(cycle)

        state = DummyState(strategy_state=ss.to_dict())
        first = s.on_tick(tick=_tick(T0 + timedelta(minutes=1), "159.85", "159.87"), state=state)
        assert [event.entry_id for event in _close_events(first)] == [3]
        persisted = SnowballStrategyState.from_strategy_state(state.strategy_state)
        persisted_cycle = persisted.find_cycle(5)
        assert persisted_cycle is not None
        assert len(persisted_cycle.grid.layers) == 2

        second = s.on_tick(tick=_tick(T0 + timedelta(minutes=2), "160.25", "160.27"), state=state)
        assert [event.entry_id for event in _close_events(second)] == [4, 2]
        persisted = SnowballStrategyState.from_strategy_state(state.strategy_state)
        persisted_cycle = persisted.find_cycle(5)
        assert persisted_cycle is not None
        assert [layer.layer_number for layer in persisted_cycle.grid.layers] == [1]

    def test_layer_initial_close_keeps_layer_with_pending_rebuild(self):
        s = _strategy(
            counter_tp_mode="fixed",
            counter_tp_pips="25",
        )
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("100000"))
        cycle = SnowballCycle(cycle_id=6, direction=Direction.LONG)
        l1 = Layer.create(1, 7, 1000, 3)
        l1.slot_at(0).fill(
            Entry(
                entry_id=1,
                step=1,
                direction=Direction.LONG,
                entry_price=Decimal("160.000"),
                close_price=Decimal("160.500"),
                units=1000,
                opened_at=T0,
                role="initial",
                layer_number=1,
                retracement_count=0,
                root_entry_id=1,
            )
        )
        l2 = Layer.create(2, 7, 1000, 3)
        l2.slot_at(0).fill(
            Entry(
                entry_id=2,
                step=1,
                direction=Direction.LONG,
                entry_price=Decimal("159.400"),
                close_price=Decimal("159.800"),
                units=1000,
                opened_at=T0,
                role="layer_initial",
                layer_number=2,
                retracement_count=0,
                root_entry_id=1,
                parent_entry_id=1,
            )
        )
        l2.slot_at(1).pending_rebuild = StopLossClosedEntry(
            entry_price=Decimal("159.200"),
            close_price=Decimal("159.700"),
            units=2000,
            direction=Direction.LONG,
            role="counter",
            layer_number=2,
            retracement_count=1,
            step=2,
            root_entry_id=1,
            parent_entry_id=1,
            cycle_id=6,
        )
        cycle.add_layer(l1)
        cycle.add_layer(l2)
        ss.cycles.append(cycle)

        state = DummyState(strategy_state=ss.to_dict())
        result = s.on_tick(tick=_tick(T0 + timedelta(minutes=1), "159.85", "159.87"), state=state)

        assert [event.entry_id for event in _close_events(result)] == [2]
        persisted = SnowballStrategyState.from_strategy_state(state.strategy_state)
        persisted_cycle = persisted.find_cycle(6)
        assert persisted_cycle is not None
        assert [layer.layer_number for layer in persisted_cycle.grid.layers] == [1, 2]
        persisted_l2 = persisted_cycle.grid.layers[1]
        assert persisted_l2.slot_at(1).pending_rebuild is not None

    def test_same_tick_counter_add_skips_rebuilt_slot_with_synthetic_entry_price(self):
        s = _strategy()
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("100000"))
        cycle = SnowballCycle(cycle_id=4, direction=Direction.LONG)
        layer = Layer.create(2, 7, 1000, 3)
        layer.slot_at(0).fill(
            Entry(
                entry_id=1,
                step=1,
                direction=Direction.LONG,
                entry_price=Decimal("157.797"),
                close_price=Decimal("158.100"),
                units=1000,
                opened_at=T0,
                role="initial",
                layer_number=2,
                retracement_count=0,
                root_entry_id=1,
            )
        )
        layer.slot_at(1).fill(
            Entry(
                entry_id=2,
                step=2,
                direction=Direction.LONG,
                entry_price=Decimal("157.150"),
                close_price=Decimal("157.450"),
                units=2000,
                opened_at=T0,
                role="counter",
                layer_number=2,
                retracement_count=1,
                root_entry_id=1,
                parent_entry_id=1,
            )
        )
        layer.slot_at(2).fill(
            Entry(
                entry_id=3,
                step=3,
                direction=Direction.LONG,
                entry_price=Decimal("156.852"),
                close_price=Decimal("157.525"),
                units=3000,
                opened_at=T0 + timedelta(minutes=1),
                role="counter",
                layer_number=2,
                retracement_count=2,
                root_entry_id=1,
                parent_entry_id=1,
                is_rebuild=True,
            )
        )
        cycle.add_layer(layer)
        ss.cycles.append(cycle)

        tick = _tick(T0 + timedelta(minutes=1), "156.864", "156.866")
        events = s._process_cycle_counter_adds(ss, tick, cycle)

        assert events == []
        assert layer.slot_at(3).entry is None

    def test_short_cycle_does_not_fail_when_tp_prices_are_not_ascending(self):
        s = _strategy(counter_tp_mode="fixed", counter_tp_pips="25")
        s.configure_runtime(account_currency="JPY", hedging_enabled=False)
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("100000"))
        cycle = SnowballCycle(cycle_id=2, direction=Direction.SHORT)
        layer = Layer.create(1, 7, 1000, 3)
        layer.slot_at(0).fill(
            Entry(
                entry_id=10,
                step=1,
                direction=Direction.SHORT,
                entry_price=Decimal("150.000"),
                close_price=Decimal("149.500"),
                units=1000,
                opened_at=T0,
                role="initial",
                layer_number=1,
                retracement_count=0,
                root_entry_id=10,
            )
        )
        layer.slot_at(1).fill(
            Entry(
                entry_id=11,
                step=2,
                direction=Direction.SHORT,
                entry_price=Decimal("150.300"),
                close_price=Decimal("149.400"),
                units=2000,
                opened_at=T0,
                role="counter",
                layer_number=1,
                retracement_count=1,
                root_entry_id=10,
                parent_entry_id=10,
            )
        )
        cycle.add_layer(layer)
        ss.cycles.append(cycle)

        state = DummyState(strategy_state=ss.to_dict())
        result = s.on_tick(tick=_tick(T0 + timedelta(minutes=1), "149.90", "149.92"), state=state)

        assert result.should_stop is False
        assert result.is_error is False
        assert result.stop_reason == ""
