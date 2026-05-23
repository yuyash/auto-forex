"""Command objects for task lifecycle orchestration."""

from __future__ import annotations

from logging import Logger
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from celery.result import AsyncResult
from django.conf import settings
from django.db import transaction

from apps.trading.enums import StopMode, TaskStatus
from apps.trading.models import BacktestTask, TradingTask
from apps.trading.tasks.lifecycle_adapters import (
    LifecycleCommandAdapters,
    create_default_lifecycle_adapters,
)
from apps.trading.tasks.lifecycle_events import (
    TaskLifecycleEventPublisher,
    build_cancelled_event_spec,
    build_pause_requested_event_spec,
    build_restart_requested_event_spec,
    build_start_requested_event_spec,
    build_stop_requested_event_spec,
)
from apps.trading.tasks.lifecycle_plans import (
    LifecycleCommandResult,
    build_resume_command_plan,
    build_stop_command_plan,
)
from apps.trading.tasks.lifecycle_state_machine import allowed_statuses_for_command
from apps.trading.tasks.lifecycle_validators import ResumeCommandValidator
from apps.trading.services.status_reasons import (
    empty_status_reason_update,
    stop_request_reason,
)

if TYPE_CHECKING:
    from apps.trading.tasks.service import TaskService


class TaskLifecycleCommands:
    """Encapsulate task lifecycle command flows behind explicit operations."""

    def __init__(
        self,
        *,
        service: TaskService,
        logger: Logger,
        events: TaskLifecycleEventPublisher | None = None,
        adapters: LifecycleCommandAdapters | None = None,
    ) -> None:
        self.service = service
        self.logger = logger
        self.events = events or TaskLifecycleEventPublisher(logger=logger)
        self.adapters = adapters or create_default_lifecycle_adapters()
        self.resume_validator = ResumeCommandValidator(
            logger=logger,
            ensure_dispatch_risk_guard_allows=service._ensure_dispatch_risk_guard_allows,
        )

    def start(self, task: BacktestTask | TradingTask) -> BacktestTask | TradingTask:
        self._assert_transition_allowed(
            command="start",
            task_status=task.status,
            message=(f"Task must be in CREATED status to submit (current status: {task.status})"),
        )
        self.logger.info(
            "[SERVICE:START] Submitting task - task_id=%s, task_status=%s, instrument=%s, start_time=%s, end_time=%s",
            task.pk,
            task.status,
            task.instrument,
            getattr(task, "start_time", "N/A"),
            getattr(task, "end_time", "N/A"),
        )

        is_backtest_task = isinstance(task, BacktestTask) or hasattr(task, "start_time")
        model_class = BacktestTask if is_backtest_task else TradingTask
        task_type = "backtest" if is_backtest_task else "trading"

        try:
            if (
                getattr(task, "initial_positions_enabled", False) is True
                and getattr(task, "in_memory_mode", False) is not True
            ):
                from apps.trading.services.backtest_initial_positions import (
                    BacktestInitialPositionService,
                )

                BacktestInitialPositionService().sync_for_task(task)
                task.refresh_from_db()
            task = self._prepare_start(task=task, model_class=model_class)
            self.logger.info(
                "[SERVICE:START] Task type determined - task_id=%s, type=%s, execution_id=%s",
                task.pk,
                task_type,
                task.execution_id,
            )
            self.logger.info(
                "[SERVICE:START] Submitting to Celery - task_id=%s, execution_id=%s",
                task.pk,
                task.execution_id,
            )
            transition = LifecycleCommandResult(
                command="start",
                previous_status=TaskStatus.CREATED,
                current_status=task.status,
                event=build_start_requested_event_spec(),
                dispatch_task=True,
            )
            if transition.dispatch_task:
                self.service._dispatch_task(task, task_type)
            if task_type == "trading":
                self._kick_market_supervisor()
            self.logger.info(
                "[SERVICE:START] Task submitted to Celery - task_id=%s, execution_id=%s, new_status=%s",
                task.pk,
                task.execution_id,
                task.status,
            )
            self._audit_command_transition(task=task, task_type=task_type, transition=transition)
            self._publish_command_event(task=task, task_type=task_type, transition=transition)
            self._log_worker_state(task)
            return task
        except Exception:
            self._reset_failed_start(task=task, model_class=model_class)
            raise

    def _kick_market_supervisor(self) -> None:
        """Kick the market tick supervisor outside eager test execution."""
        if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
            self.logger.info("[SERVICE:START] Skipping market supervisor kick in eager Celery mode")
            return

        from apps.market.tasks import ensure_tick_pubsub_running

        ensure_tick_pubsub_running.apply_async(countdown=0, queue="system")

    def stop(
        self,
        task_id: UUID,
        mode: str = "graceful",
        *,
        drain_duration_minutes: int | None = None,
        user: Any | None = None,
    ) -> bool:
        self.logger.info(
            "[SERVICE:STOP] Stopping task - task_id=%s, mode=%s, drain_duration_minutes=%s",
            task_id,
            mode,
            drain_duration_minutes,
        )
        try:
            stop_mode = StopMode(mode)
        except ValueError as exc:
            raise ValueError(f"Invalid stop mode: {mode}") from exc
        task, task_type = self.service._get_task_and_type(task_id, user=user)
        if (
            task_type == "backtest"
            and getattr(task, "in_memory_mode", False) is True
            and stop_mode == StopMode.DRAIN
        ):
            raise ValueError("Drain stop is not supported for in-memory backtests.")
        is_backtest = task_type == "backtest"
        task_name = (
            "trading.tasks.run_backtest_task" if is_backtest else "trading.tasks.run_trading_task"
        )

        self.logger.info(
            "[SERVICE:STOP] Current task state - task_id=%s, status=%s, execution_id=%s",
            task_id,
            task.status,
            task.execution_id,
        )
        previous_status = task.status

        if task.status in [TaskStatus.STOPPED, TaskStatus.COMPLETED, TaskStatus.FAILED]:
            self.logger.info(
                "[SERVICE:STOP] Already in terminal state: %s - task_id=%s",
                task.status,
                task_id,
            )
            return True
        self._assert_transition_allowed(
            command="stop",
            task_status=task.status,
            message=f"Task cannot be stopped from {task.status} state",
        )

        stop_plan = build_stop_command_plan(
            current_status=task.status,
            requested_mode=stop_mode,
        )
        if stop_plan.escalation_log_message:
            self.logger.info(
                stop_plan.escalation_log_message,
                task_id,
            )

        stop_reason = stop_request_reason(stop_plan.effective_mode)
        self.service.writer.persist_state_if_current(
            command="stop",
            task=task,
            from_status=previous_status,
            to_status=stop_plan.next_status,
            extra_updates={
                **stop_plan.extra_updates,
                **stop_reason.as_update(),
            },
        )
        transition = LifecycleCommandResult(
            command="stop",
            previous_status=previous_status,
            current_status=task.status,
            event=build_stop_requested_event_spec(mode=stop_plan.effective_mode),
            audit_details={
                "mode": stop_plan.effective_mode.value,
                "drain_duration_minutes": drain_duration_minutes,
            },
        )
        self._audit_command_transition(task=task, task_type=task_type, transition=transition)

        # Persist per-stop drain duration override so the executor picks
        # it up on the next drain evaluation. Written only when drain is
        # the effective mode and a positive value was supplied.
        if (
            stop_plan.effective_mode == StopMode.DRAIN
            and drain_duration_minutes
            and drain_duration_minutes > 0
        ):
            self._record_drain_duration_minutes_override(
                task_id=task_id,
                task_type=task_type,
                execution_id=task.execution_id,
                minutes=int(drain_duration_minutes),
            )

        self._signal_redis_stop(
            task_id=task_id,
            task_name=task_name,
            execution_id=task.execution_id,
            stop_mode=stop_plan.effective_mode,
        )
        # Fall back to execution_id for older rows that pre-date the
        # celery_task_id field and may still have it set to NULL.
        celery_id = getattr(task, "celery_task_id", None) or task.execution_id
        if stop_plan.should_revoke_execution and celery_id:
            self._revoke_execution(celery_id)
        # DRAIN mode keeps the worker running — don't dispatch the stop
        # finalisation task; the executor will transition to STOPPED when
        # it finishes draining.
        if stop_plan.should_dispatch_stop_task:
            self._trigger_stop_task(
                task_id=task_id,
                is_backtest=is_backtest,
                stop_mode=stop_plan.effective_mode,
            )

        self._publish_command_event(task=task, task_type=task_type, transition=transition)
        return True

    def pause(self, task_id: UUID, *, user: Any | None = None) -> bool:
        task, task_type = self.service._get_task_and_type(task_id, user=user)
        previous_status = task.status

        # Pause is only supported for backtest tasks.  Trading tasks should
        # use stop (which preserves execution state) and then resume.
        if task_type == "trading":
            raise ValueError(
                "Pause is not supported for trading tasks. "
                "Use stop instead — stopped trading tasks can be resumed."
            )
        if getattr(task, "in_memory_mode", False) is True:
            raise ValueError("Pause is not supported for in-memory backtests.")

        self._assert_transition_allowed(
            command="pause",
            task_status=task.status,
            message=(
                f"Task cannot be paused in {task.status} state. "
                "Only STARTING or RUNNING tasks can be paused."
            ),
        )
        task_name = (
            "trading.tasks.run_backtest_task"
            if task_type == "backtest"
            else "trading.tasks.run_trading_task"
        )
        self.service.writer.persist_state_if_current(
            command="pause",
            task=task,
            from_status=previous_status,
            to_status=TaskStatus.PAUSED,
        )
        transition = LifecycleCommandResult(
            command="pause",
            previous_status=previous_status,
            current_status=TaskStatus.PAUSED,
            event=build_pause_requested_event_spec(),
        )
        self._audit_command_transition(task=task, task_type=task_type, transition=transition)
        self._signal_redis_pause(
            task_id=task_id,
            task_name=task_name,
            execution_id=task.execution_id,
        )
        self._publish_command_event(task=task, task_type=task_type, transition=transition)
        return True

    def cancel(self, task_id: UUID, *, user: Any | None = None) -> bool:
        task, task_type = self.service._get_task_and_type(task_id, user=user)
        if task.status not in [TaskStatus.STARTING, TaskStatus.RUNNING, TaskStatus.PAUSED]:
            self.logger.warning(
                "Task not in cancellable state",
                extra={"task_id": str(task_id), "status": task.status},
            )
            return False

        previous_status = task.status
        self.service.writer.persist_terminal_state_if_current(
            command="cancel",
            task=task,
            from_status=previous_status,
            to_status=TaskStatus.STOPPED,
        )
        transition = LifecycleCommandResult(
            command="cancel",
            previous_status=previous_status,
            current_status=TaskStatus.STOPPED,
            event=build_cancelled_event_spec(),
        )

        # Fall back to execution_id for older rows that pre-date the
        # celery_task_id field.
        celery_id = getattr(task, "celery_task_id", None) or task.execution_id
        result = self.service.get_celery_result(str(celery_id) if celery_id else None)
        if result:
            result.revoke(terminate=True)

        self._publish_command_event(task=task, task_type=task_type, transition=transition)
        return True

    def restart(
        self,
        task_id: UUID,
        *,
        user: Any | None = None,
    ) -> BacktestTask | TradingTask:
        task, task_type = self.service._get_task_and_type(task_id, user=user)
        self._assert_transition_allowed(
            command="restart",
            task_status=task.status,
            message=f"Task cannot be restarted from {task.status} state",
        )
        previous_status = task.status
        if task.status in [TaskStatus.STARTING, TaskStatus.RUNNING, TaskStatus.STOPPING]:
            try:
                if user is None:
                    self.service.stop_task(task_id)
                else:
                    self.service.stop_task(task_id, user=user)
                self.adapters.sleep(1)
                task.refresh_from_db()
            except Exception as exc:  # pragma: no cover - defensive logging path
                self.logger.warning(
                    "[SERVICE:RESTART] Stop failed, forcing restart anyway - task_id=%s, error=%s",
                    task_id,
                    exc,
                )

        # Fall back to execution_id for older rows that pre-date the
        # celery_task_id field.
        celery_id = getattr(task, "celery_task_id", None) or task.execution_id
        if celery_id:
            self._revoke_execution(celery_id)

        self.service.writer.clear_execution_history(task=task, task_type=task_type)
        self.service.writer.update_if_current(
            command="restart",
            task=task,
            expected_status=task.status,
            updates={
                "execution_id": None,
                "celery_task_id": None,
                "status": TaskStatus.CREATED,
                "started_at": None,
                "completed_at": None,
                "error_message": None,
                "error_traceback": None,
                **empty_status_reason_update(),
            },
        )
        task.refresh_from_db()
        if task.status != TaskStatus.CREATED:
            raise RuntimeError(f"Failed to reset task status: expected CREATED, got {task.status}")
        transition = LifecycleCommandResult(
            command="restart",
            previous_status=previous_status,
            current_status=TaskStatus.CREATED,
            event=build_restart_requested_event_spec(),
        )
        self._audit_command_transition(task=task, task_type=task_type, transition=transition)
        self._publish_command_event(task=task, task_type=task_type, transition=transition)
        if user is None:
            return self.service.start_task(task)
        return self.service.start_task(task, user=user)

    def resume(
        self,
        task_id: UUID,
        *,
        user: Any | None = None,
    ) -> BacktestTask | TradingTask:
        task, task_type = self.service._get_task_and_type(task_id, user=user)
        if task_type == "backtest" and getattr(task, "in_memory_mode", False) is True:
            raise ValueError("Resume is not supported for in-memory backtests.")
        model_class = self.service._get_task_model(task_type)
        is_trading = task_type == "trading"

        transition: LifecycleCommandResult
        with transaction.atomic():
            locked_task = model_class.objects.select_for_update().get(pk=task.pk)
            previous_status = locked_task.status
            self.resume_validator.validate(task=locked_task, task_type=task_type)

            previous_celery_task_id = locked_task.celery_task_id
            result = self.service.get_celery_result(
                str(previous_celery_task_id) if previous_celery_task_id else None
            )
            self._ensure_resumeable_celery_state(
                result=result,
                task_id=task_id,
                db_status=locked_task.status,
                celery_task_id=previous_celery_task_id,
            )
            resume_plan = build_resume_command_plan(
                previous_status=previous_status,
                previous_celery_task_id=previous_celery_task_id,
                new_celery_task_id=uuid4(),
            )

            # Revoke any lingering Celery task for this execution before
            # dispatching a new one. This is a no-op for a clean exit but
            # defensively handles cases where a previous worker crashed
            # without cleaning up its result backend entry.
            #
            # After revoking, we MUST allocate a fresh ``celery_task_id``
            # for the next run: Celery's revoke list persists by task_id,
            # so re-submitting ``apply_async(task_id=<same>)`` causes the
            # worker to drop the message immediately (the symptom is a
            # task stuck in STARTING indefinitely).  Rotating just the
            # ``celery_task_id`` — not ``execution_id`` — sidesteps the
            # revoke list while keeping the execution-scoped state
            # (ExecutionState, positions, events, trades, ...) continuous
            # across the resume.
            if resume_plan.should_revoke_previous_execution:
                try:
                    self._revoke_execution(previous_celery_task_id)
                except Exception as exc:  # pragma: no cover - best effort
                    self.logger.debug(
                        "Pre-resume revoke skipped - task_id=%s, error=%s",
                        task_id,
                        exc,
                    )

            # Clear error fields when resuming from a terminal state so the
            # execution starts cleanly while preserving execution_id and
            # all persisted state (strategy_state, events, positions, etc.).
            if resume_plan.should_clear_terminal_fields:
                locked_task.error_message = None
                locked_task.error_traceback = None
                locked_task.completed_at = None
                locked_task.status_reason_code = ""
                locked_task.status_reason_message = ""

            # Always rotate the Celery task id on resume so the next
            # worker invocation is guaranteed to be accepted.
            locked_task.celery_task_id = resume_plan.new_celery_task_id

            locked_task.status = resume_plan.next_status
            locked_task.save(update_fields=list(resume_plan.update_fields))
            transition = resume_plan.transition
            self._audit_command_transition(
                task=locked_task,
                task_type=task_type,
                transition=transition,
            )
            task = locked_task

        self._publish_command_event(task=task, task_type=task_type, transition=transition)
        if transition.dispatch_task:
            self.service._dispatch_task(task, task_type)
        if is_trading:
            self._kick_market_supervisor()
        return task

    def _prepare_start(
        self,
        *,
        task: BacktestTask | TradingTask,
        model_class: type[BacktestTask] | type[TradingTask],
    ) -> BacktestTask | TradingTask:
        if type(task) in (BacktestTask, TradingTask):
            return self.service._prepare_locked_start_task(task, model_class=model_class)
        return self.service._prepare_detached_start_task(task)

    def _reset_failed_start(
        self,
        *,
        task: BacktestTask | TradingTask,
        model_class: type[BacktestTask] | type[TradingTask],
    ) -> None:
        if type(task) in (BacktestTask, TradingTask):
            model_class.objects.filter(pk=task.pk).update(
                status=TaskStatus.CREATED,
                execution_id=None,
                celery_task_id=None,
                **empty_status_reason_update(),
            )
            task.refresh_from_db()
            return

        task.status = TaskStatus.CREATED
        task.execution_id = None
        task.celery_task_id = None
        task.status_reason_code = ""
        task.status_reason_message = ""
        try:
            task.save(
                update_fields=[
                    "status",
                    "execution_id",
                    "celery_task_id",
                    "status_reason_code",
                    "status_reason_message",
                ]
            )
        except TypeError:
            task.save()

    def _log_worker_state(self, task: BacktestTask | TradingTask) -> None:
        active_workers = self.adapters.inspect_workers()
        if not active_workers:
            self.logger.warning(
                "[SERVICE:START] NO_WORKERS - No active Celery workers detected. task_id=%s, execution_id=%s",
                task.pk,
                task.execution_id,
            )
            return
        self.logger.info(
            "[SERVICE:START] Active workers found - task_id=%s, workers=%s",
            task.pk,
            list(active_workers.keys()),
        )

    def _signal_redis_stop(
        self,
        *,
        task_id: UUID,
        task_name: str,
        execution_id: object,
        stop_mode: StopMode,
    ) -> None:
        try:
            self.adapters.signal_stop(task_id, task_name, execution_id, stop_mode)
        except Exception as exc:  # pragma: no cover - defensive logging path
            self.logger.warning(
                "[SERVICE:STOP] Redis signal failed (non-fatal) - task_id=%s, error=%s",
                task_id,
                exc,
            )

    def _signal_redis_pause(
        self,
        *,
        task_id: UUID,
        task_name: str,
        execution_id: object,
    ) -> None:
        try:
            self.adapters.signal_pause(task_id, task_name, execution_id)
        except Exception as exc:  # pragma: no cover - defensive logging path
            self.logger.warning(
                "[SERVICE:PAUSE] Redis signal failed (non-fatal) - task_id=%s, error=%s",
                task_id,
                exc,
            )

    def _revoke_execution(self, celery_task_id: object) -> None:
        try:
            self.adapters.revoke_execution(celery_task_id)
        except Exception as exc:  # pragma: no cover - defensive logging path
            self.logger.warning(
                "[SERVICE:LIFECYCLE] Celery revoke failed (non-fatal) - celery_task_id=%s, error=%s",
                celery_task_id,
                exc,
            )

    def _trigger_stop_task(
        self,
        *,
        task_id: UUID,
        is_backtest: bool,
        stop_mode: StopMode,
    ) -> None:
        try:
            self.adapters.dispatch_stop(task_id, is_backtest, stop_mode)
        except Exception as exc:  # pragma: no cover - defensive logging path
            self.logger.warning(
                "[SERVICE:STOP] Stop task trigger failed (non-fatal) - task_id=%s, error=%s",
                task_id,
                exc,
            )

    def _record_drain_duration_minutes_override(
        self,
        *,
        task_id: UUID,
        task_type: str,
        execution_id: object,
        minutes: int,
    ) -> None:
        """Store a per-stop drain duration override on the execution state.

        The executor reads this value on the next drain evaluation and
        prefers it over the task-level ``drain_duration_hours``.  A
        missing or zero value means "fall back to the task field".
        """
        from apps.trading.models import ExecutionState

        try:
            state = ExecutionState.objects.filter(
                task_type=task_type,
                task_id=task_id,
                execution_id=execution_id,
            ).first()
            if state is None:
                self.logger.debug(
                    "[SERVICE:STOP] No ExecutionState to record drain override - "
                    "task_id=%s execution_id=%s",
                    task_id,
                    execution_id,
                )
                return
            strategy_state = state.strategy_state if isinstance(state.strategy_state, dict) else {}
            strategy_state["_drain_duration_minutes_override"] = int(minutes)
            state.strategy_state = strategy_state
            state.save(update_fields=["strategy_state", "updated_at"])
        except Exception as exc:  # pragma: no cover - best effort
            self.logger.warning(
                "[SERVICE:STOP] Failed to record drain duration override - task_id=%s error=%s",
                task_id,
                exc,
            )

    def _ensure_resumeable_celery_state(
        self,
        *,
        result: AsyncResult | None,
        task_id: UUID,
        db_status: TaskStatus,
        celery_task_id: object,
    ) -> None:
        if not result:
            return
        celery_state = result.state
        # For STOPPED/FAILED tasks the worker has already exited — the
        # Celery result backend may still report STARTED if the previous
        # worker crashed before updating the backend.  Since the DB is
        # the authoritative state for task lifecycle, skip the Celery
        # guard for terminal DB statuses and allow the resume to proceed.
        if db_status in (TaskStatus.STOPPED, TaskStatus.FAILED):
            if celery_state in ["PENDING", "STARTED", "RETRY"]:
                self.logger.info(
                    "Stale Celery state detected for terminal task; "
                    "proceeding with resume - task_id=%s, db_status=%s, "
                    "celery_state=%s, celery_task_id=%s",
                    task_id,
                    db_status,
                    celery_state,
                    celery_task_id,
                )
            return

        if celery_state in ["PENDING", "STARTED", "RETRY"]:
            self.logger.warning(
                "Task status mismatch detected",
                extra={
                    "task_id": str(task_id),
                    "db_status": db_status,
                    "celery_state": celery_state,
                    "celery_task_id": str(celery_task_id),
                },
            )
            from apps.trading.tasks.service import TaskValidationError

            raise TaskValidationError(
                f"Task status mismatch: task is marked as {db_status} in database "
                f"but Celery task is still {celery_state}. "
                "Please wait for the task to fully stop before resuming."
            )

    def _assert_transition_allowed(
        self,
        *,
        command: str,
        task_status: TaskStatus,
        message: str,
    ) -> None:
        allowed = allowed_statuses_for_command(command)
        if not allowed or task_status in allowed:
            return
        from apps.trading.tasks.service import TaskValidationError

        raise TaskValidationError(message)

    def _audit_command_transition(
        self,
        *,
        task: BacktestTask | TradingTask,
        task_type: str,
        transition: LifecycleCommandResult,
    ) -> None:
        self._audit_lifecycle_transition(
            command=transition.command,
            task_id=task.pk,
            task_type=task_type,
            from_status=transition.previous_status,
            to_status=transition.current_status,
            execution_id=task.execution_id,
            celery_task_id=getattr(task, "celery_task_id", None),
            **transition.audit_details,
        )

    def _publish_command_event(
        self,
        *,
        task: BacktestTask | TradingTask,
        task_type: str,
        transition: LifecycleCommandResult,
    ) -> None:
        self.events.publish_spec(
            task=task,
            task_type=task_type,
            event=transition.event,
        )

    def _audit_lifecycle_transition(
        self,
        *,
        command: str,
        task_id: UUID,
        task_type: str,
        from_status: TaskStatus | str,
        to_status: TaskStatus | str,
        execution_id: object,
        celery_task_id: object,
        **extra: object,
    ) -> None:
        payload: dict[str, object] = {
            "command": command,
            "task_id": str(task_id),
            "task_type": task_type,
            "from_status": str(from_status),
            "to_status": str(to_status),
            "execution_id": str(execution_id) if execution_id else "",
            "celery_task_id": str(celery_task_id) if celery_task_id else "",
        }
        payload.update(extra)
        self.logger.info("[LIFECYCLE:AUDIT] %s", payload)
