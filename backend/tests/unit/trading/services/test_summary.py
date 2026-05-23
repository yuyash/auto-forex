"""Unit tests for task summary PnL source selection."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.trading.enums import Direction, TaskStatus, TaskType
from apps.trading.models import (
    BacktestTask,
    ExecutionMetricAggregate,
    Metrics,
    StrategyConfiguration,
    TaskExecutionSnapshot,
)
from apps.trading.models.positions import Position
from apps.trading.models.state import ExecutionState
from apps.trading.models.trades import Trade
from apps.trading.services.execution_snapshots import get_metrics_snapshot
from apps.trading.services.summary import compute_cached_task_summary, compute_task_summary


def _make_task(*, strategy_type: str, display_currency: str = "JPY") -> BacktestTask:
    user = get_user_model().objects.create_user(
        username=f"user-{uuid4()}",
        email=f"{uuid4()}@example.com",
        password="testpass123",
    )
    config = StrategyConfiguration.objects.create(
        user=user,
        name=f"config-{uuid4()}",
        strategy_type=strategy_type,
        parameters={},
    )
    return BacktestTask.objects.create(
        user=user,
        config=config,
        name=f"task-{uuid4()}",
        instrument="USD_JPY",
        account_currency="USD",
        display_currency=display_currency,
        initial_balance=Decimal("10000"),
        start_time=datetime(2026, 1, 1, tzinfo=UTC),
        end_time=datetime(2026, 1, 2, tzinfo=UTC),
    )


def _create_closed_position(*, task: BacktestTask, execution_id, quote_pnl: Decimal) -> None:
    entry_time = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    Position.objects.create(
        task_type=TaskType.BACKTEST,
        task_id=task.pk,
        execution_id=execution_id,
        instrument=task.instrument,
        direction=Direction.LONG,
        units=1000,
        entry_price=Decimal("150"),
        entry_time=entry_time,
        exit_price=Decimal("150") + quote_pnl / Decimal("1000"),
        exit_time=entry_time + timedelta(minutes=5),
        is_open=False,
    )


def _create_state(
    *,
    task: BacktestTask,
    execution_id,
    realized_account: Decimal,
    realized_quote: Decimal,
    extra_metrics: dict[str, str] | None = None,
) -> None:
    tick_time = datetime(2026, 1, 1, 13, 0, tzinfo=UTC)
    metrics = {
        "realized_pnl": str(realized_account),
        "realized_pnl_quote": str(realized_quote),
        "unrealized_pnl": "0",
        "unrealized_pnl_quote": "0",
        **(extra_metrics or {}),
    }
    ExecutionState.objects.create(
        task_type=TaskType.BACKTEST,
        task_id=task.pk,
        execution_id=execution_id,
        current_balance=Decimal("10000") + realized_account,
        ticks_processed=10,
        last_tick_timestamp=tick_time,
        last_tick_price=Decimal("150"),
        last_tick_bid=Decimal("149.99"),
        last_tick_ask=Decimal("150.01"),
        strategy_state={"metrics": metrics},
    )


@pytest.mark.django_db
def test_snowball_net_summary_uses_runtime_pnl_for_partial_close_accounting():
    task = _make_task(strategy_type="snowball_net")
    execution_id = uuid4()
    _create_closed_position(
        task=task,
        execution_id=execution_id,
        quote_pnl=Decimal("85000"),
    )
    _create_state(
        task=task,
        execution_id=execution_id,
        realized_account=Decimal("5000"),
        realized_quote=Decimal("750000"),
    )

    summary = compute_task_summary(
        task_type=TaskType.BACKTEST,
        task_id=str(task.pk),
        execution_id=execution_id,
    )

    assert summary.pnl.realized == Decimal("750000")
    assert summary.pnl.realized_display_money == {
        "amount": "750000",
        "currency": "JPY",
    }
    assert summary.pnl.display_conversion_context == {
        "source_currency": "JPY",
        "target_currency": "JPY",
        "rate": Decimal("1"),
        "rate_source": "instrument_mid",
        "rate_as_of": datetime(2026, 1, 1, 13, 0, tzinfo=UTC),
        "rate_path": ["JPY", "JPY"],
        "conversion_available": True,
        "conversion_policy": "identity",
    }
    assert summary.execution.current_balance == Decimal("15000")
    assert summary.execution.current_balance_display == Decimal("2250000")
    assert summary.execution.current_balance_display_conversion_context == {
        "source_currency": "USD",
        "target_currency": "JPY",
        "rate": Decimal("150"),
        "rate_source": "instrument_mid",
        "rate_as_of": datetime(2026, 1, 1, 13, 0, tzinfo=UTC),
        "rate_path": ["USD/JPY", "direct"],
        "conversion_available": True,
        "conversion_policy": "runtime_fx_rate",
    }


@pytest.mark.django_db
def test_non_net_summary_keeps_closed_position_pnl_as_authoritative():
    task = _make_task(strategy_type="snowball")
    execution_id = uuid4()
    _create_closed_position(
        task=task,
        execution_id=execution_id,
        quote_pnl=Decimal("85000"),
    )
    _create_state(
        task=task,
        execution_id=execution_id,
        realized_account=Decimal("5000"),
        realized_quote=Decimal("750000"),
    )

    summary = compute_task_summary(
        task_type=TaskType.BACKTEST,
        task_id=str(task.pk),
        execution_id=execution_id,
    )

    assert summary.pnl.realized == Decimal("85000")


@pytest.mark.django_db
def test_task_summary_has_serializer_ready_dto_payload():
    task = _make_task(strategy_type="snowball")
    execution_id = uuid4()
    _create_state(
        task=task,
        execution_id=execution_id,
        realized_account=Decimal("5"),
        realized_quote=Decimal("5"),
    )

    summary = compute_task_summary(
        task_type=TaskType.BACKTEST,
        task_id=str(task.pk),
        execution_id=execution_id,
    )
    payload = summary.to_dict()

    assert payload["pnl"]["realized"] == Decimal("0")
    assert payload["pnl"]["unrealized"] == Decimal("0")
    assert payload["pnl"]["currency"] == "JPY"
    assert payload["pnl"]["total_money"] == {"amount": "0", "currency": "JPY"}
    assert payload["pnl"]["total_display_money"] == {"amount": "0", "currency": "JPY"}
    assert payload["pnl"]["display_conversion_context"]["target_currency"] == "JPY"
    assert (
        payload["execution"]["current_balance_display_conversion_context"]["target_currency"]
        == "JPY"
    )
    assert payload["execution"]["ticks_processed"] == 10


@pytest.mark.django_db
def test_task_summary_repairs_snowball_net_margin_watermark_from_metrics():
    task = _make_task(strategy_type="snowball_net")
    execution_id = uuid4()
    task.execution_id = execution_id
    task.save(update_fields=["execution_id"])
    first_timestamp = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    second_timestamp = datetime(2026, 1, 1, 12, 1, tzinfo=UTC)
    _create_state(
        task=task,
        execution_id=execution_id,
        realized_account=Decimal("0"),
        realized_quote=Decimal("0"),
        extra_metrics={
            "margin_ratio": "0.002",
            "snowball_net_margin_ratio_pct": "20",
        },
    )
    Metrics.objects.bulk_create(
        [
            Metrics(
                task_type=TaskType.BACKTEST,
                task_id=task.pk,
                execution_id=execution_id,
                timestamp=first_timestamp,
                metrics={
                    "margin_ratio": "0.0105",
                    "snowball_net_margin_ratio_pct": "20",
                },
            ),
            Metrics(
                task_type=TaskType.BACKTEST,
                task_id=task.pk,
                execution_id=execution_id,
                timestamp=second_timestamp,
                metrics={
                    "margin_ratio": "0.009",
                    "snowball_net_margin_ratio_pct": "42",
                },
            ),
        ]
    )
    ExecutionMetricAggregate.objects.create(
        task_type=TaskType.BACKTEST,
        task_id=task.pk,
        execution_id=execution_id,
        latest_timestamp=second_timestamp,
        latest_metrics={
            "margin_ratio": "0.009",
            "snowball_net_margin_ratio_pct": "42",
        },
        sample_count=2,
        watermarks={
            "margin_ratio_max": {
                "value": "0.0105",
                "timestamp": first_timestamp.isoformat(),
                "source_metric": "margin_ratio",
            }
        },
    )

    summary = compute_task_summary(
        task_type=TaskType.BACKTEST,
        task_id=str(task.pk),
        execution_id=execution_id,
    )

    assert summary.watermarks.margin_ratio_max.value == Decimal("0.42")
    assert summary.watermarks.margin_ratio_max.timestamp == second_timestamp.isoformat()
    assert summary.watermarks.margin_ratio_max.source_metric == "snowball_net_margin_ratio_pct"


@pytest.mark.django_db
def test_backtest_summary_defaults_display_currency_to_account_currency():
    task = _make_task(strategy_type="snowball", display_currency="")
    execution_id = uuid4()
    _create_state(
        task=task,
        execution_id=execution_id,
        realized_account=Decimal("5"),
        realized_quote=Decimal("5"),
    )

    summary = compute_task_summary(
        task_type=TaskType.BACKTEST,
        task_id=str(task.pk),
        execution_id=execution_id,
    )

    assert summary.execution.display_currency == "USD"
    assert summary.execution.current_balance_display_money == {
        "amount": "10005",
        "currency": "USD",
    }
    assert summary.pnl.total_display_money == {"amount": "0", "currency": "USD"}


@pytest.mark.django_db
def test_task_summary_query_count_stays_bounded_for_overview_api():
    task = _make_task(strategy_type="snowball")
    execution_id = uuid4()
    _create_closed_position(
        task=task,
        execution_id=execution_id,
        quote_pnl=Decimal("10"),
    )
    _create_state(
        task=task,
        execution_id=execution_id,
        realized_account=Decimal("10"),
        realized_quote=Decimal("10"),
    )
    Trade.objects.create(
        task_type=TaskType.BACKTEST,
        task_id=task.pk,
        execution_id=execution_id,
        timestamp=datetime(2026, 1, 1, 12, 1, tzinfo=UTC),
        direction=Direction.LONG,
        units=1000,
        instrument=task.instrument,
        price=Decimal("150.01"),
        execution_method="close_position",
    )

    with CaptureQueriesContext(connection) as queries:
        summary = compute_task_summary(
            task_type=TaskType.BACKTEST,
            task_id=str(task.pk),
            execution_id=execution_id,
        )

    assert summary.counts.total_trades == 1
    assert len(queries) <= 9


@pytest.mark.django_db
def test_snowball_net_cached_summary_recomputes_stale_terminal_snapshot():
    task = _make_task(strategy_type="snowball_net")
    execution_id = uuid4()
    task.execution_id = execution_id
    task.save(update_fields=["execution_id"])
    _create_closed_position(
        task=task,
        execution_id=execution_id,
        quote_pnl=Decimal("85000"),
    )
    _create_state(
        task=task,
        execution_id=execution_id,
        realized_account=Decimal("5000"),
        realized_quote=Decimal("750000"),
    )
    TaskExecutionSnapshot.objects.create(
        task_type=TaskType.BACKTEST,
        task_id=task.pk,
        execution_id=execution_id,
        summary={
            "timestamp": "2026-01-01T13:00:00+00:00",
            "pnl": {"realized": "85000", "unrealized": "0"},
            "counts": {},
            "execution": {"current_balance": "15000", "ticks_processed": 10},
            "tick": {"timestamp": None},
            "task": {},
        },
    )

    summary = compute_cached_task_summary(
        task_type=TaskType.BACKTEST,
        task_id=str(task.pk),
        execution_id=execution_id,
    )

    assert summary.pnl.realized == Decimal("750000")


@pytest.mark.django_db
def test_active_backtest_current_execution_ignores_persisted_summary_snapshot():
    task = _make_task(strategy_type="snowball")
    execution_id = uuid4()
    task.execution_id = execution_id
    task.status = TaskStatus.RUNNING
    task.save(update_fields=["execution_id", "status"])
    _create_state(
        task=task,
        execution_id=execution_id,
        realized_account=Decimal("5"),
        realized_quote=Decimal("5"),
    )
    TaskExecutionSnapshot.objects.create(
        task_type=TaskType.BACKTEST,
        task_id=task.pk,
        execution_id=execution_id,
        summary={
            "timestamp": "2026-01-01T12:00:00+00:00",
            "pnl": {"realized": "999", "unrealized": "0"},
            "counts": {},
            "execution": {"current_balance": "99999", "ticks_processed": 1},
            "tick": {
                "timestamp": "2026-01-01T12:00:00+00:00",
                "bid": "149.00",
                "ask": "149.02",
                "mid": "149.01",
            },
            "task": {"status": "stopped"},
        },
        metrics={"ticks_processed": 1},
    )

    summary = compute_cached_task_summary(
        task_type=TaskType.BACKTEST,
        task_id=str(task.pk),
        execution_id=execution_id,
    )

    assert summary.tick.timestamp == "2026-01-01T13:00:00+00:00"
    assert summary.tick.mid == Decimal("150")
    assert summary.execution.ticks_processed == 10
    assert summary.task.status == TaskStatus.RUNNING


@pytest.mark.django_db
def test_active_backtest_current_execution_ignores_persisted_metrics_snapshot():
    task = _make_task(strategy_type="snowball")
    execution_id = uuid4()
    task.execution_id = execution_id
    task.status = TaskStatus.RUNNING
    task.save(update_fields=["execution_id", "status"])
    TaskExecutionSnapshot.objects.create(
        task_type=TaskType.BACKTEST,
        task_id=task.pk,
        execution_id=execution_id,
        metrics={"ticks_processed": 1},
    )

    metrics = get_metrics_snapshot(
        task=task,
        task_type=TaskType.BACKTEST,
        task_id=str(task.pk),
        execution_id=str(execution_id),
    )

    assert metrics is None
