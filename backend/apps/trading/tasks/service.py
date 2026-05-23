"""Task service layer for managing task lifecycle and execution.

This module provides the service layer for task management, including:
- Task submission to Celery
- Task stopping with graceful shutdown
- Task restart and resume operations
"""

from __future__ import annotations

import logging
from logging import Logger
from typing import Any
from uuid import UUID, uuid4

from celery.result import AsyncResult
from django.db import transaction
from django.utils import timezone as _timezone

from apps.trading.enums import TaskStatus
from apps.trading.models import (
    BacktestTask,
    TradingTask,
)
from apps.trading.services.public_errors import (
    TASK_FAILED_ERROR_CODE,
    TASK_FAILED_PUBLIC_MESSAGE,
)
from apps.trading.services.status_reasons import empty_status_reason_update
from apps.trading.services.task_policy import ACCOUNT_BLOCKING_STATUSES
from apps.trading.tasks.lifecycle_commands import TaskLifecycleCommands
from apps.trading.tasks.lifecycle_events import TaskLifecycleEventPublisher
from apps.trading.tasks.lifecycle_writes import TaskLifecycleWriter
from apps.trading.tasks import (
    run_backtest_task,
    run_trading_task,
    stop_backtest_task as _stop_backtest_task,
    stop_trading_task as _stop_trading_task,
)

logger: Logger = logging.getLogger(name=__name__)
timezone = _timezone
stop_backtest_task = _stop_backtest_task
stop_trading_task = _stop_trading_task
_UNSET = object()


class TaskServiceError(Exception):
    """Base exception for task service failures."""


