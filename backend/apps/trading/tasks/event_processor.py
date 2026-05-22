"""Event processing orchestration for task executors."""

from __future__ import annotations

from decimal import Decimal
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from apps.trading.dataclasses import EventExecutionResult
from apps.trading.enums import TaskType
from apps.trading.events.handler import CycleResolutionError
from apps.trading.order import OrderServiceError

if TYPE_CHECKING:
    from apps.trading.models.state import ExecutionState
    from apps.trading.tasks.executor import TaskExecutor


class TaskEventProcessor:
    """Process saved strategy events for a task executor."""

    def __init__(self, executor: TaskExecutor) -> None:
        self.executor = executor

    def process(
        self,
        state: ExecutionState,
        events: Sequence[Any],
        *,
        replaying: bool = False,
    ) -> None:
        executor = self.executor
        for trading_event in events:
            if getattr(trading_event, "is_processed", False):
                continue

            replay_classification = (
                executor._classify_replay_event(trading_event) if replaying else ""
            )
            if replaying:
                executor.logger.warning(
                    "Replaying event - task_id=%s, event_id=%s, event_type=%s, "
                    "strategy_event_type=%s, classification=%s, position_id=%s",
                    executor.task.pk,
                    trading_event.pk,
                    trading_event.event_type,
                    (
                        trading_event.details.get("strategy_event_type")
                        if isinstance(trading_event.details, dict)
                        else None
                    ),
                    replay_classification,
                    trading_event.position_id,
                )

            if executor.task_type == TaskType.TRADING and executor._event_already_applied(
                trading_event=trading_event,
                state=state,
            ):
                executor._mark_event_processed(trading_event)
                if replaying:
                    executor.logger.info(
                        "Skipped replayed event already reflected in state - task_id=%s, "
                        "event_id=%s, classification=%s",
                        executor.task.pk,
                        trading_event.pk,
                        replay_classification,
                    )
                continue

            try:
                execution_result: EventExecutionResult = (
                    executor.event_handler.handle_event_with_replay(
                        trading_event,
                        replaying=replaying,
                    )
                )
                self._apply_execution_result(state, execution_result)
                executor.engine.apply_event_execution_result(
                    state=state,
                    execution_result=execution_result,
                )
                executor._mark_event_processed(trading_event)

                if replaying:
                    executor.logger.warning(
                        "Replay applied - task_id=%s, event_id=%s, classification=%s, "
                        "position_ids=%s, order_ids=%s, trade_ids=%s, "
                        "broker_order_ids=%s, oanda_trade_ids=%s",
                        executor.task.pk,
                        trading_event.pk,
                        replay_classification,
                        list(execution_result.position_ids),
                        list(execution_result.order_ids),
                        list(execution_result.trade_ids),
                        list(execution_result.broker_order_ids),
                        list(execution_result.oanda_trade_ids),
                    )

                if executor.task_type == TaskType.TRADING:
                    executor.save_state(state)
            except OrderServiceError as exc:
                executor.logger.error(
                    "Order execution failed for trading event %s: %s",
                    trading_event.pk,
                    exc,
                    exc_info=True,
                )
                executor._mark_event_processing_error(trading_event, str(exc))
            except CycleResolutionError as exc:
                executor._mark_event_processing_error(trading_event, str(exc))
                raise

        executor._refresh_open_positions_cache()

        executor.logger.debug(
            "Processed %s events for trading task %s (open positions: %s)",
            len(events),
            executor.task.pk,
            len(executor.event_handler.get_open_positions()),
        )

    def _apply_execution_result(
        self,
        state: ExecutionState,
        execution_result: EventExecutionResult,
    ) -> None:
        executor = self.executor
        if execution_result.realized_pnl_delta != Decimal("0"):
            state.current_balance = (
                Decimal(str(state.current_balance)) + execution_result.realized_pnl_delta
            )
            if execution_result.realized_pnl_delta_currency:
                state.current_balance_currency = execution_result.realized_pnl_delta_currency
            executor._runtime_metrics.record_position_closed(
                execution_result.realized_pnl_delta,
                realized_pnl_quote=execution_result.realized_pnl_delta_quote,
            )
        uses_in_memory_mode = getattr(executor, "uses_in_memory_mode", False) is True
        if (
            execution_result.realized_pnl_delta == Decimal("0")
            and uses_in_memory_mode
            and execution_result.entry_binding is None
            and execution_result.executed_units
        ):
            executor._runtime_metrics.record_position_closed(
                Decimal("0"),
                realized_pnl_quote=Decimal("0"),
            )
        if uses_in_memory_mode and execution_result.trade_ids:
            for _ in execution_result.trade_ids:
                executor._runtime_metrics.record_trade()
        elif execution_result.entry_binding is not None:
            executor._runtime_metrics.record_trade()
