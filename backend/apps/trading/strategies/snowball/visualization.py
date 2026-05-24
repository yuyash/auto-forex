"""Snowball strategy visualization adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.trading.strategies.snowball.cycle_state import SnowballStrategyState

__all__ = ["SNOWBALL_VISUALIZATION", "SnowballVisualizationBuilder"]


@dataclass(frozen=True, slots=True)
class SnowballVisualizationBuilder:
    """Build strategy visualization payloads from Snowball runtime state."""

    def cycle_grid_state_map(
        self,
        *,
        strategy_state: dict[str, Any] | None,
    ) -> dict[str, dict[str, Any]]:
        """Return cycle_id -> grid state mappings for Snowball cycles."""
        state = self._parse_state(strategy_state)
        if state is None:
            return {}

        result: dict[str, dict[str, Any]] = {}

        for cycle in state.cycles:
            grid_state = self._serialize_cycle_grid(cycle)
            cycle_keys = {
                str(key)
                for key in (cycle.trade_cycle_id, cycle.cycle_id)
                if key is not None and str(key) != ""
            }
            for cycle_key in cycle_keys:
                result[cycle_key] = grid_state

        return result

    def cycle_status_map(
        self,
        *,
        strategy_state: dict[str, Any] | None,
    ) -> dict[str, str]:
        """Return trade_cycle_id -> status mappings for Snowball cycles."""
        state = self._parse_state(strategy_state)
        if state is None:
            return {}

        result: dict[str, str] = {}
        for cycle in state.cycles:
            if cycle.trade_cycle_id:
                result[str(cycle.trade_cycle_id)] = str(cycle.status.value)
        return result

    def _parse_state(self, strategy_state: dict[str, Any] | None) -> SnowballStrategyState | None:
        if not isinstance(strategy_state, dict):
            return None

        try:
            return SnowballStrategyState.from_dict(strategy_state)
        except (KeyError, TypeError, ValueError):
            return None

    def _serialize_cycle_grid(self, cycle: Any) -> dict[str, Any]:
        layers: list[dict[str, Any]] = []
        counts = {
            "filled": 0,
            "stopped": 0,
            "rebuilt": 0,
            "empty": 0,
        }
        max_slot_index = 0

        for layer in cycle.grid.layers:
            slots: list[dict[str, Any]] = []
            for slot in layer.slots:
                state, position_id = self._resolve_slot_state(slot)
                counts[state] += 1
                max_slot_index = max(max_slot_index, slot.index)
                slots.append(
                    {
                        "slot": slot.index,
                        "state": state,
                        "position_id": position_id,
                        "build_count": slot.build_count,
                    }
                )

            layers.append(
                {
                    "layer": layer.layer_number,
                    "slots": slots,
                }
            )

        return {
            "layers": layers,
            "summary": {
                **counts,
                "layer_count": len(layers),
                "slot_count_per_layer": max_slot_index + 1 if layers else 0,
            },
        }

    def _resolve_slot_state(self, slot: Any) -> tuple[str, str | None]:
        if slot.entry is not None:
            return (
                ("rebuilt", slot.entry.position_id)
                if slot.entry.is_rebuild
                else (
                    "filled",
                    slot.entry.position_id,
                )
            )

        if slot.pending_rebuild is not None:
            return "stopped", slot.pending_rebuild.position_id

        return "empty", None


SNOWBALL_VISUALIZATION = SnowballVisualizationBuilder()
