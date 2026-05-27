"""E2E tests for /api/trading/tasks/backtest/."""

from decimal import Decimal
from uuid import uuid4

import pytest

from apps.trading.enums import TaskStatus, TaskType
from apps.trading.models import BacktestTask, ExecutionState, TaskExecutionSnapshot, TaskLog


def _create_backtest(client, config_id, name):
    """Helper: create a backtest task and return its ID."""
    resp = client.post(
        "/api/trading/tasks/backtest/",
        {
            "name": name,
            "config": str(config_id),
            "instrument": "USD_JPY",
            "start_time": "2026-01-02T00:00:00Z",
            "end_time": "2026-01-02T21:59:58Z",
            "initial_balance": "10000.00",
            "data_source": "postgresql",
            "tick_granularity": "tick",
        },
        format="json",
    )
    assert resp.status_code in (200, 201), resp.data
    # Create serializer may not return id; fetch from list
    list_resp = client.get("/api/trading/tasks/backtest/", {"search": name})
    assert list_resp.status_code == 200
    results = list_resp.data.get("results", list_resp.data)
    task = next(t for t in results if t["name"] == name)
    return task["id"]


@pytest.mark.django_db
class TestBacktestTasks:
    # ── Basic CRUD ────────────────────────────────────────────────────────

    def test_list_backtest_tasks(self, authenticated_client):
        resp = authenticated_client.get("/api/trading/tasks/backtest/")
        assert resp.status_code == 200

    def test_create_backtest_task(self, authenticated_client, strategy_config):
        _create_backtest(authenticated_client, strategy_config.id, "E2E Backtest")

    def test_get_backtest_detail(self, authenticated_client, strategy_config):
        task_id = _create_backtest(authenticated_client, strategy_config.id, "E2E Backtest Detail")
        resp = authenticated_client.get(f"/api/trading/tasks/backtest/{task_id}/")
        assert resp.status_code == 200
        assert resp.data["id"] == task_id
        assert resp.data["action_policy"]["can_start"] is True
        assert resp.data["action_policy"]["can_edit_metadata"] is True

    def test_delete_backtest_task(self, authenticated_client, strategy_config):
        task_id = _create_backtest(authenticated_client, strategy_config.id, "E2E Backtest Delete")
        resp = authenticated_client.delete(f"/api/trading/tasks/backtest/{task_id}/")
        assert resp.status_code in (200, 204)

    # ── Pagination ────────────────────────────────────────────────────────

    def test_list_pagination(self, authenticated_client, strategy_config):
        """Create 2 tasks and verify paginated response structure."""
        _create_backtest(authenticated_client, strategy_config.id, "BT Pagination 1")
        _create_backtest(authenticated_client, strategy_config.id, "BT Pagination 2")
        resp = authenticated_client.get("/api/trading/tasks/backtest/")
        assert resp.status_code == 200
        assert resp.data["count"] >= 2
        assert "results" in resp.data
        assert "next" in resp.data
        assert "previous" in resp.data

    # ── Filtering ─────────────────────────────────────────────────────────

    def test_list_filter_by_status(self, authenticated_client, strategy_config):
        """Verify status filter returns only matching tasks."""
        _create_backtest(authenticated_client, strategy_config.id, "BT Filter Status")
        resp = authenticated_client.get("/api/trading/tasks/backtest/", {"status": "created"})
        assert resp.status_code == 200
        assert all(t["status"] == "created" for t in resp.data["results"])
        assert all("action_policy" in t for t in resp.data["results"])

    def test_list_search(self, authenticated_client, strategy_config):
        """Verify search filter finds tasks by name."""
        _create_backtest(authenticated_client, strategy_config.id, "UniqueBacktestSearchName789")
        resp = authenticated_client.get(
            "/api/trading/tasks/backtest/", {"search": "UniqueBacktestSearchName789"}
        )
        assert resp.status_code == 200
        assert resp.data["count"] == 1

    # ── Start + verify sub-resources ──────────────────────────────────────

    @pytest.mark.timeout(300)
    def test_start_and_verify_sub_resources(self, authenticated_client, strategy_config):
        """Start a backtest, wait for completion, verify sub-resources have data."""
        task_id = _create_backtest(authenticated_client, strategy_config.id, "BT Execute SubRes")

        # Start (runs synchronously in eager mode)
        resp = authenticated_client.post(f"/api/trading/tasks/backtest/{task_id}/start/")
        assert resp.status_code == 200

        # Check task completed
        detail = authenticated_client.get(f"/api/trading/tasks/backtest/{task_id}/")
        assert detail.status_code == 200
        assert detail.data["status"] in ("completed", "stopped", "failed")

        # ── Logs ──────────────────────────────────────────────────────────
        logs_resp = authenticated_client.get(f"/api/trading/tasks/backtest/{task_id}/logs/")
        assert logs_resp.status_code == 200
        assert logs_resp.data["count"] > 0
        log_item = logs_resp.data["results"][0]
        assert "level" in log_item
        assert "message" in log_item
        assert "timestamp" in log_item

        # ── Summary ───────────────────────────────────────────────────────
        summary = authenticated_client.get(f"/api/trading/tasks/backtest/{task_id}/summary/")
        assert summary.status_code == 200
        assert "task" in summary.data
        assert "pnl" in summary.data
        assert "counts" in summary.data

        # ── Executions ────────────────────────────────────────────────────
        exec_resp = authenticated_client.get(f"/api/trading/tasks/backtest/{task_id}/executions/")
        assert exec_resp.status_code == 200
        assert exec_resp.data["count"] > 0

        # ── Events ────────────────────────────────────────────────────────
        events_resp = authenticated_client.get(f"/api/trading/tasks/backtest/{task_id}/events/")
        assert events_resp.status_code == 200

        # ── Metrics ───────────────────────────────────────────────────────
        metrics_resp = authenticated_client.get(
            f"/api/trading/tasks/backtest/{task_id}/strategy/metrics/"
        )
        assert metrics_resp.status_code == 200
        assert "results" in metrics_resp.data
        assert "count" in metrics_resp.data

        # ── Sub-resource pagination ───────────────────────────────────────
        logs_page = authenticated_client.get(
            f"/api/trading/tasks/backtest/{task_id}/logs/", {"page_size": 1}
        )
        assert logs_page.status_code == 200
        assert len(logs_page.data["results"]) <= 1
        if logs_page.data["count"] > 1:
            assert logs_page.data["next"] is not None

        # ── Sub-resource filtering ────────────────────────────────────────
        logs_filtered = authenticated_client.get(
            f"/api/trading/tasks/backtest/{task_id}/logs/", {"level": "INFO"}
        )
        assert logs_filtered.status_code == 200

    # ── Remaining sub-resource endpoints (no execution needed) ────────────

    def test_sub_resources_accessible(self, authenticated_client, strategy_config):
        """Verify all sub-resource endpoints return 200 on a non-started task."""
        task_id = _create_backtest(
            authenticated_client, strategy_config.id, "E2E Backtest SubRes Access"
        )
        for endpoint in (
            "logs",
            "events",
            "strategy-events",
            "trades",
            "positions",
            "orders",
            "summary",
            "executions",
            "strategy/snapshot",
            "strategy/history",
            "strategy/metrics",
        ):
            resp = authenticated_client.get(f"/api/trading/tasks/backtest/{task_id}/{endpoint}/")
            assert resp.status_code == 200, f"{endpoint} returned {resp.status_code}"

    def test_adjust_balance_updates_paused_execution_state(
        self, authenticated_client, strategy_config
    ):
        task_id = _create_backtest(
            authenticated_client, strategy_config.id, "E2E Backtest Balance Adjust"
        )
        execution_id = uuid4()
        task = BacktestTask.objects.get(pk=task_id)
        task.status = TaskStatus.PAUSED
        task.execution_id = execution_id
        task.save(update_fields=["status", "execution_id", "updated_at"])
        state = ExecutionState.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=execution_id,
            current_balance=Decimal("10000.0000000000"),
            ticks_processed=42,
        )

        resp = authenticated_client.post(
            f"/api/trading/tasks/backtest/{task_id}/adjust-balance/",
            {"current_balance": "12500.5000000000", "reason": "manual deposit"},
            format="json",
        )

        assert resp.status_code == 200, resp.data
        state.refresh_from_db()
        assert state.current_balance == Decimal("12500.5000000000")
        assert state.state_version == 1
        assert resp.data["previous_balance"] == "10000.0000000000"
        assert resp.data["current_balance"] == "12500.5000000000"
        assert resp.data["adjustment"] == "2500.5000000000"
        assert resp.data["previous_balance_display_money"] == {
            "amount": "10000.0000000000",
            "currency": "USD",
        }
        assert resp.data["current_balance_display_money"] == {
            "amount": "12500.5000000000",
            "currency": "USD",
        }
        assert resp.data["adjustment_display_money"] == {
            "amount": "2500.5000000000",
            "currency": "USD",
        }
        assert resp.data["display_conversion_context"]["source_currency"] == "USD"
        assert resp.data["display_conversion_context"]["target_currency"] == "USD"
        assert resp.data["display_conversion_context"]["conversion_policy"] == "identity"
        log = TaskLog.objects.get(
            task_id=task.pk,
            component="backtest.balance_adjustment",
        )
        assert log.execution_id == execution_id
        assert log.details["reason"] == "manual deposit"
        assert log.details["current_balance_display_money"] == {
            "amount": "12500.5",
            "currency": "USD",
        }
        assert log.details["display_conversion_context"]["conversion_policy"] == "identity"

    def test_adjust_balance_updates_stopped_execution_state(
        self, authenticated_client, strategy_config
    ):
        task_id = _create_backtest(
            authenticated_client, strategy_config.id, "E2E Backtest Balance Stopped"
        )
        execution_id = uuid4()
        task = BacktestTask.objects.get(pk=task_id)
        task.status = TaskStatus.STOPPED
        task.execution_id = execution_id
        task.save(update_fields=["status", "execution_id", "updated_at"])
        state = ExecutionState.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=execution_id,
            current_balance=Decimal("10000.0000000000"),
            ticks_processed=42,
        )
        TaskExecutionSnapshot.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=execution_id,
            summary={
                "timestamp": None,
                "pnl": {"realized": "0", "unrealized": "0"},
                "counts": {},
                "execution": {
                    "current_balance": "10000.0000000000",
                    "ticks_processed": 42,
                },
                "tick": {},
                "task": {"status": "stopped"},
            },
            metrics={"current_balance": "10000.0000000000"},
        )

        resp = authenticated_client.post(
            f"/api/trading/tasks/backtest/{task_id}/adjust-balance/",
            {"current_balance": "11000.0000000000"},
            format="json",
        )

        assert resp.status_code == 200, resp.data
        state.refresh_from_db()
        assert state.current_balance == Decimal("11000.0000000000")
        snapshot = TaskExecutionSnapshot.objects.get(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=execution_id,
        )
        assert snapshot.summary["execution"]["current_balance"] == "11000.0000000000"
        assert snapshot.metrics["current_balance"] == "11000.0000000000"

        summary_resp = authenticated_client.get(
            f"/api/trading/tasks/backtest/{task_id}/summary/",
            {"execution_id": str(execution_id)},
        )
        assert summary_resp.status_code == 200, summary_resp.data
        assert summary_resp.data["execution"]["current_balance"] == "11000.0000000000"

    def test_adjust_balance_requires_resumable_task(self, authenticated_client, strategy_config):
        task_id = _create_backtest(
            authenticated_client, strategy_config.id, "E2E Backtest Balance Running"
        )
        execution_id = uuid4()
        task = BacktestTask.objects.get(pk=task_id)
        task.status = TaskStatus.RUNNING
        task.execution_id = execution_id
        task.save(update_fields=["status", "execution_id", "updated_at"])
        ExecutionState.objects.create(
            task_type=TaskType.BACKTEST,
            task_id=task.pk,
            execution_id=execution_id,
            current_balance=Decimal("10000.0000000000"),
            ticks_processed=42,
        )

        resp = authenticated_client.post(
            f"/api/trading/tasks/backtest/{task_id}/adjust-balance/",
            {"current_balance": "12500.0000000000"},
            format="json",
        )

        assert resp.status_code == 400
        assert resp.data["error_code"] == "backtest_balance_requires_paused_or_stopped"

    # ── Auth ──────────────────────────────────────────────────────────────

    def test_backtest_tasks_unauthenticated(self, api_client):
        resp = api_client.get("/api/trading/tasks/backtest/")
        assert resp.status_code == 401
