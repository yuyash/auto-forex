"""Durable task execution intent and recovery contracts."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol, Self
from uuid import UUID, uuid4

from autoforex.core import DomainModel, TaskStatus, Tick, now
from pydantic import AwareDatetime, Field

from autoforex.server.components import TaskBinding


class TaskExecutionDisposition(StrEnum):
    """User-intended lifecycle state across server process restarts."""

    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"
    RECOVERY_REQUIRED = "recovery_required"


class TaskExecutionIntent(DomainModel):
    """Durable desired state and ownership metadata for one task."""

    task_id: UUID
    definition_id: UUID
    disposition: TaskExecutionDisposition
    generation: int = Field(default=1, ge=1)
    revision: int = Field(default=0, ge=0)
    owner_id: str = Field(min_length=1)
    submission_id: UUID | None = None
    submission_fingerprint: str = ""
    lease_id: UUID = Field(default_factory=uuid4)
    lease_expires_at: AwareDatetime = Field(default_factory=now)
    heartbeat_at: AwareDatetime = Field(default_factory=now)
    last_processed_at: AwareDatetime | None = None

    def heartbeat(self, tick: Tick | None = None) -> Self:
        """Return a refreshed execution heartbeat."""
        return self.evolve(
            heartbeat_at=now(),
            last_processed_at=(self.last_processed_at if tick is None else tick.timestamp),
        )

    def lease_is_valid(self, *, at: datetime | None = None) -> bool:
        """Return whether the current ownership lease is unexpired."""
        return self.lease_expires_at > (at or now())

    def acquire(
        self,
        owner_id: str,
        *,
        duration: timedelta,
    ) -> Self:
        """Return intent with a new ownership lease and fencing generation."""
        acquired_at = now()
        return self.evolve(
            generation=self.generation + 1,
            owner_id=owner_id,
            lease_id=uuid4(),
            lease_expires_at=acquired_at + duration,
            heartbeat_at=acquired_at,
        )

    def renew(
        self,
        *,
        duration: timedelta,
        tick: Tick | None = None,
    ) -> Self:
        """Return intent with its current lease extended."""
        renewed_at = now()
        return self.evolve(
            lease_expires_at=renewed_at + duration,
            heartbeat_at=renewed_at,
            last_processed_at=(self.last_processed_at if tick is None else tick.timestamp),
        )

    def expire_lease(self) -> Self:
        """Return intent whose current lease is no longer valid."""
        expired_at = now()
        return self.evolve(
            lease_expires_at=expired_at,
            heartbeat_at=expired_at,
        )

    def transition(
        self,
        disposition: TaskExecutionDisposition,
        *,
        owner_id: str | None = None,
        increment_generation: bool = False,
        expire_lease: bool = False,
    ) -> Self:
        """Return intent updated for a lifecycle transition."""
        transitioned_at = now()
        return self.evolve(
            disposition=disposition,
            generation=self.generation + int(increment_generation),
            owner_id=owner_id or self.owner_id,
            heartbeat_at=transitioned_at,
            lease_expires_at=(transitioned_at if expire_lease else self.lease_expires_at),
        )


class TaskRecoveryStore(Protocol):
    """Persistence boundary for task bindings and desired execution state."""

    def save_binding(self, definition_id: UUID, binding: TaskBinding) -> TaskBinding:
        """Persist a task's immutable runtime binding."""

    def get_binding(self, definition_id: UUID) -> TaskBinding:
        """Return the runtime binding for a task definition."""

    def delete_binding(self, definition_id: UUID) -> None:
        """Delete a task binding."""

    def save_intent(self, intent: TaskExecutionIntent) -> TaskExecutionIntent:
        """Persist desired execution state."""

    def get_intent(self, task_id: UUID) -> TaskExecutionIntent:
        """Return desired execution state."""

    def list_intents(
        self,
        *,
        disposition: TaskExecutionDisposition | None = None,
    ) -> Sequence[TaskExecutionIntent]:
        """List intents, optionally filtered by disposition."""

    def delete_intent(self, task_id: UUID) -> None:
        """Delete execution intent."""

    def is_healthy(self) -> bool:
        """Return whether the persistence backend is reachable."""


class TaskRecoveryRecordNotFoundError(KeyError):
    """Raised when durable task recovery metadata does not exist."""


class TaskIntentConflictError(RuntimeError):
    """Raised when an intent update is based on a stale revision."""


class TaskBindingConflictError(RuntimeError):
    """Raised when an immutable task binding is overwritten."""


class TaskStatusDispositionMapper:
    """Map observed Core task states to durable terminal dispositions."""

    @classmethod
    def terminal_disposition(
        cls,
        status: TaskStatus,
    ) -> TaskExecutionDisposition | None:
        """Return a terminal disposition, or none for active states."""
        if status == TaskStatus.COMPLETED:
            return TaskExecutionDisposition.COMPLETED
        if status == TaskStatus.FAILED:
            return TaskExecutionDisposition.FAILED
        if status == TaskStatus.STOPPED:
            return TaskExecutionDisposition.STOPPED
        if status == TaskStatus.PAUSED:
            return TaskExecutionDisposition.PAUSED
        return None
