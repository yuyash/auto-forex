"""Production-derived Snowball scenario fixtures."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from apps.trading.dataclasses import StrategyResult
from apps.trading.dataclasses.tick import Tick
from apps.trading.enums import Direction
from apps.trading.strategies.snowball.config import SnowballStrategyConfig
from apps.trading.strategies.snowball.cycle_state import SnowballCycle, SnowballStrategyState
from apps.trading.strategies.snowball.entries import Entry, StopLossClosedEntry
from apps.trading.strategies.snowball.grid_models import Layer, Slot
from apps.trading.strategies.snowball.strategy import SnowballStrategy


@dataclass
class SnowballScenarioState:
    """Minimal execution-state shape for Snowball scenario tests."""

    strategy_state: dict[str, Any] = field(default_factory=dict)
    current_balance: Decimal = Decimal("1000000")
    ticks_processed: int = 1


@dataclass(frozen=True, slots=True)
class SnowballOnTickScenario:
    """A production-inspired on_tick scenario."""

    strategy: SnowballStrategy
    state: SnowballScenarioState
    tick: Tick


@dataclass(frozen=True, slots=True)
class SnowballRebuildScenario:
    """A production-inspired stop-loss rebuild scenario."""

    strategy: SnowballStrategy
    snowball_state: SnowballStrategyState
    cycle: SnowballCycle
    tick: Tick


@dataclass(frozen=True, slots=True)
class SnowballReplayOandaResponse:
    """Mocked OANDA response captured beside a production tick."""

    label: str
    status: int
    body: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return a compact replay response payload."""
        return {
            "label": self.label,
            "status": self.status,
            "body": self.body,
        }


@dataclass(frozen=True, slots=True)
class SnowballIncidentReplayStep:
    """One tick plus any mocked broker responses observed around it."""

    tick: Tick
    oanda_responses: tuple[SnowballReplayOandaResponse, ...] = ()


@dataclass(frozen=True, slots=True)
class SnowballIncidentReplayResult:
    """Result of replaying a production incident fixture."""

    strategy_results: tuple[StrategyResult, ...]
    consumed_oanda_responses: tuple[SnowballReplayOandaResponse, ...]


class SnowballMockOandaResponseFeed:
    """Consume mocked OANDA responses while a replay walks through ticks."""

    def __init__(self) -> None:
        self.consumed: list[SnowballReplayOandaResponse] = []

    def consume(self, response: SnowballReplayOandaResponse) -> SnowballReplayOandaResponse:
        """Record and return one mocked OANDA response."""
        self.consumed.append(response)
        return response

    def consumed_statuses(self) -> list[int]:
        """Return consumed response statuses in replay order."""
        return [response.status for response in self.consumed]


@dataclass(frozen=True, slots=True)
class SnowballIncidentReplayFixture:
    """Replay a production tick sequence and its mocked OANDA responses."""

    name: str
    strategy: SnowballStrategy
    state: SnowballScenarioState
    steps: tuple[SnowballIncidentReplayStep, ...]
    response_feed: SnowballMockOandaResponseFeed = field(
        default_factory=SnowballMockOandaResponseFeed
    )

    def replay(self) -> SnowballIncidentReplayResult:
        """Run all fixture ticks and consume mocked OANDA responses in order."""
        results: list[StrategyResult] = []
        for step in self.steps:
            for response in step.oanda_responses:
                self.response_feed.consume(response)
            result = self.strategy.on_tick(tick=step.tick, state=self.state)
            self.state.strategy_state = result.state.strategy_state
            results.append(result)
        return SnowballIncidentReplayResult(
            strategy_results=tuple(results),
            consumed_oanda_responses=tuple(self.response_feed.consumed),
        )


