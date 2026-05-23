"""Trading engine for the SnowballNet strategy.

SnowballNet is the netting/FIFO-compatible variant of Snowball. It never
depends on independent hedge-side positions. The strategy manages one net
position per instrument and makes decisions from the weighted average entry
price of that net exposure.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_HALF_UP
from logging import getLogger
from typing import Any

from apps.trading.dataclasses import EventExecutionResult, StrategyResult
from apps.trading.dataclasses.tick import Tick
from apps.trading.enums import Direction, EventType, StrategyType
from apps.trading.events import ClosePositionEvent, OpenPositionEvent, StrategyEvent
from apps.trading.models.state import ExecutionState
from apps.trading.strategies.base import Strategy
from apps.trading.strategies.registry import register_strategy
from apps.trading.strategies.snowball_net.config import SnowballNetConfig
from apps.trading.strategies.snowball_net.parameters import (
    default_parameters,
    normalize_parameters,
    parse_config,
    validate_parameters,
)
from apps.trading.strategies.snowball_net.state import SnowballNetState

logger = getLogger(__name__)


@register_strategy(
    id="snowball_net",
    schema="trading/schemas/snowball_net.json",
    display_name="SnowballNet Strategy",
    description=(
        "Net-position Snowball variant for OANDA accounts that cannot hedge and "
        "must respect FIFO. Adds and partial closes are based on the weighted "
        "average entry price of one net position."
    ),
)
class SnowballNetStrategy(Strategy):
    """Netting/FIFO-compatible Snowball strategy."""

    config: SnowballNetConfig

    @staticmethod
    def parse_config(strategy_config: Any) -> SnowballNetConfig:
        return parse_config(strategy_config)

    @classmethod
    def normalize_parameters(cls, parameters: dict[str, Any]) -> dict[str, Any]:
        return normalize_parameters(parameters)

    @classmethod
    def default_parameters(cls) -> dict[str, Any]:
        return default_parameters()

    @classmethod
    def validate_parameters(
        cls,
        *,
        parameters: dict[str, Any],
        config_schema: dict[str, Any] | None = None,
    ) -> None:
        validate_parameters(parameters=parameters, config_schema=config_schema)

    @property
    def strategy_type(self) -> StrategyType:
        return StrategyType.SNOWBALL_NET

    @classmethod
    def supports_stateful_broker_reconciliation(cls) -> bool:
        return True

    @classmethod
    def capabilities(cls) -> dict[str, Any]:
        return {
            "runtime": {
                "hedging": False,
                "netting": True,
            },
            "visualization": {
                "kind": "snowball_net",
                "cycle_statuses": False,
                "grid": False,
                "net_chart": True,
            },
            "ui": {
                "hidden_tabs": ["positions"],
            },
            "events": {
                "close_reason_labels": {
                    "net_take_profit": "Net take profit",
                    "net_loss_cut": "Net loss cut",
                    "margin_protection": "Margin protection",
                    "manual_close": "Manual close",
                },
                "strategy_event_labels": {
                    "snowball_net_initial": "SnowballNet initial entry",
                    "snowball_net_add": "SnowballNet add",
                    "snowball_net_take_profit": "SnowballNet take profit",
                    "snowball_net_margin_reduce": "SnowballNet margin reduce",
                    "snowball_net_loss_cut": "SnowballNet loss cut",
                },
            },
            "resume": {
                "stateful_broker_reconciliation": True,
            },
        }

    @classmethod
    def reconcile_broker_positions(
        cls,
        *,
        state: ExecutionState,
        open_positions: list[Any],
        report: Any,
        strategy_config: Any | None = None,
    ) -> None:
        from apps.trading.strategies.snowball_net.reconciliation import (
            reconcile_broker_positions,
        )

        reconcile_broker_positions(
            state=state,
            open_positions=open_positions,
            report=report,
            strategy_config=strategy_config,
        )

    def configure_runtime(self, *, account_currency: str, hedging_enabled: bool) -> None:
        super().configure_runtime(
            account_currency=account_currency,
            hedging_enabled=hedging_enabled,
        )
        if hedging_enabled:
            logger.info("SnowballNet ignores hedging runtime mode and uses netting semantics")

    def on_start(self, *, state: ExecutionState) -> StrategyResult:
        result = super().on_start(state=state)
        snowball_net = SnowballNetState.from_strategy_state(state.strategy_state)
        self._sync_direction_mode(snowball_net)
        state.strategy_state = snowball_net.to_dict()
        result.state = state
        return result

    def on_tick(self, *, tick: Tick, state: ExecutionState) -> StrategyResult:
        sn = SnowballNetState.from_strategy_state(state.strategy_state)
        self._sync_direction_mode(sn)
        previous_mid = sn.last_mid
        self._update_auto_direction_signal(sn, tick)
        self._update_risk_indicators(sn, tick, previous_mid=previous_mid)
        sn.last_bid = tick.bid
        sn.last_ask = tick.ask
        sn.last_mid = tick.mid
        sn.last_tick_timestamp = tick.timestamp.isoformat()

        self._update_metrics(sn, tick)

        if sn.has_pending_action:
            state.strategy_state = sn.to_dict()
            return StrategyResult.from_state(state)

        if self._emergency_stop_triggered(sn):
            margin_pct = self._margin_pct(sn)
            state.strategy_state = sn.to_dict()
            return StrategyResult(
                state=state,
                events=[],
                should_stop=True,
                stop_reason=(f"SnowballNet emergency margin threshold reached: {margin_pct}%"),
                is_error=True,
            )

        if sn.net_units <= 0 or sn.average_price is None or not sn.initialised:
            direction = self._direction_for_new_position(sn, tick)
            if direction is None:
                self._update_metrics(sn, tick)
                state.strategy_state = sn.to_dict()
                return StrategyResult.from_state(state)
            sn.direction = direction.value
            events = [self._build_open_event(sn, tick, role="initial")]
            self._update_metrics(sn, tick)
            state.strategy_state = sn.to_dict()
            return StrategyResult(state=state, events=events)

        if self._loss_cut_triggered(sn, tick):
            events = [self._build_close_event(sn, tick, reason="loss_cut")]
            self._update_metrics(sn, tick)
            state.strategy_state = sn.to_dict()
            return StrategyResult(state=state, events=events)

        if self._margin_reduce_triggered(sn):
            events = [self._build_close_event(sn, tick, reason="margin_reduce")]
            self._update_metrics(sn, tick)
            state.strategy_state = sn.to_dict()
            return StrategyResult(state=state, events=events)

        if self._take_profit_hit(sn, tick):
            events = [self._build_close_event(sn, tick, reason="take_profit")]
            self._update_metrics(sn, tick)
            state.strategy_state = sn.to_dict()
            return StrategyResult(state=state, events=events)

        if self._should_add(sn, tick):
            events = [self._build_open_event(sn, tick, role="add")]
            self._update_metrics(sn, tick)
            state.strategy_state = sn.to_dict()
            return StrategyResult(state=state, events=events)

        state.strategy_state = sn.to_dict()
        return StrategyResult.from_state(state)

    def apply_event_execution_result(
        self,
        *,
        state: ExecutionState,
        execution_result: EventExecutionResult,
    ) -> None:
        sn = SnowballNetState.from_strategy_state(state.strategy_state)
        pending = dict(sn.pending_action)
        if not pending:
            binding = execution_result.entry_binding
            if binding is not None and binding.position_id:
                sn.position_id = binding.position_id
                state.strategy_state = sn.to_dict()
            return

        kind = str(pending.get("kind") or "")
        if kind == "open":
            self._apply_open_result(sn, pending, execution_result)
        elif kind == "close":
            self._apply_close_result(sn, pending, execution_result)

        sn.clear_pending_action()
        state.strategy_state = sn.to_dict()

    # ------------------------------------------------------------------
    # Signal decisions
    # ------------------------------------------------------------------

    def _sync_direction_mode(self, sn: SnowballNetState) -> None:
        if self.config.trade_direction == "auto":
            sn.direction_mode = "auto"
            if sn.net_units <= 0 and not sn.initialised and not sn.has_pending_action:
                sn.direction = "auto"
            return
        sn.direction_mode = "fixed"
        sn.direction = self.config.trade_direction

    def _update_auto_direction_signal(self, sn: SnowballNetState, tick: Tick) -> None:
        if self.config.trade_direction != "auto":
            return

        previous_slow = sn.auto_direction_slow_ema
        fast = self._ema_next(
            current=sn.auto_direction_fast_ema,
            price=tick.mid,
            period=self.config.auto_direction_fast_period,
        )
        slow = self._ema_next(
            current=sn.auto_direction_slow_ema,
            price=tick.mid,
            period=self.config.auto_direction_slow_period,
        )
        sn.auto_direction_fast_ema = fast
        sn.auto_direction_slow_ema = slow
        sn.auto_direction_slope_pips = (
            (slow - previous_slow) / self.pip_size if previous_slow is not None else None
        )
        sn.auto_direction_samples += 1

        diff_pips = (fast - slow) / self.pip_size
        threshold = self.config.auto_direction_threshold_pips
        if diff_pips >= threshold:
            sn.auto_direction_signal = "long"
        elif diff_pips <= -threshold:
            sn.auto_direction_signal = "short"
        else:
            sn.auto_direction_signal = None

    def _update_risk_indicators(
        self,
        sn: SnowballNetState,
        tick: Tick,
        *,
        previous_mid: Decimal | None,
    ) -> None:
        previous_trend = sn.risk_trend_ema
        trend = self._ema_next(
            current=sn.risk_trend_ema,
            price=tick.mid,
            period=self.config.add_trend_ema_period,
        )
        sn.risk_trend_ema = trend
        sn.risk_trend_slope_pips = (
            (trend - previous_trend) / self.pip_size if previous_trend is not None else None
        )

        if previous_mid is None:
            return
        move_pips = abs(tick.mid - previous_mid) / self.pip_size
        sn.auto_direction_volatility_ema_pips = self._ema_next(
            current=sn.auto_direction_volatility_ema_pips,
            price=move_pips,
            period=self.config.auto_direction_volatility_ema_period,
        )
        sn.adaptive_interval_volatility_ema_pips = self._ema_next(
            current=sn.adaptive_interval_volatility_ema_pips,
            price=move_pips,
            period=self.config.adaptive_interval_volatility_ema_period,
        )
        sn.volatility_guard_volatility_ema_pips = self._ema_next(
            current=sn.volatility_guard_volatility_ema_pips,
            price=move_pips,
            period=self.config.volatility_guard_volatility_ema_period,
        )

    @staticmethod
    def _ema_next(*, current: Decimal | None, price: Decimal, period: int) -> Decimal:
        if current is None:
            return price
        alpha = Decimal("2") / Decimal(period + 1)
        return current + (price - current) * alpha

    def _direction_for_new_position(self, sn: SnowballNetState, tick: Tick) -> Direction | None:
        if self.config.trade_direction != "auto":
            direction = self._direction(sn)
            sn.direction = direction.value
            return direction

        if sn.auto_direction_samples < self.config.auto_direction_min_samples:
            sn.last_action = {
                "kind": "wait",
                "action": "auto_direction_warmup",
                "timestamp": tick.timestamp.isoformat(),
                "samples": sn.auto_direction_samples,
                "required_samples": self.config.auto_direction_min_samples,
            }
            return None

        if sn.auto_direction_signal not in {Direction.LONG.value, Direction.SHORT.value}:
            sn.last_action = {
                "kind": "wait",
                "action": "auto_direction_neutral",
                "timestamp": tick.timestamp.isoformat(),
                "fast_ema": str(sn.auto_direction_fast_ema)
                if sn.auto_direction_fast_ema is not None
                else None,
                "slow_ema": str(sn.auto_direction_slow_ema)
                if sn.auto_direction_slow_ema is not None
                else None,
            }
            return None

        direction = Direction(str(sn.auto_direction_signal))
        block_reason = self._auto_direction_block_reason(sn, tick)
        if block_reason is not None:
            sn.last_action = {
                "kind": "wait",
                "action": "auto_direction_filtered",
                "reason": block_reason,
                "timestamp": tick.timestamp.isoformat(),
                "signal": direction.value,
                "spread_pips": str(self._spread_pips(tick)),
                "volatility_pips": str(
                    self._volatility_pips(
                        sn,
                        current_atr_key="snowball_net_auto_direction_current_atr",
                        fallback_volatility=sn.auto_direction_volatility_ema_pips,
                    )
                ),
                "slow_ema_slope_pips": str(sn.auto_direction_slope_pips)
                if sn.auto_direction_slope_pips is not None
                else None,
            }
            return None

        diff_pips = Decimal("0")
        if sn.auto_direction_fast_ema is not None and sn.auto_direction_slow_ema is not None:
            diff_pips = (sn.auto_direction_fast_ema - sn.auto_direction_slow_ema) / self.pip_size
        sn.direction = direction.value
        sn.auto_direction_last_decision = {
            "direction": direction.value,
            "reason": "ema_trend",
            "timestamp": tick.timestamp.isoformat(),
            "samples": sn.auto_direction_samples,
            "fast_ema": str(sn.auto_direction_fast_ema)
            if sn.auto_direction_fast_ema is not None
            else None,
            "slow_ema": str(sn.auto_direction_slow_ema)
            if sn.auto_direction_slow_ema is not None
            else None,
            "difference_pips": str(diff_pips),
            "threshold_pips": str(self.config.auto_direction_threshold_pips),
            "slow_ema_slope_pips": str(sn.auto_direction_slope_pips)
            if sn.auto_direction_slope_pips is not None
            else None,
        }
        return direction

    def _direction(self, sn: SnowballNetState) -> Direction:
        if self.config.trade_direction != "auto":
            return Direction.LONG if self.config.trade_direction == "long" else Direction.SHORT
        if sn.direction in {Direction.LONG.value, Direction.SHORT.value}:
            return Direction(str(sn.direction))
        if sn.auto_direction_signal in {Direction.LONG.value, Direction.SHORT.value}:
            return Direction(str(sn.auto_direction_signal))
        return Direction.LONG

    def _auto_direction_block_reason(self, sn: SnowballNetState, tick: Tick) -> str | None:
        if not self.config.auto_direction_filter_enabled:
            return None
        if self._spread_pips(tick) > self.config.auto_direction_max_spread_pips:
            return "spread"
        if self._volatility_exceeded(
            sn,
            current_atr_key="snowball_net_auto_direction_current_atr",
            baseline_atr_key="snowball_net_auto_direction_baseline_atr",
            fallback_volatility=sn.auto_direction_volatility_ema_pips,
            max_pips=self.config.auto_direction_max_volatility_pips,
            max_multiplier=self.config.auto_direction_max_volatility_multiplier,
        ):
            return "volatility"
        slope = abs(sn.auto_direction_slope_pips or Decimal("0"))
        if slope > self.config.auto_direction_max_slope_pips:
            return "trend_slope"
        return None

    def _entry_price(self, sn: SnowballNetState, tick: Tick) -> Decimal:
        return tick.ask if self._direction(sn) == Direction.LONG else tick.bid

    def _exit_price(self, sn: SnowballNetState, tick: Tick) -> Decimal:
        return tick.bid if self._direction(sn) == Direction.LONG else tick.ask

    def _target_price(self, sn: SnowballNetState, average_price: Decimal) -> Decimal:
        offset = self.config.take_profit_pips * self.pip_size
        if self._direction(sn) == Direction.LONG:
            return average_price + offset
        return average_price - offset

    def _next_add_price(
        self, sn: SnowballNetState, average_price: Decimal, add_step: int
    ) -> Decimal:
        offset = self._add_interval_pips(sn, add_step) * self.pip_size
        if self._direction(sn) == Direction.LONG:
            return average_price - offset
        return average_price + offset

    def _favorable_pips(self, sn: SnowballNetState, tick: Tick) -> Decimal:
        if sn.average_price is None:
            return Decimal("0")
        price = self._exit_price(sn, tick)
        if self._direction(sn) == Direction.LONG:
            return (price - sn.average_price) / self.pip_size
        return (sn.average_price - price) / self.pip_size

    def _adverse_pips(self, sn: SnowballNetState, tick: Tick) -> Decimal:
        if sn.average_price is None:
            return Decimal("0")
        price = self._entry_price(sn, tick)
        if self._direction(sn) == Direction.LONG:
            return (sn.average_price - price) / self.pip_size
        return (price - sn.average_price) / self.pip_size

    def _take_profit_hit(self, sn: SnowballNetState, tick: Tick) -> bool:
        return sn.net_units > 0 and self._favorable_pips(sn, tick) >= self.config.take_profit_pips

    def _should_add(self, sn: SnowballNetState, tick: Tick) -> bool:
        if sn.add_count >= self.config.max_add_count:
            return False
        if sn.net_units >= self.config.effective_max_net_units:
            return False
        if self._add_block_reason(sn, tick) is not None:
            return False
        next_step = sn.add_count + 1
        return self._adverse_pips(sn, tick) >= self._add_interval_pips(sn, next_step)

    def _margin_pct(self, sn: SnowballNetState) -> Decimal:
        raw = sn.metrics.get("margin_ratio")
        if raw not in (None, ""):
            try:
                return Decimal(str(raw)) * Decimal("100")
            except (InvalidOperation, TypeError, ValueError):
                pass

        pct_raw = sn.metrics.get("snowball_net_margin_ratio_pct")
        if pct_raw not in (None, ""):
            try:
                return Decimal(str(pct_raw))
            except (InvalidOperation, TypeError, ValueError):
                pass
        return Decimal("0")

    def _margin_reduce_triggered(self, sn: SnowballNetState) -> bool:
        if not self.config.margin_reduce_enabled or sn.net_units <= self.config.initial_units:
            return False
        return self._margin_pct(sn) >= self.config.margin_reduce_threshold_pct

    def _emergency_stop_triggered(self, sn: SnowballNetState) -> bool:
        if not self.config.emergency_enabled or sn.net_units <= 0:
            return False
        return self._margin_pct(sn) >= self.config.emergency_threshold_pct

    def _loss_cut_triggered(self, sn: SnowballNetState, tick: Tick) -> bool:
        if not self.config.loss_cut_enabled or sn.net_units <= 0:
            return False
        pips_triggered = self._favorable_pips(sn, tick) <= -self.config.loss_cut_threshold_pips
        if self.config.loss_cut_mode == "staged_margin":
            return (
                pips_triggered or self._margin_pct(sn) >= self.config.loss_cut_stage_threshold_pct
            )
        return pips_triggered

    def _add_interval_pips(self, sn: SnowballNetState, step: int) -> Decimal:
        base = self.config.add_interval_pips(step)
        if not self.config.adaptive_interval_enabled:
            return base
        volatility = self._volatility_pips(
            sn,
            current_atr_key="snowball_net_adaptive_interval_current_atr",
            fallback_volatility=sn.adaptive_interval_volatility_ema_pips,
        )
        if volatility <= 0:
            return base
        reference = self._adaptive_reference_pips(sn)
        if reference <= 0:
            return base
        multiplier = volatility / reference
        multiplier = max(self.config.adaptive_interval_min_multiplier, multiplier)
        multiplier = min(self.config.adaptive_interval_max_multiplier, multiplier)
        return self.config.round_pips(base * multiplier)

    def _adaptive_reference_pips(self, sn: SnowballNetState) -> Decimal:
        baseline = self._decimal_metric(
            sn,
            "snowball_net_adaptive_interval_baseline_atr",
            legacy_key="baseline_atr",
        )
        if baseline is not None and baseline > 0:
            return baseline
        return self.config.adaptive_interval_reference_pips

    def _exposure_ratio(self, sn: SnowballNetState) -> Decimal:
        denominator = self.config.effective_max_net_units - self.config.initial_units
        if denominator <= 0:
            return Decimal("0")
        raw = Decimal(max(0, sn.net_units - self.config.initial_units)) / Decimal(denominator)
        return max(Decimal("0"), min(Decimal("1"), raw))

    def _add_block_reason(self, sn: SnowballNetState, tick: Tick) -> str | None:
        if (
            self.config.spread_guard_enabled
            and self._spread_pips(tick) > self.config.max_spread_pips
        ):
            return "spread"
        if self.config.volatility_guard_enabled and self._volatility_exceeded(
            sn,
            current_atr_key="snowball_net_volatility_guard_current_atr",
            baseline_atr_key="snowball_net_volatility_guard_baseline_atr",
            fallback_volatility=sn.volatility_guard_volatility_ema_pips,
            max_pips=self.config.volatility_guard_max_atr_pips,
            max_multiplier=self.config.volatility_guard_max_atr_multiplier,
        ):
            return "volatility"
        if self.config.add_margin_guard_enabled and (
            self._margin_pct(sn) >= self.config.add_margin_guard_max_pct
        ):
            return "margin"
        if self.config.add_trend_guard_enabled:
            trend_reason = self._trend_block_reason(sn, tick)
            if trend_reason is not None:
                return trend_reason
        return None

    def _trend_block_reason(self, sn: SnowballNetState, tick: Tick) -> str | None:
        deviation = self._trend_deviation_pips(sn, tick)
        direction = self._direction(sn)
        if direction == Direction.LONG:
            if deviation <= -self.config.add_trend_max_opposite_deviation_pips:
                return "trend_deviation"
            slope = sn.risk_trend_slope_pips or Decimal("0")
            if (
                self.config.add_trend_max_opposite_slope_pips > 0
                and slope <= -self.config.add_trend_max_opposite_slope_pips
            ):
                return "trend_slope"
        else:
            if deviation >= self.config.add_trend_max_opposite_deviation_pips:
                return "trend_deviation"
            slope = sn.risk_trend_slope_pips or Decimal("0")
            if (
                self.config.add_trend_max_opposite_slope_pips > 0
                and slope >= self.config.add_trend_max_opposite_slope_pips
            ):
                return "trend_slope"
        return None

    def _trend_deviation_pips(self, sn: SnowballNetState, tick: Tick) -> Decimal:
        if sn.risk_trend_ema is None:
            return Decimal("0")
        return (tick.mid - sn.risk_trend_ema) / self.pip_size

    def _spread_pips(self, tick: Tick) -> Decimal:
        return max(Decimal("0"), (tick.ask - tick.bid) / self.pip_size)

    def _volatility_pips(
        self,
        sn: SnowballNetState,
        *,
        current_atr_key: str,
        fallback_volatility: Decimal | None,
    ) -> Decimal:
        current_atr = self._decimal_metric(
            sn,
            current_atr_key,
            legacy_key="current_atr",
        )
        if current_atr is not None and current_atr > 0:
            return current_atr
        return fallback_volatility or Decimal("0")

    def _volatility_exceeded(
        self,
        sn: SnowballNetState,
        *,
        current_atr_key: str,
        baseline_atr_key: str,
        fallback_volatility: Decimal | None,
        max_pips: Decimal,
        max_multiplier: Decimal,
    ) -> bool:
        volatility = self._volatility_pips(
            sn,
            current_atr_key=current_atr_key,
            fallback_volatility=fallback_volatility,
        )
        if volatility <= 0:
            return False
        if volatility > max_pips:
            return True
        baseline = self._decimal_metric(sn, baseline_atr_key, legacy_key="baseline_atr")
        return baseline is not None and baseline > 0 and volatility > baseline * max_multiplier

    # ------------------------------------------------------------------
    # Event builders
    # ------------------------------------------------------------------

    def _build_open_event(
        self,
        sn: SnowballNetState,
        tick: Tick,
        *,
        role: str,
    ) -> StrategyEvent:
        direction = self._direction(sn)
        price = self._entry_price(sn, tick)
        units = self._open_units(sn, role=role)
        entry_id = sn.allocate_entry_id()
        previous_units = sn.net_units
        previous_average = sn.average_price
        add_step = sn.add_count + 1 if role == "add" else 0
        provisional_average = self._weighted_average(previous_average, previous_units, price, units)
        target_price = self._target_price(sn, provisional_average)
        event_type = "snowball_net_initial" if role == "initial" else "snowball_net_add"
        interval = self._add_interval_pips(sn, add_step) if add_step else None
        description = self._open_description(
            role=role,
            units=units,
            price=price,
            provisional_average=provisional_average,
            target_price=target_price,
            add_step=add_step,
            interval=interval,
        )

        sn.pending_action = {
            "kind": "open",
            "role": role,
            "entry_id": entry_id,
            "units": units,
            "previous_units": previous_units,
            "previous_average_price": str(previous_average) if previous_average else None,
            "request_price": str(price),
            "add_step": add_step,
            "timestamp": tick.timestamp.isoformat(),
        }
        sn.last_action = {
            "kind": "signal",
            "action": event_type,
            "timestamp": tick.timestamp.isoformat(),
            "units": units,
            "price": str(price),
        }

        event = OpenPositionEvent(
            event_type=EventType.OPEN_POSITION,
            timestamp=tick.timestamp,
            layer_number=1,
            direction=direction.value,
            price=price,
            units=units,
            retracement_count=add_step,
            entry_id=entry_id,
            strategy_event_type=event_type,
            planned_exit_price=target_price,
            planned_exit_price_formula=(
                f"weighted_avg({previous_units}+{units}) "
                f"{'+' if direction == Direction.LONG else '-'} "
                f"{self.config.take_profit_pips} * {self.pip_size}"
            ),
            description=description,
            merge_with_existing=True,
        )
        event.strategy_type = "snowball_net"
        event.visual_group_id = "snowball_net"
        event.basket = "net"
        event.expected_interval_pips = interval
        event.actual_interval_pips = self._adverse_pips(sn, tick) if role == "add" else None
        event.expected_tp_pips = self.config.take_profit_pips
        event.expected_exit_price = target_price
        return event

    def _build_close_event(
        self,
        sn: SnowballNetState,
        tick: Tick,
        *,
        reason: str,
    ) -> StrategyEvent:
        direction = self._direction(sn)
        exit_price = self._exit_price(sn, tick)
        average = sn.average_price or exit_price
        units = self._close_units(sn, reason=reason)
        favorable_pips = self._favorable_pips(sn, tick)
        strategy_event_type = {
            "loss_cut": "snowball_net_loss_cut",
            "margin_reduce": "snowball_net_margin_reduce",
        }.get(reason, "snowball_net_take_profit")
        close_reason = {
            "loss_cut": "net_loss_cut",
            "margin_reduce": "margin_protection",
        }.get(reason, "net_take_profit")
        description = self._close_description(
            reason=reason,
            units=units,
            average=average,
            exit_price=exit_price,
            favorable_pips=favorable_pips,
        )

        sn.pending_action = {
            "kind": "close",
            "reason": reason,
            "units": units,
            "previous_units": sn.net_units,
            "previous_average_price": str(sn.average_price) if sn.average_price else None,
            "position_id": sn.position_id,
            "request_price": str(exit_price),
            "previous_add_count": sn.add_count,
            "timestamp": tick.timestamp.isoformat(),
        }
        sn.last_action = {
            "kind": "signal",
            "action": strategy_event_type,
            "timestamp": tick.timestamp.isoformat(),
            "units": units,
            "price": str(exit_price),
        }

        event = ClosePositionEvent(
            event_type=EventType.CLOSE_POSITION,
            timestamp=tick.timestamp,
            layer_number=1,
            direction=direction.value,
            entry_price=average,
            exit_price=exit_price,
            units=units,
            pips=favorable_pips,
            retracement_count=sn.add_count,
            position_id=sn.position_id,
            strategy_event_type=strategy_event_type,
            description=description,
            force_instrument_close=True,
        )
        event.strategy_type = "snowball_net"
        event.visual_group_id = "snowball_net"
        event.basket = "net"
        event.close_reason = close_reason
        event.actual_tp_pips = favorable_pips
        event.expected_tp_pips = self.config.take_profit_pips
        event.actual_exit_price = exit_price
        event.margin_ratio = self._margin_pct(sn) / Decimal("100")
        return event

    def _open_units(self, sn: SnowballNetState, *, role: str) -> int:
        available = self.config.effective_max_net_units - max(0, sn.net_units)
        if role == "initial":
            configured = self.config.initial_units
        elif self.config.add_unit_allocation_mode == "remaining_linear":
            remaining_steps = max(1, self.config.max_add_count - sn.add_count)
            configured = int(
                (Decimal(max(0, available)) / Decimal(remaining_steps)).to_integral_value(
                    rounding=ROUND_FLOOR
                )
            )
            configured = max(1, configured)
        elif self.config.add_lot_progression_mode == "linear_increment":
            configured = self.config.add_units * (sn.add_count + 1)
        else:
            configured = self.config.add_units
        return max(0, min(configured, available))

    def _close_units(self, sn: SnowballNetState, *, reason: str) -> int:
        if reason == "loss_cut" and self.config.loss_cut_mode == "full":
            return sn.net_units
        if sn.net_units <= self.config.min_close_units:
            return sn.net_units
        if reason == "loss_cut":
            calculated = self._close_units_to_margin_target(
                sn,
                target_pct=self.config.loss_cut_stage_target_pct,
                fallback_ratio=self.config.loss_cut_stage_ratio,
            )
        elif reason == "margin_reduce":
            calculated = self._margin_reduce_close_units(sn)
        else:
            raw_units = Decimal(sn.net_units) * self.config.partial_close_ratio
            calculated = int(raw_units.to_integral_value(rounding=ROUND_HALF_UP))
        units = max(self.config.min_close_units, calculated)
        if sn.net_units - units < self.config.min_close_units:
            return sn.net_units
        return min(sn.net_units, units)

    def _margin_reduce_close_units(self, sn: SnowballNetState) -> int:
        return self._close_units_to_margin_target(
            sn,
            target_pct=self.config.margin_reduce_target_pct,
            fallback_ratio=self.config.margin_reduce_ratio,
        )

    def _close_units_to_margin_target(
        self,
        sn: SnowballNetState,
        *,
        target_pct: Decimal,
        fallback_ratio: Decimal,
    ) -> int:
        current_margin_pct = self._margin_pct(sn)
        if current_margin_pct > 0 and target_pct > 0:
            target_units = (
                Decimal(sn.net_units) * target_pct / current_margin_pct
            ).to_integral_value(rounding=ROUND_FLOOR)
            remaining_units = max(self.config.initial_units, int(target_units))
            close_units = max(0, sn.net_units - remaining_units)
            if close_units > 0:
                return close_units

        raw_units = Decimal(sn.net_units) * fallback_ratio
        return int(raw_units.to_integral_value(rounding=ROUND_HALF_UP))

    # ------------------------------------------------------------------
    # Execution feedback
    # ------------------------------------------------------------------

    def _apply_open_result(
        self,
        sn: SnowballNetState,
        pending: dict[str, Any],
        execution_result: EventExecutionResult,
    ) -> None:
        units = self._int_from_pending(pending, "units")
        previous_units = self._int_from_pending(pending, "previous_units")
        previous_average = self._decimal_from_pending(pending, "previous_average_price")
        fill_price = (
            execution_result.entry_binding.fill_price
            if execution_result.entry_binding and execution_result.entry_binding.fill_price
            else execution_result.execution_price
        )
        if fill_price is None:
            fill_price = self._decimal_from_pending(pending, "request_price") or Decimal("0")

        sn.net_units = previous_units + units
        sn.average_price = self._weighted_average(
            previous_average, previous_units, fill_price, units
        )
        sn.initialised = sn.net_units > 0
        if str(pending.get("role") or "") == "add":
            sn.add_count += 1
            sn.max_consecutive_add_count = max(
                sn.max_consecutive_add_count,
                sn.add_count,
            )
        else:
            sn.add_count = 0
            sn.current_trend_realized_pnl = Decimal("0")
        sn.max_net_units_seen = max(sn.max_net_units_seen, sn.net_units)
        if execution_result.entry_binding is not None:
            sn.position_id = execution_result.entry_binding.position_id
        sn.last_action = {
            "kind": "executed",
            "action": "open",
            "role": pending.get("role"),
            "entry_id": pending.get("entry_id"),
            "units": units,
            "price": str(fill_price),
            "timestamp": pending.get("timestamp"),
        }

    def _apply_close_result(
        self,
        sn: SnowballNetState,
        pending: dict[str, Any],
        execution_result: EventExecutionResult,
    ) -> None:
        requested_units = self._int_from_pending(pending, "units")
        previous_units = self._int_from_pending(pending, "previous_units")
        closed_units = execution_result.executed_units or requested_units
        remaining_units = max(0, previous_units - closed_units)
        sn.current_trend_realized_pnl += execution_result.realized_pnl_delta
        if sn.current_trend_realized_pnl < 0:
            sn.max_trend_loss = max(
                sn.max_trend_loss,
                abs(sn.current_trend_realized_pnl),
            )
        sn.net_units = remaining_units
        if remaining_units <= 0:
            sn.initialised = False
            sn.average_price = None
            sn.position_id = None
            sn.add_count = 0
            sn.current_trend_realized_pnl = Decimal("0")
            if self.config.trade_direction == "auto":
                sn.direction = "auto"
        else:
            sn.average_price = self._decimal_from_pending(pending, "previous_average_price")
            if (
                self.config.add_unit_allocation_mode == "fixed"
                and self.config.add_lot_progression_mode == "fixed"
            ):
                sn.add_count = self._recalculate_add_count(remaining_units)
            else:
                sn.add_count = self._int_from_pending(pending, "previous_add_count")
            if pending.get("position_id"):
                sn.position_id = str(pending["position_id"])
        sn.last_action = {
            "kind": "executed",
            "action": "close",
            "reason": pending.get("reason"),
            "units": closed_units,
            "position_id": pending.get("position_id"),
            "price": str(execution_result.execution_price)
            if execution_result.execution_price is not None
            else pending.get("request_price"),
            "timestamp": pending.get("timestamp"),
        }

    def _recalculate_add_count(self, remaining_units: int) -> int:
        extra_units = max(0, remaining_units - self.config.initial_units)
        if extra_units <= 0:
            return 0
        add_units = max(1, self.config.add_units)
        return min(self.config.max_add_count, (extra_units + add_units - 1) // add_units)

    def _update_extreme_metrics(
        self,
        sn: SnowballNetState,
        *,
        favorable_pips: Decimal,
        margin_pct: Decimal,
    ) -> None:
        sn.max_net_units_seen = max(sn.max_net_units_seen, sn.net_units)
        sn.max_margin_ratio_pct = max(sn.max_margin_ratio_pct, margin_pct)

        unrealized = self._decimal_metric(sn, "unrealized_pnl")
        if unrealized is None and sn.net_units > 0:
            unrealized = favorable_pips * self.pip_size * Decimal(sn.net_units)
        if unrealized is not None and unrealized < 0:
            sn.max_unrealized_loss = max(sn.max_unrealized_loss, abs(unrealized))

    # ------------------------------------------------------------------
    # Metrics and formatting
    # ------------------------------------------------------------------

    def _update_metrics(self, sn: SnowballNetState, tick: Tick) -> None:
        current_price = self._exit_price(sn, tick)
        average = sn.average_price
        favorable = self._favorable_pips(sn, tick)
        adverse = self._adverse_pips(sn, tick)
        next_step = sn.add_count + 1
        structurally_can_add = (
            sn.net_units > 0
            and sn.add_count < self.config.max_add_count
            and sn.net_units < self.config.effective_max_net_units
        )
        add_block_reason = self._add_block_reason(sn, tick) if structurally_can_add else None
        can_add = structurally_can_add and add_block_reason is None
        next_interval = self._add_interval_pips(sn, next_step) if structurally_can_add else None
        target_price = self._target_price(sn, average) if average is not None else None
        theoretical_next_add_price = (
            self._next_add_price(sn, average, next_step)
            if average is not None and sn.net_units > 0
            else None
        )
        next_add_price = theoretical_next_add_price if can_add else None
        next_add_distance = (
            max(Decimal("0"), next_interval - adverse) if next_interval is not None else None
        )
        exposure_pct = (
            Decimal(sn.net_units) / Decimal(self.config.effective_max_net_units) * Decimal("100")
            if self.config.effective_max_net_units > 0
            else Decimal("0")
        )
        margin_pct = self._margin_pct(sn)
        self._update_extreme_metrics(sn, favorable_pips=favorable, margin_pct=margin_pct)
        adaptive_volatility = self._volatility_pips(
            sn,
            current_atr_key="snowball_net_adaptive_interval_current_atr",
            fallback_volatility=sn.adaptive_interval_volatility_ema_pips,
        )
        guard_volatility = self._volatility_pips(
            sn,
            current_atr_key="snowball_net_volatility_guard_current_atr",
            fallback_volatility=sn.volatility_guard_volatility_ema_pips,
        )
        auto_direction_volatility = self._volatility_pips(
            sn,
            current_atr_key="snowball_net_auto_direction_current_atr",
            fallback_volatility=sn.auto_direction_volatility_ema_pips,
        )
        spread = self._spread_pips(tick)
        trend_deviation = self._trend_deviation_pips(sn, tick)

        metrics = dict(sn.metrics)
        metrics.update(
            {
                "active_cycles": "1" if sn.net_units > 0 else "0",
                "snowball_net_net_units": str(sn.net_units),
                "snowball_net_direction": sn.direction,
                "snowball_net_direction_mode": sn.direction_mode,
                "snowball_net_auto_direction_signal": sn.auto_direction_signal,
                "snowball_net_auto_direction_samples": str(sn.auto_direction_samples),
                "snowball_net_auto_direction_fast_ema": (
                    str(sn.auto_direction_fast_ema)
                    if sn.auto_direction_fast_ema is not None
                    else None
                ),
                "snowball_net_auto_direction_slow_ema": (
                    str(sn.auto_direction_slow_ema)
                    if sn.auto_direction_slow_ema is not None
                    else None
                ),
                "snowball_net_auto_direction_slope_pips": (
                    str(sn.auto_direction_slope_pips)
                    if sn.auto_direction_slope_pips is not None
                    else None
                ),
                "snowball_net_average_price": str(average) if average is not None else None,
                "snowball_net_current_price": str(current_price),
                "snowball_net_pips_from_average": str(favorable),
                "snowball_net_adverse_pips": str(max(Decimal("0"), adverse)),
                "snowball_net_loss_cut_enabled": self.config.loss_cut_enabled,
                "snowball_net_loss_cut_threshold_pips": (
                    str(self.config.loss_cut_threshold_pips)
                    if self.config.loss_cut_enabled
                    else None
                ),
                "snowball_net_target_price": str(target_price) if target_price else None,
                "snowball_net_next_add_price": str(next_add_price) if next_add_price else None,
                "snowball_net_theoretical_next_add_price": (
                    str(theoretical_next_add_price)
                    if theoretical_next_add_price is not None
                    else None
                ),
                "snowball_net_can_add": can_add,
                "snowball_net_add_block_reason": add_block_reason,
                "snowball_net_effective_add_interval_pips": (
                    str(next_interval) if next_interval is not None else None
                ),
                "snowball_net_next_add_distance_pips": str(next_add_distance)
                if next_add_distance is not None
                else None,
                "snowball_net_add_count": str(sn.add_count),
                "snowball_net_exposure_pct": str(exposure_pct),
                "snowball_net_margin_ratio_pct": str(margin_pct),
                "snowball_net_spread_pips": str(spread),
                "snowball_net_volatility_pips": str(adaptive_volatility),
                "snowball_net_adaptive_interval_volatility_pips": str(adaptive_volatility),
                "snowball_net_volatility_guard_volatility_pips": str(guard_volatility),
                "snowball_net_auto_direction_volatility_pips": str(auto_direction_volatility),
                "snowball_net_trend_ema": (
                    str(sn.risk_trend_ema) if sn.risk_trend_ema is not None else None
                ),
                "snowball_net_trend_deviation_pips": str(trend_deviation),
                "snowball_net_trend_slope_pips": (
                    str(sn.risk_trend_slope_pips) if sn.risk_trend_slope_pips is not None else None
                ),
                "snowball_net_margin_reduce_enabled": self.config.margin_reduce_enabled,
                "snowball_net_margin_reduce_threshold_pct": (
                    str(self.config.margin_reduce_threshold_pct)
                    if self.config.margin_reduce_enabled
                    else None
                ),
                "snowball_net_margin_reduce_target_pct": (
                    str(self.config.margin_reduce_target_pct)
                    if self.config.margin_reduce_enabled
                    else None
                ),
                "snowball_net_emergency_enabled": self.config.emergency_enabled,
                "snowball_net_emergency_threshold_pct": (
                    str(self.config.emergency_threshold_pct)
                    if self.config.emergency_enabled
                    else None
                ),
                "snowball_net_pending_action": str(sn.pending_action.get("kind") or ""),
                "snowball_net_max_unrealized_loss": str(sn.max_unrealized_loss),
                "snowball_net_max_net_units": str(sn.max_net_units_seen),
                "snowball_net_max_margin_ratio_pct": str(sn.max_margin_ratio_pct),
                "snowball_net_max_consecutive_add_count": str(sn.max_consecutive_add_count),
                "snowball_net_max_trend_loss": str(sn.max_trend_loss),
            }
        )
        sn.metrics = metrics

    def _open_description(
        self,
        *,
        role: str,
        units: int,
        price: Decimal,
        provisional_average: Decimal,
        target_price: Decimal,
        add_step: int,
        interval: Decimal | None,
    ) -> str:
        if role == "initial":
            return (
                "SnowballNet initial entry | "
                f"units={units}, entry={price:.5f}, avg={provisional_average:.5f}, "
                f"target={target_price:.5f}"
            )
        return (
            "SnowballNet add | "
            f"step={add_step}, interval={interval} pips, units={units}, "
            f"entry={price:.5f}, avg={provisional_average:.5f}, "
            f"target={target_price:.5f}"
        )

    @staticmethod
    def _close_description(
        *,
        reason: str,
        units: int,
        average: Decimal,
        exit_price: Decimal,
        favorable_pips: Decimal,
    ) -> str:
        label = {
            "loss_cut": "loss cut",
            "margin_reduce": "margin reduce",
        }.get(reason, "take profit")
        return (
            f"SnowballNet {label} | units={units}, avg={average:.5f}, "
            f"exit={exit_price:.5f}, pips_from_avg={favorable_pips:.1f}"
        )

    @staticmethod
    def _weighted_average(
        previous_average: Decimal | None,
        previous_units: int,
        fill_price: Decimal,
        fill_units: int,
    ) -> Decimal:
        if previous_average is None or previous_units <= 0:
            return fill_price
        total_units = previous_units + fill_units
        if total_units <= 0:
            return fill_price
        return (
            previous_average * Decimal(previous_units) + fill_price * Decimal(fill_units)
        ) / Decimal(total_units)

    @staticmethod
    def _decimal_from_pending(pending: dict[str, Any], key: str) -> Decimal | None:
        value = pending.get(key)
        if value in (None, ""):
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None

    @staticmethod
    def _decimal_metric(
        sn: SnowballNetState,
        key: str,
        *,
        legacy_key: str | None = None,
    ) -> Decimal | None:
        value = sn.metrics.get(key)
        if value in (None, "") and legacy_key is not None:
            value = sn.metrics.get(legacy_key)
        if value in (None, ""):
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None

    @staticmethod
    def _int_from_pending(pending: dict[str, Any], key: str) -> int:
        try:
            return int(pending.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(UTC).isoformat()
