"""Structured event error models."""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum

from pydantic import Field

from autoforex.core.events.types import EventType
from autoforex.core.models.base import DomainModel
from autoforex.core.models.mapping import MappingValueObject


class ErrorCategory(StrEnum):
    """High-level error category used by retry, alerting, and diagnostics."""

    UNKNOWN = "unknown"
    VALIDATION = "validation"
    CONFIGURATION = "configuration"
    TASK = "task"
    MARKET_DATA = "market_data"
    DATA_SOURCE = "data_source"
    STRATEGY = "strategy"
    RISK = "risk"
    BROKER = "broker"
    ORDER = "order"
    POSITION = "position"
    ACCOUNT = "account"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    RATE_LIMIT = "rate_limit"
    NETWORK = "network"
    TIMEOUT = "timeout"
    INFRASTRUCTURE = "infrastructure"
    PERSISTENCE = "persistence"
    SERIALIZATION = "serialization"
    PROTOCOL = "protocol"
    DEPENDENCY = "dependency"

    @property
    def is_domain(self) -> bool:
        """Return whether this category belongs to AutoForex domain logic."""
        return self in {
            ErrorCategory.VALIDATION,
            ErrorCategory.CONFIGURATION,
            ErrorCategory.TASK,
            ErrorCategory.MARKET_DATA,
            ErrorCategory.STRATEGY,
            ErrorCategory.RISK,
            ErrorCategory.ORDER,
            ErrorCategory.POSITION,
            ErrorCategory.ACCOUNT,
        }

    @property
    def is_external(self) -> bool:
        """Return whether this category involves external systems."""
        return self in {
            ErrorCategory.DATA_SOURCE,
            ErrorCategory.BROKER,
            ErrorCategory.AUTHENTICATION,
            ErrorCategory.AUTHORIZATION,
            ErrorCategory.RATE_LIMIT,
            ErrorCategory.NETWORK,
            ErrorCategory.TIMEOUT,
            ErrorCategory.PROTOCOL,
            ErrorCategory.DEPENDENCY,
        }

    @property
    def is_transient(self) -> bool:
        """Return whether this category is commonly recoverable by retry."""
        return self in {
            ErrorCategory.DATA_SOURCE,
            ErrorCategory.BROKER,
            ErrorCategory.RATE_LIMIT,
            ErrorCategory.NETWORK,
            ErrorCategory.TIMEOUT,
            ErrorCategory.INFRASTRUCTURE,
            ErrorCategory.PERSISTENCE,
            ErrorCategory.DEPENDENCY,
        }


class ErrorCode(StrEnum):
    """Stable machine-readable error codes."""

    UNKNOWN = "unknown"
    WARNING = "warning"
    ERROR = "error"
    RETRYABLE_ERROR = "retryable_error"
    FATAL_ERROR = "fatal_error"
    TASK_FAILED = "task_failed"
    ERROR_OCCURRED = "error_occurred"
    RETRYABLE_ERROR_OCCURRED = "retryable_error_occurred"
    FATAL_ERROR_OCCURRED = "fatal_error_occurred"
    VALIDATION_FAILED = "validation_failed"
    CONFIGURATION_INVALID = "configuration_invalid"
    TASK_STATE_INVALID = "task_state_invalid"
    MARKET_DATA_UNAVAILABLE = "market_data_unavailable"
    MARKET_DATA_INVALID = "market_data_invalid"
    SPREAD_WARNING = "spread_warning"
    DATA_SOURCE_UNAVAILABLE = "data_source_unavailable"
    STRATEGY_FAILED = "strategy_failed"
    STRATEGY_STATE_CORRUPTED = "strategy_state_corrupted"
    RISK_LIMIT_EXCEEDED = "risk_limit_exceeded"
    BROKER_UNAVAILABLE = "broker_unavailable"
    BROKER_TIMEOUT = "broker_timeout"
    ORDER_REJECTED = "order_rejected"
    ORDER_FAILED = "order_failed"
    POSITION_FAILED = "position_failed"
    ACCOUNT_UNAVAILABLE = "account_unavailable"
    AUTHENTICATION_FAILED = "authentication_failed"
    AUTHORIZATION_FAILED = "authorization_failed"
    RATE_LIMITED = "rate_limited"
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"
    PERSISTENCE_FAILED = "persistence_failed"
    SERIALIZATION_FAILED = "serialization_failed"
    PROTOCOL_ERROR = "protocol_error"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"

    @classmethod
    def for_event_type(cls, event_type: EventType) -> ErrorCode:
        """Return the default error code for an event type."""
        return ERROR_CODE_BY_EVENT_TYPE.get(event_type, cls.UNKNOWN)


class ErrorDetails(MappingValueObject):
    """Read-only structured details attached to an error."""


ERROR_CODE_BY_EVENT_TYPE: dict[EventType, ErrorCode] = {
    EventType.TASK_FAILED: ErrorCode.TASK_FAILED,
    EventType.ERROR_OCCURRED: ErrorCode.ERROR_OCCURRED,
    EventType.RETRYABLE_ERROR_OCCURRED: ErrorCode.RETRYABLE_ERROR_OCCURRED,
    EventType.FATAL_ERROR_OCCURRED: ErrorCode.FATAL_ERROR_OCCURRED,
}


class EventError(DomainModel):
    """Structured error details attached to warning and error events."""

    code: ErrorCode = ErrorCode.UNKNOWN
    category: ErrorCategory = ErrorCategory.UNKNOWN
    retryable: bool = False
    fatal: bool = False
    retry_after: timedelta | None = None
    details: ErrorDetails = Field(default_factory=ErrorDetails)