class SnowballProductionScenarioFactory:
    """Build scenarios from observed Snowball failure and recovery shapes."""

    base_time = datetime(2026, 1, 1, tzinfo=UTC)

    def short_rebuild_ghost_guard(self) -> SnowballOnTickScenario:
        """Cycle 20883 shape: rebuilt SHORT ghost blocks unsafe lower-layer add."""
        strategy = self.strategy(
            counter_tp_mode="weighted_avg",
            interval_mode="manual",
            manual_intervals=["30", "30", "25", "20", "16"],
            n_pips_head="30",
            n_pips_tail="14",
            f_max=5,
            r_max=5,
            refill_up_to=3,
            pip_size="0.01",
        )
        snowball_state = SnowballStrategyState(initialised=True, account_nav=Decimal("100000"))
        cycle = SnowballCycle(cycle_id=20883, direction=Direction.SHORT)
        layer1 = Layer.create(1, 5, 9000, 3)
        layer1.slot_at(0).fill(
            self.entry(
                entry_id=20946,
                direction=Direction.SHORT,
                entry_price="142.315",
                close_price="141.929",
                units=9000,
                role="initial",
                layer_number=1,
                retracement_count=0,
                root_entry_id=20883,
                is_rebuild=True,
            )
        )
        layer1.slot_at(1).fill(
            self.entry(
                entry_id=20943,
                direction=Direction.SHORT,
                entry_price="142.687",
                close_price="142.207",
                units=18000,
                role="counter",
                layer_number=1,
                retracement_count=1,
                root_entry_id=20883,
                parent_entry_id=20883,
                is_rebuild=True,
            )
        )
        layer2 = Layer.create(2, 5, 9000, 3)
        layer2.slot_at(0).ever_closed = True
        cycle.add_layer(layer1)
        cycle.add_layer(layer2)
        snowball_state.cycles.append(cycle)
        return SnowballOnTickScenario(
            strategy=strategy,
            state=SnowballScenarioState(strategy_state=snowball_state.to_dict()),
            tick=self.tick(self.base_time + timedelta(minutes=1), "142.616", "142.618"),
        )

    def ignored_grid_violation(self) -> SnowballOnTickScenario:
        """Grid violation must warn internally and continue."""
        strategy = self.strategy(
            counter_tp_mode="fixed",
            counter_tp_pips="25",
        )
        strategy.configure_runtime(account_currency="JPY", hedging_enabled=False)
        snowball_state = SnowballStrategyState(initialised=True, account_nav=Decimal("100000"))
        cycle = SnowballCycle(cycle_id=3, direction=Direction.LONG)
        layer = Layer.create(1, 7, 1000, 3)
        layer.slot_at(0).fill(
            self.entry(
                entry_id=1,
                direction=Direction.LONG,
                entry_price="160.000",
                close_price="160.500",
                units=1000,
                role="initial",
                layer_number=1,
                retracement_count=0,
                root_entry_id=1,
            )
        )
        layer.slot_at(1).fill(
            self.entry(
                entry_id=2,
                direction=Direction.LONG,
                entry_price="160.100",
                close_price="160.400",
                units=2000,
                role="counter",
                layer_number=1,
                retracement_count=1,
                root_entry_id=1,
                parent_entry_id=1,
            )
        )
        cycle.add_layer(layer)
        snowball_state.cycles.append(cycle)
        return SnowballOnTickScenario(
            strategy=strategy,
            state=SnowballScenarioState(strategy_state=snowball_state.to_dict()),
            tick=self.tick(self.base_time + timedelta(minutes=1), "160.10", "160.12"),
        )

    def cross_layer_pending_rebuild(self) -> SnowballRebuildScenario:
        """Pending predecessor TP bounds cross-layer rebuilds so ordering stays intact."""
        strategy = self.strategy(stop_loss_enabled=True)
        l1 = Layer(layer_number=1, slots=[], base_units=1000, refill_up_to=3)
        l2 = Layer(layer_number=2, slots=[], base_units=1000, refill_up_to=3)
        for idx in range(8):
            l1.slots.append(Slot(index=idx))
            l2.slots.append(Slot(index=idx))

        l1.slots[0].entry = self.entry(
            entry_id=1,
            direction=Direction.SHORT,
            entry_price="130.000",
            close_price="129.500",
            units=1000,
            role="initial",
            layer_number=1,
            retracement_count=0,
        )
        l1.slots[7].pending_rebuild = StopLossClosedEntry(
            entry_price=Decimal("131.015"),
            close_price=Decimal("130.644"),
            units=8000,
            direction=Direction.SHORT,
            role="counter",
            layer_number=1,
            retracement_count=7,
            step=8,
            cycle_id=1,
        )
        l2.slots[0].pending_rebuild = StopLossClosedEntry(
            entry_price=Decimal("131.177"),
            close_price=Decimal("130.64392"),
            units=1000,
            direction=Direction.SHORT,
            role="layer_initial",
            layer_number=2,
            retracement_count=0,
            step=1,
            cycle_id=1,
        )
        cycle = SnowballCycle(cycle_id=1, direction=Direction.SHORT)
        cycle.grid.layers.extend([l1, l2])
        return SnowballRebuildScenario(
            strategy=strategy,
            snowball_state=SnowballStrategyState(
                initialised=True,
                account_nav=Decimal("1000000"),
            ),
            cycle=cycle,
            tick=self.tick(self.base_time.replace(hour=9), "131.167", "131.177"),
        )

    def oanda_response_replay(self) -> SnowballIncidentReplayFixture:
        """Fixture that replays ticks beside retry/recovery-shaped OANDA responses."""
        strategy = self.strategy(counter_tp_mode="fixed", counter_tp_pips="25")
        strategy.configure_runtime(account_currency="JPY", hedging_enabled=False)
        state = SnowballScenarioState()
        return SnowballIncidentReplayFixture(
            name="pending-orders-401-recovered",
            strategy=strategy,
            state=state,
            steps=(
                SnowballIncidentReplayStep(
                    tick=self.tick(self.base_time, "150.000", "150.020"),
                    oanda_responses=(
                        SnowballReplayOandaResponse(
                            label="Fetch pending orders",
                            status=401,
                            body={"errorMessage": "temporary unauthorized"},
                        ),
                    ),
                ),
                SnowballIncidentReplayStep(
                    tick=self.tick(self.base_time + timedelta(minutes=1), "149.960", "149.980"),
                    oanda_responses=(
                        SnowballReplayOandaResponse(
                            label="Fetch pending orders",
                            status=200,
                            body={"orders": []},
                        ),
                    ),
                ),
            ),
        )

    def strategy(self, **overrides: Any) -> SnowballStrategy:
        """Build the Snowball strategy used by production scenarios."""
        params: dict[str, Any] = {
            "base_units": 1000,
            "m_pips": "50",
            "trend_lot_size": 1,
            "r_max": 7,
            "f_max": 3,
            "post_r_max_base_factor": "1",
            "n_pips_head": "30",
            "n_pips_tail": "14",
            "n_pips_flat_steps": 2,
            "n_pips_gamma": "1.4",
            "interval_mode": "constant",
            "counter_tp_mode": "fixed",
            "counter_tp_pips": "25",
            "counter_tp_step_amount": "2.5",
            "counter_tp_multiplier": "1.2",
            "round_step_pips": "0.1",
            "shrink_enabled": False,
            "m_th": "70",
            "pip_size": "0.01",
        }
        params.update(overrides)
        return SnowballStrategy(
            "USD_JPY",
            Decimal("0.01"),
            SnowballStrategyConfig.from_dict(params),
        )

    def entry(
        self,
        *,
        entry_id: int,
        direction: Direction,
        entry_price: str,
        close_price: str,
        units: int,
        role: str,
        layer_number: int,
        retracement_count: int,
        root_entry_id: int | None = None,
        parent_entry_id: int | None = None,
        is_rebuild: bool = False,
    ) -> Entry:
        """Build an entry matching production scenario shapes."""
        return Entry(
            entry_id=entry_id,
            step=retracement_count + 1,
            direction=direction,
            entry_price=Decimal(entry_price),
            close_price=Decimal(close_price),
            units=units,
            opened_at=self.base_time,
            role=role,
            layer_number=layer_number,
            retracement_count=retracement_count,
            root_entry_id=root_entry_id,
            parent_entry_id=parent_entry_id,
            is_rebuild=is_rebuild,
        )

    def tick(self, timestamp: datetime, bid: str, ask: str) -> Tick:
        """Build a USD_JPY tick."""
        return Tick.create(
            instrument="USD_JPY",
            timestamp=timestamp,
            bid=Decimal(bid),
            ask=Decimal(ask),
        )