class TaskValidationError(TaskServiceError, ValueError):
    """Raised when a task request fails domain validation."""

    def __init__(
        self,
        message: str,
        *,
        resume_config_error: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.resume_config_error = resume_config_error


class TaskConflictError(TaskServiceError, ValueError):
    """Raised when a task conflicts with current system state."""


class TaskCapacityError(TaskConflictError):
    """Raised when worker capacity is insufficient for a new task."""

    def __init__(
        self,
        message: str,
        *,
        decision: object | None = None,
    ) -> None:
        super().__init__(message)
        self.decision = decision


class TaskSubmissionError(TaskServiceError, RuntimeError):
    """Raised when dispatching a task to workers fails."""


class TaskLookupError(TaskValidationError):
    """Raised when a task cannot be found."""


class TaskService:
    """Service for managing task lifecycle.

    This service provides:
    - Task starting with STARTING state
    - Task stopping with STOPPING state
    - Task restart and resume operations
    """

    def __init__(self) -> None:
        from apps.trading.services.live_risk import LiveTradingRiskGuard
        from apps.trading.services.task_capacity import TaskCapacityService

        self.writer = TaskLifecycleWriter(logger=logger)
        self.events = TaskLifecycleEventPublisher(logger=logger)
        self.commands = TaskLifecycleCommands(service=self, logger=logger, events=self.events)
        self.capacity = TaskCapacityService()
        self.risk_guard = LiveTradingRiskGuard()

    @staticmethod
    def get_celery_result(celery_task_id: str | None) -> AsyncResult | None:
        """Get Celery AsyncResult for a task ID.

        Args:
            celery_task_id: Celery task ID

        Returns:
            AsyncResult | None: Celery AsyncResult if task ID exists, None otherwise
        """
        if celery_task_id:
            return AsyncResult(celery_task_id)
        return None

    @staticmethod
    def _resolve_task_type(task: BacktestTask | TradingTask) -> str:
        model_name = str(getattr(getattr(task, "_meta", None), "model_name", "")).lower()
        if model_name == "backtesttask":
            return "backtest"
        if model_name == "tradingtask":
            return "trading"

        class_name = str(task.__class__.__name__).lower()
        if class_name.startswith("backtest"):
            return "backtest"
        if class_name.startswith("trading"):
            return "trading"

        if hasattr(task, "start_time") and hasattr(task, "end_time"):
            return "backtest"

        return "trading"

    @staticmethod
    def _dispatch_task(task: BacktestTask | TradingTask, task_type: str) -> None:
        celery_task = run_backtest_task if task_type == "backtest" else run_trading_task
        queue = "backtest" if task_type == "backtest" else "trading"
        celery_task_id = getattr(task, "celery_task_id", None)
        if not celery_task_id:
            # Defensive: should have been set by start/resume/restart, but
            # if it is missing we still need a unique Celery id so the
            # worker can accept the message.
            celery_task_id = uuid4()
            type(task).objects.filter(pk=task.pk).update(celery_task_id=celery_task_id)
            task.celery_task_id = celery_task_id

        dispatch_idempotency_key = uuid4()
        model_objects = getattr(type(task), "objects", None)
        if model_objects is not None:
            rows_updated = model_objects.filter(
                pk=task.pk,
                status=TaskStatus.STARTING,
                celery_task_id=celery_task_id,
            ).update(
                dispatch_idempotency_key=dispatch_idempotency_key,
                updated_at=timezone.now(),
            )
            if rows_updated == 0:
                raise TaskConflictError(
                    "Task dispatch was superseded by another lifecycle transition. "
                    "Reload the task before retrying."
                )
        task.dispatch_idempotency_key = dispatch_idempotency_key
        celery_task.apply_async(
            args=[task.pk, str(dispatch_idempotency_key)],
            task_id=str(celery_task_id),
            queue=queue,
            headers={
                "dispatch_idempotency_key": str(dispatch_idempotency_key),
                "task_id": str(task.pk),
                "execution_id": str(getattr(task, "execution_id", "") or ""),
                "task_type": task_type,
            },
        )

    @staticmethod
    def _resolve_user_id(user: Any | None) -> Any | None:
        if user is None:
            return None
        if isinstance(user, int):
            return user
        return getattr(user, "pk", getattr(user, "id", None))

    @classmethod
    def _task_lookup_kwargs(cls, task_id: UUID, user: Any | None) -> dict[str, Any]:
        lookup: dict[str, Any] = {"pk": task_id}
        if user is None:
            return lookup

        user_id = cls._resolve_user_id(user)
        if user_id is None:
            raise TaskValidationError("Task does not exist or is not accessible")
        lookup["user_id"] = user_id
        return lookup

    @classmethod
    def _ensure_task_owned_by_user(
        cls,
        task: BacktestTask | TradingTask,
        user: Any | None,
    ) -> None:
        if user is None:
            return

        user_id = cls._resolve_user_id(user)
        task_user_id = getattr(task, "user_id", None)
        if task_user_id is None:
            task_user = getattr(task, "user", None)
            task_user_id = cls._resolve_user_id(task_user)

        if user_id is None or task_user_id != user_id:
            raise TaskValidationError("Task does not exist or is not accessible")

    @classmethod
    def _get_task_and_type(
        cls,
        task_id: UUID,
        *,
        user: Any | None = None,
    ) -> tuple[BacktestTask | TradingTask, str]:
        lookup = cls._task_lookup_kwargs(task_id, user)
        try:
            return BacktestTask.objects.get(**lookup), "backtest"
        except BacktestTask.DoesNotExist:
            try:
                return TradingTask.objects.get(**lookup), "trading"
            except TradingTask.DoesNotExist as exc:
                raise TaskLookupError(
                    f"Task with id {task_id} does not exist or is not accessible"
                ) from exc

    @staticmethod
    def _get_task_model(task_type: str):
        return BacktestTask if task_type == "backtest" else TradingTask

    @staticmethod
    def _ensure_task_status(
        task: BacktestTask | TradingTask,
        *,
        allowed: tuple[TaskStatus, ...],
        message: str,
    ) -> None:
        if task.status not in allowed:
            raise TaskValidationError(message)

    @staticmethod
    def _ensure_trading_account_available(task: TradingTask) -> None:
        active_task = (
            TradingTask.objects.filter(
                oanda_account=task.oanda_account,
                status__in=ACCOUNT_BLOCKING_STATUSES,
            )
            .exclude(pk=task.pk)
            .first()
        )
        if active_task:
            raise TaskConflictError(
                f"Account already has an active task: '{active_task.name}' "
                f"(status: {active_task.status}). "
                f"Please stop the existing task before starting a new one."
            )

    def _prepare_locked_start_task(
        self,
        task: BacktestTask | TradingTask,
        *,
        model_class,
    ) -> BacktestTask | TradingTask:
        with transaction.atomic():
            locked_task = model_class.objects.select_for_update().get(pk=task.pk)
            self._ensure_task_status(
                locked_task,
                allowed=(TaskStatus.CREATED,),
                message=(
                    "Task must be in CREATED status to submit "
                    f"(current status: {locked_task.status})"
                ),
            )
            if isinstance(locked_task, TradingTask):
                self._ensure_trading_account_available(locked_task)
            self._ensure_worker_capacity_available(locked_task)

            is_valid, error_message = locked_task.validate_configuration()
            if not is_valid:
                raise TaskValidationError(f"Task configuration is invalid: {error_message}")
            self._ensure_dispatch_risk_guard_allows(locked_task)

            if not self._should_preserve_initial_position_preview_execution_id(locked_task):
                locked_task.execution_id = uuid4()
            locked_task.celery_task_id = uuid4()
            locked_task.status = TaskStatus.STARTING
            for field, value in empty_status_reason_update().items():
                setattr(locked_task, field, value)
            locked_task.save(
                update_fields=[
                    "execution_id",
                    "celery_task_id",
                    "status",
                    "status_reason_code",
                    "status_reason_message",
                    "updated_at",
                ]
            )
            return locked_task

    def _prepare_detached_start_task(
        self, task: BacktestTask | TradingTask
    ) -> BacktestTask | TradingTask:
        self._ensure_task_status(
            task,
            allowed=(TaskStatus.CREATED,),
            message=f"Task must be in CREATED status to submit (current status: {task.status})",
        )
        if isinstance(task, TradingTask):
            self._ensure_trading_account_available(task)
        self._ensure_worker_capacity_available(task)

        is_valid, error_message = task.validate_configuration()
        if not is_valid:
            raise TaskValidationError(f"Task configuration is invalid: {error_message}")
        self._ensure_dispatch_risk_guard_allows(task)

        if not self._should_preserve_initial_position_preview_execution_id(task):
            task.execution_id = uuid4()
        task.celery_task_id = uuid4()
        task.status = TaskStatus.STARTING
        for field, value in empty_status_reason_update().items():
            setattr(task, field, value)
        try:
            task.save(
                update_fields=[
                    "execution_id",
                    "celery_task_id",
                    "status",
                    "status_reason_code",
                    "status_reason_message",
                    "updated_at",
                ]
            )
        except TypeError:
            task.save()
        return task

    def _ensure_worker_capacity_available(self, task: BacktestTask | TradingTask) -> None:
        admission = self.capacity.get_task_admission(task)
        if admission.allowed:
            return
        raise TaskCapacityError(admission.reason, decision=admission)

    @staticmethod
    def _should_preserve_initial_position_preview_execution_id(
        task: BacktestTask | TradingTask,
    ) -> bool:
        if task.execution_id is None:
            return False
        if getattr(task, "initial_positions_enabled", False) is not True:
            return False
        from apps.trading.models import ExecutionState
        from apps.trading.services.backtest_initial_positions import (
            is_initial_position_preview_state,
            task_type_for_initial_position_task,
        )

        task_type = task_type_for_initial_position_task(task)
        state = (
            ExecutionState.objects.filter(
                task_type=task_type.value,
                task_id=task.pk,
                execution_id=task.execution_id,
            )
            .only("strategy_state")
            .first()
        )
        return is_initial_position_preview_state(state)

    def _ensure_dispatch_risk_guard_allows(self, task: BacktestTask | TradingTask) -> None:
        from apps.trading.services.live_risk import LiveTradingRiskError

        try:
            self.risk_guard.validate_task_dispatch(task)
        except LiveTradingRiskError as exc:
            raise TaskValidationError(str(exc)) from exc

    def _finalize_terminal_task(
        self,
        *,
        task: BacktestTask | TradingTask,
        task_type: str,
        status: TaskStatus,
        description: str,
        kind: str,
        extra_updates: dict[str, object] | None = None,
    ) -> None:
        self.writer.finalize_terminal_task(
            task=task,
            status=status,
            extra_updates=extra_updates,
        )
        self.events.publish(
            task=task,
            task_type=task_type,
            kind=kind,
            description=description,
        )

    def start_task(
        self,
        task: BacktestTask | TradingTask,
        *,
        user: Any | None = None,
    ) -> BacktestTask | TradingTask:
        """Submit a task to Celery for execution.

        Sets task status to STARTING and submits to Celery queue.
        The Celery task will update to RUNNING when it actually starts.

        Args:
            task: Task instance to submit

        Returns:
            BacktestTask | TradingTask: The updated task instance

        Raises:
            ValueError: If task is not in CREATED status
            RuntimeError: If Celery submission fails
        """

        try:
            self._ensure_task_owned_by_user(task, user)
            return self.commands.start(task)

        except TaskServiceError:
            raise
        except Exception as e:
            logger.error(
                "[SERVICE:START] CELERY_SUBMISSION_FAILED - task_id=%s, execution_id=%s, error=%s",
                task.pk,
                getattr(task, "execution_id", None),
                str(e),
                exc_info=True,
            )
            raise TaskSubmissionError(f"Failed to submit task to Celery: {str(e)}") from e

    def recover_trading_task(
        self,
        task: TradingTask,
        *,
        expected_celery_task_id: object = _UNSET,
    ) -> TradingTask:
        """Requeue an orphaned trading task in the same execution run."""

        previous_status = task.status
        previous_execution_id = task.execution_id

        with transaction.atomic():
            locked_task = TradingTask.objects.select_for_update().get(pk=task.pk)

            if locked_task.status not in (
                TaskStatus.STARTING,
                TaskStatus.RUNNING,
                TaskStatus.IDLE,
            ):
                raise TaskConflictError(
                    "Orphan recovery requires task in STARTING/RUNNING/IDLE state; "
                    f"got {locked_task.status}"
                )
            if not locked_task.execution_id:
                raise ValueError("Cannot recover trading task without an execution_id")
            if _identifier_mismatch(locked_task.celery_task_id, expected_celery_task_id):
                raise TaskConflictError(
                    "Trading task recovery was already claimed by another dispatch. "
                    "Reload the task before retrying."
                )
            self._ensure_dispatch_risk_guard_allows(locked_task)

            locked_task.status = TaskStatus.STARTING
            locked_task.completed_at = None
            locked_task.error_message = None
            locked_task.error_traceback = None
            locked_task.status_reason_code = ""
            locked_task.status_reason_message = ""
            # Rotate celery_task_id so the new Celery job is not suppressed
            # by the revoke list left over from the previous (orphaned)
            # worker.  execution_id is preserved so execution-scoped state
            # (ExecutionState, positions, events, ...) stays continuous.
            locked_task.celery_task_id = uuid4()
            locked_task.save(
                update_fields=[
                    "status",
                    "completed_at",
                    "error_message",
                    "error_traceback",
                    "status_reason_code",
                    "status_reason_message",
                    "celery_task_id",
                    "updated_at",
                ]
            )
            task = locked_task

        try:
            self._dispatch_task(task, "trading")
            return task
        except TaskConflictError:
            task.refresh_from_db()
            raise
        except Exception as exc:
            TradingTask.objects.filter(pk=task.pk).update(
                status=TaskStatus.FAILED,
                error_message=f"Failed to requeue orphaned trading task: {exc}",
                status_reason_code=TASK_FAILED_ERROR_CODE,
                status_reason_message=TASK_FAILED_PUBLIC_MESSAGE,
            )
            task.refresh_from_db()
            raise RuntimeError(
                "Failed to requeue orphaned trading task "
                f"(prev_status={previous_status}, prev_execution_id={previous_execution_id})"
            ) from exc

    def stop_task(
        self,
        task_id: UUID,
        mode: str = "graceful",
        *,
        drain_duration_minutes: int | None = None,
        user: Any | None = None,
    ) -> bool:
        """Stop a running task.

        Sets task status to STOPPING and signals Redis coordinator to stop.
        The Celery task will update to STOPPED when it actually stops.

        Args:
            task_id: UUID of the task to stop
            mode: Stop mode ('immediate', 'graceful', 'graceful_close', 'drain')
            drain_duration_minutes: Optional override (minutes) for drain
                timeout when ``mode == 'drain'``. When omitted the task's
                configured ``drain_duration_hours`` is used.

        Returns:
            bool: True if stop was successfully initiated, False otherwise

        Raises:
            ValueError: If task does not exist
        """

        try:
            if user is None:
                return self.commands.stop(
                    task_id,
                    mode,
                    drain_duration_minutes=drain_duration_minutes,
                )
            return self.commands.stop(
                task_id,
                mode,
                drain_duration_minutes=drain_duration_minutes,
                user=user,
            )
        except TaskValidationError:
            # Re-raise ValueError as-is (already logged)
            raise
        except ValueError as e:
            logger.error(
                f"[SERVICE:STOP] UNEXPECTED_ERROR - task_id={task_id}, error={str(e)}",
                exc_info=True,
            )
            raise ValueError(f"Failed to stop task: {str(e)}") from e
        except Exception as e:
            logger.error(
                f"[SERVICE:STOP] UNEXPECTED_ERROR - task_id={task_id}, error={str(e)}",
                exc_info=True,
            )
            raise ValueError(f"Failed to stop task: {str(e)}") from e

    def pause_task(self, task_id: UUID, *, user: Any | None = None) -> bool:
        """Pause a running task.

        Sets task status to PAUSED. The task can be resumed later.

        Args:
            task_id: UUID of the task to pause

        Returns:
            bool: True if task was successfully paused, False otherwise

        Raises:
            ValueError: If task does not exist or is not running
        """

        logger.info("Pausing task", extra={"task_id": str(task_id)})

        try:
            if user is None:
                self.commands.pause(task_id)
            else:
                self.commands.pause(task_id, user=user)

            logger.info(
                "Task paused successfully",
                extra={"task_id": str(task_id)},
            )
            return True

        except TaskValidationError:
            raise
        except Exception as e:
            logger.error(
                "Unexpected error pausing task",
                extra={"task_id": str(task_id)},
                exc_info=True,
            )
            raise ValueError(f"Failed to pause task: {str(e)}") from e

    def cancel_task(self, task_id: UUID, *, user: Any | None = None) -> bool:
        """Cancel a running task immediately.

        Revokes the Celery task and updates status to STOPPED.
        This is different from stop_task which uses graceful shutdown.

        Args:
            task_id: UUID of the task to cancel

        Returns:
            bool: True if task was successfully cancelled, False otherwise

        Raises:
            ValueError: If task does not exist
        """

        logger.info("Cancelling task", extra={"task_id": str(task_id)})

        try:
            if user is None:
                cancelled = self.commands.cancel(task_id)
            else:
                cancelled = self.commands.cancel(task_id, user=user)
            if not cancelled:
                return False

            logger.info(
                "Task cancelled successfully",
                extra={"task_id": str(task_id)},
            )
            return cancelled

        except TaskValidationError:
            raise
        except Exception as e:
            logger.error(
                "Unexpected error cancelling task",
                extra={"task_id": str(task_id)},
                exc_info=True,
            )
            raise ValueError(f"Failed to cancel task: {str(e)}") from e

    def restart_task(
        self,
        task_id: UUID,
        *,
        user: Any | None = None,
    ) -> BacktestTask | TradingTask:
        """Restart a task from the beginning, clearing all execution data.

        Clears all previous execution data and resets status to CREATED.
        Then resubmits the task.

        Args:
            task_id: UUID of the task to restart

        Returns:
            BacktestTask | TradingTask: The restarted task instance

        Raises:
            ValueError: If task does not exist
        """

        logger.info(f"[SERVICE:RESTART] Restarting task - task_id={task_id}")

        try:
            if user is None:
                return self.commands.restart(task_id)
            return self.commands.restart(task_id, user=user)

        except TaskValidationError:
            raise
        except Exception as e:
            logger.error(
                f"[SERVICE:RESTART] UNEXPECTED_ERROR - task_id={task_id}, error={str(e)}",
                exc_info=True,
            )
            raise ValueError(f"Failed to restart task: {str(e)}") from e

    def resume_task(
        self,
        task_id: UUID,
        *,
        user: Any | None = None,
    ) -> BacktestTask | TradingTask:
        """Resume a paused task, preserving execution context.

        Preserves existing execution data (started_at, logs, metrics) and
        resubmits the same execution run so persisted state can be loaded.

        Args:
            task_id: UUID of the task to resume

        Returns:
            BacktestTask | TradingTask: The resumed task instance

        Raises:
            TaskValidationError: If the task is not in a resumable state.
            TaskServiceError: If an unexpected internal failure occurred.
        """

        logger.info("Resuming task", extra={"task_id": str(task_id)})

        try:
            if user is None:
                task = self.commands.resume(task_id)
            else:
                task = self.commands.resume(task_id, user=user)
            logger.info("Task resumed, resubmitting", extra={"task_id": str(task_id)})
            return task

        except TaskValidationError:
            # Domain-level validation failure — message is a safe,
            # human-readable string constructed inside the service.
            raise
        except Exception as exc:
            # Anything else is an unexpected internal error.  We log the
            # full traceback but deliberately do NOT propagate the raw
            # message to callers because it may include DB driver /
            # Celery / third-party text that discloses implementation
            # details.  Callers should render a generic "try again"
            # message.
            logger.exception(
                "Unexpected error resuming task",
                extra={"task_id": str(task_id)},
            )
            raise TaskServiceError("Failed to resume task due to an internal error") from exc


def _identifier_mismatch(current: object, expected: object) -> bool:
    """Return whether an optional lifecycle identifier no longer matches."""

    if expected is _UNSET:
        return False
    return str(current or "") != str(expected or "")
