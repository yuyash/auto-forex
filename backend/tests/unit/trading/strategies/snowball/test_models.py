"""Unit tests for Snowball strategy models (unified position grid)."""

from decimal import Decimal

import pytest

from apps.trading.enums import Direction
from apps.trading.strategies.snowball.enums import ProtectionLevel
from apps.trading.strategies.snowball.config import SnowballStrategyConfig
from apps.trading.strategies.snowball.cycle_state import SnowballCycle, SnowballStrategyState
from apps.trading.strategies.snowball.entries import Entry, StopLossClosedEntry
from apps.trading.strategies.snowball.grid_models import Layer, PositionGrid, Slot

from .factories import T0, entry as _entry


class TestSnowballStrategyConfig:
    def test_from_dict_defaults(self):
        cfg = SnowballStrategyConfig.from_dict({})
        assert cfg.base_units == 1000
        assert cfg.m_pips == Decimal("50")
        assert cfg.r_max == 7
        assert cfg.f_max == 3
        assert cfg.base_units_auto_adjust_enabled is False
        assert cfg.base_units_balance_ratio == Decimal("1000")
        assert cfg.base_units_step == 100
        assert cfg.base_units_auto_adjust_floor_enabled is False
        assert cfg.refill_limit_enabled is True
        assert cfg.refill_up_to == 2
        assert cfg.effective_refill_up_to == 2
        assert cfg.interval_mode == "constant"
        assert cfg.stop_loss_mode == "auto"
        assert cfg.counter_tp_mode == "weighted_avg"
        assert cfg.rebuild_entry_price_mode == "original_entry"
        assert cfg.rebuild_stop_loss_mode == "same_pips"
        assert cfg.rebuild_stop_loss_manual_pips == []
        assert cfg.rebuild_take_profit_mode == "same_pips"
        assert cfg.rebuild_take_profit_manual_pips == []
        assert cfg.preserve_highest_retracement_enabled is False
        assert cfg.preserve_highest_r_from == 0
        assert cfg.cycle_rebuild_guard_enabled is False
        assert cfg.cycle_rebuild_guard_stop_count == 15
        assert cfg.cycle_rebuild_guard_min_loss == Decimal("0")
        assert cfg.cycle_rebuild_guard_recovery_pips == Decimal("0")
        assert cfg.warmup_enabled is False
        assert cfg.warmup_initial_unit_ratio_pct == Decimal("50")
        assert cfg.warmup_start_gate_enabled is True
        assert cfg.warmup_gate_spread_enabled is True
        assert cfg.warmup_position_limit_enabled is True
        assert cfg.warmup_rebuild_limit_enabled is True
        assert cfg.warmup_completion_mode == "duration"
        assert cfg.add_margin_guard_enabled is False
        assert cfg.add_margin_guard_max_pct == Decimal("65")
        assert cfg.add_margin_guard_scope == "adds_only"
        assert cfg.volatility_guard_enabled is False
        assert cfg.volatility_guard_source == "atr"
        assert cfg.add_trend_guard_enabled is False
        assert cfg.add_trend_max_opposite_deviation_pips == Decimal("50")
        assert cfg.adaptive_counter_interval_enabled is False
        assert cfg.adaptive_counter_interval_source == "atr"
        assert cfg.adaptive_trend_interval_enabled is False
        assert cfg.adaptive_trend_interval_source == "atr"

    def test_from_dict_custom(self):
        cfg = SnowballStrategyConfig.from_dict(
            {
                "base_units": 2000,
                "m_pips": "30",
                "r_max": 5,
                "interval_mode": "manual",
                "manual_intervals": ["10", "20", "30", "40", "50"],
            }
        )
        assert cfg.base_units == 2000
        assert cfg.m_pips == Decimal("30")
        assert cfg.r_max == 5
        assert len(cfg.manual_intervals) == 5

    def test_value_object_views_expose_focused_policy_groups(self):
        cfg = SnowballStrategyConfig.from_dict(
            {
                "interval_mode": "manual",
                "manual_intervals": ["10", "11", "12", "13", "14"],
                "r_max": 5,
                "counter_tp_mode": "fixed",
                "counter_tp_pips": "21",
                "stop_loss_enabled": True,
                "rebuild_enabled": True,
                "rebuild_entry_price_mode": "stop_loss_exit",
                "reseed_on_all_pending": True,
                "shrink_enabled": False,
            }
        )

        assert cfg.intervals.mode == "manual"
        assert cfg.intervals.manual_intervals[-1] == Decimal("14")
        assert cfg.take_profit.mode == "fixed"
        assert cfg.take_profit.pips == Decimal("21")
        assert cfg.rebuild_policy.reseed_on_all_pending is True
        assert cfg.rebuild_policy.entry_price_mode == "stop_loss_exit"
        assert cfg.cycle_rebuild_guard.enabled is False
        assert cfg.cycle_rebuild_guard.stop_count == 15
        assert cfg.rebuild.refill_limit_enabled is True
        assert cfg.rebuild.refill_up_to == 2
        assert cfg.risk_limits.stop_loss_enabled is True
        assert cfg.margin_add_guard.scope == "adds_only"
        assert cfg.volatility_guard.source == "atr"
        assert cfg.volatility_guard.candle_granularity == "M1"
        assert cfg.volatility_guard.candle_ema_period == 60
        assert cfg.trend_add_guard.candle_granularity == "M1"
        assert cfg.trend_add_guard.ema_period == 200
        assert cfg.adaptive_counter_interval.candle_granularity == "M1"
        assert cfg.adaptive_counter_interval.reference_pips == Decimal("10")
        assert cfg.adaptive_trend_interval.candle_granularity == "M1"
        assert cfg.adaptive_trend_interval.reference_pips == Decimal("10")

    def test_from_dict_parses_string_booleans(self):
        cfg = SnowballStrategyConfig.from_dict(
            {
                "shrink_enabled": "false",
                "stop_loss_enabled": "false",
                "rebuild_enabled": "0",
                "emergency_enabled": "yes",
            }
        )

        assert cfg.shrink_enabled is False
        assert cfg.stop_loss_enabled is False
        assert cfg.rebuild_enabled is False
        assert cfg.emergency_enabled is True

    def test_refill_limit_toggle_allows_all_counter_slots(self):
        cfg = SnowballStrategyConfig.from_dict(
            {"r_max": 5, "refill_limit_enabled": False, "refill_up_to": 2}
        )

        assert cfg.refill_limit_enabled is False
        assert cfg.refill_up_to == 2
        assert cfg.effective_refill_up_to == 5
        assert cfg.grid.refill_up_to == 5

    def test_legacy_zero_refill_limit_keeps_refill_disabled(self):
        cfg = SnowballStrategyConfig.from_dict({"refill_up_to": 0})

        assert cfg.refill_limit_enabled is True
        assert cfg.effective_refill_up_to == 0

    def test_legacy_refill_enabled_false_keeps_refill_disabled(self):
        cfg = SnowballStrategyConfig.from_dict({"refill_enabled": False, "refill_up_to": 2})

        assert cfg.refill_limit_enabled is True
        assert cfg.refill_up_to == 0
        assert cfg.effective_refill_up_to == 0

    def test_to_dict_roundtrip(self):
        cfg = SnowballStrategyConfig.from_dict(
            {
                "m_pips": "30",
                "rebuild_entry_price_mode": "stop_loss_exit",
                "rebuild_stop_loss_mode": "manual",
                "rebuild_stop_loss_manual_pips": ["11", "12", "13", "14", "15", "16"],
                "rebuild_take_profit_mode": "manual",
                "rebuild_take_profit_manual_pips": ["21", "22", "23", "24", "25", "26"],
                "preserve_highest_retracement_enabled": True,
                "preserve_highest_r_from": 3,
                "cycle_rebuild_guard_enabled": True,
                "cycle_rebuild_guard_stop_count": 12,
                "cycle_rebuild_guard_min_loss": "5000",
                "cycle_rebuild_guard_recovery_pips": "5",
            }
        )
        d = cfg.to_dict()
        cfg2 = SnowballStrategyConfig.from_dict(d)
        assert cfg2.m_pips == Decimal("30")
        assert cfg2.base_units == cfg.base_units
        assert cfg2.refill_limit_enabled is True
        assert cfg2.rebuild_entry_price_mode == "stop_loss_exit"
        assert cfg2.rebuild_stop_loss_mode == "manual"
        assert cfg2.rebuild_stop_loss_manual_pips == [
            Decimal("11"),
            Decimal("12"),
            Decimal("13"),
            Decimal("14"),
            Decimal("15"),
            Decimal("16"),
        ]
        assert cfg2.rebuild_take_profit_mode == "manual"
        assert cfg2.rebuild_take_profit_manual_pips == [
            Decimal("21"),
            Decimal("22"),
            Decimal("23"),
            Decimal("24"),
            Decimal("25"),
            Decimal("26"),
        ]
        assert cfg2.preserve_highest_retracement_enabled is True
        assert cfg2.preserve_highest_r_from == 3
        assert cfg2.cycle_rebuild_guard_enabled is True
        assert cfg2.cycle_rebuild_guard_stop_count == 12
        assert cfg2.cycle_rebuild_guard_min_loss == Decimal("5000")
        assert cfg2.cycle_rebuild_guard_recovery_pips == Decimal("5")

    def test_auto_base_units_floor_to_configured_step(self):
        cfg = SnowballStrategyConfig.from_dict(
            {
                "base_units": 9999,
                "base_units_auto_adjust_enabled": True,
                "base_units_balance_ratio": "1000",
                "base_units_step": 100,
            }
        )

        assert cfg.effective_base_units(Decimal("1000000")) == 1000
        assert cfg.effective_base_units(Decimal("1099999")) == 1000
        assert cfg.effective_base_units(Decimal("1100000")) == 1100
        assert cfg.effective_base_units(Decimal("2000000")) == 2000
        assert cfg.effective_base_units(Decimal("950000")) == 900

    def test_auto_base_units_can_floor_to_configured_base_units(self):
        cfg = SnowballStrategyConfig.from_dict(
            {
                "base_units": 1000,
                "base_units_auto_adjust_enabled": True,
                "base_units_balance_ratio": "1000",
                "base_units_step": 100,
                "base_units_auto_adjust_floor_enabled": True,
            }
        )

        assert cfg.effective_base_units(Decimal("950000")) == 1000
        assert cfg.effective_base_units(Decimal("1000000")) == 1000
        assert cfg.effective_base_units(Decimal("1100000")) == 1100

    def test_auto_base_units_disabled_uses_fixed_base_units(self):
        cfg = SnowballStrategyConfig.from_dict(
            {
                "base_units": 1500,
                "base_units_auto_adjust_enabled": False,
            }
        )

        assert cfg.effective_base_units(Decimal("2000000")) == 1500

    def test_warmup_scaled_base_units_applies_ratio_to_current_base_units(self):
        cfg = SnowballStrategyConfig.from_dict(
            {
                "base_units": 9999,
                "base_units_auto_adjust_enabled": True,
                "base_units_balance_ratio": "1000",
                "base_units_step": 100,
            }
        )

        assert (
            cfg.warmup_scaled_base_units(
                Decimal("1000000"),
                ratio_pct=Decimal("50"),
            )
            == 500
        )
        assert (
            cfg.warmup_scaled_base_units(
                Decimal("1100000"),
                ratio_pct=Decimal("50"),
            )
            == 500
        )
        assert (
            cfg.warmup_scaled_base_units(
                Decimal("1200000"),
                ratio_pct=Decimal("50"),
            )
            == 600
        )

    def test_auto_base_units_validate_ratio_and_step(self):
        with pytest.raises(ValueError, match="base_units_balance_ratio"):
            SnowballStrategyConfig.from_dict(
                {
                    "base_units_auto_adjust_enabled": True,
                    "base_units_balance_ratio": "0",
                }
            ).validate()

        with pytest.raises(ValueError, match="base_units_step"):
            SnowballStrategyConfig.from_dict(
                {
                    "base_units_auto_adjust_enabled": True,
                    "base_units_step": 0,
                }
            ).validate()

    def test_validate_warmup_controls(self):
        with pytest.raises(ValueError, match="warmup_initial_unit_ratio_pct"):
            SnowballStrategyConfig.from_dict({"warmup_initial_unit_ratio_pct": "0"}).validate()

        with pytest.raises(ValueError, match="warmup_completion_mode"):
            SnowballStrategyConfig.from_dict({"warmup_completion_mode": "unknown"}).validate()

        SnowballStrategyConfig.from_dict(
            {
                "warmup_enabled": True,
                "warmup_completion_mode": "duration_or_tp_closes",
                "warmup_min_elapsed_minutes": 60,
                "warmup_required_tp_closes": 2,
            }
        ).validate()

    def test_validate_rebuild_entry_price_mode(self):
        with pytest.raises(ValueError, match="rebuild_entry_price_mode"):
            SnowballStrategyConfig.from_dict({"rebuild_entry_price_mode": "unknown"}).validate()

    def test_validate_manual_intervals_count(self):
        with pytest.raises(ValueError, match="manual_intervals"):
            SnowballStrategyConfig.from_dict(
                {
                    "interval_mode": "manual",
                    "manual_intervals": ["10", "20"],
                    "r_max": 5,
                    "m_pips": "30",
                }
            ).validate()

    def test_validate_passes_for_valid_config(self):
        cfg = SnowballStrategyConfig.from_dict(
            {
                "shrink_enabled": True,
                "m_th": "70",
                "m_pips": "30",
            }
        )
        cfg.validate()

    def test_validate_refill_limit_only_applies_when_refill_limit_enabled(self):
        SnowballStrategyConfig.from_dict(
            {"r_max": 3, "refill_limit_enabled": False, "refill_up_to": 5}
        ).validate()
        SnowballStrategyConfig.from_dict(
            {"r_max": 3, "refill_limit_enabled": True, "refill_up_to": 3}
        ).validate()

        with pytest.raises(ValueError, match="refill_up_to"):
            SnowballStrategyConfig.from_dict(
                {"r_max": 3, "refill_limit_enabled": True, "refill_up_to": 4}
            ).validate()

    def test_validate_rebuild_manual_stop_loss_requires_all_slots(self):
        with pytest.raises(ValueError, match="rebuild_stop_loss_manual_pips"):
            SnowballStrategyConfig.from_dict(
                {
                    "r_max": 5,
                    "rebuild_stop_loss_mode": "manual",
                    "rebuild_stop_loss_manual_pips": ["10", "11", "12"],
                }
            ).validate()

    def test_rebuild_same_pips_stop_loss_mode_is_valid(self):
        cfg = SnowballStrategyConfig.from_dict({"rebuild_stop_loss_mode": "same_pips"})

        cfg.validate()

        assert cfg.rebuild_stop_loss_mode == "same_pips"

    def test_validate_rebuild_manual_take_profit_requires_all_slots(self):
        with pytest.raises(ValueError, match="rebuild_take_profit_manual_pips"):
            SnowballStrategyConfig.from_dict(
                {
                    "r_max": 5,
                    "rebuild_take_profit_mode": "manual",
                    "rebuild_take_profit_manual_pips": ["10", "11", "12"],
                }
            ).validate()

    def test_rebuild_manual_take_profit_is_valid(self):
        cfg = SnowballStrategyConfig.from_dict(
            {
                "rebuild_take_profit_mode": "manual",
                "rebuild_take_profit_manual_pips": [
                    "10",
                    "11",
                    "12",
                    "13",
                    "14",
                    "15",
                    "16",
                    "17",
                ],
            }
        )

        cfg.validate()
        assert cfg.rebuild_take_profit_mode == "manual"

    def test_rebuild_stop_loss_exit_entry_price_mode_is_valid(self):
        cfg = SnowballStrategyConfig.from_dict(
            {
                "rebuild_entry_price_mode": "stop_loss_exit",
            }
        )

        cfg.validate()

        assert cfg.rebuild_entry_price_mode == "stop_loss_exit"

    def test_validate_cycle_rebuild_guard_controls(self):
        SnowballStrategyConfig.from_dict(
            {
                "stop_loss_enabled": True,
                "rebuild_enabled": True,
                "cycle_rebuild_guard_enabled": True,
                "cycle_rebuild_guard_stop_count": 15,
                "cycle_rebuild_guard_min_loss": "0",
                "cycle_rebuild_guard_recovery_pips": "3",
            }
        ).validate()

        with pytest.raises(ValueError, match="cycle_rebuild_guard_stop_count"):
            SnowballStrategyConfig.from_dict(
                {
                    "stop_loss_enabled": True,
                    "rebuild_enabled": True,
                    "cycle_rebuild_guard_enabled": True,
                    "cycle_rebuild_guard_stop_count": 0,
                }
            ).validate()

        with pytest.raises(ValueError, match="cycle_rebuild_guard_enabled"):
            SnowballStrategyConfig.from_dict(
                {
                    "stop_loss_enabled": False,
                    "rebuild_enabled": True,
                    "cycle_rebuild_guard_enabled": True,
                }
            ).validate()

    def test_validate_rejects_preserve_highest_r_from_above_r_max(self):
        with pytest.raises(ValueError, match="preserve_highest_r_from"):
            SnowballStrategyConfig.from_dict(
                {
                    "m_pips": "30",
                    "r_max": 4,
                    "preserve_highest_retracement_enabled": True,
                    "preserve_highest_r_from": 5,
                }
            ).validate()

    def test_from_dict_ignores_preserve_highest_r_from_when_flag_disabled(self):
        cfg = SnowballStrategyConfig.from_dict(
            {
                "m_pips": "30",
                "preserve_highest_retracement_enabled": False,
                "preserve_highest_r_from": 2,
            }
        )

        assert cfg.preserve_highest_retracement_enabled is False
        assert cfg.preserve_highest_r_from == 0

    def test_strict_from_dict_allows_omitted_preserve_highest_r_from_when_disabled(self):
        raw = SnowballStrategyConfig.from_dict({}).to_dict()
        raw["preserve_highest_retracement_enabled"] = False
        raw.pop("preserve_highest_r_from")

        cfg = SnowballStrategyConfig.strict_from_dict(raw)

        assert cfg.preserve_highest_retracement_enabled is False
        assert cfg.preserve_highest_r_from == 0

    def test_strict_from_dict_requires_preserve_highest_r_from_when_enabled(self):
        raw = SnowballStrategyConfig.from_dict({}).to_dict()
        raw["preserve_highest_retracement_enabled"] = True
        raw.pop("preserve_highest_r_from")

        with pytest.raises(ValueError, match="preserve_highest_r_from"):
            SnowballStrategyConfig.strict_from_dict(raw)

    def test_strict_from_dict_accepts_legacy_parameters_without_warmup_fields(self):
        raw = SnowballStrategyConfig.from_dict({}).to_dict()
        for key in list(raw):
            if key.startswith("warmup_"):
                raw.pop(key)

        cfg = SnowballStrategyConfig.strict_from_dict(raw)

        assert cfg.warmup_enabled is False
        assert cfg.warmup_completion_mode == "duration"


