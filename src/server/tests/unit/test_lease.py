from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from autoforex.core import now

from autoforex.server.components import TaskBinding
from autoforex.server.lease import (
    TaskLeaseCoordinator,
    TaskLeaseLostError,
    TaskLeaseRegistry,
    TaskLeaseToken,
)
from autoforex.server.recovery import (
    TaskExecutionDisposition,
    TaskExecutionIntent,
    TaskIntentConflictError,
    TaskRecoveryRecordNotFoundError,
)


class MemoryRecoveryStore:
    def __init__(self) -> None:
        self.intents: dict[UUID, TaskExecutionIntent] = {}

    def save_intent(self, intent: TaskExecutionIntent) -> TaskExecutionIntent:
        current = self.intents.get(intent.task_id)
        current_revision = 0 if current is None else current.revision
        if current_revision != intent.revision:
            raise TaskIntentConflictError("stale revision")
        saved = intent.evolve(revision=intent.revision + 1)
        self.intents[intent.task_id] = saved
        return saved

    def get_intent(self, task_id: UUID) -> TaskExecutionIntent:
        try:
            return self.intents[task_id]
        except KeyError as exc:
            raise TaskRecoveryRecordNotFoundError(str(task_id)) from exc

    def save_binding(self, definition_id: UUID, binding: TaskBinding) -> TaskBinding:
        _ = definition_id
        return binding

    def get_binding(self, definition_id: UUID) -> TaskBinding:
        raise TaskRecoveryRecordNotFoundError(str(definition_id))

    def delete_binding(self, definition_id: UUID) -> None:
        _ = definition_id

    def list_intents(
        self,
        *,
        disposition: TaskExecutionDisposition | None = None,
    ) -> Sequence[TaskExecutionIntent]:
        intents = tuple(self.intents.values())
        if disposition is None:
            return intents
        return tuple(intent for intent in intents if intent.disposition == disposition)

    def delete_intent(self, task_id: UUID) -> None:
        self.intents.pop(task_id, None)

    def is_healthy(self) -> bool:
        return True


class TestTaskLeaseRegistry:
    def test_tracks_and_removes_local_ownership_tokens(self) -> None:
        registry = TaskLeaseRegistry()
        token = TaskLeaseToken(self._intent())

        registry.put(token)

        assert registry.contains(token.task_id)
        assert registry.get(token.task_id) is token
        assert registry.values() == (token,)
        assert registry.remove(token.task_id) is token
        assert not registry.contains(token.task_id)

    def test_missing_local_token_is_reported_as_lease_loss(self) -> None:
        with pytest.raises(TaskLeaseLostError, match="no local lease"):
            TaskLeaseRegistry().get(uuid4())

    def test_stale_renewal_cannot_remove_a_replacement_token(self) -> None:
        registry = TaskLeaseRegistry()
        stale = TaskLeaseToken(self._intent())
        replacement_intent = self._intent().evolve(task_id=stale.task_id)
        replacement = TaskLeaseToken(replacement_intent)
        registry.put(stale)
        registry.put(replacement)

        assert not registry.remove_if_current(stale)
        assert registry.get(stale.task_id) is replacement
        assert registry.remove_if_current(replacement)
        assert not registry.contains(stale.task_id)

    @staticmethod
    def _intent() -> TaskExecutionIntent:
        return TaskExecutionIntent(
            task_id=uuid4(),
            definition_id=uuid4(),
            disposition=TaskExecutionDisposition.RUNNING,
            owner_id="server-a",
            lease_expires_at=now() + timedelta(seconds=30),
        )


class TestTaskLeaseCoordinator:
    def test_acquires_expired_lease_and_fences_the_previous_generation(self) -> None:
        store = MemoryRecoveryStore()
        original = store.save_intent(
            TaskExecutionIntent(
                task_id=uuid4(),
                definition_id=uuid4(),
                disposition=TaskExecutionDisposition.RUNNING,
                owner_id="server-a",
                lease_expires_at=now(),
            )
        )
        coordinator = TaskLeaseCoordinator(
            store,
            owner_id="server-b",
            duration_seconds=30,
        )

        token = coordinator.acquire(original.task_id)

        assert token is not None
        assert token.owner_id == "server-b"
        assert token.fencing_token == original.generation + 1
        assert coordinator.assert_current(token).lease_is_valid()

    def test_does_not_take_a_live_lease_owned_by_another_server(self) -> None:
        store = MemoryRecoveryStore()
        intent = store.save_intent(
            TaskExecutionIntent(
                task_id=uuid4(),
                definition_id=uuid4(),
                disposition=TaskExecutionDisposition.RUNNING,
                owner_id="server-a",
                lease_expires_at=now() + timedelta(seconds=30),
            )
        )
        coordinator = TaskLeaseCoordinator(
            store,
            owner_id="server-b",
            duration_seconds=30,
        )

        assert coordinator.acquire(intent.task_id) is None

    def test_release_expires_the_owned_lease_and_clears_local_state(self) -> None:
        store = MemoryRecoveryStore()
        saved = store.save_intent(
            TaskExecutionIntent(
                task_id=uuid4(),
                definition_id=uuid4(),
                disposition=TaskExecutionDisposition.RUNNING,
                owner_id="server-a",
                lease_expires_at=now() + timedelta(seconds=30),
            )
        )
        coordinator = TaskLeaseCoordinator(
            store,
            owner_id="server-a",
            duration_seconds=30,
        )
        token = coordinator.register_new(saved)

        coordinator.release(saved.task_id)

        assert not coordinator.registry.contains(saved.task_id)
        assert not store.get_intent(saved.task_id).lease_is_valid()
        with pytest.raises(TaskLeaseLostError):
            coordinator.assert_current(token)

    def test_rejects_non_positive_lease_duration(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            TaskLeaseCoordinator(
                MemoryRecoveryStore(),
                owner_id="server-a",
                duration_seconds=0,
            )
