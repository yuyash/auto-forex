"""Domain events exported by the Core package."""

from autoforex.core.events.bus import (
    EventBus,
    EventHandlerError,
    EventPublication,
)
from autoforex.core.events.errors import (
    ErrorCategory,
    ErrorCode,
    ErrorDetails,
    EventError,
)
from autoforex.core.events.event import Event
from autoforex.core.events.handlers import RecordingEventHandler
from autoforex.core.events.routing import EventHandler, EventSubscription
from autoforex.core.events.types import (
    EventMessageKey,
    EventSeverity,
    EventSource,
    EventType,
    EventTypeMetadata,
)

__all__ = [
    "ErrorCategory",
    "ErrorCode",
    "ErrorDetails",
    "Event",
    "EventBus",
    "EventError",
    "EventHandler",
    "EventHandlerError",
    "EventMessageKey",
    "EventPublication",
    "EventSeverity",
    "EventSource",
    "EventSubscription",
    "EventType",
    "EventTypeMetadata",
    "RecordingEventHandler",
]
