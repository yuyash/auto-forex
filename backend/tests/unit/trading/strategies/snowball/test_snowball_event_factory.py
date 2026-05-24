"""Tests for Snowball strategy event construction."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from apps.trading.dataclasses.tick import Tick
from apps.trading.enums import Direction
from apps.trading.strategies.snowball.entries import Entry
from apps.trading.strategies.snowball.events import SNOWBALL_EVENTS


def _tick(*, bid: str, ask: str) -> Tick:
    return Tick.create(
        instrument="USD_JPY",
        timestamp=datetime(2024, 4, 29, tzinfo=UTC),
        bid=Decimal(bid),
        ask=Decimal(ask),
    )


def test_take_profit_close_uses_trigger_tick_price_when_overshot():
    entry = Entry(
        entry_id=1,
        step=1,
        direction=Direction.SHORT,
        entry_price=Decimal("160.000"),
        close_price=Decimal("159.600"),
        units=1000,
        opened_at=datetime(2024, 4, 29, tzinfo=UTC),
        role="initial",
    )

    event = SNOWBALL_EVENTS.entry_close_event(
        entry,
        _tick(bid="155.000", ask="155.010"),
        instrument="USD_JPY",
        pip_size=Decimal("0.01"),
        account_currency="JPY",
        close_reason="tp",
        actual_tp_pips=Decimal("499.0"),
    )

    assert event.exit_price == Decimal("155.010")
    assert event.pnl == Decimal("4990.000")
    assert event.pips == Decimal("499.0")
    assert event.actual_tp_pips == Decimal("499.0")


def test_stop_loss_close_uses_trigger_tick_price_when_overshot():
    entry = Entry(
        entry_id=1,
        step=1,
        direction=Direction.SHORT,
        entry_price=Decimal("160.000"),
        close_price=Decimal("159.600"),
        units=1000,
        opened_at=datetime(2024, 4, 29, tzinfo=UTC),
        role="initial",
        stop_loss_price=Decimal("160.150"),
    )

    event = SNOWBALL_EVENTS.entry_close_event(
        entry,
        _tick(bid="162.000", ask="162.010"),
        instrument="USD_JPY",
        pip_size=Decimal("0.01"),
        account_currency="JPY",
        close_reason="stop_loss",
    )

    assert event.exit_price == Decimal("162.010")
    assert event.pnl == Decimal("-2010.000")
    assert event.pips == Decimal("201.0")
