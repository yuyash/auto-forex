"""Unit tests for strategy grid-state helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from apps.trading.enums import Direction
from apps.trading.services.strategy_cycles import _load_cycle_statuses
from apps.trading.services.strategy_grid_state import build_cycle_grid_state_map
from apps.trading.strategies.snowball.cycle_state import SnowballCycle, SnowballStrategyState
from apps.trading.strategies.snowball.entries import Entry, StopLossClosedEntry
from apps.trading.strategies.snowball.grid_models import Layer, PositionGrid, Slot


def _entry(*, entry_id: int, layer: int, slot: int, is_rebuild: bool = False) -> Entry:
    return Entry(
        entry_id=entry_id,
        step=entry_id,
        direction=Direction.LONG,
        entry_price=Decimal("150.100"),
        close_price=Decimal("150.300"),
        units=1000,
        opened_at=datetime(2026, 4, 11, 12, 0, tzinfo=UTC),
        role="counter" if slot > 0 else "initial",
        layer_number=layer,
        retracement_count=slot,
        root_entry_id=1,
        parent_entry_id=1,
        position_id=f"pos-{entry_id}",
        is_rebuild=is_rebuild,
    )


class TestBuildCycleGridStateMap:
    def test_returns_empty_for_unsupported_strategy(self):
        assert build_cycle_grid_state_map(strategy_type="floor", strategy_state={}) == {}

    def test_returns_empty_for_incomplete_snowball_state(self):
        assert (
            build_cycle_grid_state_map(
                strategy_type="snowball",
                strategy_state={"metrics": {}},
            )
            == {}
        )

    def test_serializes_snowball_slot_states(self):
        layer = Layer(
            layer_number=1,
            slots=[
                Slot(index=0, entry=_entry(entry_id=1, layer=1, slot=0)),
                Slot(index=1, pending_rebuild=_pending_rebuild(layer=1, slot=1)),
                Slot(index=2, entry=_entry(entry_id=2, layer=1, slot=2, is_rebuild=True)),
                Slot(index=3),
            ],
            base_units=1000,
            refill_up_to=2,
        )
        cycle = SnowballCycle(
            cycle_id=11,
            direction=Direction.LONG,
            grid=PositionGrid(layers=[layer]),
            trade_cycle_id="trade-cycle-1",
        )
        state = SnowballStrategyState(cycles=[cycle])

        result = build_cycle_grid_state_map(
            strategy_type="snowball",
            strategy_state=state.to_dict(),
        )

        grid_state = result["trade-cycle-1"]
        assert grid_state["summary"] == {
            "filled": 1,
            "stopped": 1,
            "rebuilt": 1,
            "empty": 1,
            "layer_count": 1,
            "slot_count_per_layer": 4,
        }
        assert grid_state["layers"][0]["layer"] == 1
        assert [slot["state"] for slot in grid_state["layers"][0]["slots"]] == [
            "filled",
            "stopped",
            "rebuilt",
            "empty",
        ]
        assert grid_state["layers"][0]["slots"][0]["position_id"] == "pos-1"
        assert grid_state["layers"][0]["slots"][0]["build_count"] == 1
        assert grid_state["layers"][0]["slots"][1]["position_id"] == "sl-pos-1-1"
        assert grid_state["layers"][0]["slots"][1]["build_count"] == 1


class TestBuildCycleStatusMap:
    def test_returns_empty_for_unsupported_strategy(self):
        assert (
            _load_cycle_statuses(
                strategy_type="unknown",
                strategy_state={"cycles": [{"trade_cycle_id": "cycle-1"}]},
            )
            == {}
        )

    def test_returns_empty_for_incomplete_snowball_state(self):
        assert (
            _load_cycle_statuses(
                strategy_type="snowball",
                strategy_state={"metrics": {}},
            )
            == {}
        )

    def test_serializes_snowball_cycle_statuses(self):
        cycle = SnowballCycle(
            cycle_id=11,
            direction=Direction.LONG,
            trade_cycle_id="trade-cycle-1",
        )
        state = SnowballStrategyState(cycles=[cycle])

        assert _load_cycle_statuses(
            strategy_type="snowball",
            strategy_state=state.to_dict(),
        ) == {"trade-cycle-1": "active"}


def _pending_rebuild(*, layer: int, slot: int) -> StopLossClosedEntry:
    return StopLossClosedEntry(
        entry_price=Decimal("149.900"),
        close_price=Decimal("150.200"),
        units=1000,
        direction=Direction.LONG,
        role="counter",
        layer_number=layer,
        retracement_count=slot,
        step=slot + 1,
        root_entry_id=1,
        parent_entry_id=1,
        cycle_id=11,
        position_id=f"sl-pos-{layer}-{slot}",
    )
