"""Event type, severity, source, and message-key models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EventType(StrEnum):
    """Known event categories emitted by AutoForex components."""

    TASK_STARTED = "task_started"
    TASK_PAUSED = "task_paused"
    TASK_STOPPED = "task_stopped"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TICK_RECEIVED = "tick_received"
    CANDLE_RECEIVED = "candle_received"
    STRATEGY_STARTED = "strategy_started"
    STRATEGY_STOPPED = "strategy_stopped"
    STRATEGY_SIGNAL = "strategy_signal"
    ORDER_REQUESTED = "order_requested"
    ORDER_FILLED = "order_filled"
    WARNING_OCCURRED = "warning_occurred"
    ERROR_OCCURRED = "error_occurred"
    RETRYABLE_ERROR_OCCURRED = "retryable_error_occurred"
    FATAL_ERROR_OCCURRED = "fatal_error_occurred"

    @property
    def metadata(self) -> EventTypeMetadata:
        """Return default handling metadata for this event type."""
        return EVENT_TYPE_METADATA.get(self, EventTypeMetadata(EventSeverity.INFO))

    @property
    def message_key(self) -> EventMessageKey:
        """Return the default i18n message key for this event type."""
        return MESSAGE_KEY_BY_EVENT_TYPE.get(self, EventMessageKey.NONE)


class EventSeverity(StrEnum):
    """Operational severity for emitted events."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class EventSource(StrEnum):
    """Core-owned and generic components that can emit events."""

    CORE = "core"
    SERVER = "server"
    STRATEGY = "strategy"
    BROKER = "broker"
    DATA_SOURCE = "data_source"
    SYSTEM = "system"


class EventMessageKey(StrEnum):
    """Stable i18n message keys for events."""

    NONE = "event.none"
    TASK_STARTED = "event.task.started"
    TASK_PAUSED = "event.task.paused"
    TASK_STOPPED = "event.task.stopped"
    TASK_COMPLETED = "event.task.completed"
    TASK_FAILED = "event.task.failed"
    TICK_RECEIVED = "event.market.tick_received"
    CANDLE_RECEIVED = "event.market.candle_received"
    STRATEGY_STARTED = "event.strategy.started"
    STRATEGY_STOPPED = "event.strategy.stopped"
    STRATEGY_SIGNAL = "event.strategy.signal"
    ORDER_REQUESTED = "event.order.requested"
    ORDER_FILLED = "event.order.filled"
    WARNING_OCCURRED = "event.warning.occurred"
    ERROR_OCCURRED = "event.error.occurred"
    RETRYABLE_ERROR_OCCURRED = "event.error.retryable_occurred"
    FATAL_ERROR_OCCURRED = "event.error.fatal_occurred"
    SPREAD_WARNING = "event.warning.spread"
    BROKER_TIMEOUT = "event.error.broker_timeout"
    STRATEGY_STATE_CORRUPTED = "event.error.strategy_state_corrupted"


@dataclass(frozen=True, slots=True)
class EventTypeMetadata:
    """Default handling metadata attached to an EventType."""

    severity: EventSeverity
    retryable: bool = False
    fatal: bool = False


EVENT_TYPE_METADATA: dict[EventType, EventTypeMetadata] = {
    EventType.TASK_FAILED: EventTypeMetadata(EventSeverity.CRITICAL, fatal=True),
    EventType.WARNING_OCCURRED: EventTypeMetadata(EventSeverity.WARNING),
    EventType.ERROR_OCCURRED: EventTypeMetadata(EventSeverity.ERROR),
    EventType.RETRYABLE_ERROR_OCCURRED: EventTypeMetadata(EventSeverity.ERROR, retryable=True),
    EventType.FATAL_ERROR_OCCURRED: EventTypeMetadata(EventSeverity.CRITICAL, fatal=True),
}

MESSAGE_KEY_BY_EVENT_TYPE: dict[EventType, EventMessageKey] = {
    EventType.TASK_STARTED: EventMessageKey.TASK_STARTED,
    EventType.TASK_PAUSED: EventMessageKey.TASK_PAUSED,
    EventType.TASK_STOPPED: EventMessageKey.TASK_STOPPED,
    EventType.TASK_COMPLETED: EventMessageKey.TASK_COMPLETED,
    EventType.TASK_FAILED: EventMessageKey.TASK_FAILED,
    EventType.TICK_RECEIVED: EventMessageKey.TICK_RECEIVED,
    EventType.CANDLE_RECEIVED: EventMessageKey.CANDLE_RECEIVED,
    EventType.STRATEGY_STARTED: EventMessageKey.STRATEGY_STARTED,
    EventType.STRATEGY_STOPPED: EventMessageKey.STRATEGY_STOPPED,
    EventType.STRATEGY_SIGNAL: EventMessageKey.STRATEGY_SIGNAL,
    EventType.ORDER_REQUESTED: EventMessageKey.ORDER_REQUESTED,
    EventType.ORDER_FILLED: EventMessageKey.ORDER_FILLED,
    EventType.WARNING_OCCURRED: EventMessageKey.WARNING_OCCURRED,
    EventType.ERROR_OCCURRED: EventMessageKey.ERROR_OCCURRED,
    EventType.RETRYABLE_ERROR_OCCURRED: EventMessageKey.RETRYABLE_ERROR_OCCURRED,
    EventType.FATAL_ERROR_OCCURRED: EventMessageKey.FATAL_ERROR_OCCURRED,
}
