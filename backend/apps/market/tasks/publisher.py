"""Publisher task runner for streaming ticks to Redis."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from logging import Logger, getLogger
from typing import Any

from celery import shared_task
from django.apps import apps as django_apps
from django.conf import settings

from apps.market.enums import MarketEventCategory, MarketEventSeverity, MarketEventType
from apps.market.models import CeleryTaskStatus, OandaAccounts
from apps.market.services.celery import CeleryTaskService
from apps.market.services.events import MarketEventService
from apps.market.services.oanda import OandaService
from apps.market.tasks.base import (
    acquire_lock,
    current_task_id,
    isoformat,
    LockHeartbeat,
    lock_value,
    release_lock_if_owner,
    redis_client,
)

logger: Logger = getLogger(name=__name__)

OANDA_TICK_PUBLISH_LATENCY_SECONDS_KEY = "oanda_tick_publish_latency_seconds"
OANDA_TICK_PUBLISHED_AT_KEY = "oanda_tick_published_at"
STREAM_EVENT_TASK_STATUSES = (
    "starting",
    "running",
    "paused",
    "idle",
    "draining",
    "stopping",
)


def publisher_lock_key_for_account(account_id: int) -> str:
    """Return the Redis lock key for a specific publisher account."""
    base_key = getattr(settings, "MARKET_TICK_PUBLISHER_LOCK_KEY", "market:tick_publisher:lock")
    return f"{base_key}:{account_id}"


def normalize_instruments(instruments: list[str] | tuple[str, ...] | None) -> list[str]:
    """Return a stable, de-duplicated instrument list for publisher state."""
    source = instruments or getattr(settings, "MARKET_TICK_INSTRUMENTS", ["EUR_USD"])
    normalized = sorted({str(instrument) for instrument in source if instrument})
    return normalized or ["EUR_USD"]


def _coerce_aware_datetime(value: Any) -> datetime | None:
    """Return a timezone-aware datetime when *value* can be parsed."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    try:
        value_str = str(value).strip()
        if value_str.endswith("Z"):
            value_str = value_str[:-1] + "+00:00"
        parsed = datetime.fromisoformat(value_str)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def build_tick_latency_payload(
    tick_timestamp: Any,
    *,
    observed_at: datetime | None = None,
) -> dict[str, str]:
    """Build Redis payload fields describing OANDA tick publish latency."""
    tick_ts = _coerce_aware_datetime(tick_timestamp)
    if tick_ts is None:
        return {}

    published_at = observed_at or datetime.now(UTC)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    latency_seconds = max(0.0, (published_at - tick_ts).total_seconds())
    return {
        OANDA_TICK_PUBLISHED_AT_KEY: isoformat(published_at),
        OANDA_TICK_PUBLISH_LATENCY_SECONDS_KEY: f"{latency_seconds:.6f}",
    }


@shared_task(bind=True, name="market.tasks.publish_oanda_ticks")
def publish_oanda_ticks(self: Any, account_id: int, instruments: list[str] | None = None) -> None:
    """Stream live pricing ticks from OANDA and publish to Redis pub/sub.

    Args:
        account_id: OANDA account ID
        instruments: List of instruments to stream (optional)
    """
    runner = TickPublisherRunner()
    runner.run(account_id, instruments)


