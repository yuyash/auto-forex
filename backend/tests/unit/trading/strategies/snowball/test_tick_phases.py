"""Tests for the Snowball tick phase pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from apps.trading.dataclasses import StrategyResult
from apps.trading.dataclasses.tick import Tick
from apps.trading.enums import Direction
from apps.trading.strategies.snowball.cycle_state import SnowballCycle, SnowballStrategyState
from apps.trading.strategies.snowball.config import SnowballStrategyConfig
from apps.trading.strategies.snowball.decision_trace import (
    DISABLED_SNOWBALL_DECISION_TRACE,
    SnowballDecisionTraceRecorder,
)
from apps.trading.strategies.snowball.enums import CycleStatus
from apps.trading.strategies.snowball.tick_phases import (
    ARCHIVED_COMPLETED_CYCLES_KEY,
    SnowballExecutionStateBoundary,
    SnowballRiskGuardPhase,
    SnowballTickContext,
    SnowballTickPhaseOutcome,
    SnowballTickPipeline,
    SnowballTickStrategy,
)


@dataclass
class ExecutionStateDouble:
    """ExecutionState stand-in for phase tests."""

    strategy_state: dict[str, Any] = field(default_factory=dict)
    current_balance: Decimal = Decimal("10000")


@dataclass(frozen=True, slots=True)
class InvariantDecisionDouble:
    """Invariant decision stand-in."""

    should_stop: bool = False
    stop_reason: str = ""
    is_error: bool = False


class DecisionEngineDouble:
    """Decision engine that always allows pipeline execution."""

    def invariant_decision(self, _snowball_state: SnowballStrategyState) -> InvariantDecisionDouble:
        return InvariantDecisionDouble()


class StrategyDouble:
    """Minimal strategy surface required by SnowballTickPipeline."""

    def __init__(self) -> None:
        self.instrument = "USD_JPY"
        self.account_currency = "USD"
        self.config = SnowballStrategyConfig.from_dict({})
        self.pip_size = Decimal("0.01")
        self._hedging_enabled = False
        self._grid_order_violation: str | None = "previous-grid-error"
        self._close_order_violation: str | None = "previous-close-error"
        self.decision_engine = DecisionEngineDouble()

    def _create_cycle(
        self,
        _ss: SnowballStrategyState,
        _tick: Tick,
        _direction: Direction,
    ) -> tuple[list[Any], Any]:
        return [], None

    def _close_entry(self, *args: Any, **kwargs: Any) -> Any:
        _ = (args, kwargs)
        return None

    def _effective_base_units(self, ss: SnowballStrategyState) -> int:
        return self.config.effective_base_units(ss.account_balance)


class RecordingPhase:
    """Pipeline phase test double that records execution order."""

    def __init__(self, *, name: str, calls: list[str], stop: bool = False) -> None:
        self.name = name
        self.calls = calls
        self.stop = stop

    def run(self, context: SnowballTickContext) -> SnowballTickPhaseOutcome:
        self.calls.append(self.name)
        if not self.stop:
            return SnowballTickPhaseOutcome()
        return SnowballTickPhaseOutcome(
            result=StrategyResult(
                state=context.state,
                events=list(context.events),
                should_stop=True,
                stop_reason=f"{self.name} stopped",
            )
        )


class PipelineFixture:
    """Factory object for pipeline phase tests."""

    def strategy(self) -> SnowballTickStrategy:
        return cast(SnowballTickStrategy, StrategyDouble())

    def state(self) -> ExecutionStateDouble:
        return ExecutionStateDouble()

    def tick(self) -> Tick:
        return Tick.create(
            instrument="USD_JPY",
            timestamp=datetime(2026, 5, 8, tzinfo=UTC),
            bid=Decimal("155.00"),
            ask=Decimal("155.02"),
        )


class TestSnowballTickPipeline:
    """Verify pipeline phase ordering and stop behavior."""

    def test_runs_phases_in_configured_order(self) -> None:
        fixture = PipelineFixture()
        calls: list[str] = []
        pipeline = SnowballTickPipeline()
        pipeline.phases = (
            RecordingPhase(name="first", calls=calls),
            RecordingPhase(name="second", calls=calls),
            RecordingPhase(name="third", calls=calls),
        )

        result = pipeline.run(
            strategy=fixture.strategy(),
            tick=fixture.tick(),
            state=fixture.state(),
        )

        assert calls == ["first", "second", "third"]
        assert result.should_stop is False

    def test_stops_after_completed_phase(self) -> None:
        fixture = PipelineFixture()
        calls: list[str] = []
        pipeline = SnowballTickPipeline()
        pipeline.phases = (
            RecordingPhase(name="first", calls=calls),
            RecordingPhase(name="stop", calls=calls, stop=True),
            RecordingPhase(name="after", calls=calls),
        )

        result = pipeline.run(
            strategy=fixture.strategy(),
            tick=fixture.tick(),
            state=fixture.state(),
        )

        assert calls == ["first", "stop"]
        assert result.should_stop is True
        assert result.stop_reason == "stop stopped"

    def test_resets_strategy_violation_state_before_phases(self) -> None:
        fixture = PipelineFixture()
        strategy = fixture.strategy()
        pipeline = SnowballTickPipeline()
        pipeline.phases = (RecordingPhase(name="only", calls=[]),)

        pipeline.run(strategy=strategy, tick=fixture.tick(), state=fixture.state())

        assert strategy._grid_order_violation is None
        assert strategy._close_order_violation is None


class TestSnowballRiskGuardPhase:
    """Verify add/rebuild gates derived from runtime risk indicators."""

    def _context(
        self,
        *,
        config_overrides: dict[str, Any],
        previous_mid: Decimal = Decimal("155.00"),
        bid: str = "155.50",
        ask: str = "155.52",
        ratio: Decimal = Decimal("0"),
        metrics: dict[str, str] | None = None,
        timestamp: datetime | None = None,
    ) -> SnowballTickContext:
        fixture = PipelineFixture()
        strategy = StrategyDouble()
        strategy.config = SnowballStrategyConfig.from_dict(config_overrides)
        state = fixture.state()
        boundary = SnowballExecutionStateBoundary(state=state)
        snowball_state = SnowballStrategyState(metrics=dict(metrics or {}))
        tick = Tick.create(
            instrument="USD_JPY",
            timestamp=timestamp or datetime(2026, 5, 8, 0, 1, tzinfo=UTC),
            bid=Decimal(bid),
            ask=Decimal(ask),
        )
        return SnowballTickContext(
            strategy=cast(SnowballTickStrategy, strategy),
            state=state,
            tick=tick,
            state_boundary=boundary,
            snowball_state=snowball_state,
            ratio=ratio,
            previous_mid=previous_mid,
        )

    def _completed_candle_metrics(
        self,
        *,
        prefix: str,
        open_price: str,
        high: str,
        low: str,
        close: str,
        bucket: datetime | None = None,
        previous_close: str | None = None,
    ) -> dict[str, str]:
        bucket_dt = bucket or datetime(2026, 5, 8, 0, 0, tzinfo=UTC)
        metrics = {
            f"{prefix}_active_candle_bucket": str(int(bucket_dt.timestamp())),
            f"{prefix}_active_candle_open": open_price,
            f"{prefix}_active_candle_high": high,
            f"{prefix}_active_candle_low": low,
            f"{prefix}_active_candle_close": close,
        }
        if previous_close is not None:
            metrics[f"{prefix}_previous_candle_close"] = previous_close
        return metrics

    def test_margin_guard_can_block_adds_only(self) -> None:
        context = self._context(
            config_overrides={
                "add_margin_guard_enabled": True,
                "add_margin_guard_max_pct": "65",
                "add_margin_guard_scope": "adds_only",
            },
            ratio=Decimal("70"),
        )

        SnowballRiskGuardPhase().run(context)

        assert context.allow_new_positions is False
        assert context.allow_rebuilds is True
        assert context.snowball_state.metrics["snowball_add_block_reason"] == "margin"
        assert context.snowball_state.metrics["snowball_rebuild_block_reason"] == ""

    def test_margin_guard_can_block_rebuilds_too(self) -> None:
        context = self._context(
            config_overrides={
                "add_margin_guard_enabled": True,
                "add_margin_guard_max_pct": "65",
                "add_margin_guard_scope": "adds_and_rebuilds",
            },
            ratio=Decimal("70"),
        )

        SnowballRiskGuardPhase().run(context)

        assert context.allow_new_positions is False
        assert context.allow_rebuilds is False
        assert context.snowball_state.metrics["snowball_rebuild_block_reason"] == "margin"

    def test_volatility_guard_blocks_adds_and_rebuilds(self) -> None:
        context = self._context(
            config_overrides={
                "volatility_guard_enabled": True,
                "volatility_guard_source": "candle_ema",
                "volatility_guard_candle_ema_period": 3,
                "volatility_guard_max_pips": "10",
            },
            metrics=self._completed_candle_metrics(
                prefix="snowball_volatility_guard",
                open_price="155.00",
                high="155.20",
                low="155.00",
                close="155.20",
            ),
            bid="155.50",
            ask="155.52",
        )

        SnowballRiskGuardPhase().run(context)

        assert context.allow_new_positions is False
        assert context.allow_rebuilds is False
        assert context.snowball_state.metrics["snowball_add_block_reason"] == "volatility"

    def test_trend_guard_blocks_only_adverse_direction_adds(self) -> None:
        context = self._context(
            config_overrides={
                "add_trend_guard_enabled": True,
                "add_trend_candle_granularity": "M1",
                "add_trend_ema_period": 200,
                "add_trend_max_opposite_deviation_pips": "50",
            },
            bid="155.00",
            ask="155.02",
            metrics={"snowball_trend_guard_ema": "160"},
        )

        SnowballRiskGuardPhase().run(context)

        assert context.allow_new_positions is True
        assert context.allow_rebuilds is True
        assert context.blocked_counter_add_directions == {Direction.LONG}
        assert context.snowball_state.metrics["snowball_trend_blocked_directions"] == "long"

    def test_adaptive_intervals_set_separate_counter_and_trend_multipliers(self) -> None:
        context = self._context(
            config_overrides={
                "adaptive_counter_interval_enabled": True,
                "adaptive_counter_interval_source": "candle_ema",
                "adaptive_counter_interval_candle_ema_period": 3,
                "adaptive_counter_interval_reference_pips": "10",
                "adaptive_counter_interval_max_multiplier": "2.5",
                "adaptive_trend_interval_enabled": True,
                "adaptive_trend_interval_source": "candle_ema",
                "adaptive_trend_interval_candle_ema_period": 3,
                "adaptive_trend_interval_reference_pips": "20",
                "adaptive_trend_interval_max_multiplier": "2.5",
            },
            metrics={
                **self._completed_candle_metrics(
                    prefix="snowball_adaptive_counter_interval",
                    open_price="155.00",
                    high="155.21",
                    low="155.00",
                    close="155.21",
                ),
                **self._completed_candle_metrics(
                    prefix="snowball_adaptive_trend_interval",
                    open_price="155.00",
                    high="155.21",
                    low="155.00",
                    close="155.21",
                ),
            },
            bid="155.30",
            ask="155.32",
        )

        SnowballRiskGuardPhase().run(context)

        assert getattr(context.strategy, "_snowball_adaptive_counter_interval_multiplier") == (
            Decimal("2.1")
        )
        assert getattr(context.strategy, "_snowball_adaptive_trend_interval_multiplier") == (
            Decimal("1.05")
        )

    def test_adaptive_intervals_allow_contraction_to_min_multiplier(self) -> None:
        context = self._context(
            config_overrides={
                "adaptive_counter_interval_enabled": True,
                "adaptive_counter_interval_source": "candle_ema",
                "adaptive_counter_interval_candle_ema_period": 3,
                "adaptive_counter_interval_reference_pips": "10",
                "adaptive_counter_interval_min_multiplier": "0.5",
                "adaptive_counter_interval_max_multiplier": "2.5",
                "adaptive_trend_interval_enabled": True,
                "adaptive_trend_interval_source": "candle_ema",
                "adaptive_trend_interval_candle_ema_period": 3,
                "adaptive_trend_interval_reference_pips": "20",
                "adaptive_trend_interval_min_multiplier": "0.5",
                "adaptive_trend_interval_max_multiplier": "2.5",
            },
            metrics={
                **self._completed_candle_metrics(
                    prefix="snowball_adaptive_counter_interval",
                    open_price="155.00",
                    high="155.05",
                    low="155.00",
                    close="155.05",
                ),
                **self._completed_candle_metrics(
                    prefix="snowball_adaptive_trend_interval",
                    open_price="155.00",
                    high="155.05",
                    low="155.00",
                    close="155.05",
                ),
            },
            bid="155.30",
            ask="155.32",
        )

        SnowballRiskGuardPhase().run(context)

        assert getattr(context.strategy, "_snowball_adaptive_counter_interval_multiplier") == (
            Decimal("0.5")
        )
        assert getattr(context.strategy, "_snowball_adaptive_trend_interval_multiplier") == (
            Decimal("0.5")
        )


class TestSnowballDecisionTraceRecorder:
    """Verify disabled tracing stays allocation-light."""

    def test_disabled_trace_reuses_noop_trace(self) -> None:
        fixture = PipelineFixture()
        recorder = SnowballDecisionTraceRecorder(enabled=False)

        trace = recorder.start_tick(tick=fixture.tick())

        assert trace is DISABLED_SNOWBALL_DECISION_TRACE


class TestSnowballExecutionStateBoundary:
    """Verify the typed state boundary around ExecutionState.strategy_state."""

    def test_loads_and_persists_snowball_state(self) -> None:
        state = ExecutionStateDouble()
        boundary = SnowballExecutionStateBoundary(state=state)

        snowball_state = boundary.load()
        snowball_state.initialised = True
        boundary.persist(snowball_state)

        assert state.strategy_state["initialised"] is True
        assert state.strategy_state["cycles"] == []

    def test_deferred_persist_uses_cached_state_until_materialized(self) -> None:
        state = ExecutionStateDouble()
        state._defer_snowball_state_serialization = True  # type: ignore[attr-defined]
        boundary = SnowballExecutionStateBoundary(state=state)

        snowball_state = boundary.load()
        snowball_state.initialised = True
        snowball_state.metrics["margin_ratio"] = "0.25"
        boundary.persist(snowball_state)
        state.strategy_state["metrics"]["current_balance"] = "10000"
        state.strategy_state["_idle_entered_at"] = "2026-05-15T00:00:00+00:00"

        assert state.strategy_state["initialised"] is True
        assert "cycles" not in state.strategy_state
        assert boundary.load() is snowball_state

        state._strategy_state_materializer()  # type: ignore[attr-defined]

        assert state.strategy_state["cycles"] == []
        assert state.strategy_state["_idle_entered_at"] == "2026-05-15T00:00:00+00:00"
        assert state.strategy_state["metrics"]["margin_ratio"] == "0.25"
        assert state.strategy_state["metrics"]["current_balance"] == "10000"

    def test_materialize_keeps_fresh_deferred_base_units_over_runtime_view(self) -> None:
        initial_state = SnowballStrategyState()
        initial_state.metrics.update(
            {
                "current_base_units": "2000",
                "snowball_current_base_units": "2000",
                "current_balance": "1183656.600000",
            }
        )
        state = ExecutionStateDouble(strategy_state=initial_state.to_dict())
        state._defer_snowball_state_serialization = True  # type: ignore[attr-defined]
        state._defer_snowball_runtime_view_updates = True  # type: ignore[attr-defined]
        boundary = SnowballExecutionStateBoundary(state=state)

        snowball_state = boundary.load()
        snowball_state.set_metric("current_base_units", "2300", defer=True)
        snowball_state.set_metric("snowball_current_base_units", "2300", defer=True)
        boundary.persist(snowball_state)

        assert state.strategy_state["metrics"]["current_base_units"] == "2000"

        state._strategy_state_materializer()  # type: ignore[attr-defined]

        assert state.strategy_state["metrics"]["current_base_units"] == "2300"
        assert state.strategy_state["metrics"]["snowball_current_base_units"] == "2300"
        assert state.strategy_state["metrics"]["current_balance"] == "1183656.600000"

    def test_persist_archives_completed_trade_backed_cycles(self) -> None:
        state = ExecutionStateDouble(strategy_state={ARCHIVED_COMPLETED_CYCLES_KEY: 2})
        boundary = SnowballExecutionStateBoundary(state=state)
        active_cycle = SnowballCycle(cycle_id=10, direction=Direction.LONG)
        completed_cycle = SnowballCycle(
            cycle_id=1,
            direction=Direction.SHORT,
            status=CycleStatus.COMPLETED,
            trade_cycle_id="trade-cycle-1",
        )
        snowball_state = SnowballStrategyState(cycles=[completed_cycle, active_cycle])

        boundary.persist(snowball_state)

        assert [cycle["cycle_id"] for cycle in state.strategy_state["cycles"]] == [10]
        assert state.strategy_state[ARCHIVED_COMPLETED_CYCLES_KEY] == 3
        assert [cycle.cycle_id for cycle in snowball_state.cycles] == [10]

    def test_persist_keeps_completed_cycles_without_trade_history(self) -> None:
        state = ExecutionStateDouble()
        boundary = SnowballExecutionStateBoundary(state=state)
        state_only_cycle = SnowballCycle(
            cycle_id=1,
            direction=Direction.LONG,
            status=CycleStatus.COMPLETED,
        )
        snowball_state = SnowballStrategyState(cycles=[state_only_cycle])

        boundary.persist(snowball_state)

        assert [cycle["cycle_id"] for cycle in state.strategy_state["cycles"]] == [1]
        assert ARCHIVED_COMPLETED_CYCLES_KEY not in state.strategy_state

    def test_loads_empty_state_when_raw_value_is_malformed(self) -> None:
        state = ExecutionStateDouble(strategy_state="invalid")  # type: ignore[arg-type]
        boundary = SnowballExecutionStateBoundary(state=state)

        snowball_state = boundary.load()

        assert snowball_state.initialised is False
        assert snowball_state.cycles == []
