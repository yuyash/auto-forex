"""Tests for strategy-agnostic runtime metrics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from apps.trading.services.runtime_metrics import RuntimeMetricsTracker


def _position(
    *,
    direction: str,
    units: int,
    entry_price: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        direction=direction,
        units=units,
        entry_price=Decimal(entry_price),
        is_open=True,
    )


class TestRuntimeMetricsTracker:
    """Tests for common runtime metric generation."""

    def test_build_metrics_includes_margin_ratio_from_open_positions(self):
        tracker = RuntimeMetricsTracker(
            instrument="USD_JPY",
            pip_size=Decimal("0.01"),
            account_currency="JPY",
            margin_rate=Decimal("0.04"),
            atr_period=14,
        )
        tracker.sync_open_positions(
            [
                _position(direction="long", units=1000, entry_price="150.00"),
                _position(direction="short", units=-500, entry_price="150.20"),
            ]
        )

        metrics = tracker.build_metrics(
            timestamp=datetime(2026, 3, 22, 10, 0, tzinfo=UTC),
            bid=Decimal("150.10"),
            ask=Decimal("150.12"),
            mid=Decimal("150.11"),
            current_balance=Decimal("100000"),
        )

        assert Decimal(metrics["margin_ratio"]) > Decimal("0")
        assert Decimal(metrics["margin_ratio"]) < Decimal("1")
        assert metrics["current_balance_money"] == {
            "amount": "100000",
            "currency": "JPY",
        }
        assert metrics["total_pnl_money"]["currency"] == "JPY"
        assert metrics["total_pnl_quote_money"]["currency"] == "JPY"
        assert metrics["mid_price"] == "150.11"

    def test_build_metrics_includes_execution_tick_rate_when_elapsed_is_positive(self):
        tracker = RuntimeMetricsTracker(
            instrument="USD_JPY",
            pip_size=Decimal("0.01"),
            account_currency="JPY",
            margin_rate=Decimal("0.04"),
            atr_period=14,
        )

        metrics = tracker.build_metrics(
            timestamp=datetime(2026, 3, 22, 10, 0, tzinfo=UTC),
            bid=Decimal("150.10"),
            ask=Decimal("150.12"),
            mid=Decimal("150.11"),
            current_balance=Decimal("100000"),
            ticks_processed=250,
            execution_elapsed_seconds=Decimal("2.5"),
        )

        assert metrics["execution_elapsed_seconds"] == "2.500000"
        assert Decimal(metrics["ticks_per_second"]) == Decimal("100.000000")

    def test_build_metrics_includes_oanda_order_response_milliseconds(self):
        tracker = RuntimeMetricsTracker(
            instrument="USD_JPY",
            pip_size=Decimal("0.01"),
            account_currency="JPY",
            margin_rate=Decimal("0.04"),
            atr_period=14,
        )
        tracker.record_oanda_order_response(Decimal("0.120"))
        tracker.record_oanda_order_response(Decimal("0.240"))

        metrics = tracker.build_metrics(
            timestamp=datetime(2026, 3, 22, 10, 0, tzinfo=UTC),
            bid=Decimal("150.10"),
            ask=Decimal("150.12"),
            mid=Decimal("150.11"),
            current_balance=Decimal("100000"),
        )

        assert metrics["oanda_order_response_ms"] == "240.000"
        assert metrics["oanda_order_response_avg_ms"] == "180.000"
        assert metrics["oanda_order_response_max_ms"] == "240.000"
        assert metrics["oanda_order_response_count"] == "2"

    def test_build_metrics_includes_current_atr_without_strategy_specific_metrics(self):
        tracker = RuntimeMetricsTracker(
            instrument="USD_JPY",
            pip_size=Decimal("0.01"),
            account_currency="JPY",
            margin_rate=Decimal("0.04"),
            atr_period=2,
            atr_baseline_period=3,
            atr_periods={
                "snowball_net_adaptive_interval": 2,
                "snowball_net_volatility_guard": 3,
            },
            atr_baseline_periods={
                "snowball_net_adaptive_interval": 3,
                "snowball_net_volatility_guard": 4,
            },
            volatility_lock_multiplier=Decimal("2"),
        )

        start = datetime(2026, 3, 22, 10, 0, tzinfo=UTC)
        prices = ["150.00", "150.20", "150.05", "150.35"]
        for index, price in enumerate(prices):
            metrics = tracker.build_metrics(
                timestamp=start + timedelta(minutes=index),
                bid=Decimal(price) - Decimal("0.01"),
                ask=Decimal(price) + Decimal("0.01"),
                mid=Decimal(price),
                current_balance=Decimal("100000"),
            )

        assert Decimal(metrics["current_atr"]) > Decimal("0")
        assert Decimal(metrics["baseline_atr"]) > Decimal("0")
        assert Decimal(metrics["volatility_threshold"]) > Decimal("0")
        assert Decimal(metrics["snowball_net_adaptive_interval_current_atr"]) > Decimal("0")
        assert Decimal(metrics["snowball_net_adaptive_interval_baseline_atr"]) > Decimal("0")
        assert Decimal(metrics["snowball_net_volatility_guard_current_atr"]) > Decimal("0")
        assert Decimal(metrics["snowball_net_volatility_guard_baseline_atr"]) > Decimal("0")
        assert (
            metrics["snowball_net_adaptive_interval_current_atr"]
            != metrics["snowball_net_volatility_guard_current_atr"]
        )

    def test_build_metrics_uses_executable_prices_for_unrealized_pnl(self):
        tracker = RuntimeMetricsTracker(
            instrument="USD_JPY",
            pip_size=Decimal("0.01"),
            account_currency="JPY",
            margin_rate=Decimal("0.04"),
            atr_period=14,
        )
        tracker.sync_open_positions(
            [
                _position(direction="long", units=1000, entry_price="158.681"),
                _position(direction="short", units=-1000, entry_price="158.682"),
            ]
        )

        metrics = tracker.build_metrics(
            timestamp=datetime(2026, 4, 14, 21, 22, tzinfo=UTC),
            bid=Decimal("158.802"),
            ask=Decimal("158.872"),
            mid=Decimal("158.837"),
            current_balance=Decimal("2999809.1963"),
        )

        assert Decimal(metrics["realized_pnl"]) == Decimal("0")
        assert Decimal(metrics["realized_pnl_quote"]) == Decimal("0")
        assert Decimal(metrics["unrealized_pnl"]) == Decimal("-69.000")
        assert Decimal(metrics["total_pnl"]) == Decimal("-69.000")
        assert metrics["unrealized_pnl_money"] == {
            "amount": "-69",
            "currency": "JPY",
        }
