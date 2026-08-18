"""Base domain event model."""

from __future__ import annotations

from datetime import timedelta
from logging import Logger
from typing import Any, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from autoforex.core.clock import now
from autoforex.core.events.errors import (
    ErrorCategory,
    ErrorCode,
    ErrorDetails,
    EventError,
)
from autoforex.core.events.types import (
    EventMessageKey,
    EventSeverity,
    EventSource,
    EventType,
)
from autoforex.core.logging import get_logger
from autoforex.core.models.base import DomainModel
from autoforex.core.models.identifiers import new_uuid
from autoforex.core.models.metadata import Metadata

_LOGGER: Logger = get_logger(__name__)


class Event(DomainModel):
    """A timestamped domain event independent from persistence or transport."""

    id: UUID = Field(default_factory=new_uuid)
    type: EventType
    severity: EventSeverity = EventSeverity.INFO
    timestamp: AwareDatetime = Field(default_factory=now)
    source: EventSource = EventSource.CORE
    task_id: UUID | None = None
    display_id: str = ""
    message_key: EventMessageKey = EventMessageKey.NONE
    error: EventError | None = None
    metadata: Metadata = Field(default_factory=Metadata)

    @model_validator(mode="before")
    @classmethod
    def _apply_event_type_defaults(cls, data: Any) -> Any:
        if not isinstance(data, dict) or data.get("type") is None:
            return data

        event_type = EventType(data["type"])
        event_type_metadata = event_type.metadata
        normalized = dict(data)
        normalized.setdefault("severity", event_type_metadata.severity)
        normalized.setdefault("message_key", event_type.message_key)

        if normalized.get("error") is None and event_type_metadata.severity in {
            EventSeverity.ERROR,
            EventSeverity.CRITICAL,
        }:
            normalized["error"] = {
                "code": ErrorCode.for_event_type(event_type),
                "retryable": event_type_metadata.retryable,
                "fatal": event_type_metadata.fatal,
            }
            return normalized

        if isinstance(normalized.get("error"), dict):
            error = dict(normalized["error"])
            error.setdefault("code", ErrorCode.for_event_type(event_type))
            error.setdefault("retryable", event_type_metadata.retryable)
            error.setdefault("fatal", event_type_metadata.fatal)
            normalized["error"] = error
        return normalized

    @model_validator(mode="after")
    def _log_event(self) -> Self:
        _LOGGER.debug(
            "Validated event %s",
            self.id,
            extra=self._log_extra(),
        )
        return self

    @classmethod
    def warning(
        cls,
        message_key: EventMessageKey = EventMessageKey.WARNING_OCCURRED,
        *,
        code: ErrorCode = ErrorCode.WARNING,
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        details: ErrorDetails | None = None,
        **kwargs: Any,
    ) -> Event:
        """Create a warning event."""
        _LOGGER.debug(
            "Creating warning event",
            extra={
                "event_type": EventType.WARNING_OCCURRED.value,
                "message_key": message_key.value,
                "error_code": code.value,
                "error_category": category.value,
            },
        )
        return cls(
            type=EventType.WARNING_OCCURRED,
            message_key=message_key,
            error=EventError(
                code=code,
                category=category,
                details=details or ErrorDetails(),
            ),
            **kwargs,
        )

    @classmethod
    def retryable_error(
        cls,
        message_key: EventMessageKey = EventMessageKey.RETRYABLE_ERROR_OCCURRED,
        *,
        code: ErrorCode = ErrorCode.RETRYABLE_ERROR,
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        retry_after: timedelta | None = None,
        details: ErrorDetails | None = None,
        **kwargs: Any,
    ) -> Event:
        """Create an error event that callers may retry."""
        retry_delay = cls._retry_after(retry_after)
        _LOGGER.debug(
            "Creating retryable error event",
            extra={
                "event_type": EventType.RETRYABLE_ERROR_OCCURRED.value,
                "message_key": message_key.value,
                "error_code": code.value,
                "error_category": category.value,
                "retry_after": str(retry_delay or ""),
            },
        )
        return cls(
            type=EventType.RETRYABLE_ERROR_OCCURRED,
            message_key=message_key,
            error=EventError(
                code=code,
                category=category,
                retryable=True,
                fatal=False,
                retry_after=retry_delay,
                details=details or ErrorDetails(),
            ),
            **kwargs,
        )

    @classmethod
    def fatal_error(
        cls,
        message_key: EventMessageKey = EventMessageKey.FATAL_ERROR_OCCURRED,
        *,
        code: ErrorCode = ErrorCode.FATAL_ERROR,
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        details: ErrorDetails | None = None,
        **kwargs: Any,
    ) -> Event:
        """Create an error event that should fail the task or process."""
        _LOGGER.debug(
            "Creating fatal error event",
            extra={
                "event_type": EventType.FATAL_ERROR_OCCURRED.value,
                "message_key": message_key.value,
                "error_code": code.value,
                "error_category": category.value,
            },
        )
        return cls(
            type=EventType.FATAL_ERROR_OCCURRED,
            message_key=message_key,
            error=EventError(
                code=code,
                category=category,
                retryable=False,
                fatal=True,
                details=details or ErrorDetails(),
            ),
            **kwargs,
        )

    @property
    def is_warning(self) -> bool:
        """Return whether the event is a warning."""
        return self.severity == EventSeverity.WARNING

    @property
    def is_error(self) -> bool:
        """Return whether the event represents an error."""
        return self.severity in {EventSeverity.ERROR, EventSeverity.CRITICAL}

    @property
    def is_retryable(self) -> bool:
        """Return whether the event error can be retried."""
        return bool(self.error and self.error.retryable)

    @property
    def is_fatal(self) -> bool:
        """Return whether the event should fail the task or process."""
        return bool(self.error and self.error.fatal)

    def _log_extra(self) -> dict[str, str | bool]:
        return {
            "event_id": str(self.id),
            "event_type": self.type.value,
            "event_severity": self.severity.value,
            "event_source": self._source_value(),
            "task_id": str(self.task_id or ""),
            "display_id": self.display_id,
            "message_key": self.message_key.value,
            "is_warning": self.is_warning,
            "is_error": self.is_error,
            "is_retryable": self.is_retryable,
            "is_fatal": self.is_fatal,
            "error_code": self.error.code.value if self.error is not None else "",
            "error_category": self.error.category.value if self.error is not None else "",
        }

    def _source_value(self) -> str:
        return self.source.value

    @staticmethod
    def _retry_after(value: timedelta | None) -> timedelta | None:
        if value is None:
            return None
        if isinstance(value, timedelta):
            if value.total_seconds() < 0:
                raise ValueError("retry_after must not be negative")
            return value
        raise TypeError("retry_after must be a timedelta")
