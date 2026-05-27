"""Tests for strategy snapshot projectors."""

from datetime import UTC, datetime
from decimal import Decimal

from apps.trading.enums import Direction
from apps.trading.services.strategy_snapshot import build_strategy_snapshot
from apps.trading.strategies.snowball.cycle_state import SnowballCycle, SnowballStrategyState
from apps.trading.strategies.snowball.entries import Entry
from apps.trading.strategies.snowball.enums import CycleStatus
from apps.trading.strategies.snowball.grid_models import Layer, PositionGrid
from apps.trading.strategies.snowball.tick_phases import ARCHIVED_COMPLETED_CYCLES_KEY
from apps.trading.strategies.snowball_net.state import SnowballNetState


def test_snowball_snapshot_omits_internal_metric_cards() -> None:
    state = SnowballStrategyState(
        initialised=True,
        account_balance=Decimal("10000"),
        account_nav=Decimal("10001"),
        last_mid=Decimal("157.123"),
        metrics={"margin_ratio": "0"},
    )

    snapshot = build_strategy_snapshot("snowball", state.to_dict())

    card_ids = {card["id"] for card in snapshot["cards"]}

    assert "last_mid" not in card_ids
    assert "margin_ratio" not in card_ids
    assert snapshot["state"]["last_mid"] == "157.123"
    assert snapshot["state"]["margin_ratio"] == "0"


def test_snowball_snapshot_includes_current_base_units_metric() -> None:
    state = SnowballStrategyState(
        initialised=True,
        account_balance=Decimal("1000000"),
        account_nav=Decimal("1000000"),
        metrics={
            "current_base_units": "1200",
            "snowball_current_base_units": "1200",
        },
    )

    snapshot = build_strategy_snapshot("snowball", state.to_dict())
    cards = {card["id"]: card["value"] for card in snapshot["cards"]}

    assert cards["current_base_units"] == "1200"


def test_snowball_snapshot_includes_warmup_status_metric() -> None:
    state = SnowballStrategyState(
        initialised=True,
        account_balance=Decimal("1000000"),
        account_nav=Decimal("1000000"),
        metrics={"warmup_status": "warmup"},
    )

    snapshot = build_strategy_snapshot("snowball", state.to_dict())
    cards = {card["id"]: card["value"] for card in snapshot["cards"]}

    assert cards["warmup_status"] == "warmup"


def test_snowball_snapshot_uses_completed_warmup_state_over_stale_metric() -> None:
    state = SnowballStrategyState(
        initialised=True,
        account_balance=Decimal("1000000"),
        account_nav=Decimal("1000000"),
        metrics={"warmup_status": "warmup"},
        warmup_completed_at="2025-01-14T15:00:00+00:00",
        warmup_phase="normal",
    )

    snapshot = build_strategy_snapshot("snowball", state.to_dict())
    cards = {card["id"]: card["value"] for card in snapshot["cards"]}

    assert cards["warmup_status"] == "normal"


def test_snowball_snapshot_groups_open_entry_counts_and_units() -> None:
    opened_at = datetime(2026, 1, 1, tzinfo=UTC)
    layer = Layer.create(layer_number=1, r_max=1, base_units=1000)
    layer.slot_at(0).fill(
        Entry(
            entry_id=1,
            step=0,
            direction=Direction.LONG,
            entry_price=Decimal("157"),
            close_price=Decimal("158"),
            units=1000,
            opened_at=opened_at,
            role="initial",
            layer_number=1,
        )
    )
    layer.slot_at(1).fill(
        Entry(
            entry_id=2,
            step=1,
            direction=Direction.SHORT,
            entry_price=Decimal("156"),
            close_price=Decimal("155"),
            units=2000,
            opened_at=opened_at,
            role="counter",
            layer_number=1,
            retracement_count=1,
        )
    )
    state = SnowballStrategyState(
        initialised=True,
        cycles=[
            SnowballCycle(
                cycle_id=1,
                direction=Direction.LONG,
                grid=PositionGrid(layers=[layer]),
            )
        ],
        account_balance=Decimal("10000"),
        account_nav=Decimal("10001"),
    )

    snapshot = build_strategy_snapshot("snowball", state.to_dict())
    cards = {card["id"]: card["value"] for card in snapshot["cards"]}
    card_ids = list(cards)

    assert cards["open_entries"] == 2
    assert cards["open_long_units"] == 1000
    assert cards["open_short_units"] == 2000
    assert card_ids.index("open_entries") < card_ids.index("open_long_units")
    assert card_ids.index("open_long_units") < card_ids.index("open_short_units")


def test_snowball_snapshot_counts_archived_completed_cycles() -> None:
    state = SnowballStrategyState(
        initialised=True,
        cycles=[
            SnowballCycle(
                cycle_id=1,
                direction=Direction.LONG,
                status=CycleStatus.COMPLETED,
                trade_cycle_id="trade-cycle-1",
            ),
            SnowballCycle(cycle_id=2, direction=Direction.SHORT),
        ],
    ).to_dict()
    state[ARCHIVED_COMPLETED_CYCLES_KEY] = 7

    snapshot = build_strategy_snapshot("snowball", state)
    cards = {card["id"]: card["value"] for card in snapshot["cards"]}

    assert cards["active_cycles"] == 1
    assert cards["completed_cycles"] == 8


def test_snowball_net_snapshot_includes_risk_extreme_cards() -> None:
    state = SnowballNetState(
        initialised=True,
        direction="long",
        net_units=2000,
        average_price=Decimal("150.00"),
        max_unrealized_loss=Decimal("123.45"),
        max_net_units_seen=4000,
        max_margin_ratio_pct=Decimal("72.5"),
        max_consecutive_add_count=3,
        max_trend_loss=Decimal("234.56"),
        metrics={
            "snowball_net_current_price": "149.90",
            "snowball_net_pips_from_average": "-10",
            "snowball_net_margin_ratio_pct": "40",
        },
    )

    snapshot = build_strategy_snapshot("snowball_net", state.to_dict())
    cards = {card["id"]: card["value"] for card in snapshot["cards"]}

    assert cards["max_unrealized_loss"] == "123.45"
    assert cards["max_net_units_seen"] == 4000
    assert cards["max_margin_ratio_pct"] == "72.5"
    assert cards["max_consecutive_add_count"] == 3
    assert cards["max_trend_loss"] == "234.56"
