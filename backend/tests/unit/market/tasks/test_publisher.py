"""Unit tests for TickPublisherRunner."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4
from unittest.mock import MagicMock, patch

from apps.market.enums import MarketEventType
from apps.market.tasks.publisher import (
    TickPublisherRunner,
    build_tick_latency_payload,
    normalize_instruments,
    publisher_lock_key_for_account,
)


class TestTickPublisherRunnerInit:
    """Tests for __init__."""

    def test_initial_attributes(self):
        runner = TickPublisherRunner()

        assert runner.task_service is None
        assert runner.account is None


def test_publisher_lock_key_for_account_appends_account_id(settings):
    settings.MARKET_TICK_PUBLISHER_LOCK_KEY = "lock:pub"

    assert publisher_lock_key_for_account(7) == "lock:pub:7"


def test_normalize_instruments_sorts_and_deduplicates(settings):
    settings.MARKET_TICK_INSTRUMENTS = ["EUR_USD"]

    assert normalize_instruments(["USD_JPY", "EUR_USD", "USD_JPY"]) == [
        "EUR_USD",
        "USD_JPY",
    ]


def test_normalize_instruments_falls_back_to_settings(settings):
    settings.MARKET_TICK_INSTRUMENTS = ["USD_JPY"]

    assert normalize_instruments(None) == ["USD_JPY"]


def test_build_tick_latency_payload_uses_observed_wall_clock():
    payload = build_tick_latency_payload(
        datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
        observed_at=datetime(2026, 1, 1, 0, 0, 5, tzinfo=UTC),
    )

    assert payload["oanda_tick_published_at"] == "2026-01-01T00:00:05Z"
    assert payload["oanda_tick_publish_latency_seconds"] == "5.000000"


def test_should_log_tick_latency_respects_interval():
    observed_at = datetime(2026, 1, 1, 0, 1, tzinfo=UTC)

    assert TickPublisherRunner._should_log_tick_latency(
        last_logged_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        observed_at=observed_at,
        interval_seconds=60,
    )
    assert not TickPublisherRunner._should_log_tick_latency(
        last_logged_at=datetime(2026, 1, 1, 0, 0, 30, tzinfo=UTC),
        observed_at=observed_at,
        interval_seconds=60,
    )


class TestTickPublisherRunnerRun:
    """Tests for run method."""

    @patch("apps.market.tasks.publisher.redis_client")
    @patch("apps.market.tasks.publisher.acquire_lock", return_value=None)
    @patch("apps.market.tasks.publisher.current_task_id", return_value="task-1")
    @patch("apps.market.tasks.publisher.lock_value", return_value="worker-1")
    @patch("apps.market.tasks.publisher.CeleryTaskService")
    @patch("apps.market.tasks.publisher.settings")
    def test_run_already_locked_stops(
        self, mock_settings, MockService, mock_lock_val, mock_task_id, mock_acquire, mock_redis
    ):
        mock_settings.MARKET_REDIS_URL = "redis://localhost"
        mock_settings.MARKET_TICK_CHANNEL = "ticks"
        mock_settings.MARKET_TICK_PUBLISHER_LOCK_KEY = "lock:pub"

        svc_instance = MagicMock()
        svc_instance.should_stop.return_value = False
        MockService.return_value = svc_instance

        client = MagicMock()
        mock_redis.return_value = client

        runner = TickPublisherRunner()
        runner.run(account_id=1)

        svc_instance.start.assert_not_called()
        client.close.assert_called_once()

    @patch("apps.market.tasks.publisher.redis_client")
    @patch("apps.market.tasks.publisher.acquire_lock", return_value="owner-1")
    @patch("apps.market.tasks.publisher.LockHeartbeat")
    @patch("apps.market.tasks.publisher.current_task_id", return_value="task-1")
    @patch("apps.market.tasks.publisher.lock_value", return_value="worker-1")
    @patch("apps.market.tasks.publisher.CeleryTaskService")
    @patch("apps.market.tasks.publisher.OandaAccounts")
    @patch("apps.market.tasks.publisher.settings")
    def test_run_account_not_found_stops(
        self,
        mock_settings,
        MockAccounts,
        MockService,
        mock_lock_val,
        mock_task_id,
        MockHeartbeat,
        mock_acquire,
        mock_redis,
    ):
        mock_settings.MARKET_REDIS_URL = "redis://localhost"
        mock_settings.MARKET_TICK_CHANNEL = "ticks"
        mock_settings.MARKET_TICK_PUBLISHER_LOCK_KEY = "lock:pub"

        svc_instance = MagicMock()
        svc_instance.should_stop.return_value = False
        MockService.return_value = svc_instance

        MockAccounts.objects.filter.return_value.first.return_value = None

        client = MagicMock()
        mock_redis.return_value = client

        runner = TickPublisherRunner()
        runner.run(account_id=999)

        MockHeartbeat.return_value.start.assert_called_once()
        svc_instance.start.assert_called_once()
        svc_instance.mark_stopped.assert_called_once()
        assert MockService.call_args is not None
        assert svc_instance.start.call_args.kwargs["meta"]["instruments"] == ["EUR_USD"]

    @patch("apps.market.tasks.publisher.redis_client")
    @patch("apps.market.tasks.publisher.acquire_lock", return_value="owner-1")
    @patch("apps.market.tasks.publisher.LockHeartbeat")
    @patch("apps.market.tasks.publisher.current_task_id", return_value="task-1")
    @patch("apps.market.tasks.publisher.lock_value", return_value="worker-1")
    @patch("apps.market.tasks.publisher.CeleryTaskService")
    @patch("apps.market.tasks.publisher.settings")
    def test_run_stop_requested_immediately(
        self,
        mock_settings,
        MockService,
        mock_lock_val,
        mock_task_id,
        MockHeartbeat,
        mock_acquire,
        mock_redis,
    ):
        mock_settings.MARKET_REDIS_URL = "redis://localhost"
        mock_settings.MARKET_TICK_CHANNEL = "ticks"
        mock_settings.MARKET_TICK_PUBLISHER_LOCK_KEY = "lock:pub"

        svc_instance = MagicMock()
        svc_instance.should_stop.return_value = True
        MockService.return_value = svc_instance

        client = MagicMock()
        mock_redis.return_value = client

        runner = TickPublisherRunner()
        runner.run(account_id=1)

        MockHeartbeat.return_value.start.assert_called_once()
        svc_instance.start.assert_called_once()
        svc_instance.mark_stopped.assert_called_once()


class TestValidateAccount:
    """Tests for _validate_account."""

    def test_returns_false_when_account_none(self):
        runner = TickPublisherRunner()
        runner.account = None
        runner.task_service = MagicMock()

        result = runner._validate_account(MagicMock(), "lock:key", 1)

        assert result is False

    def test_returns_true_for_practice_account(self):
        runner = TickPublisherRunner()
        runner.account = MagicMock()
        runner.account.api_type = "practice"
        runner.task_service = MagicMock()

        result = runner._validate_account(MagicMock(), "lock:key", 1)

        assert result is True

    def test_returns_true_for_live_account(self):
        runner = TickPublisherRunner()
        runner.account = MagicMock()
        runner.account.api_type = "live"
        runner.task_service = MagicMock()

        result = runner._validate_account(MagicMock(), "lock:key", 1)

        assert result is True


class TestStreamTicks:
    """Tests for live OANDA stream retry diagnostics."""

    @patch("apps.market.tasks.publisher.time.sleep")
    @patch("apps.market.tasks.publisher.MarketEventService")
    @patch("apps.market.tasks.publisher.OandaService")
    @patch("apps.market.tasks.publisher.release_lock_if_owner")
    def test_stream_error_persists_retry_event_and_continues(
        self,
        mock_release,
        MockOandaService,
        MockMarketEventService,
        mock_sleep,
        settings,
    ):
        settings.MARKET_TICK_CHANNEL = "market:ticks"
        settings.MARKET_TICK_STREAM_RETRY_DELAY_SECONDS = 0.1

        runner = TickPublisherRunner()
        runner.account = MagicMock()
        runner.account.account_id = "101-001"
        runner.task_service = MagicMock()
        runner.task_service.should_stop.side_effect = [False, True]
        runner.lock_owner = "owner-1"

        MockOandaService.return_value.stream_pricing_ticks.side_effect = RuntimeError("stream down")
        event_service = MockMarketEventService.return_value

        runner._stream_ticks(MagicMock(), "lock:key", ["USD_JPY"], 5)

        retry_calls = [
            call
            for call in event_service.log_event.call_args_list
            if call.kwargs.get("event_type") == MarketEventType.TICK_STREAM_RETRY
        ]
        assert retry_calls
        retry_details = retry_calls[0].kwargs["details"]
        assert retry_details["account_pk"] == 5
        assert retry_details["instruments"] == ["USD_JPY"]
        assert retry_details["exception_type"] == "RuntimeError"
        assert retry_details["exception_message"] == "stream down"
        runner.task_service.heartbeat.assert_called_once()
        mock_sleep.assert_called_once_with(0.1)
        mock_release.assert_called_once()


class TestPersistStreamEvent:
    """Tests for task-scoped stream event persistence."""

    @patch("apps.market.tasks.publisher.MarketEventService")
    def test_persists_event_per_related_trading_task(self, MockMarketEventService):
        task_id = uuid4()
        execution_id = uuid4()
        task = MagicMock()
        task.pk = task_id
        task.execution_id = execution_id
        task.instrument = "USD_JPY"
        task.user = MagicMock()

        runner = TickPublisherRunner()
        runner.account = MagicMock()
        runner.account.account_id = "101-001"

        with patch.object(
            runner,
            "_stream_event_task_contexts",
            return_value=[task],
        ):
            runner._persist_stream_event(
                event_type=MarketEventType.TICK_STREAM_RETRY,
                severity="warning",
                description="retry",
                account_pk=5,
                instruments=["USD_JPY"],
                details={"error_count": 1},
            )

        event_service = MockMarketEventService.return_value
        event_service.log_event.assert_called_once()
        kwargs = event_service.log_event.call_args.kwargs
        assert kwargs["task_type"] == "trading"
        assert kwargs["task_id"] == task_id
        assert kwargs["execution_id"] == execution_id
        assert kwargs["instrument"] == "USD_JPY"
        assert kwargs["details"]["related_task_id"] == str(task_id)
        assert kwargs["details"]["error_count"] == 1


class TestCleanupAndStop:
    """Tests for _cleanup_and_stop."""

    def test_deletes_lock_and_closes_client(self):
        runner = TickPublisherRunner()
        runner.task_service = MagicMock()
        runner.lock_owner = "owner-1"
        lock_heartbeat = MagicMock()
        runner.lock_heartbeat = lock_heartbeat

        client = MagicMock()
        with patch("apps.market.tasks.publisher.release_lock_if_owner") as mock_release:
            runner._cleanup_and_stop(client, "lock:key", "done")

        mock_release.assert_called_once_with(client, "lock:key", "owner-1")
        client.close.assert_called_once()
        lock_heartbeat.stop.assert_called_once()

    def test_marks_stopped(self):
        runner = TickPublisherRunner()
        runner.task_service = MagicMock()
        runner.lock_owner = "owner-1"

        with patch("apps.market.tasks.publisher.release_lock_if_owner"):
            runner._cleanup_and_stop(MagicMock(), "lock:key", "done")

        runner.task_service.mark_stopped.assert_called_once()

    def test_marks_failed_when_flag_set(self):
        from apps.market.models import CeleryTaskStatus

        runner = TickPublisherRunner()
        runner.task_service = MagicMock()
        runner.lock_owner = "owner-1"

        with patch("apps.market.tasks.publisher.release_lock_if_owner"):
            runner._cleanup_and_stop(MagicMock(), "lock:key", "error", failed=True)

        call_kwargs = runner.task_service.mark_stopped.call_args.kwargs
        assert call_kwargs["status"] == CeleryTaskStatus.Status.FAILED

    def test_handles_client_errors_gracefully(self):
        runner = TickPublisherRunner()
        runner.task_service = MagicMock()
        runner.lock_owner = "owner-1"

        client = MagicMock()
        client.close.side_effect = Exception("redis down")

        # Should not raise
        with patch(
            "apps.market.tasks.publisher.release_lock_if_owner",
            side_effect=Exception("redis down"),
        ):
            runner._cleanup_and_stop(client, "lock:key", "done")
            runner.task_service.mark_stopped.assert_called_once()
