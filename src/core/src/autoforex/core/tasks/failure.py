"""Structured task failure details."""

from __future__ import annotations

import traceback
from datetime import datetime
from typing import Self

from pydantic import AwareDatetime, Field

from autoforex.core.clock import Clock, now
from autoforex.core.events.errors import ErrorCategory, ErrorCode, ErrorDetails
from autoforex.core.models.base import DomainModel


class TaskFailure(DomainModel):
    """Structured explanation of why a task failed.

    Built on Core's shared error vocabulary (:class:`ErrorCode`,
    :class:`ErrorCategory`, :class:`ErrorDetails`) so a failure can be traced:
    *what* failed (``message``/``code``/``category``), *where* it failed
    (``where``), *why* (``cause`` exception type and ``traceback``), *when*
    (``occurred_at``), and any extra structured context (``details``).
    """

    message: str = Field(min_length=1)
    code: ErrorCode = ErrorCode.TASK_FAILED
    category: ErrorCategory = ErrorCategory.TASK
    where: str = ""
    cause_type: str = ""
    traceback: str = ""
    details: ErrorDetails = Field(default_factory=ErrorDetails)
    occurred_at: AwareDatetime = Field(default_factory=now)

    @classmethod
    def of(
        cls,
        message: str,
        *,
        code: ErrorCode = ErrorCode.TASK_FAILED,
        category: ErrorCategory = ErrorCategory.TASK,
        where: str = "",
        details: ErrorDetails | None = None,
        occurred_at: datetime | None = None,
        clock: Clock | None = None,
    ) -> Self:
        """Create a failure from a plain message and optional context."""
        return cls(
            message=message,
            code=code,
            category=category,
            where=where,
            details=details or ErrorDetails(),
            occurred_at=occurred_at or now(clock),
        )

    @classmethod
    def from_exception(
        cls,
        exc: BaseException,
        *,
        code: ErrorCode = ErrorCode.TASK_FAILED,
        category: ErrorCategory = ErrorCategory.TASK,
        where: str = "",
        details: ErrorDetails | None = None,
        occurred_at: datetime | None = None,
        clock: Clock | None = None,
    ) -> Self:
        """Create a failure that captures an exception's type and traceback."""
        message = str(exc) or exc.__class__.__name__
        return cls(
            message=message,
            code=code,
            category=category,
            where=where,
            cause_type=exc.__class__.__name__,
            traceback="".join(traceback.format_exception(exc)),
            details=details or ErrorDetails(),
            occurred_at=occurred_at or now(clock),
        )

    def __str__(self) -> str:
        location = f" at {self.where}" if self.where else ""
        return f"[{self.code.value}/{self.category.value}]{location}: {self.message}"