class TickPublisherRunner:
    """Runner for OANDA tick publisher task."""

    def __init__(self) -> None:
        """Initialize the publisher runner."""
        self.task_service: CeleryTaskService | None = None
        self.account: OandaAccounts | None = None
        self.lock_owner: str | None = None
        self.lock_heartbeat: LockHeartbeat | None = None

    def run(self, account_id: int, instruments: list[str] | None = None) -> None:
        """Execute the tick publisher task.

        Args:
            account_id: OANDA account ID
            instruments: List of instruments to stream (optional)
        """
        instruments_list = normalize_instruments(instruments)
        task_name = "market.tasks.publish_oanda_ticks"
        instance_key = str(account_id)
        self.task_service = CeleryTaskService(
            task_name=task_name,
            instance_key=instance_key,
            stop_check_interval_seconds=1.0,
            heartbeat_interval_seconds=5.0,
        )
        redis_url = settings.MARKET_REDIS_URL

        logger.info(
            "Publisher starting (account_id=%s, redis=%s, worker=%s)",
            account_id,
            redis_url,
            lock_value(),
        )

        client = redis_client()
        lock_key = publisher_lock_key_for_account(account_id)

        owner = acquire_lock(client, lock_key, ttl_seconds=60)
        if owner is None:
            logger.warning("Publisher exiting: another instance holds the lock (lock=%s)", lock_key)
            client.close()
            return
        self.lock_owner = owner
        self.task_service.start(
            celery_task_id=current_task_id(),
            worker=lock_value(),
            meta={
                "account_id": account_id,
                "instruments": instruments_list,
                "lock_owner": owner,
            },
        )
        self.lock_heartbeat = LockHeartbeat(
            client=client,
            key=lock_key,
            owner=owner,
            ttl_seconds=60,
        )
        self.lock_heartbeat.start()

        if self.task_service.should_stop(force=True):
            logger.info("Publisher exiting: stop requested before streaming")
            self._cleanup_and_stop(client, lock_key, "Stop requested")
            return

        # Validate account
        self.account = OandaAccounts.objects.filter(id=account_id).first()
        if not self._validate_account(client, lock_key, account_id):
            return

        logger.info(
            "Publisher: streaming instruments=%s from OANDA account (pk=%s, oanda_id=%s)",
            instruments_list,
            account_id,
            self.account.account_id if self.account else "?",
        )
        self._persist_stream_event(
            event_type=MarketEventType.TICK_STREAM_STARTED,
            severity=MarketEventSeverity.INFO,
            description="OANDA pricing stream publisher started.",
            account_pk=account_id,
            instruments=instruments_list,
        )

        # Start streaming
        self._stream_ticks(client, lock_key, instruments_list, account_id)

    def _validate_account(self, client: Any, lock_key: str, account_id: int) -> bool:
        """Validate account exists."""
        if self.account is None:
            logger.error("Tick publisher cannot start: account %s not found", account_id)
            self._cleanup_and_stop(client, lock_key, "Account not found", failed=True)
            return False

        return True

    def _stream_ticks(
        self,
        client: Any,
        lock_key: str,
        instruments_list: list[str],
        account_id: int,
    ) -> None:
        """Stream ticks from OANDA to Redis.

        Each tick is published to both the shared market channel and the
        account-specific ``live:{oanda_account_id}:{instrument}`` channel.
        The shared channel feeds DB persistence while the account channel
        serves trading tasks that must follow the exact OANDA account.
        """
        assert self.account is not None
        assert self.task_service is not None
        oanda_account_id = self.account.account_id
        shared_channel = getattr(settings, "MARKET_TICK_CHANNEL", "market:ticks")
        latency_log_interval_seconds = self._live_tick_latency_metric_interval_seconds()
        last_latency_log_at_by_instrument: dict[str, datetime] = {}
        retry_delay_seconds = self._stream_retry_delay_seconds()

        ticks_published = 0
        stream_error_count = 0
        reconnect_attempt = 0
        try:
            while True:
                if self.task_service.should_stop():
                    logger.info(
                        "Publisher: stop requested, exiting stream loop (account_id=%s)",
                        account_id,
                    )
                    break

                try:
                    reconnect_attempt += 1
                    logger.info(
                        "Publisher: connecting to OANDA pricing stream "
                        "(instruments=%s, account_id=%s, attempt=%s)",
                        instruments_list,
                        account_id,
                        reconnect_attempt,
                    )
                    service = OandaService(self.account)
                    for tick in service.stream_pricing_ticks(instruments_list, snapshot=True):
                        if self.task_service.should_stop():
                            break

                        instrument = str(tick.instrument)
                        observed_at = datetime.now(UTC)
                        latency_payload = build_tick_latency_payload(
                            tick.timestamp,
                            observed_at=observed_at,
                        )
                        payload = {
                            "instrument": instrument,
                            "timestamp": isoformat(tick.timestamp),
                            "bid": str(tick.bid),
                            "ask": str(tick.ask),
                            "mid": str(tick.mid),
                        }
                        payload.update(latency_payload)
                        encoded_payload = json.dumps(payload)
                        client.publish(shared_channel, encoded_payload)
                        client.publish(f"live:{oanda_account_id}:{instrument}", encoded_payload)
                        ticks_published += 1

                        if ticks_published == 1:
                            logger.info(
                                "Publisher: first tick received and published "
                                "(instrument=%s, bid=%s, ask=%s)",
                                tick.instrument,
                                tick.bid,
                                tick.ask,
                            )

                        if (
                            latency_log_interval_seconds > 0
                            and latency_payload
                            and self._should_log_tick_latency(
                                last_logged_at=last_latency_log_at_by_instrument.get(instrument),
                                observed_at=observed_at,
                                interval_seconds=latency_log_interval_seconds,
                            )
                        ):
                            logger.info(
                                "[PUBLISHER:TICK_LATENCY] account_id=%s oanda_id=%s "
                                "instrument=%s tick_ts=%s published_at=%s "
                                "oanda_tick_publish_latency_seconds=%s published=%s",
                                account_id,
                                oanda_account_id,
                                instrument,
                                isoformat(tick.timestamp),
                                latency_payload[OANDA_TICK_PUBLISHED_AT_KEY],
                                latency_payload[OANDA_TICK_PUBLISH_LATENCY_SECONDS_KEY],
                                ticks_published,
                            )
                            last_latency_log_at_by_instrument[instrument] = observed_at

                        if ticks_published % 1000 == 0:
                            logger.info(
                                "Publisher: %s ticks published so far (account_id=%s, oanda_id=%s)",
                                ticks_published,
                                account_id,
                                oanda_account_id,
                            )

                        if ticks_published % 250 == 0:
                            self.task_service.heartbeat(
                                status_message=f"published={ticks_published}",
                                meta_update={"published": ticks_published},
                            )

                except Exception as exc:  # pylint: disable=broad-exception-caught
                    stream_error_count += 1
                    error_observed_at = datetime.now(UTC)
                    logger.exception(
                        "Publisher: stream error, retrying in %ss (account_id=%s): %s",
                        retry_delay_seconds,
                        account_id,
                        exc,
                    )
                    self._persist_stream_event(
                        event_type=MarketEventType.TICK_STREAM_RETRY,
                        severity=MarketEventSeverity.WARNING,
                        description="OANDA pricing stream error; publisher will retry.",
                        account_pk=account_id,
                        instruments=instruments_list,
                        details={
                            "error_count": stream_error_count,
                            "reconnect_attempt": reconnect_attempt,
                            "retry_delay_seconds": retry_delay_seconds,
                            "exception_type": type(exc).__name__,
                            "exception_message": self._truncate_detail(str(exc)),
                            "observed_at": isoformat(error_observed_at),
                        },
                    )
                    self.task_service.heartbeat(
                        status_message=f"error={str(exc)}",
                        meta_update={
                            "stream_error_count": stream_error_count,
                            "stream_reconnect_attempt": reconnect_attempt,
                            "last_stream_error_at": isoformat(error_observed_at),
                            "last_stream_error_type": type(exc).__name__,
                        },
                        force=True,
                    )
                    time.sleep(retry_delay_seconds)

        finally:
            logger.info(
                "Publisher: shutting down (total_ticks_published=%s, account_id=%s)",
                ticks_published,
                account_id,
            )
            self._persist_stream_event(
                event_type=MarketEventType.TICK_STREAM_STOPPED,
                severity=MarketEventSeverity.INFO,
                description="OANDA pricing stream publisher stopped.",
                account_pk=account_id,
                instruments=instruments_list,
                details={"published": ticks_published, "stream_error_count": stream_error_count},
            )
            self._cleanup_and_stop(client, lock_key, f"published={ticks_published}")

    @staticmethod
    def _stream_retry_delay_seconds() -> float:
        """Return the retry delay after a pricing stream failure."""
        raw_value = getattr(settings, "MARKET_TICK_STREAM_RETRY_DELAY_SECONDS", 5)
        try:
            return max(0.1, float(raw_value))
        except (TypeError, ValueError):
            return 5.0

    def _live_tick_latency_metric_interval_seconds(self) -> int:
        """Return the account-configured latency metric/log interval."""
        raw_value = getattr(self.account, "live_tick_latency_metric_interval_seconds", 60)
        try:
            return max(0, int(raw_value))
        except (TypeError, ValueError):
            return 60

    @staticmethod
    def _should_log_tick_latency(
        *,
        last_logged_at: datetime | None,
        observed_at: datetime,
        interval_seconds: int,
    ) -> bool:
        if interval_seconds <= 0:
            return False
        if last_logged_at is None:
            return True
        return (observed_at - last_logged_at).total_seconds() >= interval_seconds

    def _cleanup_and_stop(
        self, client: Any, lock_key: str, message: str, failed: bool = False
    ) -> None:
        """Cleanup resources and mark task as stopped."""
        logger.info("Publisher: cleaning up (reason=%s)", message)

        if self.lock_heartbeat is not None:
            self.lock_heartbeat.stop()
            self.lock_heartbeat = None

        try:
            release_lock_if_owner(client, lock_key, self.lock_owner)
        except Exception as exc:  # pylint: disable=broad-exception-caught  # nosec B110
            logger.debug("Failed to delete lock key: %s", exc)
        try:
            client.close()
        except Exception as exc:  # pylint: disable=broad-exception-caught  # nosec B110
            logger.debug("Failed to close Redis client: %s", exc)
        self.lock_owner = None

        if self.task_service:
            status_value = (
                CeleryTaskStatus.Status.FAILED if failed else CeleryTaskStatus.Status.STOPPED
            )
            self.task_service.mark_stopped(
                status=status_value,
                status_message=message,
            )

    def _persist_stream_event(
        self,
        *,
        event_type: MarketEventType,
        severity: MarketEventSeverity,
        description: str,
        account_pk: int,
        instruments: list[str],
        details: dict[str, Any] | None = None,
    ) -> None:
        """Persist stream lifecycle diagnostics for post-incident analysis."""
        account = self.account
        event_details: dict[str, Any] = {
            "account_pk": account_pk,
            "oanda_account_id": str(getattr(account, "account_id", "") or ""),
            "instruments": instruments,
            "celery_task_id": current_task_id() or "",
            "worker": lock_value(),
        }
        if details:
            event_details.update(details)

        task_contexts = self._stream_event_task_contexts(
            account_pk=account_pk,
            instruments=instruments,
        )
        event_service = MarketEventService()
        if not task_contexts:
            event_service.log_event(
                event_type=event_type,
                description=description,
                severity=severity,
                category=MarketEventCategory.MARKET,
                account=account,
                instrument=instruments[0] if len(instruments) == 1 else "",
                details=event_details,
            )
            return

        for task in task_contexts:
            task_details = {
                **event_details,
                "related_task_id": str(task.pk),
                "related_execution_id": str(task.execution_id or ""),
            }
            event_service.log_event(
                event_type=event_type,
                description=description,
                severity=severity,
                category=MarketEventCategory.MARKET,
                user=getattr(task, "user", None),
                account=account,
                instrument=str(task.instrument or ""),
                task_type="trading",
                task_id=task.pk,
                execution_id=task.execution_id,
                details=task_details,
            )

    @staticmethod
    def _stream_event_task_contexts(*, account_pk: int, instruments: list[str]) -> list[Any]:
        """Return active trading tasks whose live stream this event affects."""
        try:
            TradingTask = django_apps.get_model("trading", "TradingTask")
            return list(
                TradingTask.objects.filter(
                    oanda_account_id=account_pk,
                    instrument__in=instruments,
                    status__in=STREAM_EVENT_TASK_STATUSES,
                ).select_related("user")
            )
        except Exception:  # pylint: disable=broad-exception-caught
            logger.debug(
                "Unable to resolve trading tasks for stream market event",
                extra={"account_id": account_pk, "instruments": instruments},
                exc_info=True,
            )
            return []

    @staticmethod
    def _truncate_detail(value: str, *, max_length: int = 1000) -> str:
        """Keep persisted diagnostic strings bounded."""
        if len(value) <= max_length:
            return value
        return value[: max_length - 3] + "..."


# Note: Singleton instance is created in __init__.py
