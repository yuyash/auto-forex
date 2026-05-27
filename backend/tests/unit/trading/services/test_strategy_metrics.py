"""Tests for strategy metric projection repairs."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from apps.trading.models import BacktestTask, StrategyConfiguration
from apps.trading.models.metrics import ExecutionMetricAggregate, Metrics
from apps.trading.models.state import ExecutionState
from apps.trading.services.strategy_data_common import StrategyDataQuery
from apps.trading.services.strategy_metrics import (
    load_latest_metric_point,
    load_paginated_metric_points,
)


def _make_snowball_task() -> BacktestTask:
    user = get_user_model().objects.create_user(
        username=f"user-{uuid4()}",
        email=f"{uuid4()}@example.com",
        password="testpass123",
    )
    config = StrategyConfiguration.objects.create(
        user=user,
        name=f"config-{uuid4()}",
        strategy_type="snowball",
        parameters={},
    )
    return BacktestTask.objects.create(
        user=user,
        config=config,
        name=f"task-{uuid4()}",
        instrument="USD_JPY",
        account_currency="USD",
        initial_balance=Decimal("10000"),
        start_time=datetime(2025, 1, 1, tzinfo=UTC),
        end_time=datetime(2025, 1, 2, tzinfo=UTC),
    )


def _query(execution_id) -> StrategyDataQuery:
    return StrategyDataQuery(
        execution_id=execution_id,
        since=None,
        until=None,
        page=1,
        page_size=100,
        ordering="timestamp",
        granularity="raw",
        category="",
        metric_keys=(),
    )


def _create_execution_state(task: BacktestTask, execution_id) -> None:
    ExecutionState.objects.create(
        task_type="backtest",
        task_id=task.pk,
        execution_id=execution_id,
        current_balance=Decimal("10000"),
        strategy_state={
            "warmup_started_at": "2025-01-01T00:00:00+00:00",
            "warmup_completed_at": "2025-01-01T00:10:00+00:00",
            "warmup_phase": "normal",
        },
    )


def _stale_metrics() -> dict[str, str]:
    return {
        "warmup_status": "warmup",
        "warmup_elapsed_minutes": "0",
        "warmup_block_reason": "collecting_volatility",
        "warmup_progress_pct": "0",
        "warmup_unit_ratio_pct": "60",
        "snowball_allow_new_positions": "0",
        "snowball_allow_rebuilds": "0",
        "snowball_add_block_reason": "",
        "snowball_rebuild_block_reason": "",
        "current_balance": "1116288.100000",
    }


@pytest.mark.django_db
def test_latest_metric_repairs_stale_snowball_warmup_and_guard_values() -> None:
    task = _make_snowball_task()
    execution_id = uuid4()
    task.execution_id = execution_id
    task.save(update_fields=["execution_id", "updated_at"])
    _create_execution_state(task, execution_id)
    ExecutionMetricAggregate.objects.create(
        task_type="backtest",
        task_id=task.pk,
        execution_id=execution_id,
        latest_timestamp=datetime(2025, 1, 1, 0, 15, tzinfo=UTC),
        latest_metrics=_stale_metrics(),
    )

    row = load_latest_metric_point(
        task=task, task_type_label="backtest", query=_query(execution_id)
    )

    assert row is not None
    assert row["metrics"]["warmup_status"] == "normal"
    assert row["metrics"]["warmup_block_reason"] == ""
    assert row["metrics"]["warmup_elapsed_minutes"] == "15"
    assert row["metrics"]["snowball_allow_new_positions"] == "1"
    assert row["metrics"]["snowball_allow_rebuilds"] == "1"
    assert row["metrics"]["current_balance"] == "1116288.100000"


@pytest.mark.django_db
def test_paginated_metrics_only_repair_rows_after_snowball_warmup_completed() -> None:
    task = _make_snowball_task()
    execution_id = uuid4()
    task.execution_id = execution_id
    task.save(update_fields=["execution_id", "updated_at"])
    _create_execution_state(task, execution_id)
    Metrics.objects.create(
        task_type="backtest",
        task_id=task.pk,
        execution_id=execution_id,
        timestamp=datetime(2025, 1, 1, 0, 5, tzinfo=UTC),
        metrics=_stale_metrics(),
    )
    Metrics.objects.create(
        task_type="backtest",
        task_id=task.pk,
        execution_id=execution_id,
        timestamp=datetime(2025, 1, 1, 0, 15, tzinfo=UTC),
        metrics=_stale_metrics(),
    )

    result = load_paginated_metric_points(
        task=task,
        task_type_label="backtest",
        query=_query(execution_id),
    )

    before, after = result.rows
    assert before["metrics"]["warmup_status"] == "warmup"
    assert before["metrics"]["snowball_allow_new_positions"] == "0"
    assert after["metrics"]["warmup_status"] == "normal"
    assert after["metrics"]["snowball_allow_new_positions"] == "1"