class TestStopLossClosedEntry:
    def test_serializes_stop_loss_exit_price_and_closed_at(self):
        pending = StopLossClosedEntry(
            entry_price=Decimal("144.547"),
            close_price=Decimal("144.697"),
            units=3000,
            direction=Direction.LONG,
            role="initial",
            layer_number=1,
            retracement_count=0,
            step=1,
            cycle_id=1,
            stop_loss_loss_pips=Decimal("35"),
            stop_loss_exit_price=Decimal("144.197"),
            closed_at=T0,
        )

        restored = StopLossClosedEntry.from_dict(pending.to_dict())

        assert restored.stop_loss_exit_price == Decimal("144.197")
        assert restored.closed_at == T0


class TestEntry:
    def test_to_dict_roundtrip(self):
        entry = Entry(
            entry_id=1,
            step=2,
            direction=Direction.LONG,
            entry_price=Decimal("150.00"),
            close_price=Decimal("150.50"),
            units=1000,
            opened_at=T0,
            role="initial",
        )
        d = entry.to_dict()
        restored = Entry.from_dict(d)
        assert restored.entry_id == 1
        assert restored.direction == Direction.LONG
        assert restored.units == 1000
        assert restored.entry_price == Decimal("150.00")

    def test_grid_key(self):
        e = _entry(layer_number=2, retracement_count=3)
        assert e.grid_key == (2, 3)


