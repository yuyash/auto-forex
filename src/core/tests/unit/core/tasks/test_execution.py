import logging
from datetime import UTC, datetime

import pytest

from autoforex.core import CORE_LOGGER_NAME, CurrencyPair, ErrorCategory, ErrorCode, ManualClock
from autoforex.core.tasks import (
    BacktestTaskDefinition,
    ExecutableTask,
    TaskFailure,
    TaskStateError,
    TaskStatus,
)


def _definition() -> BacktestTaskDefinition:
    return BacktestTaskDefinition(
        name="Backtest USD_JPY",
        instrument=CurrencyPair.of("USD_JPY"),
        start_at=datetime(2026, 1, 1, tzinfo=UTC),
        end_at=datetime(2026, 1, 2, tzinfo=UTC),
    )


class TestExecution:
    def test_executable_task_has_lifecycle_behavior(self) -> None:
        definition = BacktestTaskDefinition(
            name="Backtest USD_JPY",
            instrument=CurrencyPair.of("USD_JPY"),
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        task = ExecutableTask.from_definition(definition)

        running = task.start(at=datetime(2026, 1, 3, tzinfo=UTC))
        paused = running.pause(at=datetime(2026, 1, 4, tzinfo=UTC))
        resumed = paused.start(at=datetime(2026, 1, 5, tzinfo=UTC))
        stopped = resumed.stop(at=datetime(2026, 1, 6, tzinfo=UTC))
        restarted = stopped.restart(at=datetime(2026, 1, 7, tzinfo=UTC))
        completed = running.complete(at=datetime(2026, 1, 8, tzinfo=UTC))

        assert task.status == TaskStatus.CREATED
        assert running.status == TaskStatus.RUNNING
        assert paused.status == TaskStatus.PAUSED
        assert resumed.run_count == 1
        assert stopped.status == TaskStatus.STOPPED
        assert restarted.run_count == 2
        assert completed.status == TaskStatus.COMPLETED

    def test_executable_task_rejects_invalid_lifecycle_transition(self) -> None:
        task = ExecutableTask.from_definition(
            BacktestTaskDefinition(
                name="Backtest USD_JPY",
                instrument=CurrencyPair.of("USD_JPY"),
                start_at=datetime(2026, 1, 1, tzinfo=UTC),
                end_at=datetime(2026, 1, 2, tzinfo=UTC),
            )
        )

        with pytest.raises(TaskStateError):
            task.pause()

    def test_executable_task_accepts_clock_for_lifecycle_timestamps(self) -> None:
        clock = ManualClock(datetime(2020, 1, 1, tzinfo=UTC))

        task = ExecutableTask.from_definition(_definition(), clock=clock)
        running = task.start(clock=clock)
        clock.set(datetime(2020, 1, 2, tzinfo=UTC))
        failed = running.fail("boom", clock=clock)

        assert task.created_at == datetime(2020, 1, 1, tzinfo=UTC)
        assert running.started_at == datetime(2020, 1, 1, tzinfo=UTC)
        assert failed.stopped_at == datetime(2020, 1, 2, tzinfo=UTC)
        assert failed.failure is not None
        assert failed.failure.occurred_at == datetime(2020, 1, 2, tzinfo=UTC)

    def test_executable_task_emits_structured_lifecycle_logs(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        definition = BacktestTaskDefinition(
            name="Backtest USD_JPY",
            instrument=CurrencyPair.of("USD_JPY"),
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        task = ExecutableTask.from_definition(definition)

        with caplog.at_level(logging.INFO, logger=CORE_LOGGER_NAME):
            started = task.start(at=datetime(2026, 1, 3, tzinfo=UTC))

        record = next(
            item for item in caplog.records if getattr(item, "task_action", "") == "start"
        )
        assert started.status == TaskStatus.RUNNING
        assert record.name == "core.tasks.execution"
        assert record.__dict__["task_id"] == str(task.id)
        assert record.__dict__["task_definition_id"] == str(definition.id)
        assert record.__dict__["task_status"] == TaskStatus.RUNNING.value

    def test_executable_task_fail_with_message_builds_structured_failure(self) -> None:
        running = ExecutableTask.from_definition(_definition()).start()

        failed = running.fail("data source unavailable")

        assert failed.status == TaskStatus.FAILED
        assert isinstance(failed.failure, TaskFailure)
        assert failed.failure.message == "data source unavailable"
        assert failed.failure.code == ErrorCode.TASK_FAILED
        assert failed.failure.category == ErrorCategory.TASK

    def test_executable_task_fail_with_exception_captures_traceback(self) -> None:
        running = ExecutableTask.from_definition(_definition()).start()
        try:
            raise ValueError("bad tick")
        except ValueError as exc:
            failed = running.fail(exc)

        assert failed.failure is not None
        assert failed.failure.message == "bad tick"
        assert failed.failure.cause_type == "ValueError"
        assert "ValueError" in failed.failure.traceback
        assert "bad tick" in failed.failure.traceback

    def test_executable_task_fail_accepts_prebuilt_failure(self) -> None:
        running = ExecutableTask.from_definition(_definition()).start()
        failure = TaskFailure.of(
            "broker rejected order",
            code=ErrorCode.ORDER_REJECTED,
            category=ErrorCategory.BROKER,
            where="BacktestRunner.run",
        )

        failed = running.fail(failure)

        assert failed.failure == failure

    def test_executable_task_restart_clears_failure(self) -> None:
        failed = ExecutableTask.from_definition(_definition()).start().fail("boom")

        restarted = failed.restart()

        assert restarted.failure is None

    def test_executable_task_recovery_preserves_run_and_checkpoint(self) -> None:
        checkpoint = datetime(2026, 1, 1, 12, tzinfo=UTC)
        interrupted = (
            ExecutableTask.from_definition(_definition())
            .start(at=datetime(2026, 1, 1, tzinfo=UTC))
            .with_last_processed_at(checkpoint)
            .fail("process stopped")
        )

        recovered = interrupted.recover(at=datetime(2026, 1, 1, 13, tzinfo=UTC))

        assert recovered.status == TaskStatus.RUNNING
        assert recovered.run_count == interrupted.run_count
        assert recovered.last_processed_at == checkpoint
        assert recovered.failure is None
