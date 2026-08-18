from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from autoforex.core import BacktestTaskDefinition

from autoforex.server.components import BacktestTaskBinding
from autoforex.server.submissions import TaskSubmission, TaskSubmissionId


class TestTaskSubmissionId:
    def test_normalizes_uuid_and_text_to_the_same_value_object(self) -> None:
        value = uuid4()

        assert TaskSubmissionId.of(value) == TaskSubmissionId.of(str(value))
        assert TaskSubmissionId.of(value).value == value

    def test_rejects_malformed_client_identifiers(self) -> None:
        with pytest.raises(ValueError):
            TaskSubmissionId.of("not-a-uuid")


class TestTaskSubmission:
    def test_fingerprint_ignores_generated_definition_identity(
        self,
        backtest_definition: BacktestTaskDefinition,
        backtest_binding: BacktestTaskBinding,
    ) -> None:
        submission_id = TaskSubmissionId.of(UUID("6a08ac28-7ac1-4161-a887-f0363f0e363c"))
        equivalent_definition = backtest_definition.evolve(id=uuid4())

        first = TaskSubmission.create(
            submission_id,
            definition=backtest_definition,
            binding=backtest_binding,
        )
        equivalent = TaskSubmission.create(
            submission_id,
            definition=equivalent_definition,
            binding=backtest_binding,
        )

        assert first.fingerprint == equivalent.fingerprint

    def test_fingerprint_changes_when_the_requested_runtime_binding_changes(
        self,
        backtest_definition: BacktestTaskDefinition,
        backtest_binding: BacktestTaskBinding,
    ) -> None:
        submission_id = TaskSubmissionId.of(uuid4())
        changed_binding = backtest_binding.evolve(
            data_source=backtest_binding.data_source.evolve(name={"value": "other"})
        )

        first = TaskSubmission.create(
            submission_id,
            definition=backtest_definition,
            binding=backtest_binding,
        )
        changed = TaskSubmission.create(
            submission_id,
            definition=backtest_definition,
            binding=changed_binding,
        )

        assert first.fingerprint != changed.fingerprint