class TestSlot:
    def test_fill_and_close(self):
        slot = Slot(index=1)
        assert slot.is_empty
        assert not slot.ever_closed
        entry = _entry()
        slot.fill(entry)
        assert slot.is_occupied
        assert slot.build_count == 1
        closed = slot.close(refillable=False)
        assert closed is entry
        assert slot.is_empty
        assert slot.ever_closed

    def test_build_count_increments_on_rebuild(self):
        slot = Slot(index=1)
        slot.fill(_entry(entry_id=1))
        slot.close_for_stop_loss(
            StopLossClosedEntry(
                entry_price=Decimal("150.00"),
                close_price=Decimal("150.50"),
                units=1000,
                direction=Direction.LONG,
                role="counter",
                layer_number=1,
                retracement_count=1,
                step=1,
                cycle_id=1,
                lifecycle_stop_loss_count=1,
            )
        )
        rebuilt = _entry(entry_id=2)
        rebuilt.is_rebuild = True
        slot.complete_rebuild(rebuilt)

        assert slot.build_count == 2

    def test_refillable_close(self):
        slot = Slot(index=1)
        slot.fill(_entry())
        slot.close(refillable=True)
        assert slot.is_available
        assert not slot.ever_closed

    def test_to_dict_roundtrip(self):
        slot = Slot(index=3, ever_closed=True)
        d = slot.to_dict()
        restored = Slot.from_dict(d)
        assert restored.index == 3
        assert restored.ever_closed is True
        assert restored.entry is None
        assert restored.build_count == 1

    def test_from_dict_infers_legacy_build_count(self):
        d = {
            "index": 3,
            "entry": None,
            "ever_closed": True,
        }

        restored = Slot.from_dict(d)

        assert restored.build_count == 1


