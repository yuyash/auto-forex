"""Unit tests for SnowballStrategy class."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from apps.trading.dataclasses.tick import Tick
from apps.trading.enums import Direction, EventType, StrategyType
from apps.trading.strategies.snowball.config import SnowballStrategyConfig
from apps.trading.strategies.snowball.counter_flow import (
    CounterAdverseInterval,
    CounterEntryFactory,
    CounterHeadContext,
)
from apps.trading.strategies.snowball.cycle_orchestrator import (
    SnowballActiveCycleProcessor,
    SnowballCycleReseeder,
)
from apps.trading.strategies.snowball.cycle_state import SnowballCycle, SnowballStrategyState
from apps.trading.strategies.snowball.entries import Entry, StopLossClosedEntry
from apps.trading.strategies.snowball.enums import CycleStatus
from apps.trading.strategies.snowball.grid_policy import SNOWBALL_GRID_POLICY
from apps.trading.strategies.snowball.grid_models import Layer, Slot
from apps.trading.strategies.snowball.pricing import SNOWBALL_PRICING
from apps.trading.strategies.snowball.reconciliation import SNOWBALL_RECONCILER
from apps.trading.strategies.snowball.strategy import SnowballStrategy
from apps.trading.strategies.snowball.stop_loss_flow import (
    StopLossRebuildPricePlanner,
    StopLossRebuildProcessor,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class DummyState:
    """Minimal state shape required by strategy.on_tick."""

    strategy_state: dict[str, Any] = field(default_factory=dict)
    current_balance: Decimal = Decimal("100000")
    ticks_processed: int = 1


def _make_tick(ts: datetime, bid: str, ask: str) -> Tick:
    return Tick.create(
        instrument="USD_JPY",
        timestamp=ts,
        bid=Decimal(bid),
        ask=Decimal(ask),
        mid=(Decimal(bid) + Decimal(ask)) / Decimal("2"),
    )


def _strategy(overrides: dict[str, Any] | None = None) -> SnowballStrategy:
    params: dict[str, Any] = {
        "base_units": 1000,
        "m_pips": "50",
        "r_max": 7,
        "f_max": 3,
        "n_pips_head": "30",
        "n_pips_tail": "14",
        "n_pips_flat_steps": 2,
        "interval_mode": "constant",
        "counter_tp_mode": "weighted_avg",
        "shrink_enabled": False,
        "m_th": "70",
    }
    if overrides:
        params.update(overrides)
    config = SnowballStrategyConfig.from_dict(params)
    return SnowballStrategy("USD_JPY", Decimal("0.01"), config)


class TestSnowballLayerInitialPricing:
    def _previous_layer(
        self,
        *,
        direction: Direction = Direction.LONG,
        close_price: Decimal = Decimal("157.8686666667"),
        pending: bool = False,
    ) -> Layer:
        layer = Layer.create(layer_number=1, r_max=5, base_units=1000)
        slot = layer.slot_at(5)
        assert slot is not None
        if pending:
            slot.pending_rebuild = StopLossClosedEntry(
                entry_price=Decimal("157.524"),
                close_price=close_price,
                units=9000,
                direction=direction,
                role="counter",
                layer_number=1,
                retracement_count=5,
                step=6,
                cycle_id=1,
            )
        else:
            slot.entry = Entry(
                entry_id=1,
                step=6,
                direction=direction,
                entry_price=Decimal("157.524"),
                close_price=close_price,
                units=9000,
                opened_at=datetime(2026, 1, 1, tzinfo=UTC),
                role="counter",
                layer_number=1,
                retracement_count=5,
            )
        return layer

    def test_long_layer_initial_uses_fixed_tp_when_previous_tp_is_farther(self):
        plan = SNOWBALL_PRICING.layer_initial_close_price(
            new_price=Decimal("141.299"),
            prev_layer=self._previous_layer(pending=True),
            direction=Direction.LONG,
            pip_size=Decimal("0.01"),
            m_pips=Decimal("15"),
        )
        close_price, formula = plan

        assert close_price == Decimal("141.449")
        assert formula == "141.299 + 15 * 0.01"
        assert plan.bound is not None
        assert plan.bound.mode == "min"
        assert plan.bound.price == Decimal("157.8686666667")

    def test_long_layer_initial_clamps_to_previous_tp_when_fixed_tp_crosses_it(self):
        plan = SNOWBALL_PRICING.layer_initial_close_price(
            new_price=Decimal("157.800"),
            prev_layer=self._previous_layer(close_price=Decimal("157.8686666667")),
            direction=Direction.LONG,
            pip_size=Decimal("0.01"),
            m_pips=Decimal("15"),
        )
        close_price, formula = plan

        assert close_price == Decimal("157.8686666667")
        assert formula == "min(157.800 + 15 * 0.01, 157.86867)"
        assert plan.bound is not None
        assert plan.bound.mode == "min"
        assert plan.bound.price == Decimal("157.8686666667")

    def test_short_layer_initial_uses_fixed_tp_when_previous_tp_is_farther(self):
        plan = SNOWBALL_PRICING.layer_initial_close_price(
            new_price=Decimal("157.800"),
            prev_layer=self._previous_layer(
                direction=Direction.SHORT,
                close_price=Decimal("142.280"),
                pending=True,
            ),
            direction=Direction.SHORT,
            pip_size=Decimal("0.01"),
            m_pips=Decimal("15"),
        )
        close_price, formula = plan

        assert close_price == Decimal("157.650")
        assert formula == "157.800 - 15 * 0.01"
        assert plan.bound is not None
        assert plan.bound.mode == "max"
        assert plan.bound.price == Decimal("142.280")

    def test_short_layer_initial_clamps_to_previous_tp_when_fixed_tp_crosses_it(self):
        plan = SNOWBALL_PRICING.layer_initial_close_price(
            new_price=Decimal("157.800"),
            prev_layer=self._previous_layer(
                direction=Direction.SHORT,
                close_price=Decimal("157.700"),
            ),
            direction=Direction.SHORT,
            pip_size=Decimal("0.01"),
            m_pips=Decimal("15"),
        )
        close_price, formula = plan

        assert close_price == Decimal("157.700")
        assert formula == "max(157.800 - 15 * 0.01, 157.70000)"
        assert plan.bound is not None
        assert plan.bound.mode == "max"
        assert plan.bound.price == Decimal("157.700")


# ===================================================================
# Basic properties
# ===================================================================


class TestSnowballStrategyProperties:
    def test_strategy_type(self):
        s = _strategy()
        assert s.strategy_type == StrategyType.SNOWBALL

    def test_instrument_and_pip_size(self):
        s = _strategy()
        assert s.instrument == "USD_JPY"
        assert s.pip_size == Decimal("0.01")

    def test_runtime_adaptive_interval_helpers_round_separately(self):
        s = _strategy({"m_pips": "50", "n_pips_head": "30", "round_step_pips": "0.1"})
        s._snowball_adaptive_counter_interval_multiplier = Decimal("2")
        s._snowball_adaptive_trend_interval_multiplier = Decimal("1.5")

        assert s.counter_interval_pips(1) == Decimal("60.0")
        assert s.trend_take_profit_pips() == Decimal("75.0")

    def test_runtime_adaptive_interval_helpers_allow_contraction(self):
        s = _strategy({"m_pips": "50", "n_pips_head": "30", "round_step_pips": "0.1"})
        s._snowball_adaptive_counter_interval_multiplier = Decimal("0.5")
        s._snowball_adaptive_trend_interval_multiplier = Decimal("0.6")

        assert s.counter_interval_pips(1) == Decimal("15.0")
        assert s.trend_take_profit_pips() == Decimal("30.0")


# ===================================================================
# parse_config / normalize / defaults / validate
# ===================================================================


class TestSnowballStrategyClassMethods:
    def test_normalize_parameters_returns_dict(self):
        result = SnowballStrategy.normalize_parameters({"base_units": 2000})
        assert isinstance(result, dict)
        assert result["base_units"] == 2000
        assert result["base_units_auto_adjust_enabled"] is False
        assert "base_units_balance_ratio" not in result
        assert "base_units_step" not in result
        assert "base_units_auto_adjust_floor_enabled" not in result
        assert result["rebuild_entry_price_mode"] == "original_entry"
        assert result["rebuild_stop_loss_mode"] == "same_pips"
        assert result["rebuild_take_profit_mode"] == "same_pips"
        assert result["preserve_highest_retracement_enabled"] is False
        assert result["stop_loss_mode"] == "auto"
        assert "rebuild_take_profit_recovery_enabled" not in result
        assert "rebuild_take_profit_recovery_mode" not in result
        assert "preserve_highest_r_from" not in result

    def test_default_parameters(self):
        defaults = SnowballStrategy.default_parameters()
        assert isinstance(defaults, dict)
        assert "base_units" in defaults
        assert defaults["base_units_auto_adjust_enabled"] is False
        assert "base_units_balance_ratio" not in defaults
        assert "base_units_step" not in defaults
        assert "base_units_auto_adjust_floor_enabled" not in defaults
        assert "m_pips" in defaults
        assert defaults["rebuild_entry_price_mode"] == "original_entry"
        assert "rebuild_stop_loss_mode" in defaults
        assert "rebuild_take_profit_mode" in defaults
        assert defaults["rebuild_stop_loss_mode"] == "same_pips"
        assert defaults["rebuild_take_profit_mode"] == "same_pips"
        assert "preserve_highest_retracement_enabled" in defaults
        assert defaults["stop_loss_mode"] == "auto"
        assert "rebuild_take_profit_recovery_enabled" not in defaults
        assert "rebuild_take_profit_recovery_mode" not in defaults
        assert "preserve_highest_r_from" not in defaults
        assert defaults["warmup_enabled"] is False
        assert "warmup_initial_unit_ratio_pct" not in defaults
        assert "warmup_max_positions" not in defaults
        assert "warmup_max_r" not in defaults
        assert defaults["add_margin_guard_enabled"] is False
        assert "add_margin_guard_max_pct" not in defaults
        assert defaults["volatility_guard_enabled"] is False
        assert "volatility_guard_target" not in defaults
        assert "volatility_guard_source" not in defaults
        assert "volatility_guard_candle_granularity" not in defaults
        assert "volatility_guard_cooldown_minutes" not in defaults
        assert defaults["add_trend_guard_enabled"] is False
        assert "add_trend_candle_granularity" not in defaults
        assert "add_trend_ema_period" not in defaults
        assert defaults["adaptive_counter_interval_enabled"] is False
        assert "adaptive_counter_interval_source" not in defaults
        assert "adaptive_counter_interval_candle_granularity" not in defaults
        assert defaults["adaptive_trend_interval_enabled"] is False
        assert "adaptive_trend_interval_source" not in defaults
        assert "adaptive_trend_interval_candle_granularity" not in defaults

    def test_normalize_parameters_keeps_only_visible_warmup_fields(self):
        result = SnowballStrategy.normalize_parameters(
            {
                "warmup_enabled": True,
                "warmup_initial_unit_ratio_pct": "40",
                "warmup_start_gate_enabled": False,
                "warmup_position_limit_enabled": False,
                "warmup_max_r": 1,
                "warmup_rebuild_limit_enabled": False,
                "warmup_completion_mode": "tp_closes",
                "warmup_required_tp_closes": 2,
            }
        )

        assert result["warmup_enabled"] is True
        assert result["warmup_initial_unit_ratio_pct"] == "40"
        assert result["warmup_start_gate_enabled"] is False
        assert "warmup_gate_spread_enabled" not in result
        assert "warmup_gate_max_spread_pips" not in result
        assert result["warmup_position_limit_enabled"] is False
        assert "warmup_max_positions" not in result
        assert result["warmup_max_r"] == 1
        assert result["warmup_rebuild_limit_enabled"] is False
        assert "warmup_max_rebuilds_per_tick" not in result
        assert result["warmup_completion_mode"] == "tp_closes"
        assert "warmup_min_elapsed_minutes" not in result
        assert result["warmup_required_tp_closes"] == 2

    def test_normalize_parameters_keeps_only_visible_risk_fields(self):
        result = SnowballStrategy.normalize_parameters(
            {
                "add_margin_guard_enabled": True,
                "add_margin_guard_max_pct": "68",
                "add_margin_guard_scope": "adds_and_rebuilds",
                "volatility_guard_enabled": True,
                "volatility_guard_target": "rebuilds",
                "volatility_guard_source": "candle_ema",
                "volatility_guard_candle_granularity": "M5",
                "volatility_guard_candle_ema_period": 30,
                "volatility_guard_cooldown_minutes": 45,
                "volatility_guard_atr_period": 14,
                "add_trend_guard_enabled": True,
                "add_trend_candle_granularity": "M15",
                "add_trend_ema_period": 120,
                "add_trend_max_opposite_deviation_pips": "35",
                "adaptive_counter_interval_enabled": True,
                "adaptive_counter_interval_source": "candle_ema",
                "adaptive_counter_interval_candle_granularity": "H1",
                "adaptive_counter_interval_reference_pips": "12",
                "adaptive_trend_interval_enabled": False,
                "adaptive_trend_interval_source": "atr",
            }
        )

        assert result["add_margin_guard_enabled"] is True
        assert result["add_margin_guard_max_pct"] == "68"
        assert result["add_margin_guard_scope"] == "adds_and_rebuilds"
        assert result["volatility_guard_enabled"] is True
        assert result["volatility_guard_target"] == "rebuilds"
        assert result["volatility_guard_source"] == "candle_ema"
        assert result["volatility_guard_candle_granularity"] == "M5"
        assert result["volatility_guard_candle_ema_period"] == 30
        assert result["volatility_guard_cooldown_minutes"] == 45
        assert "volatility_guard_atr_period" not in result
        assert result["add_trend_guard_enabled"] is True
        assert result["add_trend_candle_granularity"] == "M15"
        assert result["add_trend_ema_period"] == 120
        assert result["adaptive_counter_interval_enabled"] is True
        assert result["adaptive_counter_interval_source"] == "candle_ema"
        assert result["adaptive_counter_interval_candle_granularity"] == "H1"
        assert result["adaptive_counter_interval_reference_pips"] == "12"
        assert "adaptive_counter_interval_atr_period" not in result
        assert result["adaptive_trend_interval_enabled"] is False
        assert "adaptive_trend_interval_source" not in result

    def test_normalize_parameters_maps_legacy_tick_ema_source_to_candle_ema(self):
        result = SnowballStrategy.normalize_parameters(
            {
                "volatility_guard_enabled": True,
                "volatility_guard_source": "tick_ema",
                "volatility_guard_tick_ema_period": 30,
            }
        )

        assert result["volatility_guard_source"] == "candle_ema"
        assert result["volatility_guard_candle_ema_period"] == 30

    def test_parse_config_accepts_persisted_default_parameters(self):
        cfg = SnowballStrategy.parse_config(
            SimpleNamespace(config_dict=SnowballStrategy.default_parameters())
        )

        assert cfg.preserve_highest_retracement_enabled is False
        assert cfg.preserve_highest_r_from == 0
        assert cfg.base_units_auto_adjust_enabled is False

    def test_parse_config_accepts_legacy_parameters_without_auto_base_unit_fields(self):
        legacy = SnowballStrategy.default_parameters()
        legacy.pop("base_units_auto_adjust_enabled", None)
        legacy.pop("base_units_balance_ratio", None)
        legacy.pop("base_units_step", None)
        legacy.pop("base_units_auto_adjust_floor_enabled", None)

        cfg = SnowballStrategy.parse_config(SimpleNamespace(config_dict=legacy))

        assert cfg.base_units_auto_adjust_enabled is False
        assert cfg.base_units_balance_ratio == Decimal("1000")
        assert cfg.base_units_step == 100
        assert cfg.base_units_auto_adjust_floor_enabled is False

    def test_parse_config_accepts_legacy_parameters_without_warmup_fields(self):
        legacy = SnowballStrategy.default_parameters()
        for key in list(legacy):
            if key.startswith("warmup_"):
                legacy.pop(key)

        cfg = SnowballStrategy.parse_config(SimpleNamespace(config_dict=legacy))

        assert cfg.warmup_enabled is False
        assert cfg.warmup_initial_unit_ratio_pct == Decimal("50")

    def test_validate_parameters_valid(self):
        """validate_parameters should not raise for valid params + schema."""
        import json
        from pathlib import Path

        from django.conf import settings

        schema_path = Path(settings.BASE_DIR) / "apps" / "trading" / "schemas" / "snowball.json"
        with schema_path.open(encoding="utf-8") as f:
            schema = json.load(f)

        params = SnowballStrategy.default_parameters()
        SnowballStrategy.validate_parameters(parameters=params, config_schema=schema)

    def test_validate_parameters_rejects_invalid_schema_value(self):
        """JSON schema rejects base_units < 1."""
        import json
        from pathlib import Path

        from django.conf import settings

        schema_path = Path(settings.BASE_DIR) / "apps" / "trading" / "schemas" / "snowball.json"
        with schema_path.open(encoding="utf-8") as f:
            schema = json.load(f)

        params = SnowballStrategy.default_parameters()
        params["base_units"] = 0
        with pytest.raises(ValueError):
            SnowballStrategy.validate_parameters(parameters=params, config_schema=schema)


# ===================================================================
# on_tick — initialisation
# ===================================================================


class TestSnowballOnTickInit:
    def test_first_tick_initialises_baskets(self):
        s = _strategy()
        state = DummyState()
        ts = datetime(2026, 1, 1, tzinfo=UTC)

        result = s.on_tick(tick=_make_tick(ts, "150.00", "150.02"), state=state)

        ss = SnowballStrategyState.from_strategy_state(state.strategy_state)
        assert ss.initialised is True
        assert len(ss.active_cycles()) >= 1
        assert result.events  # should emit open events

    def test_second_tick_does_not_reinitialise(self):
        s = _strategy()
        state = DummyState()
        ts = datetime(2026, 1, 1, tzinfo=UTC)

        s.on_tick(tick=_make_tick(ts, "150.00", "150.02"), state=state)
        ss_after_first = SnowballStrategyState.from_strategy_state(state.strategy_state)
        entry_count = ss_after_first.next_entry_id

        state.ticks_processed += 1
        s.on_tick(tick=_make_tick(ts + timedelta(seconds=1), "150.00", "150.02"), state=state)
        ss_after_second = SnowballStrategyState.from_strategy_state(state.strategy_state)
        # next_entry_id should not jump dramatically (no re-init)
        assert ss_after_second.initialised is True
        assert ss_after_second.next_entry_id >= entry_count


class TestSnowballCycleTp:
    def _cycle_with_pending_head_and_live_counter(
        self,
        *,
        pending_head_price: Decimal = Decimal("150.00"),
        counter_close_price: Decimal = Decimal("149.80"),
    ) -> tuple[SnowballStrategyState, SnowballCycle, Layer]:
        state = SnowballStrategyState()
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        layer = Layer.create(1, 3, 1000, 2)
        layer.slot_at(0).pending_rebuild = StopLossClosedEntry(
            entry_price=pending_head_price,
            close_price=pending_head_price + Decimal("0.50"),
            units=1000,
            direction=Direction.LONG,
            role="initial",
            layer_number=1,
            retracement_count=0,
            step=1,
            root_entry_id=1,
            cycle_id=1,
            stop_loss_price=pending_head_price - Decimal("0.30"),
        )
        layer.slot_at(1).fill(
            Entry(
                entry_id=2,
                step=2,
                direction=Direction.LONG,
                entry_price=Decimal("149.70"),
                close_price=counter_close_price,
                units=2000,
                opened_at=datetime(2026, 1, 1, tzinfo=UTC),
                role="counter",
                layer_number=1,
                retracement_count=1,
                root_entry_id=1,
                parent_entry_id=1,
            )
        )
        cycle.add_layer(layer)
        state.cycles.append(cycle)
        return state, cycle, layer

    def test_head_tp_does_not_reenter_when_pending_rebuilds_remain(self):
        strategy = _strategy(
            {
                "m_pips": "15",
                "stop_loss_enabled": True,
                "rebuild_enabled": True,
                "reseed_on_all_pending": False,
            }
        )
        state, cycle, layer = self._cycle_with_pending_head_and_live_counter()

        events = strategy._process_cycle_tp(
            state,
            _make_tick(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=1), "149.80", "149.82"),
            cycle,
        )

        assert [event.event_type for event in events] == [EventType.CLOSE_POSITION]
        assert len(state.cycles) == 1
        assert layer.slot_at(0).pending_rebuild is not None
        assert layer.slot_at(1).entry is None

    def test_head_tp_does_not_reenter_when_same_direction_cycle_is_pending(self):
        strategy = _strategy({"m_pips": "15"})
        state = SnowballStrategyState()

        pending_cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        pending_cycle.status = CycleStatus.PENDING
        pending_layer = Layer.create(1, 3, 1000, 2)
        pending_layer.slot_at(0).pending_rebuild = StopLossClosedEntry(
            entry_price=Decimal("150.00"),
            close_price=Decimal("150.50"),
            units=1000,
            direction=Direction.LONG,
            role="initial",
            layer_number=1,
            retracement_count=0,
            step=1,
            root_entry_id=1,
            cycle_id=1,
        )
        pending_cycle.add_layer(pending_layer)
        state.cycles.append(pending_cycle)

        closing_cycle = SnowballCycle(cycle_id=2, direction=Direction.LONG)
        closing_layer = Layer.create(1, 3, 1000, 2)
        closing_layer.slot_at(0).fill(
            Entry(
                entry_id=2,
                step=1,
                direction=Direction.LONG,
                entry_price=Decimal("149.50"),
                close_price=Decimal("149.65"),
                units=1000,
                opened_at=datetime(2026, 1, 1, tzinfo=UTC),
                role="initial",
                layer_number=1,
                retracement_count=0,
                root_entry_id=2,
            )
        )
        closing_cycle.add_layer(closing_layer)
        state.cycles.append(closing_cycle)

        events = strategy._process_cycle_tp(
            state,
            _make_tick(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=1), "149.65", "149.67"),
            closing_cycle,
        )

        assert [event.event_type for event in events] == [EventType.CLOSE_POSITION]
        assert len(state.cycles) == 2

    def test_reseed_enabled_waits_for_reseeder_after_tp_creates_pending_cycle(self):
        strategy = _strategy(
            {
                "m_pips": "15",
                "stop_loss_enabled": True,
                "rebuild_enabled": True,
                "reseed_on_all_pending": True,
                "n_pips_head": "30",
                "interval_mode": "constant",
            }
        )
        strategy._hedging_enabled = False
        state, cycle, layer = self._cycle_with_pending_head_and_live_counter(
            pending_head_price=Decimal("150.50"),
            counter_close_price=Decimal("149.82"),
        )

        result = SnowballActiveCycleProcessor().process(
            strategy,
            state,
            _make_tick(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=1), "149.82", "149.84"),
            allow_new_positions=True,
            allow_rebuilds=True,
        )

        assert [event.event_type for event in result.events] == [EventType.CLOSE_POSITION]
        assert cycle.is_pending
        assert layer.slot_at(0).pending_rebuild is not None
        assert layer.slot_at(1).entry is None

        reseed_events = SnowballCycleReseeder().reseed(
            strategy,
            state,
            _make_tick(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=2), "149.82", "149.84"),
            allow_new_positions=True,
        )

        assert [event.event_type for event in reseed_events] == [EventType.OPEN_POSITION]
        assert len(state.cycles) == 2

    def test_rebuilt_r0_waits_for_adjusted_close_price(self):
        strategy = _strategy({"m_pips": "15"})
        state = SnowballStrategyState()
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        layer = Layer.create(1, 3, 1000, 2)
        rebuilt_r0 = Entry(
            entry_id=1,
            step=1,
            direction=Direction.LONG,
            entry_price=Decimal("141.774"),
            close_price=Decimal("143.391"),
            units=1500,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="initial",
            layer_number=1,
            retracement_count=0,
            is_rebuild=True,
            lifecycle_realized_pnl=Decimal("-2425.5"),
            lifecycle_stop_loss_count=2,
        )
        layer.slot_at(0).fill(rebuilt_r0)
        cycle.add_layer(layer)
        state.cycles.append(cycle)

        tick = _make_tick(datetime(2026, 1, 1, tzinfo=UTC), "141.954", "141.956")

        events = strategy._process_cycle_tp(state, tick, cycle)

        assert events == []
        assert layer.slot_at(0).entry is rebuilt_r0

    def test_rebuilt_r0_closes_at_adjusted_close_price(self):
        strategy = _strategy({"m_pips": "15"})
        state = SnowballStrategyState()
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        layer = Layer.create(1, 3, 1000, 2)
        rebuilt_r0 = Entry(
            entry_id=1,
            step=1,
            direction=Direction.LONG,
            entry_price=Decimal("141.774"),
            close_price=Decimal("143.391"),
            units=1500,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="initial",
            layer_number=1,
            retracement_count=0,
            is_rebuild=True,
            lifecycle_realized_pnl=Decimal("-2425.5"),
            lifecycle_stop_loss_count=2,
        )
        layer.slot_at(0).fill(rebuilt_r0)
        cycle.add_layer(layer)
        state.cycles.append(cycle)

        tick = _make_tick(
            datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=1), "143.391", "143.393"
        )

        events = strategy._process_cycle_tp(state, tick, cycle)

        assert len(events) == 2
        assert events[0].event_type == EventType.CLOSE_POSITION
        assert events[0].exit_price == Decimal("143.391")

    def test_rebuilt_r0_does_not_close_on_open_tick(self):
        strategy = _strategy({"m_pips": "15"})
        state = SnowballStrategyState()
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        layer = Layer.create(1, 3, 1000, 2)
        opened_at = datetime(2026, 1, 1, tzinfo=UTC)
        rebuilt_r0 = Entry(
            entry_id=1,
            step=1,
            direction=Direction.LONG,
            entry_price=Decimal("141.774"),
            close_price=Decimal("143.391"),
            units=1500,
            opened_at=opened_at,
            role="initial",
            layer_number=1,
            retracement_count=0,
            is_rebuild=True,
            lifecycle_realized_pnl=Decimal("-2425.5"),
            lifecycle_stop_loss_count=2,
        )
        layer.slot_at(0).fill(rebuilt_r0)
        cycle.add_layer(layer)
        state.cycles.append(cycle)

        tick = _make_tick(opened_at, "143.391", "143.393")

        events = strategy._process_cycle_tp(state, tick, cycle)

        assert events == []
        assert layer.slot_at(0).entry is rebuilt_r0

    def test_rebuilt_r0_waits_until_next_tick_before_tp_close(self):
        strategy = _strategy(
            {
                "m_pips": "15",
                "stop_loss_enabled": True,
                "rebuild_enabled": True,
            }
        )
        state = SnowballStrategyState()
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        layer = Layer.create(1, 3, 1000, 2)
        opened_at = datetime(2026, 1, 1, tzinfo=UTC)
        layer.slot_at(0).pending_rebuild = StopLossClosedEntry(
            entry_price=Decimal("141.774"),
            close_price=Decimal("143.391"),
            units=1500,
            direction=Direction.LONG,
            role="initial",
            layer_number=1,
            retracement_count=0,
            step=1,
            cycle_id=1,
            closed_at=opened_at - timedelta(seconds=1),
        )
        cycle.add_layer(layer)
        state.cycles.append(cycle)

        tick = _make_tick(opened_at, "143.391", "143.393")
        rebuild_events = strategy._process_stop_loss_rebuilds(state, tick, cycle)

        rebuilt_r0 = layer.slot_at(0).entry
        assert len(rebuild_events) == 1
        assert rebuilt_r0 is not None
        assert rebuilt_r0.opened_at == opened_at
        assert strategy._process_cycle_tp(state, tick, cycle, allow_reentry=False) == []

        next_tick_events = strategy._process_cycle_tp(
            state,
            _make_tick(opened_at + timedelta(seconds=1), "143.391", "143.393"),
            cycle,
            allow_reentry=False,
        )

        assert [event.event_type for event in next_tick_events] == [EventType.CLOSE_POSITION]

    @pytest.mark.parametrize(
        ("direction", "entry_price", "close_price", "bid", "ask", "expected_event_price"),
        [
            (
                Direction.LONG,
                Decimal("144.547"),
                Decimal("144.697"),
                "144.700",
                "144.720",
                Decimal("144.720"),
            ),
            (
                Direction.SHORT,
                Decimal("157.397"),
                Decimal("157.247"),
                "157.100",
                "157.200",
                Decimal("157.100"),
            ),
        ],
    )
    def test_rebuild_order_price_uses_tick_side_when_trigger_overshot(
        self,
        direction: Direction,
        entry_price: Decimal,
        close_price: Decimal,
        bid: str,
        ask: str,
        expected_event_price: Decimal,
    ):
        strategy = _strategy(
            {
                "stop_loss_enabled": True,
                "rebuild_enabled": True,
                "rebuild_take_profit_mode": "same",
            }
        )
        state = SnowballStrategyState()
        cycle = SnowballCycle(cycle_id=1, direction=direction)
        layer = Layer.create(1, 3, 1000, 2)
        opened_at = datetime(2026, 1, 1, tzinfo=UTC)
        layer.slot_at(0).pending_rebuild = StopLossClosedEntry(
            entry_price=entry_price,
            close_price=close_price,
            units=1500,
            direction=direction,
            role="initial",
            layer_number=1,
            retracement_count=0,
            step=1,
            cycle_id=1,
            closed_at=opened_at - timedelta(seconds=1),
        )
        cycle.add_layer(layer)
        state.cycles.append(cycle)

        events = strategy._process_stop_loss_rebuilds(
            state,
            _make_tick(opened_at, bid, ask),
            cycle,
        )

        rebuilt_r0 = layer.slot_at(0).entry
        assert len(events) == 1
        assert rebuilt_r0 is not None
        assert rebuilt_r0.entry_price == entry_price
        assert events[0].planned_entry_price == entry_price
        assert events[0].price == expected_event_price

    def test_head_tp_waits_when_counter_target_is_not_hit(self):
        strategy = _strategy({"m_pips": "15"})
        state = SnowballStrategyState()
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        layer = Layer.create(1, 3, 1000, 2)
        rebuilt_r0 = Entry(
            entry_id=1,
            step=1,
            direction=Direction.LONG,
            entry_price=Decimal("141.774"),
            close_price=Decimal("143.391"),
            units=1500,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="initial",
            layer_number=1,
            retracement_count=0,
            is_rebuild=True,
            lifecycle_realized_pnl=Decimal("-2425.5"),
            lifecycle_stop_loss_count=2,
        )
        counter = Entry(
            entry_id=2,
            step=2,
            direction=Direction.LONG,
            entry_price=Decimal("141.500"),
            close_price=Decimal("143.500"),
            units=3000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="counter",
            layer_number=1,
            retracement_count=1,
        )
        layer.slot_at(0).fill(rebuilt_r0)
        layer.slot_at(1).fill(counter)
        cycle.add_layer(layer)
        state.cycles.append(cycle)

        tick = _make_tick(datetime(2026, 1, 1, tzinfo=UTC), "143.391", "143.393")

        events = strategy._process_cycle_tp(state, tick, cycle)

        assert events == []
        assert layer.slot_at(0).entry is rebuilt_r0
        assert layer.slot_at(1).entry is counter

    @pytest.mark.parametrize(
        ("refill_limit_enabled", "expected_sealed"),
        [(False, False), (True, True)],
    )
    def test_counter_head_tp_respects_refill_policy_when_r0_is_pending(
        self, refill_limit_enabled: bool, expected_sealed: bool
    ):
        strategy = _strategy(
            {
                "r_max": 5,
                "refill_limit_enabled": refill_limit_enabled,
                "refill_up_to": 2,
            }
        )
        state = SnowballStrategyState()
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        layer = Layer.create(1, 5, 1000, strategy.config.effective_refill_up_to)
        r0_slot = layer.slot_at(0)
        counter_slot = layer.slot_at(3)
        assert r0_slot is not None
        assert counter_slot is not None
        r0_slot.pending_rebuild = StopLossClosedEntry(
            entry_price=Decimal("155.00"),
            close_price=Decimal("155.50"),
            units=1000,
            direction=Direction.LONG,
            role="initial",
            layer_number=1,
            retracement_count=0,
            step=1,
            cycle_id=1,
        )
        counter = Entry(
            entry_id=2,
            step=4,
            direction=Direction.LONG,
            entry_price=Decimal("154.00"),
            close_price=Decimal("154.50"),
            units=4000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="counter",
            layer_number=1,
            retracement_count=3,
        )
        counter_slot.fill(counter)
        cycle.add_layer(layer)
        state.cycles.append(cycle)

        tick = _make_tick(
            datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=1), "154.50", "154.52"
        )

        events = strategy._process_cycle_tp(state, tick, cycle)

        assert events[0].event_type == EventType.CLOSE_POSITION
        assert counter_slot.entry is None
        assert counter_slot.ever_closed is expected_sealed


class TestSnowballStopLossProtectionThreshold:
    def _make_cycle_with_entries(self) -> tuple[SnowballStrategyState, SnowballCycle, Entry, Entry]:
        ss = SnowballStrategyState()
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        layer = Layer.create(1, 3, 1000, 2)

        r1 = Entry(
            entry_id=1,
            step=2,
            direction=Direction.LONG,
            entry_price=Decimal("155.00"),
            close_price=Decimal("155.30"),
            units=2000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="counter",
            layer_number=1,
            retracement_count=1,
            stop_loss_price=Decimal("154.60"),
        )
        r2 = Entry(
            entry_id=2,
            step=3,
            direction=Direction.LONG,
            entry_price=Decimal("154.70"),
            close_price=Decimal("155.00"),
            units=3000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="counter",
            layer_number=1,
            retracement_count=2,
            stop_loss_price=Decimal("154.40"),
        )

        layer.slot_at(1).fill(r1)
        layer.slot_at(2).fill(r2)
        cycle.add_layer(layer)
        ss.cycles.append(cycle)
        return ss, cycle, r1, r2

    def test_highest_live_r_is_preserved_when_at_or_above_threshold(self):
        s = _strategy(
            {
                "stop_loss_enabled": True,
                "preserve_highest_retracement_enabled": True,
                "preserve_highest_r_from": 2,
            }
        )
        ss, cycle, r1, r2 = self._make_cycle_with_entries()
        tick = _make_tick(
            datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=1), "154.39", "154.41"
        )

        events = s._process_stop_loss_closes(ss, tick, cycle)

        closed_ids = {event.entry_id for event in events}
        assert r1.entry_id in closed_ids
        assert r2.entry_id not in closed_ids
        layer = cycle.grid.layers[0]
        assert layer.slot_at(1).pending_rebuild is not None
        assert layer.slot_at(2).entry is r2

    def test_highest_live_r_is_not_preserved_below_threshold(self):
        s = _strategy(
            {
                "stop_loss_enabled": True,
                "preserve_highest_retracement_enabled": True,
                "preserve_highest_r_from": 3,
            }
        )
        ss, cycle, r1, r2 = self._make_cycle_with_entries()
        tick = _make_tick(
            datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=1), "154.39", "154.41"
        )

        events = s._process_stop_loss_closes(ss, tick, cycle)

        closed_ids = {event.entry_id for event in events}
        assert r1.entry_id in closed_ids
        assert r2.entry_id in closed_ids

    def test_r0_only_layer_is_never_preserved(self):
        s = _strategy(
            {
                "stop_loss_enabled": True,
                "preserve_highest_retracement_enabled": True,
                "preserve_highest_r_from": 1,
            }
        )
        ss = SnowballStrategyState()
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        layer = Layer.create(1, 3, 1000, 2)
        r0 = Entry(
            entry_id=1,
            step=1,
            direction=Direction.LONG,
            entry_price=Decimal("155.00"),
            close_price=Decimal("155.50"),
            units=1000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="initial",
            layer_number=1,
            retracement_count=0,
            stop_loss_price=Decimal("154.60"),
        )
        layer.slot_at(0).fill(r0)
        cycle.add_layer(layer)
        ss.cycles.append(cycle)
        tick = _make_tick(
            datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=1), "154.59", "154.61"
        )

        events = s._process_stop_loss_closes(ss, tick, cycle)

        assert [event.entry_id for event in events] == [r0.entry_id]

    def test_stop_loss_does_not_close_on_open_tick(self):
        s = _strategy({"stop_loss_enabled": True})
        ss = SnowballStrategyState()
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        layer = Layer.create(1, 3, 1000, 2)
        opened_at = datetime(2026, 1, 1, tzinfo=UTC)
        r0 = Entry(
            entry_id=1,
            step=1,
            direction=Direction.LONG,
            entry_price=Decimal("155.00"),
            close_price=Decimal("155.50"),
            units=1000,
            opened_at=opened_at,
            role="initial",
            layer_number=1,
            retracement_count=0,
            stop_loss_price=Decimal("154.60"),
        )
        layer.slot_at(0).fill(r0)
        cycle.add_layer(layer)
        ss.cycles.append(cycle)

        events = s._process_stop_loss_closes(
            ss,
            _make_tick(opened_at, "154.59", "154.61"),
            cycle,
        )

        assert events == []
        assert layer.slot_at(0).entry is r0


class TestSnowballStopLossModes:
    def test_auto_mode_uses_interval_based_counter_stop_loss_formula(self):
        s = _strategy(
            {
                "stop_loss_enabled": True,
                "stop_loss_mode": "auto",
                "n_pips_head": "30",
            }
        )
        entry = Entry(
            entry_id=1,
            step=2,
            direction=Direction.LONG,
            entry_price=Decimal("155.00"),
            close_price=Decimal("155.50"),
            units=2000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="counter",
            layer_number=1,
            retracement_count=1,
        )

        s._assign_configured_stop_loss(entry, 2)

        assert entry.stop_loss_price == Decimal("154.40")

    def test_constant_mode_uses_flat_pip_distance_from_slot_entry(self):
        s = _strategy(
            {
                "stop_loss_enabled": True,
                "stop_loss_mode": "constant",
                "stop_loss_pips_head": "30",
            }
        )
        entry = Entry(
            entry_id=1,
            step=2,
            direction=Direction.LONG,
            entry_price=Decimal("155.00"),
            close_price=Decimal("155.50"),
            units=2000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="counter",
            layer_number=1,
            retracement_count=1,
        )

        s._assign_configured_stop_loss(entry, 2)

        assert entry.stop_loss_price == Decimal("154.70")

    def test_constant_mode_treats_stop_loss_pips_as_absolute_distance_for_short(self):
        s = _strategy(
            {
                "stop_loss_enabled": True,
                "stop_loss_mode": "constant",
                "stop_loss_pips_head": "30",
            }
        )
        entry = Entry(
            entry_id=1,
            step=2,
            direction=Direction.SHORT,
            entry_price=Decimal("155.00"),
            close_price=Decimal("154.50"),
            units=2000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="counter",
            layer_number=1,
            retracement_count=1,
        )

        s._assign_configured_stop_loss(entry, 2)

        assert entry.stop_loss_price == Decimal("155.30")


class TestSnowballRebuildStopLossModes:
    def _make_pending_rebuild(
        self,
        *,
        direction: Direction = Direction.LONG,
        stop_loss_price: str = "154.40",
        retracement_count: int = 1,
    ) -> StopLossClosedEntry:
        return StopLossClosedEntry(
            entry_price=Decimal("154.70"),
            close_price=Decimal("155.00") if direction == Direction.LONG else Decimal("154.40"),
            units=2000,
            direction=direction,
            role="counter",
            layer_number=1,
            retracement_count=retracement_count,
            step=2,
            cycle_id=1,
            stop_loss_price=Decimal(stop_loss_price),
        )

    def test_same_mode_reuses_original_stop_loss_price(self):
        s = _strategy(
            {
                "stop_loss_enabled": True,
                "rebuild_stop_loss_mode": "same",
            }
        )
        entry = Entry(
            entry_id=9,
            step=2,
            direction=Direction.LONG,
            entry_price=Decimal("154.70"),
            close_price=Decimal("155.00"),
            units=2000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="counter",
            layer_number=1,
            retracement_count=1,
            is_rebuild=True,
        )

        s._assign_rebuild_stop_loss(entry, self._make_pending_rebuild())

        assert entry.stop_loss_price == Decimal("154.40")

    def test_same_mode_reprojects_invalid_short_stop_loss_to_loss_side(self):
        s = _strategy(
            {
                "stop_loss_enabled": True,
                "rebuild_stop_loss_mode": "same",
            }
        )
        entry = Entry(
            entry_id=9,
            step=7,
            direction=Direction.SHORT,
            entry_price=Decimal("136.230"),
            close_price=Decimal("135.984"),
            units=7000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="counter",
            layer_number=2,
            retracement_count=6,
            is_rebuild=True,
        )
        pending = StopLossClosedEntry(
            entry_price=Decimal("136.240"),
            close_price=Decimal("135.994"),
            units=7000,
            direction=Direction.SHORT,
            role="counter",
            layer_number=2,
            retracement_count=6,
            step=7,
            cycle_id=1,
            stop_loss_price=Decimal("136.225"),
        )

        s._assign_rebuild_stop_loss(entry, pending)

        assert entry.stop_loss_price == Decimal("136.245")

    def test_same_mode_falls_back_when_pending_stop_loss_is_corrupt(self):
        s = _strategy(
            {
                "stop_loss_enabled": True,
                "stop_loss_mode": "constant",
                "stop_loss_pips_head": "31",
                "rebuild_stop_loss_mode": "same",
            }
        )
        entry = Entry(
            entry_id=9,
            step=7,
            direction=Direction.SHORT,
            entry_price=Decimal("136.230"),
            close_price=Decimal("135.984"),
            units=7000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="counter",
            layer_number=2,
            retracement_count=6,
            is_rebuild=True,
        )
        pending = StopLossClosedEntry(
            entry_price=Decimal("136.240"),
            close_price=Decimal("135.994"),
            units=7000,
            direction=Direction.SHORT,
            role="counter",
            layer_number=2,
            retracement_count=6,
            step=7,
            cycle_id=1,
            stop_loss_price=Decimal("-904.479"),
        )

        s._assign_rebuild_stop_loss(entry, pending)

        assert entry.stop_loss_price == Decimal("136.540")

    def test_same_pips_mode_reuses_original_stop_loss_distance(self):
        s = _strategy(
            {
                "stop_loss_enabled": True,
                "rebuild_stop_loss_mode": "same_pips",
            }
        )
        long_entry = Entry(
            entry_id=9,
            step=2,
            direction=Direction.LONG,
            entry_price=Decimal("154.90"),
            close_price=Decimal("155.20"),
            units=2000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="counter",
            layer_number=1,
            retracement_count=1,
            is_rebuild=True,
        )
        short_entry = Entry(
            entry_id=10,
            step=2,
            direction=Direction.SHORT,
            entry_price=Decimal("154.50"),
            close_price=Decimal("154.20"),
            units=2000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="counter",
            layer_number=1,
            retracement_count=1,
            is_rebuild=True,
        )

        s._assign_rebuild_stop_loss(long_entry, self._make_pending_rebuild())
        s._assign_rebuild_stop_loss(
            short_entry,
            self._make_pending_rebuild(
                direction=Direction.SHORT,
                stop_loss_price="155.00",
            ),
        )

        assert long_entry.stop_loss_price == Decimal("154.60")
        assert short_entry.stop_loss_price == Decimal("154.80")

    def test_same_pips_mode_falls_back_when_pending_stop_loss_is_corrupt(self):
        s = _strategy(
            {
                "stop_loss_enabled": True,
                "stop_loss_mode": "constant",
                "stop_loss_pips_head": "31",
                "rebuild_stop_loss_mode": "same_pips",
            }
        )
        entry = Entry(
            entry_id=10,
            step=7,
            direction=Direction.SHORT,
            entry_price=Decimal("136.230"),
            close_price=Decimal("135.984"),
            units=7000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="counter",
            layer_number=2,
            retracement_count=6,
            is_rebuild=True,
        )

        s._assign_rebuild_stop_loss(
            entry,
            self._make_pending_rebuild(
                direction=Direction.SHORT,
                stop_loss_price="-904.479",
                retracement_count=6,
            ),
        )

        assert entry.stop_loss_price == Decimal("136.540")

    def test_manual_mode_applies_absolute_pips_from_rebuild_entry(self):
        s = _strategy(
            {
                "stop_loss_enabled": True,
                "rebuild_stop_loss_mode": "manual",
                "rebuild_stop_loss_manual_pips": ["8", "12", "16", "20", "24", "28", "32", "36"],
            }
        )
        entry = Entry(
            entry_id=9,
            step=2,
            direction=Direction.LONG,
            entry_price=Decimal("154.70"),
            close_price=Decimal("155.00"),
            units=2000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="counter",
            layer_number=1,
            retracement_count=1,
            is_rebuild=True,
        )

        s._assign_rebuild_stop_loss(entry, self._make_pending_rebuild())

        assert entry.stop_loss_price == Decimal("154.58")


class TestSnowballRebuildTakeProfitModes:
    def _make_pending_rebuild(
        self,
        *,
        direction: Direction = Direction.LONG,
        entry_price: Decimal = Decimal("154.70"),
        retracement_count: int = 1,
        stop_loss_loss_pips: Decimal = Decimal("0"),
        stop_loss_exit_price: Decimal | None = None,
        close_price: Decimal | None = None,
    ) -> StopLossClosedEntry:
        return StopLossClosedEntry(
            entry_price=entry_price,
            close_price=(
                close_price
                if close_price is not None
                else Decimal("155.00")
                if direction == Direction.LONG
                else Decimal("154.40")
            ),
            units=2000,
            direction=direction,
            role="counter",
            layer_number=1,
            retracement_count=retracement_count,
            step=2,
            cycle_id=1,
            stop_loss_loss_pips=stop_loss_loss_pips,
            stop_loss_exit_price=stop_loss_exit_price,
        )

    def test_same_mode_reuses_pending_take_profit_price(self):
        s = _strategy(
            {
                "stop_loss_enabled": True,
                "rebuild_take_profit_mode": "same",
            }
        )

        tp = SNOWBALL_PRICING.rebuild_take_profit_price(
            pending=self._make_pending_rebuild(),
            entry_price=Decimal("154.70"),
            pip_size=s.pip_size,
            config=s.config,
        )

        assert tp == Decimal("155.00")

    def test_manual_mode_applies_absolute_pips_from_rebuild_entry(self):
        s = _strategy(
            {
                "stop_loss_enabled": True,
                "rebuild_take_profit_mode": "manual",
                "rebuild_take_profit_manual_pips": [
                    "8",
                    "12",
                    "16",
                    "20",
                    "24",
                    "28",
                    "32",
                    "36",
                ],
            }
        )

        long_tp = SNOWBALL_PRICING.rebuild_take_profit_price(
            pending=self._make_pending_rebuild(direction=Direction.LONG),
            entry_price=Decimal("154.70"),
            pip_size=s.pip_size,
            config=s.config,
        )
        short_tp = SNOWBALL_PRICING.rebuild_take_profit_price(
            pending=self._make_pending_rebuild(direction=Direction.SHORT),
            entry_price=Decimal("154.70"),
            pip_size=s.pip_size,
            config=s.config,
        )

        assert long_tp == Decimal("154.82")
        assert short_tp == Decimal("154.58")

    def test_same_pips_mode_reuses_original_take_profit_distance(self):
        s = _strategy(
            {
                "stop_loss_enabled": True,
                "rebuild_take_profit_mode": "same_pips",
            }
        )

        long_tp = SNOWBALL_PRICING.rebuild_take_profit_price(
            pending=self._make_pending_rebuild(
                direction=Direction.LONG,
                entry_price=Decimal("154.70"),
                close_price=Decimal("155.00"),
            ),
            entry_price=Decimal("154.10"),
            pip_size=s.pip_size,
            config=s.config,
        )
        short_tp = SNOWBALL_PRICING.rebuild_take_profit_price(
            pending=self._make_pending_rebuild(
                direction=Direction.SHORT,
                entry_price=Decimal("154.70"),
                close_price=Decimal("154.40"),
            ),
            entry_price=Decimal("155.10"),
            pip_size=s.pip_size,
            config=s.config,
        )

        assert long_tp == Decimal("154.40")
        assert short_tp == Decimal("154.80")

    def test_rebuild_trigger_uses_pending_entry_price(self):
        pending = self._make_pending_rebuild(
            direction=Direction.SHORT,
            entry_price=Decimal("157.397"),
            stop_loss_loss_pips=Decimal("30.1"),
            stop_loss_exit_price=Decimal("157.698"),
            close_price=Decimal("157.247"),
        )
        # Anchor the SL level explicitly so the trigger does not fall
        # through to ``stop_loss_exit_price``.  Real rebuild snapshots
        # always carry both fields.
        pending.stop_loss_price = Decimal("157.697")
        planner = StopLossRebuildPricePlanner()

        original_trigger = planner.trigger_price(pending, "original_entry")
        # ``stop_loss_exit`` mode anchors the trigger on the SL **level**
        # rather than the actual fill price.  This keeps successive
        # rebuilds at the same trigger price even when slippage causes the
        # exit price to drift across rounds.
        stop_loss_trigger = planner.trigger_price(pending, "stop_loss_exit")

        assert original_trigger == Decimal("157.397")
        assert stop_loss_trigger == Decimal("157.697")

    def test_rebuild_trigger_anchors_on_sl_level_not_exit_price(self):
        """Regression: stop_loss_exit anchored on SL level, not slipped fill price.

        Without this anchoring each round of ``stop_loss_exit`` × ``same``
        rebuilds drifted the trigger one slippage step in the adverse
        direction, eventually placing the rebuilt SL on the profit side
        of the new entry and producing spurious profit-bearing
        ``stop_loss`` closes.
        """
        pending = self._make_pending_rebuild(
            direction=Direction.LONG,
            entry_price=Decimal("150.000"),
            stop_loss_loss_pips=Decimal("30"),
            stop_loss_exit_price=Decimal("149.685"),  # 1.5 pips slipped
            close_price=Decimal("150.300"),
        )
        pending.stop_loss_price = Decimal("149.700")
        planner = StopLossRebuildPricePlanner()

        trigger = planner.trigger_price(pending, "stop_loss_exit")

        assert trigger == Decimal("149.700")

    def test_apply_entry_buffer_pushes_long_trigger_above_sl(self):
        pending = self._make_pending_rebuild(
            direction=Direction.LONG,
            entry_price=Decimal("150.000"),
            stop_loss_loss_pips=Decimal("30"),
            stop_loss_exit_price=Decimal("149.700"),
            close_price=Decimal("150.300"),
        )
        pending.stop_loss_price = Decimal("149.700")
        planner = StopLossRebuildPricePlanner()

        no_buffer = planner.apply_entry_buffer(
            pending=pending,
            trigger_price=Decimal("149.700"),
            entry_price_mode="stop_loss_exit",
            buffer_pips=Decimal("0"),
            pip_size=Decimal("0.001"),
        )
        with_buffer = planner.apply_entry_buffer(
            pending=pending,
            trigger_price=Decimal("149.700"),
            entry_price_mode="stop_loss_exit",
            buffer_pips=Decimal("5"),
            pip_size=Decimal("0.001"),
        )

        assert no_buffer == Decimal("149.700")
        assert with_buffer == Decimal("149.705")

    def test_apply_entry_buffer_pushes_short_trigger_below_sl(self):
        pending = self._make_pending_rebuild(
            direction=Direction.SHORT,
            entry_price=Decimal("150.000"),
            stop_loss_loss_pips=Decimal("30"),
            stop_loss_exit_price=Decimal("150.300"),
            close_price=Decimal("149.700"),
        )
        pending.stop_loss_price = Decimal("150.300")
        planner = StopLossRebuildPricePlanner()

        with_buffer = planner.apply_entry_buffer(
            pending=pending,
            trigger_price=Decimal("150.300"),
            entry_price_mode="stop_loss_exit",
            buffer_pips=Decimal("4"),
            pip_size=Decimal("0.001"),
        )

        assert with_buffer == Decimal("150.296")

    def test_apply_entry_buffer_is_no_op_in_original_entry_mode(self):
        """Buffer must only apply to ``stop_loss_exit`` mode."""
        pending = self._make_pending_rebuild(
            direction=Direction.LONG,
            entry_price=Decimal("150.000"),
            stop_loss_loss_pips=Decimal("30"),
            stop_loss_exit_price=Decimal("149.700"),
            close_price=Decimal("150.300"),
        )
        pending.stop_loss_price = Decimal("149.700")
        planner = StopLossRebuildPricePlanner()

        buffered = planner.apply_entry_buffer(
            pending=pending,
            trigger_price=Decimal("150.000"),
            entry_price_mode="original_entry",
            buffer_pips=Decimal("5"),
            pip_size=Decimal("0.001"),
        )

        assert buffered == Decimal("150.000")

    def test_cooldown_blocks_rebuild_until_elapsed(self):
        strategy = _strategy(
            {
                "stop_loss_enabled": True,
                "rebuild_take_profit_mode": "same",
                "rebuild_cooldown_seconds": "30",
            }
        )
        closed_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        pending = self._make_pending_rebuild(
            direction=Direction.LONG,
            entry_price=Decimal("144.547"),
            stop_loss_loss_pips=Decimal("35"),
            stop_loss_exit_price=Decimal("144.197"),
            close_price=Decimal("144.697"),
        )
        pending.stop_loss_price = Decimal("144.197")
        pending.closed_at = closed_at
        slot = Slot(index=0, pending_rebuild=pending)
        layer = Layer(layer_number=1, slots=[slot])
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        cycle.add_layer(layer)
        planner = StopLossRebuildPricePlanner()

        # 10 seconds after SL: still within the cooldown window.
        too_early_plan = planner.plan(
            strategy=strategy,
            tick=_make_tick(closed_at + timedelta(seconds=10), "144.547", "144.567"),
            cycle=cycle,
            layer=layer,
            slot=slot,
            pending=pending,
        )
        # 30 seconds after SL: cooldown elapsed.
        on_time_plan = planner.plan(
            strategy=strategy,
            tick=_make_tick(closed_at + timedelta(seconds=30), "144.547", "144.567"),
            cycle=cycle,
            layer=layer,
            slot=slot,
            pending=pending,
        )

        assert too_early_plan is None
        assert on_time_plan is not None

    def test_zero_cooldown_only_blocks_same_tick(self):
        """When cooldown is 0 only the same-tick guard remains in effect."""
        strategy = _strategy(
            {
                "stop_loss_enabled": True,
                "rebuild_take_profit_mode": "same",
                "rebuild_cooldown_seconds": "0",
            }
        )
        closed_at = datetime(2026, 1, 1, tzinfo=UTC)
        pending = self._make_pending_rebuild(
            direction=Direction.LONG,
            entry_price=Decimal("144.547"),
            stop_loss_loss_pips=Decimal("35"),
            stop_loss_exit_price=Decimal("144.197"),
            close_price=Decimal("144.697"),
        )
        pending.stop_loss_price = Decimal("144.197")
        pending.closed_at = closed_at
        slot = Slot(index=0, pending_rebuild=pending)
        layer = Layer(layer_number=1, slots=[slot])
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        cycle.add_layer(layer)
        planner = StopLossRebuildPricePlanner()

        next_tick_plan = planner.plan(
            strategy=strategy,
            tick=_make_tick(closed_at + timedelta(seconds=1), "144.547", "144.567"),
            cycle=cycle,
            layer=layer,
            slot=slot,
            pending=pending,
        )

        assert next_tick_plan is not None

    def test_rebuild_waits_until_after_stop_loss_tick(self):
        strategy = _strategy(
            {
                "stop_loss_enabled": True,
                "rebuild_take_profit_mode": "same",
            }
        )
        closed_at = datetime(2026, 1, 1, tzinfo=UTC)
        pending = self._make_pending_rebuild(
            direction=Direction.LONG,
            entry_price=Decimal("144.547"),
            stop_loss_loss_pips=Decimal("35"),
            stop_loss_exit_price=Decimal("144.197"),
            close_price=Decimal("144.697"),
        )
        pending.closed_at = closed_at
        slot = Slot(index=0, pending_rebuild=pending)
        layer = Layer(layer_number=1, slots=[slot])
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        cycle.add_layer(layer)
        planner = StopLossRebuildPricePlanner()

        same_tick_plan = planner.plan(
            strategy=strategy,
            tick=_make_tick(closed_at, "144.547", "144.567"),
            cycle=cycle,
            layer=layer,
            slot=slot,
            pending=pending,
        )
        next_tick_plan = planner.plan(
            strategy=strategy,
            tick=_make_tick(closed_at + timedelta(seconds=1), "144.547", "144.567"),
            cycle=cycle,
            layer=layer,
            slot=slot,
            pending=pending,
        )

        assert same_tick_plan is None
        assert next_tick_plan is not None
        assert next_tick_plan.trigger_price == Decimal("144.547")

    def test_rebuild_repairs_long_take_profit_from_actual_fill(self):
        strategy = _strategy(
            {
                "stop_loss_enabled": True,
                "rebuild_enabled": True,
                "rebuild_take_profit_mode": "same",
                "rebuild_take_profit_pips_head": "10",
                "rebuild_take_profit_pips_tail": "10",
            }
        )
        pending = self._make_pending_rebuild(
            direction=Direction.LONG,
            entry_price=Decimal("130.00000"),
            retracement_count=1,
            close_price=Decimal("130.00000"),
        )
        slot = Slot(index=1, pending_rebuild=pending)
        layer = Layer(layer_number=1, slots=[slot])
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        cycle.add_layer(layer)
        tick = _make_tick(datetime(2026, 1, 1, tzinfo=UTC), "130.00000", "130.05000")
        planner = StopLossRebuildPricePlanner()

        plan = planner.plan(
            strategy=strategy,
            tick=tick,
            cycle=cycle,
            layer=layer,
            slot=slot,
            pending=pending,
        )

        assert plan is not None
        assert plan.close_price == Decimal("130.10000")
        projected = planner.projected_close_price_after_fill(
            pending=pending,
            tick=tick,
            trigger_price=plan.trigger_price,
            close_price=plan.close_price,
            planned_exit_bound=None,
        )
        assert projected == Decimal("130.15000")
        assert projected > Decimal("130.05000")

    def test_rebuild_repairs_short_take_profit_from_actual_fill(self):
        strategy = _strategy(
            {
                "stop_loss_enabled": True,
                "rebuild_enabled": True,
                "rebuild_take_profit_mode": "same",
                "rebuild_take_profit_pips_head": "10",
                "rebuild_take_profit_pips_tail": "10",
            }
        )
        pending = self._make_pending_rebuild(
            direction=Direction.SHORT,
            entry_price=Decimal("150.00000"),
            retracement_count=1,
            close_price=Decimal("150.00000"),
        )
        slot = Slot(index=1, pending_rebuild=pending)
        layer = Layer(layer_number=1, slots=[slot])
        cycle = SnowballCycle(cycle_id=1, direction=Direction.SHORT)
        cycle.add_layer(layer)
        tick = _make_tick(datetime(2026, 1, 1, tzinfo=UTC), "149.95000", "150.00000")
        planner = StopLossRebuildPricePlanner()

        plan = planner.plan(
            strategy=strategy,
            tick=tick,
            cycle=cycle,
            layer=layer,
            slot=slot,
            pending=pending,
        )

        assert plan is not None
        assert plan.close_price == Decimal("149.90000")
        projected = planner.projected_close_price_after_fill(
            pending=pending,
            tick=tick,
            trigger_price=plan.trigger_price,
            close_price=plan.close_price,
            planned_exit_bound=None,
        )
        assert projected == Decimal("149.85000")
        assert projected < Decimal("149.95000")

    def test_rebuild_waits_when_bound_prevents_take_profit_repair(self):
        strategy = _strategy(
            {
                "stop_loss_enabled": True,
                "rebuild_enabled": True,
                "rebuild_take_profit_mode": "same",
            }
        )
        pending = self._make_pending_rebuild(
            direction=Direction.LONG,
            entry_price=Decimal("130.27500"),
            retracement_count=4,
            close_price=Decimal("130.3881333333333333333333333"),
        )
        previous = Entry(
            entry_id=1,
            step=1,
            direction=Direction.LONG,
            entry_price=Decimal("130.20000"),
            close_price=Decimal("130.2436388888888888888888889"),
            units=12000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="counter",
            layer_number=1,
            retracement_count=3,
        )
        slot = Slot(index=4, pending_rebuild=pending)
        layer = Layer(
            layer_number=1,
            slots=[Slot(index=3, entry=previous), slot],
        )
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        cycle.add_layer(layer)
        state = SnowballStrategyState()
        processor = StopLossRebuildProcessor()

        events = processor.process(
            strategy,
            state,
            _make_tick(datetime(2026, 1, 1, tzinfo=UTC), "130.31300", "130.32400"),
            cycle,
        )

        assert events == []
        assert slot.pending_rebuild is pending
        assert slot.entry is None

    def test_rebuild_resumes_when_projected_take_profit_is_profitable_after_fill(self):
        strategy = _strategy(
            {
                "stop_loss_enabled": True,
                "rebuild_take_profit_mode": "same",
            }
        )
        pending = self._make_pending_rebuild(
            direction=Direction.LONG,
            entry_price=Decimal("130.27500"),
            retracement_count=4,
            close_price=Decimal("130.3881333333333333333333333"),
        )
        previous = Entry(
            entry_id=1,
            step=1,
            direction=Direction.LONG,
            entry_price=Decimal("130.20000"),
            close_price=Decimal("130.33000"),
            units=12000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="counter",
            layer_number=1,
            retracement_count=3,
        )
        slot = Slot(index=4, pending_rebuild=pending)
        layer = Layer(
            layer_number=1,
            slots=[Slot(index=3, entry=previous), slot],
        )
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        cycle.add_layer(layer)
        planner = StopLossRebuildPricePlanner()

        plan = planner.plan(
            strategy=strategy,
            tick=_make_tick(datetime(2026, 1, 1, tzinfo=UTC), "130.31300", "130.32400"),
            cycle=cycle,
            layer=layer,
            slot=slot,
            pending=pending,
        )

        assert plan is not None
        assert plan.close_price == Decimal("130.33000")

    def test_rebuild_soft_tp_bound_survives_short_fill_shift(self):
        """A pending predecessor TP must still bound the post-fill rebuilt TP."""
        strategy = _strategy(
            {
                "stop_loss_enabled": True,
                "rebuild_enabled": True,
                "rebuild_take_profit_mode": "same_pips",
            }
        )
        previous_pending = StopLossClosedEntry(
            entry_price=Decimal("127.97000"),
            close_price=Decimal("128.0361428571428571428571429"),
            units=12000,
            direction=Direction.SHORT,
            role="counter",
            layer_number=1,
            retracement_count=3,
            step=4,
            cycle_id=1,
        )
        rebuilding_pending = StopLossClosedEntry(
            entry_price=Decimal("128.12600"),
            close_price=Decimal("128.0601428571428571428571429"),
            units=3000,
            direction=Direction.SHORT,
            role="layer_initial",
            layer_number=2,
            retracement_count=0,
            step=1,
            cycle_id=1,
        )
        l1 = Layer(layer_number=1, slots=[Slot(index=3, pending_rebuild=previous_pending)])
        slot = Slot(index=0, pending_rebuild=rebuilding_pending)
        l2 = Layer(layer_number=2, slots=[slot])
        cycle = SnowballCycle(cycle_id=1, direction=Direction.SHORT)
        cycle.grid.layers.extend([l1, l2])
        planner = StopLossRebuildPricePlanner()

        plan = planner.plan(
            strategy=strategy,
            tick=_make_tick(datetime(2026, 1, 1, tzinfo=UTC), "128.09800", "128.12600"),
            cycle=cycle,
            layer=l2,
            slot=slot,
            pending=rebuilding_pending,
        )

        assert plan is not None
        assert plan.close_price == Decimal("128.0601428571428571428571429")
        assert plan.planned_exit_price_bound == Decimal("128.0361428571428571428571429")
        assert plan.planned_exit_price_bound_mode == "max"

        entry = Entry(
            entry_id=99,
            step=1,
            direction=Direction.SHORT,
            entry_price=plan.trigger_price,
            close_price=plan.close_price,
            units=3000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="layer_initial",
            layer_number=2,
            retracement_count=0,
            is_rebuild=True,
        )
        SNOWBALL_PRICING.sync_entry_fill_price(
            entry=entry,
            layer=None,
            fill_price=Decimal("128.09800"),
            counter_tp_mode=strategy.config.counter_tp_mode,
            planned_exit_price_bound=plan.planned_exit_price_bound,
            planned_exit_price_bound_mode=plan.planned_exit_price_bound_mode,
        )

        assert entry.close_price == Decimal("128.0361428571428571428571429")

    def test_cycle_rebuild_guard_blocks_negative_cycle_after_repeated_stops(self):
        strategy = _strategy(
            {
                "stop_loss_enabled": True,
                "rebuild_take_profit_mode": "same",
                "cycle_rebuild_guard_enabled": True,
                "cycle_rebuild_guard_stop_count": 2,
                "cycle_rebuild_guard_recovery_pips": "5",
            }
        )
        pending = self._make_pending_rebuild(
            direction=Direction.LONG,
            entry_price=Decimal("144.547"),
            close_price=Decimal("144.697"),
        )
        slot = Slot(index=0, pending_rebuild=pending)
        layer = Layer(layer_number=1, slots=[slot])
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        cycle.stop_loss_count = 2
        cycle.realized_pnl = Decimal("-1")
        cycle.add_layer(layer)
        planner = StopLossRebuildPricePlanner()

        plan = planner.plan(
            strategy=strategy,
            tick=_make_tick(datetime(2026, 1, 1, tzinfo=UTC), "144.547", "144.567"),
            cycle=cycle,
            layer=layer,
            slot=slot,
            pending=pending,
        )

        assert plan is None

    def test_cycle_rebuild_guard_resumes_when_cycle_pnl_recovers(self):
        strategy = _strategy(
            {
                "stop_loss_enabled": True,
                "rebuild_take_profit_mode": "same",
                "cycle_rebuild_guard_enabled": True,
                "cycle_rebuild_guard_stop_count": 2,
                "cycle_rebuild_guard_recovery_pips": "5",
            }
        )
        pending = self._make_pending_rebuild(
            direction=Direction.LONG,
            entry_price=Decimal("144.547"),
            close_price=Decimal("144.697"),
        )
        slot = Slot(index=0, pending_rebuild=pending)
        layer = Layer(layer_number=1, slots=[slot])
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        cycle.stop_loss_count = 2
        cycle.realized_pnl = Decimal("0")
        cycle.add_layer(layer)
        planner = StopLossRebuildPricePlanner()

        plan = planner.plan(
            strategy=strategy,
            tick=_make_tick(datetime(2026, 1, 1, tzinfo=UTC), "144.547", "144.567"),
            cycle=cycle,
            layer=layer,
            slot=slot,
            pending=pending,
        )

        assert plan is not None

    def test_cycle_rebuild_guard_resumes_when_pending_trigger_recovers_before_cycle_head(self):
        strategy = _strategy(
            {
                "stop_loss_enabled": True,
                "rebuild_take_profit_mode": "same",
                "cycle_rebuild_guard_enabled": True,
                "cycle_rebuild_guard_stop_count": 2,
                "cycle_rebuild_guard_recovery_pips": "5",
            }
        )
        head = Entry(
            entry_id=1,
            step=1,
            direction=Direction.LONG,
            entry_price=Decimal("145.000"),
            close_price=Decimal("145.200"),
            units=2000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="initial",
            layer_number=1,
            retracement_count=0,
        )
        pending = self._make_pending_rebuild(
            direction=Direction.LONG,
            entry_price=Decimal("144.547"),
            close_price=Decimal("144.697"),
        )
        slot = Slot(index=1, pending_rebuild=pending)
        layer = Layer(layer_number=1, slots=[Slot(index=0, entry=head), slot])
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        cycle.stop_loss_count = 2
        cycle.realized_pnl = Decimal("-1")
        cycle.add_layer(layer)
        planner = StopLossRebuildPricePlanner()

        plan = planner.plan(
            strategy=strategy,
            tick=_make_tick(datetime(2026, 1, 1, tzinfo=UTC), "144.597", "144.617"),
            cycle=cycle,
            layer=layer,
            slot=slot,
            pending=pending,
        )

        assert plan is not None
        assert plan.close_price == Decimal("144.697")

    def _cycle_with_take_profit_order_violation(self) -> SnowballCycle:
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        layer = Layer(
            layer_number=1,
            slots=[Slot(index=0), Slot(index=1)],
            base_units=1000,
            refill_up_to=2,
        )
        layer.slot_at(0).fill(
            Entry(
                entry_id=1,
                step=1,
                direction=Direction.LONG,
                entry_price=Decimal("155.00"),
                close_price=Decimal("155.50"),
                units=1000,
                opened_at=datetime(2026, 1, 1, tzinfo=UTC),
                role="initial",
            )
        )
        layer.slot_at(1).fill(
            Entry(
                entry_id=2,
                step=2,
                direction=Direction.LONG,
                entry_price=Decimal("154.00"),
                close_price=Decimal("155.60"),
                units=2000,
                opened_at=datetime(2026, 1, 1, tzinfo=UTC),
                role="counter",
                retracement_count=1,
            )
        )
        cycle.grid.layers.append(layer)
        return cycle

    def test_manual_take_profit_mode_skips_grid_order_validation(self):
        s = _strategy(
            {
                "stop_loss_enabled": True,
                "rebuild_take_profit_mode": "manual",
                "rebuild_take_profit_manual_pips": [
                    "8",
                    "12",
                    "16",
                    "20",
                    "24",
                    "28",
                    "32",
                    "36",
                ],
            }
        )
        cycle = self._cycle_with_take_profit_order_violation()

        s._validate_grid_ordering(cycle)

        assert s._grid_order_violation is None

    def test_hidden_manual_take_profit_mode_does_not_skip_validation_when_rebuild_off(
        self,
    ):
        s = _strategy(
            {
                "stop_loss_enabled": True,
                "rebuild_enabled": False,
                "rebuild_take_profit_mode": "manual",
                "rebuild_take_profit_manual_pips": [
                    "8",
                    "12",
                    "16",
                    "20",
                    "24",
                    "28",
                    "32",
                    "36",
                ],
            }
        )
        cycle = self._cycle_with_take_profit_order_violation()

        s._validate_grid_ordering(cycle)

        assert s._grid_order_violation is not None
        assert "tp_ok=False" in s._grid_order_violation

    def test_validation_repairs_layer_initial_pending_tp_against_pending_neighbor(self):
        s = _strategy({"stop_loss_enabled": True, "rebuild_enabled": True})
        cycle = SnowballCycle(cycle_id=1, direction=Direction.SHORT)
        l1 = Layer(layer_number=1, slots=[Slot(index=3)])
        l1.slot_at(3).pending_rebuild = StopLossClosedEntry(
            entry_price=Decimal("127.97000"),
            close_price=Decimal("128.0361428571428571428571429"),
            units=12000,
            direction=Direction.SHORT,
            role="counter",
            layer_number=1,
            retracement_count=3,
            step=4,
            cycle_id=1,
        )
        l2 = Layer(layer_number=2, slots=[Slot(index=0)])
        l2.slot_at(0).pending_rebuild = StopLossClosedEntry(
            entry_price=Decimal("128.12600"),
            close_price=Decimal("128.0321428571428571428571429"),
            units=3000,
            direction=Direction.SHORT,
            role="layer_initial",
            layer_number=2,
            retracement_count=0,
            step=1,
            cycle_id=1,
        )
        cycle.grid.layers.extend([l1, l2])

        s._validate_grid_ordering(cycle)

        repaired = l2.slot_at(0).pending_rebuild
        assert repaired is not None
        assert repaired.close_price == Decimal("128.0361428571428571428571429")
        assert s._grid_order_violation is None


class TestSnowballPricingHelpers:
    def test_sync_entry_fill_price_reapplies_long_layer_initial_bound_after_fill(self):
        entry = Entry(
            entry_id=1,
            step=1,
            direction=Direction.LONG,
            entry_price=Decimal("161.003"),
            close_price=Decimal("161.1598888889"),
            units=1000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="layer_initial",
            layer_number=2,
            retracement_count=0,
        )

        SNOWBALL_PRICING.sync_entry_fill_price(
            entry=entry,
            layer=None,
            fill_price=Decimal("161.053"),
            counter_tp_mode="weighted_avg",
            planned_exit_price_bound=Decimal("161.1598888889"),
            planned_exit_price_bound_mode="min",
        )

        assert entry.entry_price == Decimal("161.053")
        assert entry.close_price == Decimal("161.1598888889")

    def test_sync_entry_fill_price_reapplies_short_layer_initial_bound_after_fill(self):
        entry = Entry(
            entry_id=1,
            step=1,
            direction=Direction.SHORT,
            entry_price=Decimal("147.257"),
            close_price=Decimal("147.08269"),
            units=1000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="layer_initial",
            layer_number=2,
            retracement_count=0,
        )

        SNOWBALL_PRICING.sync_entry_fill_price(
            entry=entry,
            layer=None,
            fill_price=Decimal("147.207"),
            counter_tp_mode="weighted_avg",
            planned_exit_price_bound=Decimal("147.08269"),
            planned_exit_price_bound_mode="max",
        )

        assert entry.entry_price == Decimal("147.207")
        assert entry.close_price == Decimal("147.08269")

    def test_sync_entry_fill_price_repairs_invalid_stop_loss_side(self):
        entry = Entry(
            entry_id=1,
            step=7,
            direction=Direction.SHORT,
            entry_price=Decimal("136.240"),
            close_price=Decimal("135.994"),
            units=7000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="counter",
            layer_number=2,
            retracement_count=6,
            stop_loss_price=Decimal("136.225"),
            is_rebuild=True,
        )

        SNOWBALL_PRICING.sync_entry_fill_price(
            entry=entry,
            layer=None,
            fill_price=Decimal("136.230"),
            counter_tp_mode="weighted_avg",
        )

        assert entry.entry_price == Decimal("136.230")
        assert entry.stop_loss_price == Decimal("136.245")

    def test_sync_entry_fill_price_rejects_corrupt_stop_loss(self):
        entry = Entry(
            entry_id=1,
            step=7,
            direction=Direction.SHORT,
            entry_price=Decimal("136.240"),
            close_price=Decimal("135.994"),
            units=7000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="counter",
            layer_number=2,
            retracement_count=6,
            stop_loss_price=Decimal("-904.479"),
            is_rebuild=True,
        )

        with pytest.raises(ValueError, match="Stop-loss price"):
            SNOWBALL_PRICING.sync_entry_fill_price(
                entry=entry,
                layer=None,
                fill_price=Decimal("136.230"),
                counter_tp_mode="weighted_avg",
            )

    def test_sync_entry_fill_price_shifts_weighted_counter_take_profit_by_fill_delta(self):
        layer = Layer.create(1, 7, 1000)
        head = Entry(
            entry_id=1,
            step=1,
            direction=Direction.LONG,
            entry_price=Decimal("150.00"),
            close_price=Decimal("150.50"),
            units=1000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="initial",
            layer_number=1,
            retracement_count=0,
        )
        counter = Entry(
            entry_id=2,
            step=2,
            direction=Direction.LONG,
            entry_price=Decimal("149.70"),
            close_price=Decimal("149.90"),
            units=2000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="counter",
            layer_number=1,
            retracement_count=1,
        )
        layer.slot_at(0).fill(head)
        layer.slot_at(1).fill(counter)

        SNOWBALL_PRICING.sync_entry_fill_price(
            entry=counter,
            layer=layer,
            fill_price=Decimal("149.72"),
            counter_tp_mode="weighted_avg",
        )

        assert head.close_price == Decimal("150.50")
        assert counter.entry_price == Decimal("149.72")
        assert counter.close_price == Decimal("149.92")

    def test_weighted_average_current_price_does_not_mutate_open_counter_take_profits(self):
        layer = Layer.create(1, 3, 1000)
        layer.slot_at(0).fill(
            Entry(
                entry_id=1,
                step=1,
                direction=Direction.LONG,
                entry_price=Decimal("150.00"),
                close_price=Decimal("150.50"),
                units=1000,
                opened_at=datetime(2026, 1, 1, tzinfo=UTC),
                role="initial",
            )
        )
        layer.slot_at(1).fill(
            Entry(
                entry_id=2,
                step=2,
                direction=Direction.LONG,
                entry_price=Decimal("149.70"),
                close_price=Decimal("150.00"),
                units=2000,
                opened_at=datetime(2026, 1, 1, tzinfo=UTC),
                role="counter",
                retracement_count=1,
            )
        )
        layer.slot_at(2).fill(
            Entry(
                entry_id=3,
                step=3,
                direction=Direction.LONG,
                entry_price=Decimal("149.40"),
                close_price=Decimal("149.80"),
                units=3000,
                opened_at=datetime(2026, 1, 1, tzinfo=UTC),
                role="counter",
                retracement_count=2,
            )
        )

        weighted = SNOWBALL_PRICING.current_weighted_avg_close_price(layer)

        assert weighted is not None
        assert weighted[0] == Decimal("149.600")
        assert layer.slot_at(0).entry.close_price == Decimal("150.50")
        assert layer.slot_at(1).entry.close_price == Decimal("150.00")
        assert layer.slot_at(2).entry.close_price == Decimal("149.80")

    def test_weighted_average_counter_open_preserves_existing_open_counter_take_profit(self):
        strategy = _strategy({"counter_tp_mode": "weighted_avg"})
        state = SnowballStrategyState()
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        layer = Layer.create(1, 7, 1000)
        cycle.add_layer(layer)
        r0_slot = layer.slot_at(0)
        r1_slot = layer.slot_at(1)
        r2_slot = layer.slot_at(2)
        assert r0_slot is not None
        assert r1_slot is not None
        assert r2_slot is not None
        r0_slot.fill(
            Entry(
                entry_id=1,
                step=1,
                direction=Direction.LONG,
                entry_price=Decimal("150.00"),
                close_price=Decimal("150.50"),
                units=1000,
                opened_at=datetime(2026, 1, 1, tzinfo=UTC),
                role="initial",
                layer_number=1,
                retracement_count=0,
                root_entry_id=1,
            )
        )
        r1_slot.fill(
            Entry(
                entry_id=2,
                step=2,
                direction=Direction.LONG,
                entry_price=Decimal("149.70"),
                close_price=Decimal("150.00"),
                units=2000,
                opened_at=datetime(2026, 1, 1, tzinfo=UTC),
                role="counter",
                layer_number=1,
                retracement_count=1,
                root_entry_id=1,
                parent_entry_id=1,
            )
        )

        events = CounterEntryFactory().open_counter_entry(
            strategy,
            state,
            _make_tick(datetime(2026, 1, 1, tzinfo=UTC), "149.38", "149.40"),
            cycle,
            layer,
            r2_slot,
            CounterAdverseInterval(adverse=Decimal("30"), interval=Decimal("30")),
            CounterHeadContext(
                entry=r0_slot.entry,
                entry_price=Decimal("150.00"),
                entry_id=1,
                direction=Direction.LONG,
            ),
            assign_configured_stop_loss=lambda _entry, _slot_number: None,
        )

        assert getattr(events[0], "planned_exit_price") == Decimal("149.600")
        assert r1_slot.entry is not None
        assert r2_slot.entry is not None
        assert r1_slot.entry.close_price == Decimal("150.00")
        assert r2_slot.entry.close_price == Decimal("149.600")

    def test_weighted_average_current_price_does_not_mutate_pending_counter_take_profits(self):
        cycle = SnowballCycle(cycle_id=85, direction=Direction.SHORT)
        layer = Layer.create(1, 7, 1000)
        cycle.add_layer(layer)
        r0_slot = layer.slot_at(0)
        r5_slot = layer.slot_at(5)
        r6_slot = layer.slot_at(6)
        r7_slot = layer.slot_at(7)
        assert r0_slot is not None
        assert r5_slot is not None
        assert r6_slot is not None
        assert r7_slot is not None
        r0_slot.pending_rebuild = StopLossClosedEntry(
            entry_price=Decimal("129.596"),
            close_price=Decimal("129.496"),
            units=1000,
            direction=Direction.SHORT,
            role="initial",
            layer_number=1,
            retracement_count=0,
            step=1,
            cycle_id=85,
        )
        r5_slot.pending_rebuild = StopLossClosedEntry(
            entry_price=Decimal("130.678"),
            close_price=Decimal("130.5521388888888888888888889"),
            units=6000,
            direction=Direction.SHORT,
            role="counter",
            layer_number=1,
            retracement_count=5,
            step=6,
            cycle_id=85,
        )
        r6_slot.pending_rebuild = StopLossClosedEntry(
            entry_price=Decimal("130.795"),
            close_price=Decimal("130.5536944444444444444444444"),
            units=7000,
            direction=Direction.SHORT,
            role="counter",
            layer_number=1,
            retracement_count=6,
            step=7,
            cycle_id=85,
        )
        r7_slot.fill(
            Entry(
                entry_id=212,
                step=8,
                direction=Direction.SHORT,
                entry_price=Decimal("130.924"),
                close_price=Decimal("130.5521388888888888888888889"),
                units=8000,
                opened_at=datetime(2026, 1, 1, tzinfo=UTC),
                role="counter",
                layer_number=1,
                retracement_count=7,
            )
        )
        assert "tp_ok=False" in (SNOWBALL_GRID_POLICY.validate_ordering(cycle) or "")

        weighted = SNOWBALL_PRICING.current_weighted_avg_close_price(layer)

        assert weighted is not None
        assert weighted[0] == Decimal("130.7555")
        assert r0_slot.pending_rebuild is not None
        assert r5_slot.pending_rebuild is not None
        assert r6_slot.pending_rebuild is not None
        assert r7_slot.entry is not None
        assert r0_slot.pending_rebuild.close_price == Decimal("129.496")
        assert r5_slot.pending_rebuild.close_price == Decimal("130.5521388888888888888888889")
        assert r6_slot.pending_rebuild.close_price == Decimal("130.5536944444444444444444444")
        assert r7_slot.entry.close_price == Decimal("130.5521388888888888888888889")
        assert "tp_ok=False" in (SNOWBALL_GRID_POLICY.validate_ordering(cycle) or "")

    def test_weighted_average_counter_open_preserves_pending_counter_take_profit(self):
        strategy = _strategy({"counter_tp_mode": "weighted_avg"})
        state = SnowballStrategyState()
        cycle = SnowballCycle(cycle_id=85, direction=Direction.SHORT)
        layer = Layer.create(1, 7, 1000)
        cycle.add_layer(layer)
        r0_slot = layer.slot_at(0)
        r6_slot = layer.slot_at(6)
        r7_slot = layer.slot_at(7)
        assert r0_slot is not None
        assert r6_slot is not None
        assert r7_slot is not None
        r0_slot.pending_rebuild = StopLossClosedEntry(
            entry_price=Decimal("129.596"),
            close_price=Decimal("129.496"),
            units=1000,
            direction=Direction.SHORT,
            role="initial",
            layer_number=1,
            retracement_count=0,
            step=1,
            cycle_id=85,
        )
        r6_slot.pending_rebuild = StopLossClosedEntry(
            entry_price=Decimal("130.795"),
            close_price=Decimal("130.79000"),
            units=7000,
            direction=Direction.SHORT,
            role="counter",
            layer_number=1,
            retracement_count=6,
            step=7,
            cycle_id=85,
        )

        events = CounterEntryFactory().open_counter_entry(
            strategy,
            state,
            _make_tick(datetime(2026, 1, 1, tzinfo=UTC), "130.924", "130.934"),
            cycle,
            layer,
            r7_slot,
            CounterAdverseInterval(adverse=Decimal("120"), interval=Decimal("100")),
            CounterHeadContext(
                entry=None,
                entry_price=Decimal("129.596"),
                entry_id=85,
                direction=Direction.SHORT,
            ),
            assign_configured_stop_loss=lambda _entry, _slot_number: None,
        )

        close_price = Decimal("130.7845625")
        assert getattr(events[0], "planned_exit_price") == close_price
        assert r6_slot.pending_rebuild is not None
        assert r7_slot.entry is not None
        assert r6_slot.pending_rebuild.close_price == Decimal("130.79000")
        assert r7_slot.entry.close_price == close_price
        assert "tp_ok=False" in (SNOWBALL_GRID_POLICY.validate_ordering(cycle) or "")


class TestSnowballReconciliation:
    def test_reconcile_syncs_fill_price_and_dependent_prices(self):
        ss = SnowballStrategyState(initialised=True, account_nav=Decimal("100000"))
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        layer = Layer.create(1, 7, 1000)
        entry = Entry(
            entry_id=1,
            step=1,
            direction=Direction.LONG,
            entry_price=Decimal("150.00"),
            close_price=Decimal("150.50"),
            units=1000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="initial",
            layer_number=1,
            retracement_count=0,
            position_id="pos-1",
            stop_loss_price=Decimal("149.50"),
        )
        layer.slot_at(0).fill(entry)
        cycle.add_layer(layer)
        ss.cycles.append(cycle)
        state = DummyState(strategy_state=ss.to_dict())
        report = SimpleNamespace(
            removed_open_entries=0,
            relinked_open_entries=0,
            synthesized_open_entries=0,
            blockers=[],
        )
        position = SimpleNamespace(
            id="pos-1",
            direction="long",
            units=1000,
            entry_price=Decimal("150.02"),
            layer_index=1,
            retracement_count=0,
            entry_time=None,
            unrealized_pnl=Decimal("0"),
        )
        strategy_config = SimpleNamespace(
            config_dict=SnowballStrategyConfig.from_dict({"counter_tp_mode": "fixed"}).to_dict()
        )

        SNOWBALL_RECONCILER.reconcile(
            state=state,
            open_positions=[position],
            report=report,
            strategy_config=strategy_config,
        )

        updated = SnowballStrategyState.from_strategy_state(state.strategy_state)
        updated_entry = updated.cycles[0].grid.layers[0].slot_at(0).entry
        assert updated_entry.entry_price == Decimal("150.02")
        assert updated_entry.close_price == Decimal("150.52")
        assert updated_entry.stop_loss_price == Decimal("149.52")


# ===================================================================
# Stop-loss rebuild toggle (rebuild_enabled)
# ===================================================================


class TestSnowballRebuildDisabled:
    """``rebuild_enabled=False`` closes SL slots permanently.

    The key invariant is: when a stop-loss fires under this mode, the
    slot is sealed (``slot.close(refillable=False)``), not converted
    into a ``pending_rebuild`` snapshot.  The cycle's
    ``_process_stop_loss_rebuilds`` pass returns no events.
    """

    def _make_cycle_with_two_entries(
        self,
    ) -> tuple[SnowballStrategyState, SnowballCycle, Entry, Entry]:
        ss = SnowballStrategyState()
        cycle = SnowballCycle(cycle_id=1, direction=Direction.LONG)
        layer = Layer.create(1, 3, 1000, 2)
        r0 = Entry(
            entry_id=1,
            step=1,
            direction=Direction.LONG,
            entry_price=Decimal("155.00"),
            close_price=Decimal("155.50"),
            units=1000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="initial",
            layer_number=1,
            retracement_count=0,
            stop_loss_price=Decimal("154.10"),
        )
        r1 = Entry(
            entry_id=2,
            step=2,
            direction=Direction.LONG,
            entry_price=Decimal("154.70"),
            close_price=Decimal("155.00"),
            units=2000,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            role="counter",
            layer_number=1,
            retracement_count=1,
            stop_loss_price=Decimal("154.40"),
        )
        layer.slot_at(0).fill(r0)
        layer.slot_at(1).fill(r1)
        cycle.add_layer(layer)
        ss.cycles.append(cycle)
        return ss, cycle, r0, r1

    def test_stop_loss_seals_slot_without_pending_rebuild(self):
        s = _strategy(
            {
                "stop_loss_enabled": True,
                "rebuild_enabled": False,
            }
        )
        ss, cycle, r0, r1 = self._make_cycle_with_two_entries()
        tick = _make_tick(
            datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=1), "154.39", "154.41"
        )

        events = s._process_stop_loss_closes(ss, tick, cycle)
        closed_ids = {event.entry_id for event in events}
        assert r1.entry_id in closed_ids

        layer = cycle.grid.layers[0]
        r1_slot = layer.slot_at(1)
        assert r1_slot is not None
        # Sealed: no live entry, no pending snapshot, no reopen allowed.
        assert r1_slot.entry is None
        assert r1_slot.pending_rebuild is None
        assert r1_slot.ever_closed is True
        # R0 is still alive.
        assert layer.slot_at(0).entry is r0

    def test_rebuild_pass_is_noop_when_disabled(self):
        """Even if a pending_rebuild somehow existed, the rebuild pass
        does nothing when the feature is off — no events, no state
        changes.  Guards against accidental re-enable by state
        deserialization of a persisted run.
        """
        from apps.trading.enums import Direction
        from apps.trading.strategies.snowball.entries import StopLossClosedEntry

        s = _strategy(
            {
                "stop_loss_enabled": True,
                "rebuild_enabled": False,
            }
        )
        ss, cycle, _r0, _r1 = self._make_cycle_with_two_entries()
        layer = cycle.grid.layers[0]
        r1_slot = layer.slot_at(1)
        assert r1_slot is not None
        # Manually install a pending snapshot to simulate stale state.
        r1_slot.entry = None
        r1_slot.pending_rebuild = StopLossClosedEntry(
            entry_price=Decimal("154.70"),
            close_price=Decimal("155.00"),
            units=2000,
            direction=Direction.LONG,
            role="counter",
            layer_number=1,
            retracement_count=1,
            step=2,
            cycle_id=1,
        )
        tick = _make_tick(datetime(2026, 1, 1, tzinfo=UTC), "154.71", "154.73")

        events = s._process_stop_loss_rebuilds(ss, tick, cycle)

        assert events == []
        assert r1_slot.entry is None
        assert r1_slot.pending_rebuild is not None

    def test_missing_direction_reseeds_when_rebuild_is_disabled(self):
        s = _strategy(
            {
                "stop_loss_enabled": True,
                "rebuild_enabled": False,
            }
        )
        s._hedging_enabled = False
        ss = SnowballStrategyState()
        tick = _make_tick(datetime(2026, 1, 1, tzinfo=UTC), "150.00", "150.02")

        events = SnowballCycleReseeder().reseed(
            s,
            ss,
            tick,
            allow_new_positions=True,
        )

        assert events
        assert len(ss.cycles) == 1
        assert ss.cycles[0].direction == Direction.LONG


# ===================================================================
# on_tick — trend basket take-profit
# ===================================================================


class TestSnowballTrendTakeProfit:
    def test_trend_tp_closes_and_reopens(self):
        s = _strategy({"m_pips": "5"})  # small TP for easy triggering
        state = DummyState()
        ts = datetime(2026, 1, 1, tzinfo=UTC)

        s.on_tick(tick=_make_tick(ts, "150.00", "150.02"), state=state)
        state.ticks_processed += 1

        # Move price up by 5+ pips (0.05 for USD_JPY)
        result = s.on_tick(
            tick=_make_tick(ts + timedelta(seconds=60), "150.10", "150.12"),
            state=state,
        )

        close_events = [ev for ev in result.events if ev.event_type == EventType.CLOSE_POSITION]
        open_events = [ev for ev in result.events if ev.event_type == EventType.OPEN_POSITION]
        # Should close the trend position and re-open
        assert len(close_events) >= 1 or len(open_events) >= 1


# ===================================================================
# on_tick — spread guard
# ===================================================================


# ===================================================================
# Lifecycle hooks
# ===================================================================


class TestSnowballLifecycle:
    def test_on_start(self):
        s = _strategy()
        state = DummyState()
        result = s.on_start(state=state)
        assert any(ev.event_type == EventType.STRATEGY_STARTED for ev in result.events)
        ss = SnowballStrategyState.from_strategy_state(result.state.strategy_state)
        assert ss.cycles == []
        assert result.state.strategy_state["cycles"] == []

    def test_on_stop(self):
        s = _strategy()
        state = DummyState()
        result = s.on_stop(state=state)
        assert any(ev.event_type == EventType.STRATEGY_STOPPED for ev in result.events)

    def test_on_resume(self):
        s = _strategy()
        state = DummyState()
        result = s.on_resume(state=state)
        assert any(ev.event_type == EventType.STRATEGY_RESUMED for ev in result.events)


# ===================================================================
# State serialisation
# ===================================================================


class TestSnowballStateSerialization:
    def test_deserialize_state_passthrough(self):
        s = _strategy()
        data = {"initialised": True, "layer_retracement_count": 3}
        assert s.deserialize_state(data) == data

    def test_serialize_state_passthrough(self):
        s = _strategy()
        data = {"initialised": True, "layer_retracement_count": 3}
        assert s.serialize_state(data) == data
