"""Integration tests for trading API views."""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.market.models import MarketEvent
from apps.trading.enums import TaskStatus
from tests.integration.factories import (
    BacktestTaskFactory,
    OandaAccountFactory,
    StrategyConfigurationFactory,
    TradingTaskFactory,
    UserFactory,
)


@pytest.mark.django_db
class TestStrategyConfigAPI:
    def _auth_client(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_list_configs(self):
        user = UserFactory()
        StrategyConfigurationFactory(user=user)
        StrategyConfigurationFactory(user=user)
        client = self._auth_client(user)
        response = client.get("/api/trading/strategy-configs/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 2

    def test_create_config(self):
        user = UserFactory()
        client = self._auth_client(user)
        data = {
            "name": "New Config",
            "strategy_type": "snowball",
            "parameters": {
                "instrument": "USD_JPY",
                "base_units": 1000,
                "m_pips": 50,
                "n_pips": 30,
                "r_max": 5,
                "f_max": 3,
            },
        }
        response = client.post("/api/trading/strategy-configs/", data, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["name"] == "New Config"

    def test_get_config_detail(self):
        user = UserFactory()
        config = StrategyConfigurationFactory(user=user)
        client = self._auth_client(user)
        response = client.get(f"/api/trading/strategy-configs/{config.id}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == str(config.id)
        assert response.data["has_running_tasks"] is False

    def test_update_config(self):
        user = UserFactory()
        config = StrategyConfigurationFactory(user=user)
        client = self._auth_client(user)
        data = {
            "name": "Updated Name",
            "strategy_type": "snowball",
            "parameters": config.parameters,
        }
        response = client.put(f"/api/trading/strategy-configs/{config.id}/", data, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "Updated Name"

    def test_update_config_allows_edit_when_other_task_is_running(self):
        user = UserFactory()
        config = StrategyConfigurationFactory(user=user)
        other_config = StrategyConfigurationFactory(user=user)
        account = OandaAccountFactory(user=user)
        TradingTaskFactory(
            user=user,
            config=other_config,
            oanda_account=account,
            status=TaskStatus.RUNNING,
        )
        client = self._auth_client(user)
        data = {"name": "Blocked Update", "parameters": config.parameters}
        response = client.put(f"/api/trading/strategy-configs/{config.id}/", data, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "Blocked Update"

    def test_update_config_blocked_when_same_config_task_is_running(self):
        user = UserFactory()
        config = StrategyConfigurationFactory(user=user)
        account = OandaAccountFactory(user=user)
        TradingTaskFactory(
            user=user,
            config=config,
            oanda_account=account,
            status=TaskStatus.RUNNING,
        )
        client = self._auth_client(user)
        data = {"name": "Blocked Update", "parameters": config.parameters}
        response = client.put(f"/api/trading/strategy-configs/{config.id}/", data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert (
            "cannot be updated while tasks using this configuration are running"
            in response.data["detail"].lower()
        )

    def test_delete_config(self):
        user = UserFactory()
        config = StrategyConfigurationFactory(user=user)
        client = self._auth_client(user)
        response = client.delete(f"/api/trading/strategy-configs/{config.id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_delete_config_in_use(self):
        user = UserFactory()
        config = StrategyConfigurationFactory(user=user)
        BacktestTaskFactory(user=user, config=config)
        client = self._auth_client(user)
        response = client.delete(f"/api/trading/strategy-configs/{config.id}/")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_other_user_cannot_access(self):
        user1 = UserFactory()
        user2 = UserFactory()
        config = StrategyConfigurationFactory(user=user1)
        client = self._auth_client(user2)
        response = client.get(f"/api/trading/strategy-configs/{config.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_list_filter_by_strategy_type(self):
        user = UserFactory()
        StrategyConfigurationFactory(user=user, strategy_type="snowball")
        client = self._auth_client(user)
        response = client.get("/api/trading/strategy-configs/?strategy_type=snowball")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] >= 1

    def test_list_search(self):
        user = UserFactory()
        StrategyConfigurationFactory(user=user, name="My Special Config")
        client = self._auth_client(user)
        response = client.get("/api/trading/strategy-configs/?search=Special")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1


@pytest.mark.django_db
class TestStrategyAPI:
    def test_list_strategies(self):
        user = UserFactory()
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/trading/strategies/")
        assert response.status_code == status.HTTP_200_OK
        assert "strategies" in response.data
        assert response.data["count"] >= 1

    def test_strategy_defaults(self):
        user = UserFactory()
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/trading/strategies/snowball/defaults/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["strategy_id"] == "snowball"

    def test_strategy_defaults_not_found(self):
        user = UserFactory()
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/api/trading/strategies/nonexistent/defaults/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_unauthenticated_access(self):
        client = APIClient()
        response = client.get("/api/trading/strategies/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestBacktestTaskAPI:
    def _auth_client(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_list_tasks(self):
        user = UserFactory()
        config = StrategyConfigurationFactory(user=user)
        BacktestTaskFactory(user=user, config=config)
        client = self._auth_client(user)
        response = client.get("/api/trading/tasks/backtest/")
        assert response.status_code == status.HTTP_200_OK

    def test_list_filter_by_status(self):
        user = UserFactory()
        config = StrategyConfigurationFactory(user=user)
        BacktestTaskFactory(user=user, config=config, status=TaskStatus.CREATED)
        BacktestTaskFactory(user=user, config=config, status=TaskStatus.COMPLETED, name="done")
        client = self._auth_client(user)
        response = client.get("/api/trading/tasks/backtest/?status=created")
        assert response.status_code == status.HTTP_200_OK

    def test_retrieve_task(self):
        user = UserFactory()
        config = StrategyConfigurationFactory(user=user)
        task = BacktestTaskFactory(user=user, config=config)
        client = self._auth_client(user)
        response = client.get(f"/api/trading/tasks/backtest/{task.pk}/")
        assert response.status_code == status.HTTP_200_OK

    def test_isolation_between_users(self):
        user1 = UserFactory()
        user2 = UserFactory()
        config = StrategyConfigurationFactory(user=user1)
        BacktestTaskFactory(user=user1, config=config)
        client = self._auth_client(user2)
        response = client.get("/api/trading/tasks/backtest/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 0


@pytest.mark.django_db
class TestTradingTaskAPI:
    def _auth_client(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_list_tasks(self):
        user = UserFactory()
        config = StrategyConfigurationFactory(user=user)
        account = OandaAccountFactory(user=user)
        TradingTaskFactory(user=user, config=config, oanda_account=account)
        client = self._auth_client(user)
        response = client.get("/api/trading/tasks/trading/")
        assert response.status_code == status.HTTP_200_OK

    def test_retrieve_task(self):
        task = TradingTaskFactory()
        client = self._auth_client(task.user)
        response = client.get(f"/api/trading/tasks/trading/{task.pk}/")
        assert response.status_code == status.HTTP_200_OK

    def test_isolation_between_users(self):
        TradingTaskFactory()
        other_user = UserFactory()
        client = self._auth_client(other_user)
        response = client.get("/api/trading/tasks/trading/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 0

    def test_market_events_endpoint_returns_only_task_events(self):
        task = TradingTaskFactory(status=TaskStatus.RUNNING)
        other_task = TradingTaskFactory(user=task.user)
        MarketEvent.objects.create(
            event_type="tick_stream_retry",
            category="market",
            severity="warning",
            description="Relevant stream retry",
            user=task.user,
            account=task.oanda_account,
            instrument=task.instrument,
            task_type="trading",
            task_id=task.pk,
            execution_id=task.execution_id,
            details={
                "exception_type": "RuntimeError",
                "exception_message": "raw upstream detail",
                "retry_delay_seconds": 5,
            },
        )
        MarketEvent.objects.create(
            event_type="tick_stream_retry",
            category="market",
            severity="warning",
            description="Other task stream retry",
            user=other_task.user,
            account=other_task.oanda_account,
            instrument=other_task.instrument,
            task_type="trading",
            task_id=other_task.pk,
            execution_id=other_task.execution_id,
        )
        MarketEvent.objects.create(
            event_type="tick_stream_started",
            category="market",
            severity="info",
            description="Unrelated account event",
            account=task.oanda_account,
            instrument=task.instrument,
        )

        client = self._auth_client(task.user)
        response = client.get(
            f"/api/trading/tasks/trading/{task.pk}/market-events/",
            {"severity": "warning", "ordering": "-created_at"},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1
        row = response.data["results"][0]
        assert row["task_id"] == str(task.pk)
        assert row["event_type"] == "tick_stream_retry"
        assert row["details"]["exception_type"] == "RuntimeError"
        assert row["details"]["retry_delay_seconds"] == 5
        assert "exception_message" not in row["details"]
