from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from autoforex.core import ExecutableTask, TaskStatus

from autoforex.server.discovery import ServiceInstance
from autoforex.server.execution import (
    ExecutionBatch,
    ExecutionBatchConflictError,
    ExecutionBatchState,
)
from autoforex.server.recovery import (
    TaskBindingConflictError,
    TaskExecutionDisposition,
    TaskExecutionIntent,
    TaskIntentConflictError,
)


class TestDurablePersistenceContract:
    """Apply the same observable behavior to SQLite, PostgreSQL, and DynamoDB."""

    def test_round_trips_task_binding_and_desired_execution_state(
        self,
        durable_persistence: Any,
        executable_task: ExecutableTask,
        backtest_binding: Any,
    ) -> None:
        persistence = durable_persistence.persistence
        tasks = persistence.task_registry()
        recovery = persistence.recovery_store()
        intent = TaskExecutionIntent(
            task_id=executable_task.id,
            definition_id=executable_task.definition_id,
            disposition=TaskExecutionDisposition.RUNNING,
            owner_id=f"{durable_persistence.name}-owner",
        )

        tasks.save(executable_task)
        recovery.save_binding(executable_task.definition_id, backtest_binding)
        saved_intent = recovery.save_intent(intent)

        assert tasks.get(executable_task.id) == executable_task
        assert tasks.list(status=TaskStatus.RUNNING) == (executable_task,)
        assert recovery.get_binding(executable_task.definition_id) == backtest_binding
        assert recovery.get_intent(executable_task.id) == saved_intent
        assert recovery.list_intents(disposition=TaskExecutionDisposition.RUNNING) == (
            saved_intent,
        )
        assert persistence.is_healthy()
        assert recovery.is_healthy()

    def test_enforces_immutable_bindings_and_optimistic_intent_updates(
        self,
        durable_persistence: Any,
        executable_task: ExecutableTask,
        backtest_binding: Any,
    ) -> None:
        recovery = durable_persistence.persistence.recovery_store()
        conflicting_binding = backtest_binding.evolve(
            data_source=backtest_binding.data_source.evolve(name="different-source")
        )
        original = recovery.save_intent(
            TaskExecutionIntent(
                task_id=executable_task.id,
                definition_id=executable_task.definition_id,
                disposition=TaskExecutionDisposition.RUNNING,
                owner_id=f"{durable_persistence.name}-owner",
            )
        )
        recovery.save_binding(executable_task.definition_id, backtest_binding)

        recovery.save_binding(executable_task.definition_id, backtest_binding)
        with pytest.raises(TaskBindingConflictError):
            recovery.save_binding(executable_task.definition_id, conflicting_binding)
        recovery.save_intent(original.transition(TaskExecutionDisposition.PAUSED))
        with pytest.raises(TaskIntentConflictError):
            recovery.save_intent(original.transition(TaskExecutionDisposition.STOPPED))

        assert recovery.get_binding(executable_task.definition_id) == backtest_binding

    def test_journal_indexes_requests_and_removes_checkpointed_batches_from_pending(
        self,
        durable_persistence: Any,
        execution_batch: ExecutionBatch,
    ) -> None:
        journal = durable_persistence.persistence.execution_store()

        prepared = journal.save_batch(execution_batch)
        completed = journal.save_batch(prepared.evolve(state=ExecutionBatchState.COMPLETED))

        assert journal.get_batch(prepared.batch_id) == completed
        assert journal.find_batch(prepared.requests[0].id) == completed
        assert journal.list_pending_batches(prepared.task_id) == (completed,)
        assert journal.is_healthy()

        checkpointed = journal.save_batch(completed.evolve(state=ExecutionBatchState.CHECKPOINTED))

        assert journal.get_batch(prepared.batch_id) == checkpointed
        assert journal.list_pending_batches(prepared.task_id) == ()

    def test_journal_rejects_stale_batch_updates(
        self,
        durable_persistence: Any,
        execution_batch: ExecutionBatch,
    ) -> None:
        journal = durable_persistence.persistence.execution_store()
        journal.save_batch(execution_batch)

        with pytest.raises(ExecutionBatchConflictError):
            journal.save_batch(execution_batch)

    def test_round_trips_service_discovery_registrations(
        self,
        durable_persistence: Any,
    ) -> None:
        registry = durable_persistence.persistence.service_registry()
        current = datetime.now(UTC)
        instance = ServiceInstance(
            instance_id=f"{durable_persistence.name}-server",
            host="10.0.0.5",
            port=50051,
            transport_security="plaintext",
            version="0.1.1",
            started_at=current,
            heartbeat_at=current,
            expires_at=current + timedelta(seconds=30),
        )

        registry.register(instance)

        assert registry.list_instances() == (instance,)
        assert registry.is_healthy()
        registry.deregister(instance.instance_id)
        assert registry.list_instances() == ()
