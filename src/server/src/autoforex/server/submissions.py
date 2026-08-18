"""Idempotent task submission values."""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Self
from uuid import UUID

from autoforex.core import DomainModel
from pydantic import model_validator

from autoforex.server.components import TaskBinding, TaskBindingCodec


class TaskSubmissionId(DomainModel):
    """Client-generated identifier for an idempotent start request."""

    value: UUID

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, value: Any) -> Any:
        if isinstance(value, cls):
            return value
        if isinstance(value, UUID):
            return {"value": value}
        if isinstance(value, str):
            return {"value": UUID(value)}
        return value

    @classmethod
    def of(cls, value: TaskSubmissionId | UUID | str) -> Self:
        """Create a submission identifier."""
        return cls.model_validate(value)


class TaskSubmission(DomainModel):
    """Submission identity and canonical request fingerprint."""

    id: TaskSubmissionId
    fingerprint: str

    @classmethod
    def create(
        cls,
        submission_id: TaskSubmissionId,
        *,
        definition: DomainModel,
        binding: TaskBinding,
    ) -> TaskSubmission:
        """Hash a normalized definition and runtime binding."""
        digest = sha256()
        digest.update(
            definition.model_dump_json(
                round_trip=True,
                exclude={"id", "created_at"},
            ).encode()
        )
        digest.update(b"\0")
        digest.update(TaskBindingCodec.to_json(binding).encode())
        return cls(id=submission_id, fingerprint=digest.hexdigest())


class TaskSubmissionConflictError(RuntimeError):
    """Raised when one request id is reused with a different payload."""


class TaskSubmissionInProgressError(RuntimeError):
    """Raised when an idempotent submission exists but is not yet readable."""
