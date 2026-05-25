"""Cycle and runtime state models for Snowball strategy."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from apps.trading.enums import Direction
from apps.trading.strategies.snowball.entries import Entry
from apps.trading.strategies.snowball.enums import CycleStatus, ProtectionLevel
from apps.trading.strategies.snowball.grid_models import Layer, PositionGrid
from apps.trading.strategies.snowball.state_parsing import SNOWBALL_STATE_PARSER

# ---------------------------------------------------------------------------
# Cycle
# ---------------------------------------------------------------------------


@dataclass
class SnowballCycle:
    """A single trading cycle: from first entry through to close.

    All positions live in ``grid``.  The cycle head is determined
    dynamically via ``grid.head_entry()``.
    """

    cycle_id: int
    direction: Direction
    grid: PositionGrid = field(default_factory=PositionGrid)
    hedge_entries: list[Entry] = field(default_factory=list)
    counter_close_count: int = 0
    status: CycleStatus = CycleStatus.ACTIVE
    trade_cycle_id: str | None = None
    is_initial_position_seed: bool = False

    # Realised P/L accumulated over every close that happened within this
    # cycle.  Used for end-of-cycle sanity logging (a completed cycle is
    # expected to finish non-negative).  Denominated in account currency.
    realized_pnl: Decimal = field(default_factory=lambda: Decimal("0"))
    stop_loss_count: int = 0

    # -- Status convenience --

    @property
    def completed(self) -> bool:
        return self.status == CycleStatus.COMPLETED

    @completed.setter
    def completed(self, value: bool) -> None:
        self.status = CycleStatus.COMPLETED if value else CycleStatus.ACTIVE

    @property
    def is_active(self) -> bool:
        return self.status == CycleStatus.ACTIVE

    @property
    def is_pending(self) -> bool:
        return self.status == CycleStatus.PENDING

    @property
    def is_fully_pending(self) -> bool:
        """True if the cycle is PENDING and every slot is awaiting rebuild.

        Empty or unused slots are not considered pending.
        """
        return self.is_pending and self.grid.is_fully_pending(f_max=0)

    # -- Convenience --

    @property
    def current_layer(self) -> Layer | None:
        return self.grid.current_layer

    @property
    def layer_count(self) -> int:
        return self.grid.layer_count

    @property
    def is_long(self) -> bool:
        return self.direction == Direction.LONG

    @property
    def is_short(self) -> bool:
        return self.direction == Direction.SHORT

    @property
    def initial_entry(self) -> Entry | None:
        """Dynamic cycle head — the oldest surviving position."""
        return self.grid.head_entry()

    def effective_head(self) -> tuple[Decimal | None, int | None]:
        """Return (entry_price, entry_id) for the cycle head.

        Falls back to the R0 pending-rebuild snapshot when no live entry
        exists, so callers can still compute adverse distance and loss
        checks even after all positions have been stop-loss closed.
        """
        head = self.initial_entry
        if head is not None:
            return head.entry_price, head.entry_id
        layer = self.current_layer
        if layer is None:
            return None, None
        r0 = layer.slot_at(0)
        if r0 is not None and r0.pending_rebuild is not None:
            return r0.pending_rebuild.entry_price, r0.pending_rebuild.root_entry_id
        return None, None

    def add_layer(self, layer: Layer) -> None:
        self.grid.add_layer(layer)

    def find_layer(self, layer_number: int) -> Layer | None:
        return self.grid.find_layer(layer_number)

    def all_entries(self) -> list[Entry]:
        entries = self.grid.all_entries()
        entries.extend(self.hedge_entries)
        return entries

    def iter_entries(self) -> Iterator[Entry]:
        yield from self.grid.iter_entries()
        yield from self.hedge_entries

    def entry_count(self) -> int:
        return self.grid.entry_count() + len(self.hedge_entries)

    def counter_non_hedge(self) -> list[Entry]:
        head = self.grid.head_entry()
        entries: list[Entry] = []
        for e in self.grid.iter_entries():
            if head is not None and e.entry_id == head.entry_id:
                continue
            if not e.is_hedge:
                entries.append(e)
        return entries

    @property
    def counter_entries(self) -> list[Entry]:
        return self.counter_non_hedge()

    @property
    def layers(self) -> list[Layer]:
        return self.grid.layers

    def initial_for_layer(self, layer_number: int) -> Entry | None:
        layer = self.grid.find_layer(layer_number)
        if layer is None:
            return None
        r0 = layer.slot_at(0)
        return r0.entry if r0 is not None else None

    def remove_entry(self, entry_id: int) -> None:
        self.grid.remove_entry(entry_id)
        self.hedge_entries = [e for e in self.hedge_entries if e.entry_id != entry_id]

    # -- Compat properties --

    @property
    def layer_index(self) -> int:
        return self.grid.layer_count - 1 if self.grid.layer_count > 0 else 0

    @property
    def layer_retracement_count(self) -> int:
        layer = self.grid.current_layer
        return layer.entry_count() if layer else 0

    @property
    def layer_initial_entries(self) -> dict[int, Entry]:
        result: dict[int, Entry] = {}
        for layer in self.grid.layers:
            r0 = layer.slot_at(0)
            if r0 is not None and r0.entry is not None:
                result[layer.layer_number] = r0.entry
        return result

    # -- Serialisation --

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "direction": self.direction.value,
            "grid": self.grid.to_dict(),
            "hedge_entries": [e.to_dict() for e in self.hedge_entries],
            "counter_close_count": self.counter_close_count,
            "status": self.status.value,
            "trade_cycle_id": self.trade_cycle_id,
            "is_initial_position_seed": self.is_initial_position_seed,
            "realized_pnl": str(self.realized_pnl),
            "stop_loss_count": self.stop_loss_count,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "SnowballCycle":
        data = SNOWBALL_STATE_PARSER.require_dict(data, field_name="cycle")
        raw_direction = SNOWBALL_STATE_PARSER.require(data, "direction")
        direction = (
            raw_direction
            if isinstance(raw_direction, Direction)
            else Direction(str(raw_direction).strip().lower())
        )

        grid = PositionGrid.from_dict(SNOWBALL_STATE_PARSER.require(data, "grid"))

        raw_status = SNOWBALL_STATE_PARSER.require(data, "status")
        status = CycleStatus(str(raw_status).strip().lower())

        return SnowballCycle(
            cycle_id=SNOWBALL_STATE_PARSER.strict_int(
                SNOWBALL_STATE_PARSER.require(data, "cycle_id"), field_name="cycle_id"
            ),
            direction=direction,
            grid=grid,
            hedge_entries=[
                Entry.from_dict(e)
                for e in SNOWBALL_STATE_PARSER.require_list(
                    SNOWBALL_STATE_PARSER.require(data, "hedge_entries"), field_name="hedge_entries"
                )
            ],
            counter_close_count=SNOWBALL_STATE_PARSER.strict_int(
                SNOWBALL_STATE_PARSER.require(data, "counter_close_count"),
                field_name="counter_close_count",
            ),
            status=status,
            trade_cycle_id=SNOWBALL_STATE_PARSER.optional_str(data, "trade_cycle_id"),
            is_initial_position_seed=data.get("is_initial_position_seed") is True,
            realized_pnl=SNOWBALL_STATE_PARSER.strict_decimal(
                SNOWBALL_STATE_PARSER.require(data, "realized_pnl"), field_name="realized_pnl"
            ),
            stop_loss_count=SNOWBALL_STATE_PARSER.optional_int(data, "stop_loss_count") or 0,
        )


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


@dataclass
class SnowballStrategyState:
    """Mutable runtime state for Snowball strategy."""

    protection_level: ProtectionLevel = ProtectionLevel.NORMAL
    initialised: bool = False
    cycles: list[SnowballCycle] = field(default_factory=list)
    next_entry_id: int = 1

    # Price tracking
    last_bid: Decimal | None = None
    last_ask: Decimal | None = None
    last_mid: Decimal | None = None
    account_balance: Decimal = Decimal("0")
    account_nav: Decimal = Decimal("0")

    metrics: dict[str, str | int | float] = field(default_factory=dict)
    _deferred_metric_updates: dict[str, str | int | float] = field(
        default_factory=dict,
        repr=False,
    )
    _entry_count_cache: int | None = field(default=None, init=False, repr=False)
    _entry_units_cache: tuple[int, int] | None = field(default=None, init=False, repr=False)

    # Warmup / cold-start runtime state.  These fields are intentionally
    # persisted with the strategy state so backtests, live trading, and resume
    # paths all make the same transition decisions.
    warmup_started_at: str | None = None
    warmup_completed_at: str | None = None
    warmup_tick_count: int = 0
    warmup_tp_closes: int = 0
    warmup_phase: str = "normal"
    warmup_last_log_state: str = ""
    warmup_mid_history: list[str] = field(default_factory=list)
    volatility_guard_cooldown_until: str | None = None

    def allocate_id(self) -> int:
        self.invalidate_entry_cache()
        eid = self.next_entry_id
        self.next_entry_id += 1
        return eid

    def active_cycles(self) -> list[SnowballCycle]:
        return [c for c in self.cycles if not c.completed]

    def iter_active_cycles(self) -> Iterator[SnowballCycle]:
        for cycle in self.cycles:
            if not cycle.completed:
                yield cycle

    def tradable_cycles(self) -> list[SnowballCycle]:
        """Return only cycles that are actively trading (not pending or completed)."""
        return [c for c in self.cycles if c.is_active]

    def all_entries(self) -> list[Entry]:
        entries: list[Entry] = []
        for c in self.active_cycles():
            entries.extend(c.all_entries())
        return entries

    def iter_entries(self) -> Iterator[Entry]:
        for cycle in self.iter_active_cycles():
            yield from cycle.iter_entries()

    def entry_count(self) -> int:
        if self._entry_count_cache is None:
            self._entry_count_cache = sum(
                cycle.entry_count() for cycle in self.iter_active_cycles()
            )
        return self._entry_count_cache

    def invalidate_entry_cache(self) -> None:
        self._entry_count_cache = None
        self._entry_units_cache = None

    def entry_units_by_direction(self) -> tuple[int, int]:
        if self._entry_units_cache is not None:
            return self._entry_units_cache
        long_units = 0
        short_units = 0
        for entry in self.iter_entries():
            if entry.is_long:
                long_units += abs(entry.units)
            elif entry.is_short:
                short_units += abs(entry.units)
        self._entry_units_cache = (long_units, short_units)
        return self._entry_units_cache

    def set_entry_units_cache(self, *, long_units: int, short_units: int) -> None:
        self._entry_units_cache = (long_units, short_units)

    def set_metric(
        self,
        key: str,
        value: str | int | float | Decimal,
        *,
        defer: bool = False,
    ) -> None:
        metric_value = str(value)
        if defer:
            self._deferred_metric_updates[key] = metric_value
            return
        self.metrics[key] = metric_value
        self._deferred_metric_updates.pop(key, None)

    def flush_deferred_metrics(self) -> None:
        if not self._deferred_metric_updates:
            return
        self.metrics.update(self._deferred_metric_updates)
        self._deferred_metric_updates.clear()

    def materialized_metrics(self) -> dict[str, str | int | float]:
        if not self._deferred_metric_updates:
            return dict(self.metrics)
        metrics = dict(self.metrics)
        metrics.update(self._deferred_metric_updates)
        return metrics

    def find_cycle(self, cycle_id: int) -> SnowballCycle | None:
        for c in self.cycles:
            if c.cycle_id == cycle_id:
                return c
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "protection_level": self.protection_level.value,
            "initialised": self.initialised,
            "cycles": [c.to_dict() for c in self.cycles],
            "next_entry_id": self.next_entry_id,
            "last_bid": str(self.last_bid) if self.last_bid is not None else None,
            "last_ask": str(self.last_ask) if self.last_ask is not None else None,
            "last_mid": str(self.last_mid) if self.last_mid is not None else None,
            "account_balance": str(self.account_balance),
            "account_nav": str(self.account_nav),
            "metrics": self.materialized_metrics(),
            "warmup_started_at": self.warmup_started_at,
            "warmup_completed_at": self.warmup_completed_at,
            "warmup_tick_count": self.warmup_tick_count,
            "warmup_tp_closes": self.warmup_tp_closes,
            "warmup_phase": self.warmup_phase,
            "warmup_last_log_state": self.warmup_last_log_state,
            "warmup_mid_history": list(self.warmup_mid_history),
            "volatility_guard_cooldown_until": self.volatility_guard_cooldown_until,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "SnowballStrategyState":
        data = SNOWBALL_STATE_PARSER.require_dict(data, field_name="strategy_state")
        raw_cycles = SNOWBALL_STATE_PARSER.require_list(
            SNOWBALL_STATE_PARSER.require(data, "cycles"), field_name="cycles"
        )
        cycles = [SnowballCycle.from_dict(c) for c in raw_cycles]
        raw_metrics = SNOWBALL_STATE_PARSER.require(data, "metrics")
        if not isinstance(raw_metrics, dict):
            raise ValueError("Snowball state field metrics must be an object")
        raw_warmup_mid_history = data.get("warmup_mid_history")
        warmup_mid_history = (
            [str(value) for value in raw_warmup_mid_history]
            if isinstance(raw_warmup_mid_history, list)
            else []
        )

        return SnowballStrategyState(
            protection_level=SnowballStrategyState._parse_protection_level(
                SNOWBALL_STATE_PARSER.require(data, "protection_level")
            ),
            initialised=SNOWBALL_STATE_PARSER.strict_bool(
                SNOWBALL_STATE_PARSER.require(data, "initialised"), field_name="initialised"
            ),
            cycles=cycles,
            next_entry_id=max(
                1,
                SNOWBALL_STATE_PARSER.strict_int(
                    SNOWBALL_STATE_PARSER.require(data, "next_entry_id"), field_name="next_entry_id"
                ),
            ),
            last_bid=SNOWBALL_STATE_PARSER.optional_decimal(data, "last_bid"),
            last_ask=SNOWBALL_STATE_PARSER.optional_decimal(data, "last_ask"),
            last_mid=SNOWBALL_STATE_PARSER.optional_decimal(data, "last_mid"),
            account_balance=SNOWBALL_STATE_PARSER.strict_decimal(
                SNOWBALL_STATE_PARSER.require(data, "account_balance"),
                field_name="account_balance",
            ),
            account_nav=SNOWBALL_STATE_PARSER.strict_decimal(
                SNOWBALL_STATE_PARSER.require(data, "account_nav"), field_name="account_nav"
            ),
            metrics=dict(raw_metrics),
            warmup_started_at=SNOWBALL_STATE_PARSER.optional_str(data, "warmup_started_at"),
            warmup_completed_at=SNOWBALL_STATE_PARSER.optional_str(data, "warmup_completed_at"),
            warmup_tick_count=SNOWBALL_STATE_PARSER.optional_int(data, "warmup_tick_count") or 0,
            warmup_tp_closes=SNOWBALL_STATE_PARSER.optional_int(data, "warmup_tp_closes") or 0,
            warmup_phase=SNOWBALL_STATE_PARSER.optional_str(data, "warmup_phase") or "normal",
            warmup_last_log_state=SNOWBALL_STATE_PARSER.optional_str(data, "warmup_last_log_state")
            or "",
            warmup_mid_history=warmup_mid_history,
            volatility_guard_cooldown_until=SNOWBALL_STATE_PARSER.optional_str(
                data, "volatility_guard_cooldown_until"
            ),
        )

    @classmethod
    def from_strategy_state(cls, raw: dict[str, Any] | None) -> "SnowballStrategyState":
        if raw is None or raw == {}:
            return cls()
        if not isinstance(raw, dict):
            raise ValueError("Snowball strategy_state must be an object")
        return cls.from_dict(raw)

    @staticmethod
    def _parse_protection_level(value: Any) -> ProtectionLevel:
        if value == "locked":
            return ProtectionLevel.NORMAL
        return ProtectionLevel(value)
