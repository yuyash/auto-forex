from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from autoforex.core import CurrencyPair, Money, Tick

from autoforex.snowball.composition import SnowballServiceContainer
from autoforex.snowball.config import ProtectionConfig, SnowballConfig
from autoforex.snowball.engine import SnowballEngine
from autoforex.snowball.models.state import SnowballState
from autoforex.snowball.services.stages.tick import SnowballTickContext


@dataclass(slots=True)
class RecordingStage:
    name: str
    calls: list[str]
    halt: bool = False

    def process(self, context: SnowballTickContext) -> None:
        self.calls.append(self.name)
        context.halted = self.halt


def tick() -> Tick:
    return Tick(
        instrument=CurrencyPair.of("USD_JPY"),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        bid=Money.of("150.00", "JPY"),
        ask=Money.of("150.02", "JPY"),
    )


class TestSnowballServiceContainer:
    def test_wires_cycle_stages_in_policy_order(self) -> None:
        container = SnowballServiceContainer(SnowballConfig())

        assert [type(stage).__name__ for stage in container.cycle_processor.stages] == [
            "RebuildCycleStage",
            "CounterTakeProfitCycleStage",
            "CycleTakeProfitStage",
            "StopLossCycleStage",
            "RebuildCycleStage",
            "CounterAddCycleStage",
        ]

    def test_wires_tick_stages_in_pipeline_order(self) -> None:
        container = SnowballServiceContainer(SnowballConfig())

        assert [type(stage).__name__ for stage in container.tick_stages] == [
            "EmergencyStage",
            "InitialCycleStage",
            "ProcessCyclesStage",
            "ReseedCycleStage",
            "FinalizeTickStage",
        ]
        assert container.requires_accounting is True

    def test_omits_disabled_protection_stages(self) -> None:
        container = SnowballServiceContainer(
            SnowballConfig(
                protection=ProtectionConfig(
                    emergency_enabled=False,
                    shrink_enabled=False,
                )
            )
        )

        assert [type(stage).__name__ for stage in container.tick_stages] == [
            "InitialCycleStage",
            "ProcessCyclesStage",
            "ReseedCycleStage",
            "FinalizeTickStage",
        ]
        assert container.requires_accounting is False

    def test_keeps_shrink_before_cycle_processing_when_enabled(self) -> None:
        container = SnowballServiceContainer(
            SnowballConfig(
                protection=ProtectionConfig(
                    emergency_enabled=False,
                    shrink_enabled=True,
                )
            )
        )

        assert [type(stage).__name__ for stage in container.tick_stages] == [
            "ShrinkStage",
            "InitialCycleStage",
            "ProcessCyclesStage",
            "ReseedCycleStage",
            "FinalizeTickStage",
        ]
        assert container.requires_accounting is True


class TestSnowballEnginePipeline:
    def test_stops_when_a_stage_halts_the_context(self) -> None:
        calls: list[str] = []
        engine = SnowballEngine(SnowballConfig())
        engine.services.tick_stages = (
            RecordingStage("first", calls, halt=True),
            RecordingStage("second", calls),
        )

        result = engine.process_tick(tick=tick(), state=SnowballState.new())

        assert calls == ["first"]
        assert result.events == ()
        assert result.state.live_units_by_direction() == (Decimal("0"), Decimal("0"))
