"""Unit tests for task event processing orchestration."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, call

from apps.trading.dataclasses import EntryExecutionBinding, EventExecutionResult
from apps.trading.enums import TaskType
from apps.trading.tasks.event_processor import TaskEventProcessor


def _executor(*, task_type: TaskType = TaskType.BACKTEST):
    result = EventExecutionResult(
        realized_pnl_delta=Decimal("12.5"),
        realized_pnl_delta_quote=Decimal("12.5"),
        entry_binding=EntryExecutionBinding(entry_id=1, position_id="pos-1"),
        position_ids=("pos-1",),
    )
    event_handler = SimpleNamespace(
        handle_event_with_replay=MagicMock(return_value=result),
        get_open_positions=MagicMock(return_value=[]),
    )
    return SimpleNamespace(
        task=SimpleNamespace(pk="task-1"),
        task_type=task_type,
        event_handler=event_handler,
        engine=SimpleNamespace(apply_event_execution_result=MagicMock()),
        logger=SimpleNamespace(
            debug=MagicMock(), info=MagicMock(), warning=MagicMock(), error=MagicMock()
        ),
        _runtime_metrics=SimpleNamespace(
            record_position_closed=MagicMock(),
            record_trade=MagicMock(),
            record_oanda_order_response=MagicMock(),
        ),
        _classify_replay_event=MagicMock(return_value="new"),
        _event_already_applied=MagicMock(return_value=False),
        _mark_event_processed=MagicMock(),
        _mark_event_processing_error=MagicMock(),
        _refresh_open_positions_cache=MagicMock(),
        save_state=MagicMock(),
    )


def test_process_applies_execution_result_and_records_metrics():
    executor = _executor()
    state = SimpleNamespace(current_balance=Decimal("100"))
    event = SimpleNamespace(
        pk="event-1",
        is_processed=False,
        event_type="trade_executed",
        details={},
        position_id=None,
    )

    TaskEventProcessor(executor).process(state, [event])

    assert state.current_balance == Decimal("112.5")
    executor._runtime_metrics.record_position_closed.assert_called_once_with(
        Decimal("12.5"),
        realized_pnl_quote=Decimal("12.5"),
    )
    executor._runtime_metrics.record_trade.assert_called_once()
    executor.engine.apply_event_execution_result.assert_called_once()
    executor._mark_event_processed.assert_called_once_with(event)
    executor._refresh_open_positions_cache.assert_called_once()


def test_process_records_oanda_order_response_metrics():
    executor = _executor()
    executor.event_handler.handle_event_with_replay.return_value = EventExecutionResult(
        oanda_response_seconds=(Decimal("0.123456"), Decimal("0.234567")),
    )
    state = SimpleNamespace(current_balance=Decimal("100"))
    event = SimpleNamespace(
        pk="event-1",
        is_processed=False,
        event_type="trade_executed",
        details={},
        position_id=None,
    )

    TaskEventProcessor(executor).process(state, [event])

    assert executor._runtime_metrics.record_oanda_order_response.call_args_list == [
        call(Decimal("0.123456")),
        call(Decimal("0.234567")),
    ]


def test_process_skips_already_applied_trading_replay_events():
    executor = _executor(task_type=TaskType.TRADING)
    executor._event_already_applied.return_value = True
    state = SimpleNamespace(current_balance=Decimal("100"))
    event = SimpleNamespace(
        pk="event-1",
        is_processed=False,
        event_type="trade_executed",
        details={},
        position_id=None,
    )

    TaskEventProcessor(executor).process(state, [event], replaying=True)

    executor._mark_event_processed.assert_called_once_with(event)
    executor.event_handler.handle_event_with_replay.assert_not_called()
    executor.save_state.assert_not_called()
