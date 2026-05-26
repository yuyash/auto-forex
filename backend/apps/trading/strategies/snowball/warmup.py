"""Cold-start warmup policy for the Snowball strategy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from logging import getLogger
from typing import Any

from apps.trading.dataclasses.tick import Tick
from apps.trading.strategies.snowball.config import SnowballStrategyConfig
from apps.trading.strategies.snowball.cycle_state import SnowballStrategyState

logger = getLogger(__name__)

TP_CLOSE_REASONS = frozenset({"tp", "counter_tp", "layer_initial_tp", "take_profit"})


@dataclass(frozen=True, slots=True)
class SnowballWarmupDecision:
    """Runtime decision derived from warmup settings and state."""

    active: bool
    unit_ratio_pct: Decimal
    allow_new_positions: bool
    new_position_limit: int | None = None
    max_retracement_count: int | None = None
    rebuild_limit_per_tick: int | None = None
    block_reason: str = ""


class SnowballWarmupPolicy:
    """Evaluate Snowball warmup controls on every tick."""

    def evaluate(
        self,
        *,
        config: SnowballStrategyConfig,
        state: SnowballStrategyState,
        tick: Tick,
        pip_size: Decimal,
    ) -> SnowballWarmupDecision:
        """Update warmup state and return this tick's runtime limits."""
        if not config.warmup_enabled:
            self._write_metrics(
                state,
                status="normal",
                unit_ratio_pct=Decimal("100"),
                progress_pct=Decimal("100"),
                block_reason="",
            )
            return SnowballWarmupDecision(
                active=False,
                unit_ratio_pct=Decimal("100"),
                allow_new_positions=True,
            )

        self._ensure_started(state, tick)
        self._record_market_sample(config=config, state=state, tick=tick)
        state.warmup_tick_count += 1

        elapsed_minutes = self._elapsed_minutes(state, tick)
        complete = self._is_complete(config=config, state=state, elapsed_minutes=elapsed_minutes)
        if complete:
            if not state.warmup_completed_at:
                state.warmup_completed_at = tick.timestamp.isoformat()
                logger.info(
                    "Snowball warmup completed; switching to normal operation "
                    "(elapsed_minutes=%s, tp_closes=%s)",
                    elapsed_minutes,
                    state.warmup_tp_closes,
                )
            state.warmup_phase = "normal"
            self._write_metrics(
                state,
                status="normal",
                unit_ratio_pct=Decimal("100"),
                progress_pct=Decimal("100"),
                block_reason="",
                elapsed_minutes=elapsed_minutes,
            )
            state.warmup_last_log_state = "normal"
            return SnowballWarmupDecision(
                active=False,
                unit_ratio_pct=Decimal("100"),
                allow_new_positions=True,
            )

        state.warmup_phase = "warmup"
        progress_pct = self._progress_pct(
            config=config,
            state=state,
            elapsed_minutes=elapsed_minutes,
        )
        unit_ratio_pct = self._unit_ratio_pct(config=config, progress_pct=progress_pct)
        block_reason = self._start_gate_block_reason(
            config=config,
            state=state,
            tick=tick,
            pip_size=pip_size,
        )
        open_positions = state.entry_count()
        new_position_limit = (
            max(1, config.warmup_max_positions) if config.warmup_position_limit_enabled else None
        )
        max_retracement_count = min(config.r_max, max(0, config.warmup_max_r))
        rebuild_limit = (
            max(0, config.warmup_max_rebuilds_per_tick)
            if config.warmup_rebuild_limit_enabled
            else None
        )
        allow_new_positions = not block_reason
        self._write_metrics(
            state,
            status="warmup",
            unit_ratio_pct=unit_ratio_pct,
            progress_pct=progress_pct,
            block_reason=block_reason,
            max_retracement_count=max_retracement_count,
            elapsed_minutes=elapsed_minutes,
        )
        self._log_if_changed(
            state=state,
            decision=SnowballWarmupDecision(
                active=True,
                unit_ratio_pct=unit_ratio_pct,
                allow_new_positions=allow_new_positions,
                new_position_limit=new_position_limit,
                max_retracement_count=max_retracement_count,
                rebuild_limit_per_tick=rebuild_limit,
                block_reason=block_reason,
            ),
            open_positions=open_positions,
        )
        return SnowballWarmupDecision(
            active=True,
            unit_ratio_pct=unit_ratio_pct,
            allow_new_positions=allow_new_positions,
            new_position_limit=new_position_limit,
            max_retracement_count=max_retracement_count,
            rebuild_limit_per_tick=rebuild_limit,
            block_reason=block_reason,
        )

    def record_events(self, state: SnowballStrategyState, events: list[Any]) -> None:
        """Count warmup TP closes after strategy events have mutated state."""
        if state.warmup_phase != "warmup" or state.warmup_completed_at:
            return
        tp_closes = sum(1 for event in events if self._is_tp_close(event))
        if tp_closes:
            state.warmup_tp_closes += tp_closes
            state.metrics["warmup_tp_closes"] = str(state.warmup_tp_closes)

    def _ensure_started(self, state: SnowballStrategyState, tick: Tick) -> None:
        if state.warmup_started_at:
            return
        state.warmup_started_at = tick.timestamp.isoformat()
        state.warmup_phase = "warmup"
        logger.info("Snowball warmup started at %s", state.warmup_started_at)

    def _record_market_sample(
        self,
        *,
        config: SnowballStrategyConfig,
        state: SnowballStrategyState,
        tick: Tick,
    ) -> None:
        max_window = max(
            2,
            config.warmup_gate_volatility_window_ticks,
            config.warmup_gate_trend_window_ticks,
        )
        state.warmup_mid_history.append(str(tick.mid))
        if len(state.warmup_mid_history) > max_window:
            state.warmup_mid_history = state.warmup_mid_history[-max_window:]

    def _elapsed_minutes(self, state: SnowballStrategyState, tick: Tick) -> int:
        started_at = self._parse_datetime(state.warmup_started_at)
        if started_at is None:
            return 0
        return max(0, int((tick.timestamp - started_at).total_seconds() // 60))

    def _is_complete(
        self,
        *,
        config: SnowballStrategyConfig,
        state: SnowballStrategyState,
        elapsed_minutes: int,
    ) -> bool:
        duration_ok = elapsed_minutes >= config.warmup_min_elapsed_minutes
        tp_ok = state.warmup_tp_closes >= config.warmup_required_tp_closes
        if config.warmup_completion_mode == "duration":
            return duration_ok
        if config.warmup_completion_mode == "tp_closes":
            return tp_ok
        if config.warmup_completion_mode == "duration_or_tp_closes":
            return duration_ok or tp_ok
        return duration_ok and tp_ok

    def _progress_pct(
        self,
        *,
        config: SnowballStrategyConfig,
        state: SnowballStrategyState,
        elapsed_minutes: int,
    ) -> Decimal:
        duration_progress = self._bounded_ratio(
            Decimal(elapsed_minutes),
            Decimal(max(1, config.warmup_min_elapsed_minutes)),
        )
        tp_progress = self._bounded_ratio(
            Decimal(state.warmup_tp_closes),
            Decimal(max(1, config.warmup_required_tp_closes)),
        )
        if config.warmup_completion_mode == "duration":
            return duration_progress * Decimal("100")
        if config.warmup_completion_mode == "tp_closes":
            return tp_progress * Decimal("100")
        if config.warmup_completion_mode == "duration_or_tp_closes":
            return max(duration_progress, tp_progress) * Decimal("100")
        return min(duration_progress, tp_progress) * Decimal("100")

    def _unit_ratio_pct(
        self,
        *,
        config: SnowballStrategyConfig,
        progress_pct: Decimal,
    ) -> Decimal:
        initial = max(Decimal("0.01"), min(Decimal("100"), config.warmup_initial_unit_ratio_pct))
        steps = max(1, config.warmup_unit_ramp_steps)
        progress = max(Decimal("0"), min(Decimal("1"), progress_pct / Decimal("100")))
        stepped_progress = (progress * Decimal(steps)).to_integral_value(
            rounding=ROUND_FLOOR
        ) / Decimal(steps)
        return initial + (Decimal("100") - initial) * stepped_progress

    def _start_gate_block_reason(
        self,
        *,
        config: SnowballStrategyConfig,
        state: SnowballStrategyState,
        tick: Tick,
        pip_size: Decimal,
    ) -> str:
        if not config.warmup_start_gate_enabled or state.entry_count() > 0:
            return ""
        if config.warmup_gate_spread_enabled:
            spread_pips = (tick.ask - tick.bid) / pip_size
            if spread_pips > config.warmup_gate_max_spread_pips:
                return "spread"
        if config.warmup_gate_volatility_enabled:
            volatility = self._window_range_pips(
                state.warmup_mid_history,
                config.warmup_gate_volatility_window_ticks,
                pip_size,
            )
            if volatility is None:
                return "collecting_volatility"
            if volatility > config.warmup_gate_max_volatility_pips:
                return "volatility"
        if config.warmup_gate_trend_enabled:
            trend = self._window_trend_pips(
                state.warmup_mid_history,
                config.warmup_gate_trend_window_ticks,
                pip_size,
            )
            if trend is None:
                return "collecting_trend"
            if trend > config.warmup_gate_max_trend_pips:
                return "trend"
        return ""

    def _window_range_pips(
        self,
        values: list[str],
        window: int,
        pip_size: Decimal,
    ) -> Decimal | None:
        decimals = self._window_values(values, window)
        if decimals is None:
            return None
        return (max(decimals) - min(decimals)) / pip_size

    def _window_trend_pips(
        self,
        values: list[str],
        window: int,
        pip_size: Decimal,
    ) -> Decimal | None:
        decimals = self._window_values(values, window)
        if decimals is None:
            return None
        return abs(decimals[-1] - decimals[0]) / pip_size

    def _window_values(self, values: list[str], window: int) -> list[Decimal] | None:
        window = max(2, window)
        if len(values) < window:
            return None
        decimals: list[Decimal] = []
        for value in values[-window:]:
            try:
                decimals.append(Decimal(str(value)))
            except (InvalidOperation, TypeError, ValueError):
                return None
        return decimals

    def _write_metrics(
        self,
        state: SnowballStrategyState,
        *,
        status: str,
        unit_ratio_pct: Decimal,
        progress_pct: Decimal,
        block_reason: str,
        max_retracement_count: int | None = None,
        elapsed_minutes: int | None = None,
    ) -> None:
        state.metrics["warmup_status"] = status
        state.metrics["warmup_unit_ratio_pct"] = str(unit_ratio_pct)
        state.metrics["warmup_progress_pct"] = str(progress_pct)
        state.metrics["warmup_block_reason"] = block_reason
        state.metrics["warmup_max_r"] = (
            "" if max_retracement_count is None else str(max_retracement_count)
        )
        state.metrics["warmup_tick_count"] = str(state.warmup_tick_count)
        state.metrics["warmup_tp_closes"] = str(state.warmup_tp_closes)
        if elapsed_minutes is not None:
            state.metrics["warmup_elapsed_minutes"] = str(elapsed_minutes)

    def _log_if_changed(
        self,
        *,
        state: SnowballStrategyState,
        decision: SnowballWarmupDecision,
        open_positions: int,
    ) -> None:
        log_state = (
            f"{decision.block_reason}|{decision.unit_ratio_pct}|"
            f"{decision.new_position_limit}|{decision.max_retracement_count}|"
            f"{decision.rebuild_limit_per_tick}"
        )
        if state.warmup_last_log_state == log_state:
            return
        state.warmup_last_log_state = log_state
        if decision.block_reason:
            logger.info(
                "Snowball warmup active; new entries blocked "
                "(reason=%s, open_positions=%d, unit_ratio_pct=%s)",
                decision.block_reason,
                open_positions,
                decision.unit_ratio_pct,
            )
        else:
            logger.info(
                "Snowball warmup active; new entries allowed "
                "(open_positions=%d, max_positions=%s, unit_ratio_pct=%s, "
                "max_r=%s, rebuild_limit_per_tick=%s)",
                open_positions,
                decision.new_position_limit,
                decision.unit_ratio_pct,
                decision.max_retracement_count,
                decision.rebuild_limit_per_tick,
            )

    def _is_tp_close(self, event: Any) -> bool:
        raw_event_type = getattr(event, "event_type", None)
        event_type = getattr(raw_event_type, "value", raw_event_type)
        close_reason = str(getattr(event, "close_reason", "") or "").strip().lower()
        return event_type in {"close_position", "take_profit"} and close_reason in TP_CLOSE_REASONS

    def _bounded_ratio(self, numerator: Decimal, denominator: Decimal) -> Decimal:
        if denominator <= 0:
            return Decimal("1")
        return max(Decimal("0"), min(Decimal("1"), numerator / denominator))

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        raw = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None
