"""Celery tasks for live trading execution."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from celery import shared_task

from apps.trading.engine import TradingEngine
from apps.trading.enums import StopMode, TaskStatus, TaskType
from apps.trading.logging import TaskLoggingSession
from apps.trading.models import TradingTask
from apps.trading.services.execution_lifecycle import transition_task_to_running
from apps.trading.tasks.executor import TradingExecutor
from apps.trading.tasks.lifecycle_events import (
    build_started_event_spec,
    build_stopped_event_spec,
    finalize_task_terminal_lifecycle,
    publish_task_lifecycle_event,
)
from apps.trading.tasks.source import LiveTickDataSource
from apps.trading.tasks.task_runner import handle_task_exception
from apps.trading.utils import pip_size_for_instrument

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="trading.tasks.run_trading_task",
    acks_late=True,
    reject_on_worker_lost=True,
    track_started=True,
)
def run_trading_task(self: Any, task_id: UUID, dispatch_idempotency_key: str | None = None) -> None:
    """Celery task wrapper for running trading tasks."""
    task = None
    logging_session: TaskLoggingSession | None = None

    try:
        logger.info("Starting a new celery trading task. Task ID: %s.", task_id)
        task = TradingTask.objects.get(pk=task_id)
        logging_session = TaskLoggingSession(task)
        logging_session.start()

        if dispatch_idempotency_key and str(task.dispatch_idempotency_key) != str(
            dispatch_idempotency_key
        ):
            logger.warning(
                "SKIPPING stale redelivery - task_id=%s, expected_key=%s, received_key=%s",
                task_id,
                task.dispatch_idempotency_key,
                dispatch_idempotency_key,
            )
            return

        if task.status != TaskStatus.STARTING:
            logger.warning(
                "SKIPPING execution - task_id=%s, status=%s is not STARTING",
                task_id,
                task.status,
            )
            return

        rows_updated = transition_task_to_running(task_model=TradingTask, task_id=task_id)
        if rows_updated == 0:
            task.refresh_from_db()
            logger.warning(
                "SKIPPING execution (lost race) - task_id=%s, current_status=%s",
                task_id,
                task.status,
            )
            return

        task.refresh_from_db()
        logger.info("Transitioning: STARTING -> RUNNING - task_id=%s", task_id)

        publish_task_lifecycle_event(
            logger=logger,
            task=task,
            task_type=TaskType.TRADING,
            event=build_started_event_spec(task_label="Trading", component=__name__),
        )

        execute_trading(task)

        # Mark as stopped (trading tasks run until stopped)
        task.refresh_from_db()
        if task.status not in [TaskStatus.STOPPED, TaskStatus.STOPPING, TaskStatus.PAUSED]:
            rows_updated = finalize_task_terminal_lifecycle(
                logger=logger,
                task=task,
                task_type=TaskType.TRADING,
                status=TaskStatus.STOPPED,
                event=build_stopped_event_spec(
                    task_label="Trading",
                    component=__name__,
                    description="Trading task stopped after execution completed",
                    log_message="Trading task stopped successfully",
                ),
                expected_current_status=TaskStatus.RUNNING,
            )
            if rows_updated == 0:
                task.refresh_from_db()
                logger.warning(
                    "STOPPED transition failed - task_id=%s, current_status=%s",
                    task_id,
                    task.status,
                )
                return
        else:
            logger.info(
                "Execution already finalized with status=%s - task_id=%s", task.status, task_id
            )

    except TradingTask.DoesNotExist:
        logger.error("TradingTask %s not found", task_id)
        raise
    except Exception as e:
        handle_task_exception(
            task_id=task_id,
            task=task,
            error=e,
            task_type=TaskType.TRADING,
            task_label="Trading",
            component=__name__,
        )
        raise
    finally:
        if logging_session:
            logging_session.stop()


def execute_trading(task: TradingTask) -> None:
    """Execute a trading task."""
    resolved_pip_size = task.pip_size or pip_size_for_instrument(task.instrument)

    engine = TradingEngine(
        instrument=task.instrument,
        pip_size=resolved_pip_size,
        strategy_config=task.config,
        account_currency=getattr(task.oanda_account, "currency", ""),
        hedging_enabled=task.hedging_enabled,
    )

    if not task.pip_size:
        task.pip_size = resolved_pip_size
        task.save(update_fields=["pip_size", "updated_at"])

    channel = f"live:{task.oanda_account.account_id}:{task.instrument}"
    data_source = LiveTickDataSource(
        channel=channel,
        instrument=task.instrument,
        tick_granularity=task.tick_granularity,
    )

    executor = TradingExecutor(
        task=task,
        engine=engine,
        data_source=data_source,
        dry_run=task.dry_run,
    )
    executor.execute()


@shared_task(bind=True, name="trading.tasks.stop_trading_task")
def stop_trading_task(self: Any, task_id: UUID, mode: str = "graceful") -> None:
    """Stop a running trading task."""
    try:
        logger.info("Stop task started - task_id=%s, mode=%s", task_id, mode)
        stop_mode = StopMode(mode)
        task = TradingTask.objects.get(pk=task_id)
        logger.info("Task loaded - task_id=%s, status=%s", task_id, task.status)

        # DRAIN mode does not transition the task to STOPPED here.  The
        # lifecycle command has already set DRAINING status and the
        # executor is responsible for closing positions progressively and
        # finalising the task when drain completes.
        if stop_mode == StopMode.DRAIN:
            logger.info("DRAIN stop requested; executor will finalise - task_id=%s", task_id)
            return

        if task.status == TaskStatus.STOPPING:
            # Fall back to execution_id for older rows that pre-date the
            # celery_task_id field and may still have it set to NULL.
            celery_id = task.celery_task_id or task.execution_id
            if stop_mode == StopMode.IMMEDIATE and celery_id:
                from celery import current_app

                current_app.control.revoke(str(celery_id), terminate=True, signal="SIGKILL")

            if stop_mode == StopMode.GRACEFUL_CLOSE:
                _close_open_positions_for_task(task)

            finalize_task_terminal_lifecycle(
                logger=logger,
                task=task,
                task_type=TaskType.TRADING,
                status=TaskStatus.STOPPED,
                event=build_stopped_event_spec(
                    task_label="Trading",
                    component=__name__,
                    description="Trading task stopped",
                ),
                expected_current_status=TaskStatus.STOPPING,
                extra_details={"mode": stop_mode.value},
            )
            logger.info("Trading task %s stopped successfully (mode=%s)", task_id, mode)

        elif task.status == TaskStatus.STOPPED:
            logger.info("Already STOPPED - task_id=%s, nothing to do", task_id)

        else:
            logger.warning("Unexpected state: %s - task_id=%s", task.status, task_id)
    except TradingTask.DoesNotExist:
        logger.error("Trading task %s not found", task_id)
        raise


def _close_open_positions_for_task(task: TradingTask) -> None:
    """Best-effort close of open positions before stopping."""
    from apps.trading.order import OrderService, OrderServiceError

    service = OrderService(account=task.oanda_account, task=task, dry_run=False)
    open_positions = service.get_open_positions(instrument=task.instrument)
    for position in open_positions:
        try:
            service.close_position(position=position)
        except OrderServiceError as exc:
            logger.warning(
                "Failed to close position during graceful_close - "
                "task_id=%s, position_id=%s, error=%s",
                task.pk,
                position.pk,
                exc,
            )
