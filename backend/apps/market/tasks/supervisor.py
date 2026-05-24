"""Supervisor task runner for managing tick pub/sub system."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import timedelta
from logging import Logger, getLogger
from typing import Any

from celery import shared_task
from django.conf import settings
from django.db.models import QuerySet
from django.utils import timezone

from apps.market.models import CeleryTaskStatus
from apps.market.services.celery import CeleryTaskService
from apps.market.tasks.publisher import publisher_lock_key_for_account
from apps.market.tasks.base import (
    acquire_lock,
    current_task_id,
    lock_value,
    redis_client,
    release_lock_if_owner,
)

logger: Logger = getLogger(name=__name__)


@dataclass(frozen=True, slots=True)
class AccountStreamTarget:
    """Desired streaming configuration for a single OANDA account."""

    account_pk: int
    instruments: tuple[str, ...]


@shared_task(bind=True, name="market.tasks.ensure_tick_pubsub_running")
def ensure_tick_pubsub_running(self: Any) -> None:
    """Ensure the required publisher/subscriber tasks are active.

    Publishers are maintained per active trading account. The subscriber
    remains a singleton because it persists the shared market channel.
    Celery Beat schedules this task periodically. It is also triggered on:
    - worker startup
    - OANDA account creation
    - trading-task starts
    """
    runner = TickSupervisorRunner()
    runner.run()


class TickSupervisorRunner:
    """Runner for tick pub/sub supervisor task."""

    def __init__(self) -> None:
        """Initialize the supervisor runner."""
        self.task_service: CeleryTaskService | None = None

    def run(self) -> None:
        """Execute the supervisor task."""
        # Import here to avoid circular dependency

        task_name = "market.tasks.ensure_tick_pubsub_running"
        instance_key = "supervisor"
        self.task_service = CeleryTaskService(
            task_name=task_name,
            instance_key=instance_key,
            stop_check_interval_seconds=5.0,
            heartbeat_interval_seconds=10.0,
        )
        logger.info("Supervisor starting (worker=%s)", lock_value())

        client = redis_client()

        interval_seconds = int(getattr(settings, "MARKET_TICK_SUPERVISOR_INTERVAL", 30))
        supervisor_lock = getattr(
            settings, "MARKET_TICK_SUPERVISOR_LOCK_KEY", "market:tick_supervisor:lock"
        )
        owner = acquire_lock(client, supervisor_lock, ttl_seconds=interval_seconds + 30)
        if owner is None:
            logger.info(
                "Supervisor exiting: another instance holds the lock (lock=%s)", supervisor_lock
            )
            with contextlib.suppress(Exception):
                client.close()
            return

        stop_requested = False
        try:
            self.task_service.start(
                celery_task_id=current_task_id(),
                worker=lock_value(),
                meta={"kind": "supervisor", "lock_owner": owner},
            )

            if self.task_service.should_stop(force=True):
                logger.info("Supervisor exiting: stop requested before main loop")
                self.task_service.mark_stopped(
                    status=CeleryTaskStatus.Status.STOPPED,
                    status_message="Stop requested",
                )
                return

            self.task_service.heartbeat(status_message="running", force=True)

            account_targets = self._target_account_targets()
            if not account_targets:
                logger.warning(
                    "Supervisor: no active trading-task accounts found — "
                    "tick streaming will stay idle until a trading task starts"
                )
            else:
                logger.info(
                    "Supervisor: ensuring tick publishers for targets=%s",
                    account_targets,
                )
                self._ensure_publishers_running(client, account_targets)

            # Check and restart subscriber if needed
            self._ensure_subscriber_running(client)

            # Best-effort cleanup of stale legacy single-account cache keys.
            account_key = getattr(settings, "MARKET_TICK_ACCOUNT_KEY", "market:tick_pubsub:account")
            init_key = getattr(settings, "MARKET_TICK_PUBSUB_INIT_KEY", "market:tick_pubsub:init")
            with contextlib.suppress(Exception):
                client.delete(account_key)
                client.delete(init_key)

        finally:
            with contextlib.suppress(Exception):
                release_lock_if_owner(client, supervisor_lock, owner)
            with contextlib.suppress(Exception):
                client.close()

            assert self.task_service is not None
            stop_requested = self.task_service.should_stop(force=True)

        if stop_requested:
            logger.info("Supervisor exiting: stop requested after check cycle")
            self.task_service.mark_stopped(
                status=CeleryTaskStatus.Status.STOPPED,
                status_message="Stop requested",
            )
            return

        # Do not self-schedule here. Celery Beat owns the periodic cadence;
        # enqueueing another delayed supervisor task after every run creates
        # duplicate chains that can starve higher-priority system work such as
        # task stop finalisation.

    def _active_trading_tasks(self) -> QuerySet[Any]:
        """Return active trading tasks that require live market data."""
        from apps.trading.enums import TaskStatus as TradingTaskStatus
        from apps.trading.models import TradingTask

        active_statuses = (
            TradingTaskStatus.STARTING,
            TradingTaskStatus.RUNNING,
            TradingTaskStatus.PAUSED,
            TradingTaskStatus.STOPPING,
        )

        return (
            TradingTask.objects.filter(
                status__in=active_statuses,
                oanda_account__is_active=True,
            )
            .select_related("oanda_account")
            .order_by("oanda_account_id", "instrument", "created_at")
        )

    def _target_account_targets(self) -> list[AccountStreamTarget]:
        """Return account targets with the exact instruments required."""
        targets: dict[int, set[str]] = {}
        for task in self._active_trading_tasks():
            if not task.oanda_account_id:
                continue
            targets.setdefault(int(task.oanda_account_id), set()).add(str(task.instrument))

        return [
            AccountStreamTarget(account_pk=account_pk, instruments=tuple(sorted(instruments)))
            for account_pk, instruments in sorted(targets.items())
        ]

    def _target_account_pks(self) -> list[int]:
        """Return active OANDA account PKs required by active trading tasks."""
        return [target.account_pk for target in self._target_account_targets()]

    def _publisher_matches_target(self, account_pk: int, instruments: tuple[str, ...]) -> bool:
        """Return whether the persisted publisher configuration matches the target."""
        publisher = self._fresh_market_task(
            task_name="market.tasks.publish_oanda_ticks",
            instance_key=str(account_pk),
        )
        if publisher is None:
            return False

        meta = publisher.meta if isinstance(publisher.meta, dict) else {}
        configured = tuple(sorted(str(item) for item in meta.get("instruments", []) if item))
        return configured == instruments

    def _market_task_cutoff(self):
        stale_after_seconds = int(getattr(settings, "CELERY_MARKET_TASK_STALE_AFTER_SECONDS", 90))
        return timezone.now() - timedelta(seconds=stale_after_seconds)

    def _fresh_market_task(self, *, task_name: str, instance_key: str) -> CeleryTaskStatus | None:
        return (
            CeleryTaskStatus.objects.filter(
                task_name=task_name,
                instance_key=instance_key,
                status__in=(
                    CeleryTaskStatus.Status.RUNNING,
                    CeleryTaskStatus.Status.STOPPING,
                ),
                last_heartbeat_at__gte=self._market_task_cutoff(),
            )
            .only("meta", "status", "status_message", "last_heartbeat_at")
            .first()
        )

    @staticmethod
    def _lock_matches_row(client: Any, lock_key: str, row: CeleryTaskStatus | None) -> bool:
        if row is None or not isinstance(row.meta, dict):
            return False
        owner = str(row.meta.get("lock_owner") or "")
        if not owner:
            return False
        return str(client.get(lock_key) or "") == owner

    def _request_publisher_restart(self, account_pk: int, instruments: tuple[str, ...]) -> None:
        """Request a running publisher to restart with an updated instrument set."""
        updated = CeleryTaskStatus.objects.filter(
            task_name="market.tasks.publish_oanda_ticks",
            instance_key=str(account_pk),
            status=CeleryTaskStatus.Status.RUNNING,
        ).update(
            status=CeleryTaskStatus.Status.STOPPING,
            status_message=(
                "Restarting publisher with updated instruments: " + ", ".join(instruments)
            ),
        )
        if updated:
            logger.warning(
                "Supervisor: requested publisher restart for account_pk=%s with instruments=%s",
                account_pk,
                instruments,
            )

    def _ensure_publishers_running(
        self, client: Any, account_targets: list[AccountStreamTarget]
    ) -> None:
        """Ensure account-specific publisher tasks are running with the required instruments."""
        from apps.market.tasks import publish_oanda_ticks

        for target in account_targets:
            publisher_lock = publisher_lock_key_for_account(int(target.account_pk))
            publisher_row = self._fresh_market_task(
                task_name="market.tasks.publish_oanda_ticks",
                instance_key=str(target.account_pk),
            )
            publisher_alive = publisher_row is not None
            lock_matches = self._lock_matches_row(client, publisher_lock, publisher_row)
            publisher_matches = self._publisher_matches_target(
                target.account_pk,
                target.instruments,
            )
            logger.info(
                "Supervisor: publisher status for account_pk=%s is %s (lock_matches=%s, matches_target=%s, instruments=%s)",
                target.account_pk,
                "running" if publisher_alive else "NOT running",
                lock_matches,
                publisher_matches,
                target.instruments,
            )
            if publisher_alive and not publisher_matches:
                self._request_publisher_restart(target.account_pk, target.instruments)
                continue
            if not publisher_alive:
                logger.info(
                    "Supervisor: spawning publisher task (account_pk=%s, instruments=%s)",
                    target.account_pk,
                    target.instruments,
                )
                publish_oanda_ticks.apply_async(
                    kwargs={
                        "account_id": int(target.account_pk),
                        "instruments": list(target.instruments),
                    },
                    queue="market",
                )

    def _ensure_subscriber_running(self, client: Any) -> None:
        """Ensure the shared DB subscriber task is running."""
        from apps.market.tasks import subscribe_ticks_to_db

        subscriber_lock = getattr(
            settings, "MARKET_TICK_SUBSCRIBER_LOCK_KEY", "market:tick_subscriber:lock"
        )
        subscriber_row = self._fresh_market_task(
            task_name="market.tasks.subscribe_ticks_to_db",
            instance_key="default",
        )
        subscriber_alive = subscriber_row is not None
        logger.info(
            "Supervisor: subscriber status is %s (lock_matches=%s)",
            "running" if subscriber_alive else "NOT running",
            self._lock_matches_row(client, subscriber_lock, subscriber_row),
        )
        if not subscriber_alive:
            logger.info("Supervisor: spawning subscriber task")
            subscribe_ticks_to_db.apply_async(queue="market")
