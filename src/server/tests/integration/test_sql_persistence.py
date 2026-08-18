from __future__ import annotations

from datetime import UTC, datetime

import pytest
from autoforex.core import (
    BacktestTaskDefinition,
    CurrencyPair,
    ExecutableTask,
    StrategyParameters,
    TaskStatus,
)

from autoforex.server.components import (
    BacktestTaskBinding,
    ComponentName,
    DataSourceReference,
    StrategyReference,
)
from autoforex.server.persistence import SqlPersistence
from autoforex.server.recovery import (
    TaskBindingConflictError,
    TaskExecutionDisposition,
    TaskExecutionIntent,
    TaskIntentConflictError,
)


class TestSqlPersistence:
    def test_schema_migration_is_versioned_and_idempotent(
        self,
        sqlite_persistence: SqlPersistence,
    ) -> None:
        sqlite_persistence.create_schema()

        with sqlite_persistence.engine.connect() as connection:
            version = connection.exec_driver_sql(
                "SELECT MAX(version) FROM schema_migrations"
            ).scalar_one()
            tables = {
                row[0]
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        assert version == 2
        assert {
            "tasks",
            "task_bindings",
            "task_execution_intents",
            "execution_batches",
            "execution_requests",
            "schema_migrations",
            "server_instances",
        } <= tables

    def test_round_trips_task_binding_and_intent(
        self,
        sqlite_persistence: SqlPersistence,
    ) -> None:
        registry = sqlite_persistence.task_registry()
        recovery = sqlite_persistence.recovery_store()
        definition = BacktestTaskDefinition(
            name="Replay",
            instrument=CurrencyPair.of("USD_JPY"),
            parameters=StrategyParameters.of(window="20"),
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        task = ExecutableTask.from_definition(definition).start(at=definition.start_at)
        binding = BacktestTaskBinding(
            strategy=StrategyReference(
                name=ComponentName.of("hold"),
                parameters=definition.parameters,
            ),
            data_source=DataSourceReference(name=ComponentName.of("memory")),
        )

        registry.save(task)
        recovery.save_binding(definition.id, binding)
        saved_intent = recovery.save_intent(
            TaskExecutionIntent(
                task_id=task.id,
                definition_id=definition.id,
                disposition=TaskExecutionDisposition.RUNNING,
                owner_id="server-1",
            )
        )

        assert registry.get(task.id) == task
        assert registry.list(status=TaskStatus.RUNNING) == (task,)
        assert recovery.get_binding(definition.id) == binding
        assert saved_intent.revision == 1
        assert recovery.get_intent(task.id) == saved_intent

    def test_rejects_stale_intent_update(
        self,
        sqlite_persistence: SqlPersistence,
    ) -> None:
        recovery = sqlite_persistence.recovery_store()
        definition = BacktestTaskDefinition(
            name="Replay",
            instrument=CurrencyPair.of("USD_JPY"),
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        task = ExecutableTask.from_definition(definition)
        original = TaskExecutionIntent(
            task_id=task.id,
            definition_id=definition.id,
            disposition=TaskExecutionDisposition.RUNNING,
            owner_id="server-1",
        )
        saved = recovery.save_intent(original)
        recovery.save_intent(saved.transition(TaskExecutionDisposition.PAUSED))

        with pytest.raises(TaskIntentConflictError):
            recovery.save_intent(saved.transition(TaskExecutionDisposition.STOPPED))

    def test_task_binding_is_immutable_but_accepts_an_identical_retry(
        self,
        sqlite_persistence: SqlPersistence,
    ) -> None:
        recovery = sqlite_persistence.recovery_store()
        definition_id = BacktestTaskDefinition(
            name="Immutable binding",
            instrument=CurrencyPair.of("USD_JPY"),
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        ).id
        binding = BacktestTaskBinding(
            strategy=StrategyReference(name=ComponentName.of("hold")),
            data_source=DataSourceReference(name=ComponentName.of("memory")),
        )
        conflicting = binding.evolve(
            data_source=DataSourceReference(name=ComponentName.of("other"))
        )

        recovery.save_binding(definition_id, binding)
        recovery.save_binding(definition_id, binding)

        with pytest.raises(TaskBindingConflictError):
            recovery.save_binding(definition_id, conflicting)
        assert recovery.get_binding(definition_id) == binding
