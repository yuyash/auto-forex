"""Extended integration tests for supervisor task."""

from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from apps.market.enums import ApiType
from apps.market.models import CeleryTaskStatus, OandaAccounts
from apps.market.tasks.supervisor import AccountStreamTarget, TickSupervisorRunner
from apps.trading.enums import TaskStatus
from apps.trading.models import StrategyConfiguration, TradingTask


@pytest.mark.django_db
class TestTickSupervisorRunnerExtendedIntegration:
    """Extended integration tests for TickSupervisorRunner."""

    def test_target_account_pks_returns_only_active_trading_accounts(self, user: Any) -> None:
        practice = OandaAccounts.objects.create(
            user=user,
            account_id="101-001-1234567-001",
            api_type=ApiType.PRACTICE,
            api_token="token-1",
        )
        live = OandaAccounts.objects.create(
            user=user,
            account_id="001-001-1234567-001",
            api_type=ApiType.LIVE,
            api_token="token-2",
        )
        unused = OandaAccounts.objects.create(
            user=user,
            account_id="101-001-1234567-002",
            api_type=ApiType.PRACTICE,
            api_token="token-3",
        )
        config = StrategyConfiguration.objects.create(
            user=user,
            name="Config",
            strategy_type="snowball",
            parameters={"instrument": "USD_JPY"},
        )
        TradingTask.objects.create(
            user=user,
            config=config,
            oanda_account=practice,
            name="Practice task",
            instrument="USD_JPY",
            status=TaskStatus.RUNNING,
        )
        TradingTask.objects.create(
            user=user,
            config=config,
            oanda_account=live,
            name="Live task",
            instrument="USD_JPY",
            status=TaskStatus.STARTING,
        )
        TradingTask.objects.create(
            user=user,
            config=config,
            oanda_account=unused,
            name="Stopped task",
            instrument="USD_JPY",
            status=TaskStatus.STOPPED,
        )

        runner = TickSupervisorRunner()

        assert runner._target_account_pks() == [practice.pk, live.pk]
        assert runner._target_account_targets() == [
            AccountStreamTarget(
                account_pk=practice.pk,
                instruments=("USD_JPY",),
            ),
            AccountStreamTarget(
                account_pk=live.pk,
                instruments=("USD_JPY",),
            ),
        ]

    @patch("apps.market.tasks.publish_oanda_ticks.apply_async")
    def test_ensure_publishers_running(
        self,
        mock_pub_apply_async: Any,
    ) -> None:
        mock_client = MagicMock()
        mock_client.get.return_value = None
        CeleryTaskStatus.objects.create(
            task_name="market.tasks.publish_oanda_ticks",
            instance_key="2",
            status=CeleryTaskStatus.Status.RUNNING,
            last_heartbeat_at=timezone.now(),
            meta={"account_id": 2, "instruments": ["EUR_USD"]},
        )

        runner = TickSupervisorRunner()
        runner._ensure_publishers_running(
            client=mock_client,
            account_targets=[
                AccountStreamTarget(1, ("USD_JPY",)),
                AccountStreamTarget(2, ("EUR_USD",)),
            ],
        )

        mock_pub_apply_async.assert_called_once_with(
            kwargs={"account_id": 1, "instruments": ["USD_JPY"]},
            queue="market",
        )

    @patch("apps.market.tasks.publish_oanda_ticks.apply_async")
    def test_requests_restart_when_running_publisher_has_wrong_instruments(
        self,
        mock_pub_apply_async: Any,
    ) -> None:
        CeleryTaskStatus.objects.create(
            task_name="market.tasks.publish_oanda_ticks",
            instance_key="1",
            status=CeleryTaskStatus.Status.RUNNING,
            last_heartbeat_at=timezone.now(),
            meta={"account_id": 1, "instruments": ["EUR_USD"]},
        )
        mock_client = MagicMock()
        mock_client.get.return_value = None

        runner = TickSupervisorRunner()
        runner._ensure_publishers_running(
            client=mock_client,
            account_targets=[AccountStreamTarget(1, ("USD_JPY",))],
        )

        mock_pub_apply_async.assert_not_called()
        row = CeleryTaskStatus.objects.get(
            task_name="market.tasks.publish_oanda_ticks",
            instance_key="1",
        )
        assert row.status == CeleryTaskStatus.Status.STOPPING
        assert "USD_JPY" in row.status_message

    @patch("apps.market.tasks.subscribe_ticks_to_db.apply_async")
    def test_ensure_subscriber_running(self, mock_sub_apply_async: Any) -> None:
        mock_client = MagicMock()
        mock_client.get.return_value = None

        runner = TickSupervisorRunner()
        runner._ensure_subscriber_running(mock_client)

        mock_sub_apply_async.assert_called_once_with(queue="market")

    def test_run_does_not_self_schedule_supervisor(self) -> None:
        mock_client = MagicMock()
        mock_service_instance = MagicMock()
        mock_service_instance.should_stop.return_value = False

        with (
            patch("apps.market.tasks.supervisor.redis_client", return_value=mock_client),
            patch("apps.market.tasks.supervisor.acquire_lock", return_value="owner-1"),
            patch("apps.market.tasks.supervisor.release_lock_if_owner"),
            patch(
                "apps.market.tasks.supervisor.CeleryTaskService",
                return_value=mock_service_instance,
            ),
            patch("apps.market.tasks.subscribe_ticks_to_db.apply_async") as mock_subscribe,
            patch("apps.market.tasks.ensure_tick_pubsub_running.apply_async") as mock_supervisor,
        ):
            TickSupervisorRunner().run()

        mock_subscribe.assert_called_once_with(queue="market")
        mock_supervisor.assert_not_called()

    def test_fresh_market_task_ignores_stale_rows(self) -> None:
        CeleryTaskStatus.objects.create(
            task_name="market.tasks.subscribe_ticks_to_db",
            instance_key="default",
            status=CeleryTaskStatus.Status.RUNNING,
            last_heartbeat_at=timezone.now() - timedelta(minutes=10),
            meta={"kind": "subscriber"},
        )

        runner = TickSupervisorRunner()

        assert (
            runner._fresh_market_task(
                task_name="market.tasks.subscribe_ticks_to_db",
                instance_key="default",
            )
            is None
        )