class TestLayer:
    def test_create_has_r0_through_rmax(self):
        layer = Layer.create(1, 7, 1000)
        assert layer.layer_number == 1
        assert len(layer.slots) == 8  # R0 + R1…R7
        assert layer.slots[0].index == 0
        assert layer.slots[7].index == 7
        assert all(s.is_empty for s in layer.slots)

    def test_next_available_counter_slot_skips_r0(self):
        layer = Layer.create(1, 3, 1000)
        slot = layer.next_available_counter_slot()
        assert slot is not None
        assert slot.index == 1  # R1, not R0

    def test_next_available_counter_slot_after_fill(self):
        layer = Layer.create(1, 3, 1000)
        layer.slots[1].fill(_entry(entry_id=1, retracement_count=1))
        slot = layer.next_available_counter_slot()
        assert slot is not None
        assert slot.index == 2

    def test_needs_new_layer_after_seal(self):
        layer = Layer.create(1, 3, 1000, refill_up_to=0)
        layer.slots[1].fill(_entry(entry_id=1))
        layer.slots[1].close(refillable=False)
        assert layer.needs_new_layer is True

    def test_slot_at(self):
        layer = Layer.create(1, 3, 1000)
        assert layer.slot_at(0) is not None
        assert layer.slot_at(0).index == 0
        assert layer.slot_at(3) is not None
        assert layer.slot_at(4) is None

    def test_close_slot_auto_refillable(self):
        layer = Layer.create(1, 3, 1000, refill_up_to=2)
        layer.slots[1].fill(_entry(entry_id=1))
        layer.close_slot(1)  # R1 <= refill_up_to=2 → refillable
        assert layer.slots[1].is_available

        layer.slots[3].fill(_entry(entry_id=2))
        layer.close_slot(3)  # R3 > refill_up_to=2 → sealed
        assert layer.slots[3].ever_closed

    def test_previous_present_slot_returns_nearest_lower_present_slot(self):
        layer = Layer.create(1, 4, 1000)
        layer.slots[0].fill(_entry(entry_id=1, retracement_count=0))
        layer.slots[3].fill(_entry(entry_id=2, retracement_count=3))

        previous = layer.previous_present_slot(1)
        assert previous is not None
        assert previous.index == 0

    def test_to_dict_roundtrip(self):
        layer = Layer.create(2, 3, 1500)
        d = layer.to_dict()
        restored = Layer.from_dict(d)
        assert restored.layer_number == 2
        assert len(restored.slots) == 4  # R0…R3
        assert restored.base_units == 1500


