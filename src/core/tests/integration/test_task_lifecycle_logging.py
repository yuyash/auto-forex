import logging
from datetime import UTC, datetime

import pytest

from autoforex.core import (
    CORE_LOGGER_NAME,
    BacktestTaskDefinition,
    CurrencyPair,
    ExecutableTask,
    TaskStatus,
)


class TestTaskLifecycleLogging:
    def test_task_lifecycle_emits_structured_logs(self, caplog: pytest.LogCaptureFixture) -> None:
        definition = BacktestTaskDefinition(
            name="Backtest USD_JPY",
            instrument=CurrencyPair.of("USD_JPY"),
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        task = ExecutableTask.from_definition(definition)

        with caplog.at_level(logging.INFO, logger=CORE_LOGGER_NAME):
            started = task.start(at=datetime(2026, 1, 3, tzinfo=UTC))
            completed = started.complete(at=datetime(2026, 1, 4, tzinfo=UTC))

        actions = [getattr(record, "task_action", "") for record in caplog.records]
        assert started.status == TaskStatus.RUNNING
        assert completed.status == TaskStatus.COMPLETED
        assert "start" in actions
        assert "complete" in actions
