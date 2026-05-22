"""Collaborators that keep TaskExecutor orchestration focused."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.trading.events import StrategyEvent
from apps.trading.models import BacktestTask
from apps.trading.models.state import ExecutionState
from apps.trading.tasks.event_persistence import (
    materialize_execution_events,
    persist_strategy_events,
)

if TYPE_CHECKING:
    from apps.trading.tasks.executor import ExecutionLoopState, TaskExecutor


class ExecutionEventDispatcher:
    """Persist and dispatch strategy events for a task executor."""

    def __init__(self, executor: "TaskExecutor") -> None:
        """Bind event persistence/dispatch to an executor instance."""
        self.executor = executor

    def process(
        self,
        state: ExecutionState,
        events: list[Any],
        *,
        replaying: bool = False,
    ) -> None:
        """Dispatch persisted events through the executor's event processor."""
        self.executor.event_processor.process(state, events, replaying=replaying)

    def persist(self, events: list[StrategyEvent]) -> list[Any]:
        """Persist strategy events to database rows."""
        executor = self.executor
        strategy_type = str(getattr(executor.task.config, "strategy_type", "") or "")
        if executor.uses_in_memory_mode:
            return materialize_execution_events(
                events=events,
                context=executor.event_context,
                execution_id=executor.task.execution_id,
                strategy_type=strategy_type,
            )
        return persist_strategy_events(
            events=events,
            context=executor.event_context,
            execution_id=executor.task.execution_id,
            strategy_type=strategy_type,
        )


class ExecutionStateRepository:
    """Load and save execution state for a task executor."""

    def __init__(self, executor: "TaskExecutor") -> None:
        """Bind state persistence to an executor instance."""
        self.executor = executor

    def load(self) -> ExecutionState:
        """Load the current execution state."""
        state, _ = self.load_with_metadata()
        return state

    def load_with_metadata(self) -> tuple[ExecutionState, bool]:
        """Load state and indicate whether this execution is a resume."""
        executor = self.executor
        task = executor.task
        state_model = self._state_model()
        task.refresh_from_db()

        try:
            state = state_model.objects.get(
                task_type=executor.task_type.value,
                task_id=task.pk,
                execution_id=task.execution_id,
            )
            executor.logger.info(
                "Existing ExecutionState found (resume) - task_id=%s, "
                "execution_id=%s, balance=%s, ticks=%d",
                task.pk,
                task.execution_id,
                state.current_balance,
                state.ticks_processed,
            )
            from apps.trading.services.backtest_initial_positions import (
                is_initial_position_preview_state,
            )

            if is_initial_position_preview_state(state):
                executor.logger.info(
                    "Existing ExecutionState is a Snowball initial-position preview; "
                    "starting as a fresh execution. task_id=%s, execution_id=%s",
                    task.pk,
                    task.execution_id,
                )
                return state, False
            return state, True
        except state_model.DoesNotExist:
            pass

        existing_count = state_model.objects.filter(
            task_type=executor.task_type.value,
            task_id=task.pk,
        ).count()
        executor.logger.info(
            "No ExecutionState for current execution_id - creating fresh state. "
            "task_id=%s, execution_id=%s, task_type=%s, "
            "other_execution_states_for_task=%d",
            task.pk,
            task.execution_id,
            executor.task_type.value,
            existing_count,
        )

        initial_timestamp = task.start_time if isinstance(task, BacktestTask) else None
        state = state_model.objects.create(
            task_type=executor.task_type.value,
            task_id=task.pk,
            execution_id=task.execution_id,
            strategy_state={},
            current_balance=executor.initial_balance,
            current_balance_currency=executor.account_currency,
            ticks_processed=0,
            last_tick_timestamp=initial_timestamp,
            resume_cursor_timestamp=initial_timestamp,
        )
        return state, False

    @staticmethod
    def _state_model():
        """Return the patchable ExecutionState symbol from the executor module."""
        from apps.trading.tasks import executor as executor_module

        return executor_module.ExecutionState

    def save(self, state: ExecutionState) -> None:
        """Persist execution state."""
        self.executor.logger.debug(
            "Saving state: task_id=%s, ticks_processed=%s, "
            "last_tick_timestamp=%s, current_balance=%s",
            state.task_id,
            state.ticks_processed,
            state.last_tick_timestamp,
            state.current_balance,
        )
        self.executor.state_store.save(state)


class ExecutionTickLoop:
    """Batch/tick loop coordinator for a task executor."""

    def __init__(self, executor: "TaskExecutor") -> None:
        """Bind loop orchestration to an executor instance."""
        self.executor = executor

    def run(self, loop: "ExecutionLoopState") -> None:
        """Run batch/tick processing loop."""
        executor = self.executor
        executor.logger.info("Starting tick processing loop")
        executor._flush_task_logs()

        for tick_batch in executor.data_source:
            if executor._should_stop_before_batch(loop):
                break

            if not tick_batch:
                should_stop = executor._handle_empty_batch(loop)
                executor._flush_task_logs()
                if should_stop:
                    break
                continue

            loop.no_tick_batches = 0
            loop.market_closed_empty_batch_logged = False
            executor._process_tick_batch(loop, tick_batch)
            loop.batch_count += 1
            executor._persist_batch_progress(loop)
            executor._after_batch_processed(loop)
            executor._flush_task_logs()

            if loop.stopped_early:
                break

        executor.logger.info(
            "Exited tick processing loop - task_id=%s, stopped_early=%s, ticks_processed=%d",
            executor.task.pk,
            loop.stopped_early,
            loop.state.ticks_processed,
        )
        executor._flush_task_logs()