class TestPositionGrid:
    def _grid_with_entries(self) -> PositionGrid:
        """L1: R0(id=1), R1(id=2), R2(id=3).  L2: R0(id=4), R1(id=5)."""
        grid = PositionGrid()
        l0 = Layer.create(1, 3, 1000)
        l0.slot_at(0).fill(_entry(entry_id=1, layer_number=1, retracement_count=0, role="initial"))
        l0.slot_at(1).fill(_entry(entry_id=2, layer_number=1, retracement_count=1))
        l0.slot_at(2).fill(_entry(entry_id=3, layer_number=1, retracement_count=2))
        grid.add_layer(l0)

        l1 = Layer.create(2, 3, 1000)
        l1.slot_at(0).fill(
            _entry(entry_id=4, layer_number=2, retracement_count=0, role="layer_initial")
        )
        l1.slot_at(1).fill(_entry(entry_id=5, layer_number=2, retracement_count=1))
        grid.add_layer(l1)
        return grid

    def test_head_entry_is_oldest(self):
        grid = self._grid_with_entries()
        head = grid.head_entry()
        assert head is not None
        assert head.entry_id == 1

    def test_tail_entry_is_newest(self):
        grid = self._grid_with_entries()
        tail = grid.tail_entry()
        assert tail is not None
        assert tail.entry_id == 5

    def test_head_shifts_after_front_removal(self):
        grid = self._grid_with_entries()
        grid.remove_entry(1)  # remove L0/R0
        head = grid.head_entry()
        assert head is not None
        assert head.entry_id == 2  # L0/R1 is now the oldest

    def test_has_counter_entries(self):
        grid = self._grid_with_entries()
        assert grid.has_counter_entries() is True

    def test_no_counter_entries_when_only_head(self):
        grid = PositionGrid()
        l0 = Layer.create(1, 3, 1000)
        l0.slot_at(0).fill(_entry(entry_id=1, role="initial"))
        grid.add_layer(l0)
        assert grid.has_counter_entries() is False

    def test_front_entry_with_multi_positions_returns_lowest_r(self):
        """L1 has 3 entries → front_entry returns L1/R0 (lowest R)."""
        grid = self._grid_with_entries()
        front = grid.front_entry()
        assert front is not None
        assert front.entry_id == 1  # L1/R0

    def test_front_entry_skips_single_layer_when_upper_has_multi(self):
        """L1 has 1 entry, L2 has 2 entries → skip L1, return L2/R0."""
        grid = PositionGrid()
        l0 = Layer.create(1, 3, 1000)
        l0.slot_at(0).fill(_entry(entry_id=1, layer_number=1, retracement_count=0, role="initial"))
        grid.add_layer(l0)

        l1 = Layer.create(2, 3, 1000)
        l1.slot_at(0).fill(
            _entry(entry_id=4, layer_number=2, retracement_count=0, role="layer_initial")
        )
        l1.slot_at(1).fill(_entry(entry_id=5, layer_number=2, retracement_count=1))
        grid.add_layer(l1)

        front = grid.front_entry()
        assert front is not None
        assert front.entry_id == 4  # L2/R0, not L1/R0

    def test_front_entry_closes_single_when_no_upper_multi(self):
        """L1 has 1 entry, L2 has 1 entry → close L1/R0 (no upper multi)."""
        grid = PositionGrid()
        l0 = Layer.create(1, 3, 1000)
        l0.slot_at(0).fill(_entry(entry_id=1, layer_number=1, retracement_count=0, role="initial"))
        grid.add_layer(l0)

        l1 = Layer.create(2, 3, 1000)
        l1.slot_at(0).fill(
            _entry(entry_id=4, layer_number=2, retracement_count=0, role="layer_initial")
        )
        grid.add_layer(l1)

        front = grid.front_entry()
        assert front is not None
        assert front.entry_id == 1  # L1/R0

    def test_front_entry_progressive_shrink_sequence(self):
        """Simulate a full shrink sequence with the preservation rule.

        Grid: L1:[R0, R1], L2:[R0, R1, R2, R3]
        Expected order:
        1. L1/R0 (L1 has 2 → close lowest R)
        2. L2/R0 (L1 has 1, L2 has 4 → skip L1, close L2 lowest R)
        3. L2/R1 (L1 has 1, L2 has 3 → skip L1, close L2 lowest R)
        4. L2/R2 (L1 has 1, L2 has 2 → skip L1, close L2 lowest R)
        5. L1/R1 (L1 has 1, L2 has 1 → no upper multi, close L1)
        6. L2/R3 (L1 empty, L2 has 1 → close it)
        """
        grid = PositionGrid()
        l0 = Layer.create(1, 3, 1000)
        l0.slot_at(0).fill(_entry(entry_id=1, layer_number=1, retracement_count=0))
        l0.slot_at(1).fill(_entry(entry_id=2, layer_number=1, retracement_count=1))
        grid.add_layer(l0)

        l1 = Layer.create(2, 3, 1000)
        l1.slot_at(0).fill(_entry(entry_id=10, layer_number=2, retracement_count=0))
        l1.slot_at(1).fill(_entry(entry_id=11, layer_number=2, retracement_count=1))
        l1.slot_at(2).fill(_entry(entry_id=12, layer_number=2, retracement_count=2))
        l1.slot_at(3).fill(_entry(entry_id=13, layer_number=2, retracement_count=3))
        grid.add_layer(l1)

        close_order = []
        for _ in range(6):
            e = grid.front_entry()
            assert e is not None, f"Expected entry but got None after closing {close_order}"
            close_order.append(e.entry_id)
            grid.remove_entry(e.entry_id)

        assert close_order == [1, 10, 11, 12, 2, 13]
        assert grid.front_entry() is None

    def test_is_empty(self):
        grid = PositionGrid()
        grid.add_layer(Layer.create(1, 3, 1000))
        assert grid.is_empty() is True

    def test_all_entries(self):
        grid = self._grid_with_entries()
        assert len(grid.all_entries()) == 5

    def test_is_fully_pending_uses_f_max_as_total_layer_count(self):
        grid = PositionGrid()
        for layer_number in range(1, 4):
            layer = Layer.create(layer_number, 1, 1000)
            layer.slot_at(0).pending_rebuild = object()
            layer.slot_at(1).pending_rebuild = object()
            grid.add_layer(layer)

        assert grid.is_fully_pending(3) is True
        assert grid.is_fully_pending(4) is False


