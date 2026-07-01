"""Production-derived Snowball scenario regression tests."""

from __future__ import annotations

import json
import logging
from decimal import Decimal

from django.test import override_settings

from apps.trading.strategies.snowball.cycle_state import SnowballStrategyState
from tests.unit.trading.strategies.snowball.production_scenarios import (
    SnowballProductionScenarioFactory,
)


class TestSnowballProductionScenarios:
    """Exercise production-derived Snowball failure and recovery shapes."""

    def test_short_rebuild_ghost_guard_does_not_stop_task(self):
        scenario = SnowballProductionScenarioFactory().short_rebuild_ghost_guard()

        result = scenario.strategy.on_tick(tick=scenario.tick, state=scenario.state)

        assert result.should_stop is False
        assert result.is_error is False

    def test_grid_violation_continues_without_public_error(self, caplog):
        scenario = SnowballProductionScenarioFactory().ignored_grid_violation()

        with caplog.at_level(
            logging.INFO,
            logger="apps.trading.strategies.snowball.strategy",
        ):
            result = scenario.strategy.on_tick(tick=scenario.tick, state=scenario.state)
            scenario.strategy.on_tick(tick=scenario.tick, state=scenario.state)

        assert result.should_stop is False
        assert result.is_error is False
        assert result.stop_reason == ""
        detected_logs = [
            record
            for record in caplog.records
            if "Grid ordering violation detected; continuing counter adds" in record.getMessage()
        ]
        assert len(detected_logs) == 1
        assert not any(record.levelno >= logging.WARNING for record in caplog.records)

    def test_cross_layer_pending_rebuild_recovers_grid_ordering(self):
        scenario = SnowballProductionScenarioFactory().cross_layer_pending_rebuild()

        scenario.strategy._process_stop_loss_rebuilds(
            scenario.snowball_state,
            scenario.tick,
            scenario.cycle,
        )

        l1 = scenario.cycle.layers[0]
        l2 = scenario.cycle.layers[1]
        expected_l2r0_tp = Decimal("130.644")
        assert l2.slots[0].entry is not None
        assert l2.slots[0].entry.close_price == expected_l2r0_tp
        assert l1.slots[7].pending_rebuild is not None
        assert l1.slots[7].pending_rebuild.close_price == Decimal("130.644")

        scenario.strategy._grid_order_violation = None
        scenario.strategy._validate_grid_ordering(scenario.cycle)
        persisted = SnowballStrategyState.from_strategy_state(scenario.snowball_state.to_dict())
        assert scenario.strategy._grid_order_violation is None
        assert persisted.initialised is True

    @override_settings(SNOWBALL_DECISION_TRACE_ENABLED=True)
    def test_oanda_response_replay_runs_ticks_and_consumes_mocked_responses(self):
        replay = SnowballProductionScenarioFactory().oanda_response_replay()

        result = replay.replay()

        assert [response.status for response in result.consumed_oanda_responses] == [401, 200]
        assert len(result.strategy_results) == 2
        assert all(not item.should_stop for item in result.strategy_results)
        metrics = result.strategy_results[-1].state.strategy_state["metrics"]
        trace = json.loads(metrics["snowball_decision_trace"])
        assert trace["records"]
