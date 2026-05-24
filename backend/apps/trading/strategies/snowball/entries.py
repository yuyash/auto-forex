"""Entry models for Snowball strategy."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal

from apps.trading.enums import Direction
from apps.trading.strategies.snowball.state_parsing import SNOWBALL_STATE_PARSER

if TYPE_CHECKING:
    from apps.trading.dataclasses.tick import Tick
    from apps.trading.strategies.snowball.cycle_state import SnowballStrategyState

# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


@dataclass
class Entry:
    """A single position entry within a cycle.

    Every entry lives in a ``Slot`` inside the ``PositionGrid``.  The entry
    knows its own grid coordinates (``layer``, ``index``) and its ``role``
    which is purely descriptive — it does *not* affect close ordering.
    """

    entry_id: int
    step: int
    direction: Direction
    entry_price: Decimal
    close_price: Decimal
    units: int
    opened_at: datetime
    role: Literal["initial", "counter", "hedge", "layer_initial"]
    layer_number: int = 1
    retracement_count: int = 0
    root_entry_id: int | None = None
    parent_entry_id: int | None = None
    position_id: str | None = None
    stop_loss_price: Decimal | None = None
    is_rebuild: bool = False

    # Validation fields
    expected_interval_pips: Decimal | None = None
    actual_interval_pips: Decimal | None = None
    expected_tp_pips: Decimal | None = None
    validation_status: str = ""

    # Lifecycle P/L tracked across the full open → (optional stop-loss →
    # rebuild)+ → close chain of this grid slot.  Carried through rebuilds
    # via ``StopLossClosedEntry``.  Denominated in account currency.
    lifecycle_realized_pnl: Decimal = field(default_factory=lambda: Decimal("0"))
    lifecycle_stop_loss_count: int = 0

    @classmethod
    def open(
        cls,
        *,
        state: "SnowballStrategyState",
        tick: "Tick",
        direction: Direction,
        units: int,
        step: int,
        close_price: Decimal,
        role: Literal["initial", "counter", "hedge", "layer_initial"],
        layer_number: int = 1,
        retracement_count: int = 0,
        root_entry_id: int | None = None,
        parent_entry_id: int | None = None,
    ) -> "Entry":
        eid = state.allocate_id()
        price = tick.ask if direction == Direction.LONG else tick.bid
        if root_entry_id is None and role == "initial":
            root_entry_id = eid
        return cls(
            entry_id=eid,
            step=step,
            direction=direction,
            entry_price=price,
            close_price=close_price,
            units=units,
            opened_at=tick.timestamp,
            role=role,
            layer_number=layer_number,
            retracement_count=retracement_count,
            root_entry_id=root_entry_id,
            parent_entry_id=parent_entry_id,
        )

    # -- Convenience properties --

    @property
    def is_long(self) -> bool:
        return self.direction == Direction.LONG

    @property
    def is_short(self) -> bool:
        return self.direction == Direction.SHORT

    @property
    def is_initial(self) -> bool:
        return self.role == "initial"

    @property
    def is_layer_initial(self) -> bool:
        return self.role == "layer_initial"

    @property
    def is_counter(self) -> bool:
        return self.role == "counter"

    @property
    def is_hedge(self) -> bool:
        return self.role == "hedge"

    def exit_price(self, tick: "Tick") -> Decimal:
        return tick.bid if self.is_long else tick.ask

    def can_close_on_tick(self, tick: "Tick") -> bool:
        """Return True when the tick is strictly after the entry-open tick."""
        return tick.timestamp > self.opened_at

    def unrealised_loss_pips(self, mid_price: Decimal, pip_size: Decimal) -> Decimal:
        """Positive = losing."""
        if self.is_long:
            return (self.entry_price - mid_price) / pip_size
        return (mid_price - self.entry_price) / pip_size

    # -- Grid coordinate --

    @property
    def grid_key(self) -> tuple[int, int]:
        """(layer_number, retracement_count) — used for ordering."""
        return (self.layer_number, self.retracement_count)

    # -- Serialisation --

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "step": self.step,
            "direction": self.direction.value,
            "entry_price": str(self.entry_price),
            "close_price": str(self.close_price),
            "units": self.units,
            "opened_at": self.opened_at.isoformat(),
            "role": self.role,
            "layer_number": self.layer_number,
            "retracement_count": self.retracement_count,
            "root_entry_id": self.root_entry_id,
            "parent_entry_id": self.parent_entry_id,
            "position_id": self.position_id,
            "expected_interval_pips": (
                str(self.expected_interval_pips)
                if self.expected_interval_pips is not None
                else None
            ),
            "actual_interval_pips": (
                str(self.actual_interval_pips) if self.actual_interval_pips is not None else None
            ),
            "expected_tp_pips": (
                str(self.expected_tp_pips) if self.expected_tp_pips is not None else None
            ),
            "validation_status": self.validation_status,
            "stop_loss_price": (
                str(self.stop_loss_price) if self.stop_loss_price is not None else None
            ),
            "is_rebuild": self.is_rebuild,
            "lifecycle_realized_pnl": str(self.lifecycle_realized_pnl),
            "lifecycle_stop_loss_count": self.lifecycle_stop_loss_count,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Entry":
        d = SNOWBALL_STATE_PARSER.require_dict(d, field_name="entry")
        raw_direction = SNOWBALL_STATE_PARSER.require(d, "direction")
        direction = (
            raw_direction
            if isinstance(raw_direction, Direction)
            else Direction(str(raw_direction).strip().lower())
        )
        opened_at = SNOWBALL_STATE_PARSER.parse_datetime(
            SNOWBALL_STATE_PARSER.require(d, "opened_at"), field_name="opened_at"
        )

        return Entry(
            entry_id=SNOWBALL_STATE_PARSER.strict_int(
                SNOWBALL_STATE_PARSER.require(d, "entry_id"), field_name="entry_id"
            ),
            step=SNOWBALL_STATE_PARSER.strict_int(
                SNOWBALL_STATE_PARSER.require(d, "step"), field_name="step"
            ),
            direction=direction,
            entry_price=SNOWBALL_STATE_PARSER.strict_decimal(
                SNOWBALL_STATE_PARSER.require(d, "entry_price"), field_name="entry_price"
            ),
            close_price=SNOWBALL_STATE_PARSER.strict_decimal(
                SNOWBALL_STATE_PARSER.require(d, "close_price"), field_name="close_price"
            ),
            units=SNOWBALL_STATE_PARSER.strict_int(
                SNOWBALL_STATE_PARSER.require(d, "units"), field_name="units"
            ),
            opened_at=opened_at,
            role=SNOWBALL_STATE_PARSER.require(d, "role"),
            layer_number=SNOWBALL_STATE_PARSER.strict_int(
                SNOWBALL_STATE_PARSER.require(d, "layer_number"), field_name="layer_number"
            ),
            retracement_count=SNOWBALL_STATE_PARSER.strict_int(
                SNOWBALL_STATE_PARSER.require(d, "retracement_count"),
                field_name="retracement_count",
            ),
            root_entry_id=SNOWBALL_STATE_PARSER.optional_int(d, "root_entry_id"),
            parent_entry_id=SNOWBALL_STATE_PARSER.optional_int(d, "parent_entry_id"),
            position_id=SNOWBALL_STATE_PARSER.optional_str(d, "position_id"),
            expected_interval_pips=SNOWBALL_STATE_PARSER.optional_decimal(
                d, "expected_interval_pips"
            ),
            actual_interval_pips=SNOWBALL_STATE_PARSER.optional_decimal(d, "actual_interval_pips"),
            expected_tp_pips=SNOWBALL_STATE_PARSER.optional_decimal(d, "expected_tp_pips"),
            validation_status=str(SNOWBALL_STATE_PARSER.require(d, "validation_status")),
            stop_loss_price=SNOWBALL_STATE_PARSER.optional_decimal(d, "stop_loss_price"),
            is_rebuild=SNOWBALL_STATE_PARSER.strict_bool(
                SNOWBALL_STATE_PARSER.require(d, "is_rebuild"), field_name="is_rebuild"
            ),
            lifecycle_realized_pnl=SNOWBALL_STATE_PARSER.strict_decimal(
                SNOWBALL_STATE_PARSER.require(d, "lifecycle_realized_pnl"),
                field_name="lifecycle_realized_pnl",
            ),
            lifecycle_stop_loss_count=SNOWBALL_STATE_PARSER.strict_int(
                SNOWBALL_STATE_PARSER.require(d, "lifecycle_stop_loss_count"),
                field_name="lifecycle_stop_loss_count",
            ),
        )


# ---------------------------------------------------------------------------
# StopLossClosedEntry — tracks positions closed by stop-loss for rebuild
# ---------------------------------------------------------------------------


@dataclass
class StopLossClosedEntry:
    """Snapshot of a position closed by stop-loss, awaiting rebuild.

    The snapshot keeps both the original entry price and the actual
    stop-loss exit price.  Rebuild trigger policy decides which price to use.
    """

    entry_price: Decimal
    close_price: Decimal
    units: int
    direction: Direction
    role: Literal["initial", "counter", "hedge", "layer_initial"]
    layer_number: int
    retracement_count: int
    step: int
    root_entry_id: int | None = None
    parent_entry_id: int | None = None
    cycle_id: int = 0
    position_id: str | None = None
    stop_loss_price: Decimal | None = None
    stop_loss_exit_price: Decimal | None = None
    closed_at: datetime | None = None

    # Running lifecycle P/L for the slot: accumulates every stop-loss
    # loss so the rebuilt entry can continue the chain and the final
    # close can compare net P/L against zero.  Denominated in account
    # currency.
    lifecycle_realized_pnl: Decimal = field(default_factory=lambda: Decimal("0"))
    lifecycle_stop_loss_count: int = 0
    stop_loss_loss_pips: Decimal = field(default_factory=lambda: Decimal("0"))

    def to_dict(self) -> dict[str, Any]:
        result = {
            "entry_price": str(self.entry_price),
            "close_price": str(self.close_price),
            "units": self.units,
            "direction": self.direction.value,
            "role": self.role,
            "layer_number": self.layer_number,
            "retracement_count": self.retracement_count,
            "step": self.step,
            "root_entry_id": self.root_entry_id,
            "parent_entry_id": self.parent_entry_id,
            "cycle_id": self.cycle_id,
            "lifecycle_realized_pnl": str(self.lifecycle_realized_pnl),
            "lifecycle_stop_loss_count": self.lifecycle_stop_loss_count,
            "stop_loss_loss_pips": str(self.stop_loss_loss_pips),
        }
        if self.position_id is not None:
            result["position_id"] = self.position_id
        if self.stop_loss_price is not None:
            result["stop_loss_price"] = str(self.stop_loss_price)
        if self.stop_loss_exit_price is not None:
            result["stop_loss_exit_price"] = str(self.stop_loss_exit_price)
        if self.closed_at is not None:
            result["closed_at"] = self.closed_at.isoformat()
        return result

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "StopLossClosedEntry":
        d = SNOWBALL_STATE_PARSER.require_dict(d, field_name="pending_rebuild")
        raw_dir = SNOWBALL_STATE_PARSER.require(d, "direction")
        direction = (
            raw_dir if isinstance(raw_dir, Direction) else Direction(str(raw_dir).strip().lower())
        )
        return StopLossClosedEntry(
            entry_price=SNOWBALL_STATE_PARSER.strict_decimal(
                SNOWBALL_STATE_PARSER.require(d, "entry_price"), field_name="entry_price"
            ),
            close_price=SNOWBALL_STATE_PARSER.strict_decimal(
                SNOWBALL_STATE_PARSER.require(d, "close_price"), field_name="close_price"
            ),
            units=SNOWBALL_STATE_PARSER.strict_int(
                SNOWBALL_STATE_PARSER.require(d, "units"), field_name="units"
            ),
            direction=direction,
            role=SNOWBALL_STATE_PARSER.require(d, "role"),
            layer_number=SNOWBALL_STATE_PARSER.strict_int(
                SNOWBALL_STATE_PARSER.require(d, "layer_number"), field_name="layer_number"
            ),
            retracement_count=SNOWBALL_STATE_PARSER.strict_int(
                SNOWBALL_STATE_PARSER.require(d, "retracement_count"),
                field_name="retracement_count",
            ),
            step=SNOWBALL_STATE_PARSER.strict_int(
                SNOWBALL_STATE_PARSER.require(d, "step"), field_name="step"
            ),
            root_entry_id=SNOWBALL_STATE_PARSER.optional_int(d, "root_entry_id"),
            parent_entry_id=SNOWBALL_STATE_PARSER.optional_int(d, "parent_entry_id"),
            cycle_id=SNOWBALL_STATE_PARSER.strict_int(
                SNOWBALL_STATE_PARSER.require(d, "cycle_id"), field_name="cycle_id"
            ),
            position_id=SNOWBALL_STATE_PARSER.optional_str(d, "position_id"),
            stop_loss_price=SNOWBALL_STATE_PARSER.optional_decimal(d, "stop_loss_price"),
            stop_loss_exit_price=SNOWBALL_STATE_PARSER.optional_decimal(d, "stop_loss_exit_price"),
            closed_at=(
                SNOWBALL_STATE_PARSER.parse_datetime(d["closed_at"], field_name="closed_at")
                if d.get("closed_at") not in (None, "")
                else None
            ),
            lifecycle_realized_pnl=SNOWBALL_STATE_PARSER.strict_decimal(
                SNOWBALL_STATE_PARSER.require(d, "lifecycle_realized_pnl"),
                field_name="lifecycle_realized_pnl",
            ),
            lifecycle_stop_loss_count=SNOWBALL_STATE_PARSER.strict_int(
                SNOWBALL_STATE_PARSER.require(d, "lifecycle_stop_loss_count"),
                field_name="lifecycle_stop_loss_count",
            ),
            stop_loss_loss_pips=SNOWBALL_STATE_PARSER.optional_decimal(d, "stop_loss_loss_pips")
            or Decimal("0"),
        )