class TestSnowballCycle:
    def test_initial_entry_is_dynamic_head(self):
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        l0 = Layer.create(0, 3, 1000)
        l0.slot_at(0).fill(_entry(entry_id=10, role="initial"))
        l0.slot_at(1).fill(_entry(entry_id=11))
        cycle.add_layer(l0)

        assert cycle.initial_entry is not None
        assert cycle.initial_entry.entry_id == 10

        # Remove head → initial_entry shifts
        cycle.remove_entry(10)
        assert cycle.initial_entry is not None
        assert cycle.initial_entry.entry_id == 11

    def test_to_dict_roundtrip(self):
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        cycle.stop_loss_count = 3
        l0 = Layer.create(0, 3, 1000)
        l0.slot_at(0).fill(_entry(entry_id=1, role="initial"))
        l0.slot_at(1).fill(_entry(entry_id=2, retracement_count=1))
        cycle.add_layer(l0)

        d = cycle.to_dict()
        restored = SnowballCycle.from_dict(d)
        assert restored.cycle_id == 1
        assert restored.direction == Direction.LONG
        assert restored.initial_entry is not None
        assert restored.initial_entry.entry_id == 1
        assert len(restored.grid.all_entries()) == 2
        assert restored.stop_loss_count == 3

    def test_cycle_from_dict_requires_grid_state(self):
        stale_state = {
            "cycle_id": 1,
            "direction": "long",
            "initial_entry": {
                "entry_id": 1,
                "step": 1,
                "direction": "long",
                "entry_price": "150.00",
                "close_price": "150.50",
                "units": 1000,
                "opened_at": "2026-01-01T00:00:00+00:00",
                "role": "initial",
                "layer_number": 1,
                "retracement_count": 0,
            },
            "layers": [
                {
                    "layer_number": 1,
                    "base_units": 1000,
                    "refill_up_to": 2,
                    "slots": [
                        {
                            "index": 1,
                            "entry": {
                                "entry_id": 2,
                                "direction": "long",
                                "entry_price": "149.70",
                                "close_price": "150.00",
                                "units": 2000,
                                "opened_at": "2026-01-01T00:00:00+00:00",
                                "step": 2,
                                "layer_number": 1,
                                "retracement_count": 1,
                            },
                            "ever_closed": False,
                        },
                    ],
                }
            ],
        }

        with pytest.raises(KeyError, match="grid"):
            SnowballCycle.from_dict(stale_state)


class TestSnowballStrategyState:
    def test_default_state(self):
        ss = SnowballStrategyState()
        assert ss.protection_level == ProtectionLevel.NORMAL
        assert ss.initialised is False
        assert ss.cycles == []

    def test_to_dict_roundtrip(self):
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        l0 = Layer.create(0, 7, 1000)
        l0.slot_at(0).fill(_entry(entry_id=1, role="initial"))
        l0.slot_at(1).fill(_entry(entry_id=2, retracement_count=1))
        cycle.add_layer(l0)

        ss = SnowballStrategyState(
            initialised=True,
            cycles=[cycle],
            protection_level=ProtectionLevel.SHRINK,
        )
        d = ss.to_dict()
        ss2 = SnowballStrategyState.from_dict(d)
        assert ss2.initialised is True
        assert len(ss2.cycles) == 1
        assert ss2.protection_level == ProtectionLevel.SHRINK

    def test_from_strategy_state_none(self):
        ss = SnowballStrategyState.from_strategy_state(None)
        assert ss.initialised is False
