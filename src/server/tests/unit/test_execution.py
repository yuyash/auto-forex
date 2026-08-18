from __future__ import annotations

from uuid import uuid4

import pytest
from autoforex.core import BrokerMutation, BrokerMutationOperation, StrategyEventRequest

from autoforex.server.execution import (
    ExecutionBatch,
    ExecutionBatchConflictError,
    ExecutionBatchNotFoundError,
    ExecutionBatchState,
    ExecutionCommand,
    ExecutionCommandState,
    InMemoryExecutionJournalStore,
)


class TestExecutionBatch:
    def test_with_command_inserts_then_replaces_by_command_identity(
        self,
        execution_batch: ExecutionBatch,
        execution_request: StrategyEventRequest,
    ) -> None:
        command = self._command(execution_request)

        inserted = execution_batch.with_command(command)
        replaced = inserted.with_command(command.evolve(state=ExecutionCommandState.DISPATCHING))
        replaced_command = replaced.command(command.command_id)

        assert inserted.commands == (command,)
        assert len(replaced.commands) == 1
        assert replaced_command is not None
        assert replaced_command.state == ExecutionCommandState.DISPATCHING
        assert replaced.updated_at >= execution_batch.updated_at

    @staticmethod
    def _command(request: StrategyEventRequest) -> ExecutionCommand:
        return ExecutionCommand(
            command_id=request.id,
            request_id=request.id,
            mutation=BrokerMutation(
                command_id=request.id,
                task_id=request.task_id,
                operation=BrokerMutationOperation.PLACE_ORDER,
            ),
            fencing_token=1,
        )


class TestInMemoryExecutionJournalStore:
    def test_supports_compare_and_swap_request_lookup_and_pending_filter(
        self,
        execution_batch: ExecutionBatch,
    ) -> None:
        store = InMemoryExecutionJournalStore()

        prepared = store.save_batch(execution_batch)
        completed = store.save_batch(prepared.evolve(state=ExecutionBatchState.COMPLETED))

        assert store.get_batch(prepared.batch_id) == completed
        assert store.find_batch(prepared.requests[0].id) == completed
        assert store.list_pending_batches(prepared.task_id) == (completed,)
        assert store.is_healthy()
        with pytest.raises(ExecutionBatchConflictError):
            store.save_batch(prepared)

    def test_request_identity_conflict_does_not_partially_insert_a_batch(
        self,
        execution_batch: ExecutionBatch,
    ) -> None:
        store = InMemoryExecutionJournalStore()
        store.save_batch(execution_batch)
        conflicting = execution_batch.evolve(
            batch_id=uuid4(),
            revision=0,
        )

        with pytest.raises(ExecutionBatchConflictError, match="belongs to a batch"):
            store.save_batch(conflicting)
        with pytest.raises(ExecutionBatchNotFoundError):
            store.get_batch(conflicting.batch_id)

    def test_missing_batch_and_request_raise_domain_specific_errors(self) -> None:
        store = InMemoryExecutionJournalStore()

        with pytest.raises(ExecutionBatchNotFoundError, match="batch not found"):
            store.get_batch(uuid4())
        with pytest.raises(ExecutionBatchNotFoundError, match="request not found"):
            store.find_batch(uuid4())
