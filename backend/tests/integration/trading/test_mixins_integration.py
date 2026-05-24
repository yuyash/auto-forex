"""Integration tests for TaskSubResourceMixin via BacktestTaskViewSet endpoints.

Tests the paginated sub-resource actions (metrics, logs, events,
trades, positions, orders) using real DB records and authenticated API calls.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.trading.enums import Direction, LogLevel, TaskType
from apps.trading.models import (
    BacktestTask,
    CeleryTaskStatus,
    ExecutionMetricAggregate,
    ExecutionState,
    Metrics,
    Order,
    Position,
    TaskLog,
    TaskExecutionSnapshot,
    Trade,
    TradingEvent,
)
from apps.trading.models.orders import OrderStatus, OrderType
from tests.integration.factories import (
    BacktestTaskFactory,
    StrategyConfigurationFactory,
    UserFactory,
)


def _auth_client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _make_task(user=None, *, strategy_type: str = "floor") -> BacktestTask:
    """Create a backtest task with an execution_id for sub-resource filtering."""
    if user is None:
        user = UserFactory()
    config = StrategyConfigurationFactory(user=user, strategy_type=strategy_type)
    task = cast(BacktestTask, BacktestTaskFactory(user=user, config=config, status="running"))
    from uuid import uuid4

    task.execution_id = uuid4()
    task.save()
    return task


def _assert_invalid_query_param(response, detail: str) -> None:
    assert response.data["code"] == "invalid_query_param"
    assert str(response.data["detail"]) == detail
    assert response.data["error"] == detail
    assert response.data["error_code"] == "invalid"


@pytest.mark.django_db
class TestMetrics:
    """GET /api/trading/tasks/backtest/{id}/strategy/metrics/"""

    def test_with_data(self):
        task = _make_task()
        client = _auth_client(task.user)
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

        for i in range(3):
            Metrics.objects.create(
                task_type=TaskType.BACKTEST,
                task_id=task.pk,
                execution_id=task.execution_id,
                timestamp=now + timedelta(minutes=i),
                metrics={"margin_ratio": str(Decimal("0.05") + Decimal(str(i)) / 100)},
            )

        response = client.get(f"/api/trading/tasks/backtest/{task.pk}/strategy/metrics/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 3
        assert response.data["data_source"] == "strategy_metrics"
        assert len(response.data["results"]) == 3

    def test_without_data(self):
        task = _make_task()
        client = _auth_client(task.user)

        response = client.get(f"/api/trading/tasks/backtest/{task.pk}/strategy/metrics/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 0
        assert response.data["data_source"] == "strategy_metrics"
        assert response.data["results"] == []

    def test_interval_metrics_with_null_execution_id(self):
        task = _make_task()
        task.execution_id = None
        task.save(update_fields=["execution_id"])
        client = _auth_client(task.user)
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

        for i in range(2):
            Metrics.objects.create(
                task_type=TaskType.BACKTEST,
                task_id=task.pk,
                execution_id=None,
                timestamp=now + timedelta(minutes=i),
                metrics={"margin_ratio": str(Decimal("0.05") + Decimal(str(i)) / 100)},
            )

        response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/strategy/metrics/",
            {"granularity": "2", "page_size": 500},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1
        assert response.data["data_source"] == "strategy_metrics"
        assert len(response.data["results"]) == 1

    def test_latest_metric_uses_aggregate_snapshot(self):
        task = _make_task()
        client = _auth_client(task.user)
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        ExecutionMetricAggregate.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            latest_timestamp=now,
            latest_metrics={"margin_ratio": "0.12", "current_balance": "10050"},
            sample_count=10,
        )

        response = client.get(f"/api/trading/tasks/backtest/{task.pk}/strategy/metrics/latest/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["data_source"] == "strategy_metrics"
        assert response.data["result"]["t"] == int(now.timestamp())
        metrics = response.data["result"]["metrics"]
        assert metrics["margin_ratio"] == "0.12"
        assert metrics["current_balance"] == "10050"
        assert metrics["current_balance_money"] == {
            "amount": "10050",
            "currency": "USD",
        }
        assert metrics["current_balance_display_money"] == {
            "amount": "10050",
            "currency": "USD",
        }
        assert metrics["display_conversion_context"]["conversion_policy"] == "identity"

    def test_latest_metric_falls_back_to_latest_metric_row(self):
        task = _make_task()
        client = _auth_client(task.user)
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        Metrics.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            timestamp=now,
            metrics={"margin_ratio": "0.10"},
        )
        Metrics.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            timestamp=now + timedelta(minutes=1),
            metrics={"margin_ratio": "0.11"},
        )

        response = client.get(f"/api/trading/tasks/backtest/{task.pk}/strategy/metrics/latest/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["result"]["metrics"] == {"margin_ratio": "0.11"}

    def test_latest_metric_ignores_aggregate_outside_requested_range(self):
        task = _make_task()
        client = _auth_client(task.user)
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        ExecutionMetricAggregate.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            latest_timestamp=now + timedelta(minutes=10),
            latest_metrics={"margin_ratio": "0.99"},
            sample_count=10,
        )
        Metrics.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            timestamp=now + timedelta(minutes=1),
            metrics={"margin_ratio": "0.10"},
        )

        response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/strategy/metrics/latest/",
            {"until": (now + timedelta(minutes=5)).isoformat()},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["result"]["metrics"] == {"margin_ratio": "0.10"}

    def test_periodic_metrics_aggregate_tp_sl_and_position_activity(self):
        task = _make_task(strategy_type="snowball")
        task.instrument = "USD_JPY"
        task.save(update_fields=["instrument"])
        client = _auth_client(task.user)
        opened_at = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
        closed_at = datetime(2024, 1, 3, 9, 0, tzinfo=timezone.utc)

        tp_position = Position.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            instrument=task.instrument,
            direction=Direction.LONG,
            units=1000,
            entry_price=Decimal("150"),
            entry_time=opened_at,
            exit_price=Decimal("151"),
            exit_time=closed_at,
            is_open=False,
        )
        sl_position = Position.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            instrument=task.instrument,
            direction=Direction.SHORT,
            units=-1000,
            entry_price=Decimal("150"),
            entry_time=opened_at + timedelta(hours=1),
            exit_price=Decimal("151"),
            exit_time=closed_at,
            is_open=False,
        )
        TradingEvent.objects.bulk_create(
            [
                TradingEvent(
                    task_type=TaskType.BACKTEST,
                    task_id=task.pk,
                    execution_id=task.execution_id,
                    event_type="open_position",
                    event_timestamp=opened_at,
                    position_id=tp_position.id,
                    description="open tp",
                ),
                TradingEvent(
                    task_type=TaskType.BACKTEST,
                    task_id=task.pk,
                    execution_id=task.execution_id,
                    event_type="open_position",
                    event_timestamp=opened_at + timedelta(hours=1),
                    position_id=sl_position.id,
                    description="open sl",
                ),
                TradingEvent(
                    task_type=TaskType.BACKTEST,
                    task_id=task.pk,
                    execution_id=task.execution_id,
                    event_type="rebuild_position",
                    event_timestamp=opened_at + timedelta(days=1),
                    position_id=sl_position.id,
                    description="rebuild",
                ),
                TradingEvent(
                    task_type=TaskType.BACKTEST,
                    task_id=task.pk,
                    execution_id=task.execution_id,
                    event_type="close_position",
                    close_reason="tp",
                    event_timestamp=closed_at,
                    position_id=tp_position.id,
                    description="tp close",
                ),
                TradingEvent(
                    task_type=TaskType.BACKTEST,
                    task_id=task.pk,
                    execution_id=task.execution_id,
                    event_type="close_position",
                    close_reason="stop_loss",
                    event_timestamp=closed_at,
                    position_id=sl_position.id,
                    description="sl close",
                ),
            ]
        )
        return_start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        Metrics.objects.bulk_create(
            [
                Metrics(
                    task_type=TaskType.BACKTEST,
                    task_id=task.pk,
                    execution_id=task.execution_id,
                    timestamp=return_start + timedelta(minutes=index * 5),
                    metrics={"total_return": str(index)},
                )
                for index in range(2500)
            ]
        )

        response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/strategy/metrics/periodic/",
            {"timezone": "UTC"},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["currency"] == "JPY"
        day_rows = {row["label"]: row for row in response.data["periods"]["day"]}
        assert day_rows["2024-01-01"]["open_positions"] == 2
        assert day_rows["2024-01-02"]["rebuild_opens"] == 1
        assert day_rows["2024-01-03"]["tp_closes"] == 1
        assert day_rows["2024-01-03"]["sl_closes"] == 1
        assert day_rows["2024-01-03"]["tp_profit"] == "1000"
        assert day_rows["2024-01-03"]["sl_loss"] == "-1000"
        month = response.data["periods"]["month"][0]
        assert month["open_positions"] == 2
        assert month["rebuild_opens"] == 1
        assert month["tp_closes"] == 1
        assert month["sl_closes"] == 1
        weekly_returns = response.data["returns"]["week"]
        assert [row["label"] for row in weekly_returns] == ["2024-01-01", "2024-01-08"]
        assert [row["period_return"] for row in weekly_returns] == ["2015", "484"]


@pytest.mark.django_db
class TestStrictQueryValidation:
    """Sub-resource endpoints reject malformed query parameters."""

    def test_rejects_invalid_execution_id(self):
        task = _make_task()
        client = _auth_client(task.user)

        response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/trades/",
            {"execution_id": "not-a-uuid"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        _assert_invalid_query_param(response, "Invalid execution_id: not-a-uuid")

    def test_rejects_invalid_since(self):
        task = _make_task()
        client = _auth_client(task.user)

        response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/events/",
            {"since": "bad-date"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        _assert_invalid_query_param(response, "Invalid datetime value: bad-date")

    def test_rejects_invalid_page(self):
        task = _make_task()
        client = _auth_client(task.user)

        response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/logs/",
            {"page": "zero"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        _assert_invalid_query_param(response, "Invalid page parameter")

    def test_rejects_non_positive_page_size(self):
        task = _make_task()
        client = _auth_client(task.user)

        response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/trades/",
            {"page_size": 0},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        _assert_invalid_query_param(response, "page_size must be greater than 0")

    def test_rejects_page_size_above_maximum(self):
        task = _make_task()
        client = _auth_client(task.user)

        response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/positions/",
            {"page_size": 2000},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        _assert_invalid_query_param(response, "page_size exceeds maximum allowed value of 1000")

    def test_rejects_inverted_range(self):
        task = _make_task()
        client = _auth_client(task.user)
        start = datetime(2024, 6, 1, 12, 5, tzinfo=timezone.utc)
        end = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)

        response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/positions/",
            {
                "range_from": start.isoformat(),
                "range_to": end.isoformat(),
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        _assert_invalid_query_param(
            response,
            "range_from must be earlier than or equal to range_to",
        )

    @pytest.mark.parametrize(
        ("path", "params", "detail"),
        [
            ("logs", {"execution_id": "invalid"}, "Invalid execution_id: invalid"),
            ("events", {"page_size": -1}, "page_size must be greater than 0"),
            ("trades", {"page_size": 9999}, "page_size exceeds maximum allowed value of 1000"),
            (
                "orders",
                {"execution_id": "invalid"},
                "Invalid execution_id: invalid",
            ),
            (
                "positions",
                {"range_from": "bad-date"},
                "Invalid datetime value: bad-date",
            ),
        ],
    )
    def test_rejects_invalid_subresource_query_params(self, path, params, detail):
        task = _make_task()
        client = _auth_client(task.user)

        response = client.get(f"/api/trading/tasks/backtest/{task.pk}/{path}/", params)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        _assert_invalid_query_param(response, detail)


@pytest.mark.django_db
class TestLogs:
    """GET /api/trading/tasks/backtest/{id}/logs/"""

    def test_with_logs(self):
        task = _make_task()
        client = _auth_client(task.user)

        for i in range(3):
            TaskLog.objects.create(
                task_type=TaskType.BACKTEST,
                task_id=task.pk,
                execution_id=task.execution_id,
                level=LogLevel.INFO,
                component="test",
                message=f"Log message {i}",
            )

        response = client.get(f"/api/trading/tasks/backtest/{task.pk}/logs/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 3
        assert len(response.data["results"]) == 3
        assert "execution_id" in response.data["results"][0]

    def test_without_logs(self):
        task = _make_task()
        client = _auth_client(task.user)

        response = client.get(f"/api/trading/tasks/backtest/{task.pk}/logs/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 0


@pytest.mark.django_db
class TestEvents:
    """GET /api/trading/tasks/backtest/{id}/events/"""

    def test_with_events(self):
        task = _make_task()
        client = _auth_client(task.user)

        for i in range(2):
            TradingEvent.objects.create(
                task_type=TaskType.BACKTEST,
                task_id=task.pk,
                execution_id=task.execution_id,
                event_type="initial_entry",
                severity="info",
                description=f"Event {i}",
                user=task.user,
                instrument="USD_JPY",
                details={"entry_id": i},
            )

        response = client.get(f"/api/trading/tasks/backtest/{task.pk}/events/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 2
        assert "execution_id" in response.data["results"][0]

    def test_without_events(self):
        task = _make_task()
        client = _auth_client(task.user)

        response = client.get(f"/api/trading/tasks/backtest/{task.pk}/events/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 0

    def test_scope_filter_task_events(self):
        task = _make_task()
        client = _auth_client(task.user)

        TradingEvent.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            event_type="status_changed",
            severity="info",
            description="Task restart requested",
            user=task.user,
            instrument="USD_JPY",
            details={"kind": "task_restart_requested"},
        )
        TradingEvent.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            event_type="initial_entry",
            severity="info",
            description="Open long",
            user=task.user,
            instrument="USD_JPY",
            details={"event_type": "initial_entry"},
        )

        response = client.get(f"/api/trading/tasks/backtest/{task.pk}/events/?scope=task")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1
        assert response.data["results"][0]["event_scope"] == "task"

    def test_scope_filter_trading_events(self):
        task = _make_task()
        client = _auth_client(task.user)

        TradingEvent.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            event_type="status_changed",
            severity="info",
            description="Task stop requested",
            user=task.user,
            instrument="USD_JPY",
            details={"kind": "task_stop_requested"},
        )
        TradingEvent.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            event_type="open_position",
            severity="info",
            description="Open long position",
            user=task.user,
            instrument="USD_JPY",
            details={"event_type": "initial_entry", "strategy_event_type": "initial_entry"},
        )

        response = client.get(f"/api/trading/tasks/backtest/{task.pk}/events/?scope=trading")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1
        assert response.data["results"][0]["event_scope"] == "trading"

    def test_strategy_events_endpoint(self):
        task = _make_task(strategy_type="snowball")
        client = _auth_client(task.user)

        cycle_id = uuid4()
        Trade.objects.create(
            id=cycle_id,
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            timestamp=datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
            direction="long",
            units=1000,
            instrument="USD_JPY",
            price="150.100",
            execution_method="open_position",
            cycle_id=cycle_id,
            description="Initial entry",
        )

        response = client.get(f"/api/trading/tasks/backtest/{task.pk}/strategy-events/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["cycles"]) == 1
        assert response.data["cycles"][0]["cycle_id"] == str(cycle_id)
        assert response.data["cycles"][0]["position_ids"] == []
        assert response.data["cycles"][0]["trades"] == []
        assert response.data["summary"]["cycle_count"] == 1

    def test_strategy_data_endpoints_split_snapshot_history_and_metrics(self):
        task = _make_task(strategy_type="snowball")
        client = _auth_client(task.user)
        base = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        ExecutionState.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            current_balance=Decimal("10000"),
            last_tick_timestamp=base + timedelta(minutes=1),
            strategy_state={
                "protection_level": "normal",
                "cycles": [],
                "account_balance": "10000",
                "account_nav": "10000",
            },
        )
        TradingEvent.objects.create(
            event_type="strategy_tick",
            severity="info",
            description="strategy tick",
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            strategy_type="snowball",
            event_timestamp=base,
            details={"source": "test"},
        )
        Metrics.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            timestamp=base,
            metrics={"margin_ratio": "0.1", "current_balance": "10000"},
        )

        snapshot = client.get(f"/api/trading/tasks/backtest/{task.pk}/strategy/snapshot/")
        history = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/strategy/history/",
            {"category": "event", "page_size": 10},
        )
        metrics = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/strategy/metrics/",
            {"granularity": "M1", "metric_keys": "margin_ratio"},
        )

        assert snapshot.status_code == status.HTTP_200_OK
        assert snapshot.data["snapshot"]["state"]["protection_level"] == "normal"
        assert history.status_code == status.HTTP_200_OK
        assert history.data["results"][0]["source"] == "trading_event"
        assert metrics.status_code == status.HTTP_200_OK
        assert metrics.data["results"][0]["metrics"] == {"margin_ratio": "0.1"}
        assert metrics.data["ohlc_layers"]["price_series"] == []

    def test_strategy_events_include_snowball_grid_state(self):
        task = _make_task(strategy_type="snowball")
        client = _auth_client(task.user)

        cycle_id = uuid4()
        position_id = uuid4()
        Position.objects.create(
            id=position_id,
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            instrument="USD_JPY",
            direction=Direction.LONG,
            units=1000,
            entry_price="150.100",
            entry_time=datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
            is_open=True,
        )
        Trade.objects.create(
            id=cycle_id,
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            timestamp=datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
            direction="long",
            units=1000,
            instrument="USD_JPY",
            price="150.100",
            execution_method="open_position",
            cycle_id=cycle_id,
            position_id=position_id,
            description="Initial entry",
        )
        ExecutionState.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            current_balance=Decimal("10000"),
            ticks_processed=1,
            strategy_state={
                "cycles": [
                    {
                        "cycle_id": 1,
                        "direction": "long",
                        "status": "active",
                        "trade_cycle_id": str(cycle_id),
                        "grid": {
                            "layers": [
                                {
                                    "layer_number": 1,
                                    "base_units": 1000,
                                    "refill_up_to": 2,
                                    "slots": [
                                        {
                                            "index": 0,
                                            "entry": {
                                                "entry_id": 1,
                                                "step": 1,
                                                "direction": "long",
                                                "entry_price": "150.1",
                                                "close_price": "150.3",
                                                "units": 1000,
                                                "opened_at": "2024-06-01T12:00:00+00:00",
                                                "role": "initial",
                                                "layer_number": 1,
                                                "retracement_count": 0,
                                                "root_entry_id": 1,
                                                "parent_entry_id": 1,
                                                "position_id": str(position_id),
                                                "expected_interval_pips": None,
                                                "actual_interval_pips": None,
                                                "expected_tp_pips": None,
                                                "validation_status": "",
                                                "stop_loss_price": None,
                                                "is_rebuild": False,
                                                "lifecycle_realized_pnl": "0",
                                                "lifecycle_stop_loss_count": 0,
                                            },
                                            "ever_closed": False,
                                        },
                                        {
                                            "index": 1,
                                            "entry": None,
                                            "ever_closed": False,
                                            "pending_rebuild": {
                                                "entry_price": "149.9",
                                                "close_price": "150.2",
                                                "units": 1000,
                                                "direction": "long",
                                                "role": "counter",
                                                "layer_number": 1,
                                                "retracement_count": 1,
                                                "step": 2,
                                                "root_entry_id": 1,
                                                "parent_entry_id": 1,
                                                "cycle_id": 1,
                                                "position_id": "pending-slot",
                                                "lifecycle_realized_pnl": "0",
                                                "lifecycle_stop_loss_count": 0,
                                            },
                                        },
                                    ],
                                }
                            ]
                        },
                        "hedge_entries": [],
                        "counter_close_count": 0,
                        "realized_pnl": "0",
                    }
                ],
                "protection_level": "normal",
                "initialised": True,
                "next_entry_id": 2,
                "last_bid": None,
                "last_ask": None,
                "last_mid": None,
                "account_balance": "10000",
                "account_nav": "10000",
                "metrics": {},
            },
        )

        response = client.get(f"/api/trading/tasks/backtest/{task.pk}/strategy-events/")

        assert response.status_code == status.HTTP_200_OK
        grid_state = response.data["cycles"][0]["grid_state"]
        assert response.data["cycles"][0]["position_ids"] == [str(position_id)]
        assert response.data["cycles"][0]["trades"] == []
        assert grid_state["summary"]["filled"] == 1
        assert grid_state["summary"]["stopped"] == 1
        assert grid_state["summary"]["layer_count"] == 1
        assert grid_state["layers"][0]["slots"][0]["state"] == "filled"
        assert grid_state["layers"][0]["slots"][0]["position_id"] == str(position_id)
        assert grid_state["layers"][0]["slots"][1]["state"] == "stopped"

    def test_events_support_created_at_range_filter(self):
        task = _make_task()
        client = _auth_client(task.user)

        older = TradingEvent.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            event_type="initial_entry",
            severity="info",
            description="Older event",
            user=task.user,
            instrument="USD_JPY",
        )
        newer = TradingEvent.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            event_type="initial_entry",
            severity="info",
            description="Newer event",
            user=task.user,
            instrument="USD_JPY",
        )

        response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/events/",
            {
                "created_from": older.created_at.isoformat(),
                "created_to": newer.created_at.isoformat(),
            },
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 2

        response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/events/",
            {"created_from": newer.created_at.isoformat()},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1
        assert response.data["results"][0]["description"] == "Newer event"

    def test_strategy_events_support_cycle_id_filter(self):
        task = _make_task(strategy_type="snowball")
        client = _auth_client(task.user)

        cycle_a = uuid4()
        cycle_b = uuid4()
        Trade.objects.create(
            id=cycle_a,
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            timestamp=datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
            direction="long",
            units=1000,
            instrument="USD_JPY",
            price="150.100",
            execution_method="open_position",
            cycle_id=cycle_a,
        )
        Trade.objects.create(
            id=cycle_b,
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            timestamp=datetime(2024, 6, 1, 13, 0, 0, tzinfo=timezone.utc),
            direction="short",
            units=1000,
            instrument="USD_JPY",
            price="149.900",
            execution_method="open_position",
            cycle_id=cycle_b,
        )

        response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/strategy-events/",
            {"cycle_id": str(cycle_b), "include_trades": "true"},
        )
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["cycles"]) == 1
        assert response.data["cycles"][0]["cycle_id"] == str(cycle_b)
        assert len(response.data["cycles"][0]["trades"]) == 1

    def test_strategy_events_include_open_units_total(self):
        task = _make_task(strategy_type="snowball")
        client = _auth_client(task.user)

        cycle_id = uuid4()
        long_position = uuid4()
        closed_position = uuid4()
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

        Position.objects.create(
            id=long_position,
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            instrument="USD_JPY",
            direction=Direction.LONG,
            units=1000,
            entry_price="150.100",
            entry_time=now,
            is_open=True,
        )
        Position.objects.create(
            id=closed_position,
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            instrument="USD_JPY",
            direction=Direction.LONG,
            units=2000,
            entry_price="149.900",
            entry_time=now + timedelta(minutes=1),
            exit_price="150.300",
            exit_time=now + timedelta(minutes=2),
            is_open=False,
        )

        Trade.objects.create(
            id=uuid4(),
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            timestamp=now,
            direction="long",
            units=1000,
            instrument="USD_JPY",
            price="150.100",
            execution_method="open_position",
            cycle_id=cycle_id,
            position_id=long_position,
        )
        Trade.objects.create(
            id=uuid4(),
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            timestamp=now + timedelta(minutes=1),
            direction="long",
            units=2000,
            instrument="USD_JPY",
            price="149.900",
            execution_method="open_position",
            cycle_id=cycle_id,
            position_id=closed_position,
        )
        Trade.objects.create(
            id=uuid4(),
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            timestamp=now + timedelta(minutes=2),
            direction="long",
            units=-2000,
            instrument="USD_JPY",
            price="150.300",
            execution_method="close_position",
            cycle_id=cycle_id,
            position_id=closed_position,
        )

        response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/strategy-events/",
            {"cycle_id": str(cycle_id)},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["cycles"][0]["open_units_total"] == 1000


@pytest.mark.django_db
class TestSummary:
    """GET /api/trading/tasks/backtest/{id}/summary/"""

    def test_summary_includes_open_units_by_direction(self):
        task = _make_task()
        client = _auth_client(task.user)
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

        Position.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            instrument="USD_JPY",
            direction=Direction.LONG,
            units=1000,
            entry_price=Decimal("150.500"),
            entry_time=now,
            is_open=True,
        )
        Position.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            instrument="USD_JPY",
            direction=Direction.SHORT,
            units=-2500,
            entry_price=Decimal("150.700"),
            entry_time=now,
            is_open=True,
        )

        response = client.get(f"/api/trading/tasks/backtest/{task.pk}/summary/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["counts"]["open_long_units"] == 1000
        assert response.data["counts"]["open_short_units"] == 2500


@pytest.mark.django_db
class TestTrades:
    """GET /api/trading/tasks/backtest/{id}/trades/"""

    def test_with_trades(self):
        task = _make_task()
        client = _auth_client(task.user)
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

        Trade.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            timestamp=now,
            direction=Direction.LONG,
            units=1000,
            instrument="USD_JPY",
            price=Decimal("150.500"),
            execution_method="initial_entry",
        )

        response = client.get(f"/api/trading/tasks/backtest/{task.pk}/trades/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1
        trade = response.data["results"][0]
        assert trade["instrument"] == "USD_JPY"
        # Direction is normalized to buy/sell in the mixin
        assert trade["direction"] == "buy"

    def test_without_trades(self):
        task = _make_task()
        client = _auth_client(task.user)

        response = client.get(f"/api/trading/tasks/backtest/{task.pk}/trades/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 0

    def test_trades_support_timestamp_range_filter(self):
        task = _make_task()
        client = _auth_client(task.user)
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

        Trade.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            timestamp=now,
            direction=Direction.LONG,
            units=1000,
            instrument="USD_JPY",
            price=Decimal("150.500"),
            execution_method="initial_entry",
        )
        Trade.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            timestamp=now + timedelta(minutes=5),
            direction=Direction.SHORT,
            units=1000,
            instrument="USD_JPY",
            price=Decimal("150.700"),
            execution_method="take_profit",
        )

        response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/trades/",
            {"timestamp_from": (now + timedelta(minutes=1)).isoformat()},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1
        assert response.data["results"][0]["direction"] == "sell"

    def test_trades_support_trade_ordering_without_breaking_task_lookup(self):
        task = _make_task()
        client = _auth_client(task.user)
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

        first = Trade.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            timestamp=now,
            sequence_number=2,
            direction=Direction.LONG,
            units=1000,
            instrument="USD_JPY",
            price=Decimal("150.500"),
            execution_method="initial_entry",
        )
        second = Trade.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            timestamp=now + timedelta(minutes=5),
            sequence_number=1,
            direction=Direction.SHORT,
            units=1000,
            instrument="USD_JPY",
            price=Decimal("150.700"),
            execution_method="take_profit",
        )

        response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/trades/",
            {"ordering": "asc"},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 2
        assert [trade["id"] for trade in response.data["results"]] == [
            str(first.pk),
            str(second.pk),
        ]

    def test_trades_reject_invalid_cycle_id(self):
        task = _make_task()
        client = _auth_client(task.user)

        response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/trades/",
            {"cycle_id": "not-a-uuid"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid cycle_id" in str(response.data)

    def test_trades_filter_by_trade_id_prefix(self):
        """Trade ID prefix filter narrows results to matching UUIDs."""
        task = _make_task()
        client = _auth_client(task.user)
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

        target = Trade.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            timestamp=now,
            direction=Direction.LONG,
            units=1000,
            instrument="USD_JPY",
            price=Decimal("150.500"),
            execution_method="initial_entry",
        )
        Trade.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            timestamp=now + timedelta(minutes=1),
            direction=Direction.SHORT,
            units=1000,
            instrument="USD_JPY",
            price=Decimal("150.700"),
            execution_method="take_profit",
        )

        prefix = str(target.pk)[:8]
        response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/trades/",
            {"trade_id": prefix},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1
        assert response.data["results"][0]["id"] == str(target.pk)

    def test_trades_include_realized_pnl_for_close_rows(self):
        task = _make_task()
        client = _auth_client(task.user)
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

        position = Position.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            instrument="USD_JPY",
            direction=Direction.LONG,
            units=1000,
            entry_price=Decimal("150.500"),
            entry_time=now,
            is_open=False,
            exit_price=Decimal("151.100"),
            exit_time=now + timedelta(minutes=5),
        )
        Trade.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            timestamp=now + timedelta(minutes=5),
            direction=Direction.LONG,
            units=1000,
            instrument="USD_JPY",
            price=Decimal("151.100"),
            execution_method="close_position",
            position=position,
        )

        response = client.get(f"/api/trading/tasks/backtest/{task.pk}/trades/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1
        assert response.data["results"][0]["pnl"] == "600.0000000000"
        assert response.data["results"][0]["pnl_currency"] == "JPY"
        assert response.data["results"][0]["pnl_money"] == {
            "amount": "600.0000000000",
            "currency": "JPY",
        }
        assert response.data["results"][0]["pnl_display_money"]["currency"] == "USD"
        assert response.data["results"][0]["display_conversion_context"]["source_currency"] == "JPY"


@pytest.mark.django_db
class TestPositions:
    """GET /api/trading/tasks/backtest/{id}/positions/"""

    def test_with_positions(self):
        task = _make_task()
        client = _auth_client(task.user)
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

        Position.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            instrument="USD_JPY",
            direction=Direction.LONG,
            units=1000,
            entry_price=Decimal("150.500"),
            entry_time=now,
            is_open=True,
        )

        response = client.get(f"/api/trading/tasks/backtest/{task.pk}/positions/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1
        pos = response.data["results"][0]
        assert pos["instrument"] == "USD_JPY"
        assert pos["is_open"] is True
        assert pos["is_initial_position_seed"] is False
        assert pos["unrealized_pnl_currency"] == "JPY"
        assert pos["unrealized_pnl_money"] == {
            "amount": "0.0000000000",
            "currency": "JPY",
        }
        assert pos["unrealized_pnl_display_money"] is None
        assert pos["unrealized_pnl_display_conversion_context"]["source_currency"] == "JPY"

    def test_positions_include_initial_position_seed_flag(self):
        task = _make_task()
        client = _auth_client(task.user)
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

        Position.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            instrument="USD_JPY",
            direction=Direction.LONG,
            units=1000,
            entry_price=Decimal("150.500"),
            entry_time=now,
            is_open=True,
            is_initial_position_seed=True,
        )

        response = client.get(f"/api/trading/tasks/backtest/{task.pk}/positions/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["results"][0]["is_initial_position_seed"] is True

    def test_positions_filter_by_initial_position_seed_flag(self):
        task = _make_task()
        client = _auth_client(task.user)
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        initial_position = Position.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            instrument="USD_JPY",
            direction=Direction.LONG,
            units=1000,
            entry_price=Decimal("150.500"),
            entry_time=now,
            is_open=True,
            is_initial_position_seed=True,
        )
        normal_position = Position.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            instrument="USD_JPY",
            direction=Direction.SHORT,
            units=1000,
            entry_price=Decimal("150.000"),
            entry_time=now + timedelta(minutes=1),
            is_open=True,
            is_initial_position_seed=False,
        )

        initial_response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/positions/",
            {"initial_position_filter": "initial"},
        )
        normal_response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/positions/",
            {"initial_position_filter": "normal"},
        )
        all_response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/positions/",
            {"initial_position_filter": "all"},
        )

        assert initial_response.status_code == status.HTTP_200_OK
        assert [row["id"] for row in initial_response.data["results"]] == [str(initial_position.id)]
        assert normal_response.status_code == status.HTTP_200_OK
        assert [row["id"] for row in normal_response.data["results"]] == [str(normal_position.id)]
        assert all_response.status_code == status.HTTP_200_OK
        assert all_response.data["count"] == 2

    def test_positions_include_realized_pnl_money_for_closed_rows(self):
        task = _make_task()
        client = _auth_client(task.user)
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

        Position.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            instrument="USD_JPY",
            direction=Direction.LONG,
            units=1000,
            entry_price=Decimal("150.500"),
            entry_time=now,
            exit_price=Decimal("151.100"),
            exit_time=now + timedelta(minutes=5),
            is_open=False,
        )

        response = client.get(f"/api/trading/tasks/backtest/{task.pk}/positions/")

        assert response.status_code == status.HTTP_200_OK
        pos = response.data["results"][0]
        assert pos["realized_pnl"] == "600.0000000000"
        assert pos["realized_pnl_currency"] == "JPY"
        assert pos["realized_pnl_money"] == {
            "amount": "600.0000000000",
            "currency": "JPY",
        }
        assert pos["realized_pnl_display_money"]["currency"] == "USD"
        assert pos["realized_pnl_display_conversion_context"]["source_currency"] == "JPY"

    def test_without_positions(self):
        task = _make_task()
        client = _auth_client(task.user)

        response = client.get(f"/api/trading/tasks/backtest/{task.pk}/positions/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 0

    def test_positions_reject_invalid_cycle_id(self):
        task = _make_task()
        client = _auth_client(task.user)

        response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/positions/",
            {"cycle_id": "not-a-uuid"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid cycle_id" in str(response.data)

    def test_positions_filter_by_position_id_prefix(self):
        """Position ID prefix filter narrows results to matching UUIDs."""
        task = _make_task()
        client = _auth_client(task.user)
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

        target = Position.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            instrument="USD_JPY",
            direction=Direction.LONG,
            units=1000,
            entry_price=Decimal("150.500"),
            entry_time=now,
            is_open=True,
        )
        Position.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            instrument="USD_JPY",
            direction=Direction.SHORT,
            units=-1000,
            entry_price=Decimal("150.800"),
            entry_time=now,
            is_open=True,
        )

        prefix = str(target.pk)[:8]
        response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/positions/",
            {"position_id": prefix},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1
        assert response.data["results"][0]["id"] == str(target.pk)

    def test_positions_filter_by_position_id_no_match(self):
        task = _make_task()
        client = _auth_client(task.user)
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

        Position.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            instrument="USD_JPY",
            direction=Direction.LONG,
            units=1000,
            entry_price=Decimal("150.500"),
            entry_time=now,
            is_open=True,
        )

        response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/positions/",
            {"position_id": "ffffffff"},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 0


@pytest.mark.django_db
class TestPositionLifecycle:
    """GET /api/trading/tasks/backtest/{id}/position-lifecycle/"""

    def test_returns_chain_and_synthesizes_missing_close(self):
        task = _make_task()
        client = _auth_client(task.user)
        old_position_id = uuid4()
        rebuilt_position_id = uuid4()
        old_entry_time = datetime(2024, 9, 11, 10, 19, 40, tzinfo=timezone.utc)
        old_exit_time = datetime(2024, 9, 11, 10, 25, 50, tzinfo=timezone.utc)
        rebuilt_entry_time = datetime(2024, 9, 11, 10, 26, 5, tzinfo=timezone.utc)

        Position.objects.create(
            id=old_position_id,
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            instrument="USD_JPY",
            direction="short",
            units=-7000,
            entry_price=Decimal("142.2170"),
            entry_time=old_entry_time,
            exit_price=Decimal("142.4630"),
            exit_time=old_exit_time,
            is_open=False,
            layer_index=1,
            retracement_count=6,
            planned_exit_price=Decimal("141.8240"),
            stop_loss_price=Decimal("142.4570"),
        )
        Position.objects.create(
            id=rebuilt_position_id,
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            instrument="USD_JPY",
            direction="short",
            units=-7000,
            entry_price=Decimal("142.2170"),
            entry_time=rebuilt_entry_time,
            is_open=True,
            is_rebuild=True,
            layer_index=1,
            retracement_count=6,
            planned_exit_price=Decimal("141.8240"),
            stop_loss_price=Decimal("142.4570"),
        )

        Trade.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            timestamp=old_entry_time,
            direction="short",
            units=7000,
            instrument="USD_JPY",
            price=Decimal("142.2170"),
            execution_method="open_position",
            layer_index=1,
            retracement_count=6,
            position_id=old_position_id,
        )
        Trade.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            timestamp=old_exit_time,
            direction="short",
            units=7000,
            instrument="USD_JPY",
            price=Decimal("142.4630"),
            execution_method="stop_loss",
            layer_index=1,
            retracement_count=6,
            position_id=old_position_id,
            description="[PROTECTION] Stop loss",
        )
        Trade.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            timestamp=rebuilt_entry_time,
            direction="short",
            units=7000,
            instrument="USD_JPY",
            price=Decimal("142.2170"),
            execution_method="rebuild_position",
            layer_index=1,
            retracement_count=6,
            position_id=rebuilt_position_id,
            is_rebuild=True,
        )

        TaskLog.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            level=LogLevel.INFO,
            component="position.lifecycle",
            message="POSITION_OPENED",
            details={
                "context": {
                    "position_id": str(old_position_id),
                    "lifecycle_event": "OPENED",
                    "direction": "short",
                    "instrument": "USD_JPY",
                    "units": 7000,
                    "entry_price": "142.2170",
                    "entry_time": old_entry_time.isoformat(),
                    "layer_index": 1,
                    "retracement_count": 6,
                    "planned_exit_price": "141.8240",
                }
            },
        )
        TaskLog.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            level=LogLevel.INFO,
            component="position.lifecycle",
            message="POSITION_REBUILT",
            details={
                "context": {
                    "position_id": str(rebuilt_position_id),
                    "original_position_id": str(old_position_id),
                    "lifecycle_event": "REBUILT",
                    "direction": "short",
                    "instrument": "USD_JPY",
                    "units": 7000,
                    "entry_price": "142.2170",
                    "entry_time": rebuilt_entry_time.isoformat(),
                    "layer_index": 1,
                    "retracement_count": 6,
                    "planned_exit_price": "141.8240",
                }
            },
        )

        response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/position-lifecycle/",
            {"position_id": str(rebuilt_position_id)},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["matched_position_id"] == str(rebuilt_position_id)
        assert response.data["position_ids"] == [str(old_position_id), str(rebuilt_position_id)]

        # chain_realized_pnl is the sum of every per-position realized
        # value in the chain.  The rebuilt position is still open so it
        # contributes nothing; only the SL-closed original counts.
        assert response.data["chain_realized_pnl"] == "-1722.0000000000"
        assert response.data["chain_realized_pnl_currency"] == "JPY"
        assert response.data["chain_realized_pnl_money"] == {
            "amount": "-1722",
            "currency": "JPY",
        }
        assert response.data["chain_realized_pnl_display_money"]["currency"] == "USD"
        assert (
            response.data["chain_realized_pnl_display_conversion_context"]["source_currency"]
            == "JPY"
        )
        assert (
            response.data["chain_realized_pnl_display_conversion_context"]["target_currency"]
            == "USD"
        )

        old_position = response.data["positions"][0]
        rebuilt_position = response.data["positions"][1]

        assert old_position["summary"]["close_reason"] == "stop_loss"
        assert old_position["summary"]["realized_pnl"] == "-1722.0000000000"
        assert old_position["summary"]["realized_pnl_currency"] == "JPY"
        assert old_position["summary"]["realized_pnl_money"] == {
            "amount": "-1722",
            "currency": "JPY",
        }
        assert old_position["summary"]["realized_pnl_display_money"]["currency"] == "USD"
        assert (
            old_position["summary"]["realized_pnl_display_conversion_context"]["source_currency"]
            == "JPY"
        )
        assert [event["kind"] for event in old_position["events"]] == [
            "opened",
            "stop_loss_closed",
            "rebuilt_into",
        ]
        assert old_position["events"][1]["related_position_id"] == str(rebuilt_position_id)
        assert old_position["events"][1]["realized_pnl_money"] == {
            "amount": "-1722",
            "currency": "JPY",
        }
        assert old_position["events"][1]["realized_pnl_display_money"]["currency"] == "USD"

        assert rebuilt_position["original_position_id"] == str(old_position_id)
        assert [event["kind"] for event in rebuilt_position["events"]] == ["rebuilt"]
        assert rebuilt_position["events"][0]["related_position_id"] == str(old_position_id)

    def test_rejects_ambiguous_prefix(self):
        task = _make_task()
        client = _auth_client(task.user)

        for raw_id in (
            "abcd1234-1111-4111-8111-111111111111",
            "abcd1234-2222-4222-8222-222222222222",
        ):
            Position.objects.create(
                id=raw_id,
                task_type=TaskType.BACKTEST,
                task_id=task.pk,
                execution_id=task.execution_id,
                instrument="USD_JPY",
                direction="long",
                units=1000,
                entry_price=Decimal("150"),
                entry_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
                is_open=True,
            )

        response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/position-lifecycle/",
            {"position_id": "abcd1234"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        _assert_invalid_query_param(response, "Invalid query parameters.")


@pytest.mark.django_db
class TestOrders:
    """GET /api/trading/tasks/backtest/{id}/orders/"""

    def test_with_orders(self):
        task = _make_task()
        client = _auth_client(task.user)

        Order.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            instrument="USD_JPY",
            order_type=OrderType.MARKET,
            direction=Direction.LONG,
            units=1000,
            fill_price=Decimal("150.500"),
            status=OrderStatus.FILLED,
            is_dry_run=True,
        )

        response = client.get(f"/api/trading/tasks/backtest/{task.pk}/orders/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1
        order = response.data["results"][0]
        assert order["instrument"] == "USD_JPY"
        assert order["status"] == "filled"
        assert "execution_id" not in order

    def test_without_orders(self):
        task = _make_task()
        client = _auth_client(task.user)

        response = client.get(f"/api/trading/tasks/backtest/{task.pk}/orders/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 0

    def test_orders_filter_by_order_id_prefix(self):
        """Order ID prefix filter narrows results to matching UUIDs."""
        task = _make_task()
        client = _auth_client(task.user)

        target = Order.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            instrument="USD_JPY",
            order_type=OrderType.MARKET,
            direction=Direction.LONG,
            units=1000,
            fill_price=Decimal("150.500"),
            status=OrderStatus.FILLED,
            is_dry_run=True,
        )
        Order.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=task.execution_id,
            instrument="USD_JPY",
            order_type=OrderType.MARKET,
            direction=Direction.SHORT,
            units=500,
            fill_price=Decimal("150.700"),
            status=OrderStatus.FILLED,
            is_dry_run=True,
        )

        prefix = str(target.pk)[:8]
        response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/orders/",
            {"order_id": prefix},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1
        assert response.data["results"][0]["id"] == str(target.pk)


@pytest.mark.django_db
class TestExecutions:
    """GET /api/trading/tasks/backtest/{id}/executions/"""

    def test_with_execution_history(self):
        task = _make_task()
        client = _auth_client(task.user)
        from uuid import uuid4

        # Create a completed past execution
        old_execution_id = uuid4()
        CeleryTaskStatus.objects.create(
            task_name="trading.tasks.run_backtest_task",
            instance_key=f"{task.pk}:{old_execution_id}",
            status=CeleryTaskStatus.Status.COMPLETED,
        )

        # Set up current execution
        new_execution_id = uuid4()
        task.execution_id = new_execution_id
        task.status = "running"
        task.save(update_fields=["execution_id", "status", "updated_at"])

        CeleryTaskStatus.objects.create(
            task_name="trading.tasks.run_backtest_task",
            instance_key=f"{task.pk}:{new_execution_id}",
            status=CeleryTaskStatus.Status.RUNNING,
        )

        response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/executions/?include_metrics=true"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 2
        ids = {r["id"] for r in response.data["results"]}
        assert str(new_execution_id) in ids
        assert str(old_execution_id) in ids
        current = next(r for r in response.data["results"] if r["id"] == str(new_execution_id))
        assert current["status"] == "running"
        assert "metrics" in current

    def test_paginate_before_metric_aggregation_and_get_single_execution(self):
        task = _make_task()
        client = _auth_client(task.user)
        from uuid import uuid4

        execution_ids = [uuid4(), uuid4(), uuid4()]
        for execution_id in execution_ids:
            CeleryTaskStatus.objects.create(
                task_name="trading.tasks.run_backtest_task",
                instance_key=f"{task.pk}:{execution_id}",
                status=CeleryTaskStatus.Status.COMPLETED,
            )

        response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/executions/",
            {"page": 1, "page_size": 1, "include_metrics": "true"},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 4
        assert len(response.data["results"]) == 1
        execution_id = response.data["results"][0]["id"]
        assert "metrics" in response.data["results"][0]

        detail_response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/executions/{execution_id}/",
            {"include_metrics": "true"},
        )
        assert detail_response.status_code == status.HTTP_200_OK
        assert detail_response.data["id"] == execution_id
        assert "metrics" in detail_response.data

        missing_response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/executions/{uuid4()}/",
        )
        assert missing_response.status_code == status.HTTP_404_NOT_FOUND

    def test_execution_detail_prefers_persisted_snapshot(self):
        task = _make_task()
        client = _auth_client(task.user)
        from uuid import uuid4

        execution_id = uuid4()
        CeleryTaskStatus.objects.create(
            task_name="trading.tasks.run_backtest_task",
            instance_key=f"{task.pk}:{execution_id}",
            status=CeleryTaskStatus.Status.COMPLETED,
        )
        TaskExecutionSnapshot.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=execution_id,
            summary={
                "timestamp": "2026-03-21T00:00:00+00:00",
                "pnl": {"realized": "12.5", "unrealized": "0"},
                "counts": {
                    "total_trades": 7,
                    "open_positions": 0,
                    "closed_positions": 3,
                },
                "execution": {
                    "current_balance": "10012.5",
                    "ticks_processed": 42,
                    "account_currency": "USD",
                    "current_balance_display": "10012.5",
                    "display_currency": "USD",
                },
                "tick": {
                    "timestamp": "2026-03-21T00:00:00+00:00",
                    "bid": "150.1000",
                    "ask": "150.1100",
                    "mid": "150.1050",
                },
                "task": {
                    "status": "completed",
                    "started_at": None,
                    "completed_at": "2026-03-21T00:00:10+00:00",
                    "error_message": None,
                    "progress": 100,
                },
            },
            metrics={
                "total_pnl": "12.5",
                "unrealized_pnl": "0",
                "total_trades": 7,
                "winning_trades": 5,
                "losing_trades": 2,
                "win_rate": "71.4286",
            },
        )

        response = client.get(
            f"/api/trading/tasks/backtest/{task.pk}/executions/{execution_id}/",
            {"include_metrics": "true"},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["metrics"]["total_trades"] == 7
        assert response.data["metrics"]["winning_trades"] == 5
