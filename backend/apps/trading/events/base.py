"""Typed event classes for strategy events.

This module provides type-safe event classes for each EventType, making
it clear what fields are required for each event and enabling better
IDE support and compile-time checking.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from apps.trading.enums import EventType
from apps.trading.events.parsing import parse_datetime, parse_decimal, parse_optional_decimal

if TYPE_CHECKING:
    from apps.trading.dataclasses.context import EventContext


# Event class registry: maps EventType value -> event class
_EVENT_REGISTRY: dict[str, type["StrategyEvent"]] = {}


def parse_bool(value: Any, *, default: bool = False) -> bool:
    """Parse a JSON-ish boolean value from persisted event details."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def register_event(event_type: EventType):
    """Register an event class for automatic deserialization.

    Args:
        event_type: The EventType this class handles

    Returns:
        Decorator function
    """

    def decorator(cls: type["StrategyEvent"]) -> type["StrategyEvent"]:
        _EVENT_REGISTRY[event_type.value] = cls
        return cls

    return decorator


@dataclass
class StrategyEvent(ABC):
    """Base class for all strategy events.

    This is the abstract base class that all specific event types inherit from.
    It provides common fields and methods shared by all events.

    Attributes:
        event_type: Type of event (EventType enum value)
        timestamp: Event timestamp (optional)"""

    event_type: EventType
    timestamp: datetime | None = None
    sequence_number: int = 0
    strategy_type: str = ""
    visual_group_id: str = ""
    root_entry_id: int | None = None
    parent_entry_id: int | None = None
    basket: str = ""
    step: int | None = None
    close_reason: str = ""
    validation_status: str = ""
    expected_interval_pips: Decimal | None = None
    actual_interval_pips: Decimal | None = None
    expected_tp_pips: Decimal | None = None
    actual_tp_pips: Decimal | None = None
    expected_exit_price: Decimal | None = None
    actual_exit_price: Decimal | None = None
    validation_tolerance_pips: Decimal | None = None
    margin_ratio: Decimal | None = None
    tick_bid: Decimal | None = None
    tick_ask: Decimal | None = None
    tick_mid: Decimal | None = None

    @property
    def category(self) -> str:
        """Return the generic event category for handler dispatch.

        Categories allow the EventHandler to process events from any strategy
        without needing strategy-specific dispatch logic. Override in subclasses.

        Returns:
            One of: "entry", "exit", "risk", "info"
        """
        return "info"

    @abstractmethod
    def activate(self, context: "EventContext") -> None:
        """Execute event-specific logic.

        This method is called by the EventExecutor to perform the actions
        associated with this event. Each event type implements its own
        activation logic (e.g., opening positions, closing positions, logging).

        Args:
            context: Event context containing task, account, instrument info

        Raises:
            NotImplementedError: If the subclass doesn't implement this method
        """
        raise NotImplementedError(f"{self.__class__.__name__} must implement activate() method")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary format for database storage.

        Returns:
            Dictionary representation of the event
        """
        result = {"event_type": str(self.event_type.value)}
        if self.timestamp:
            result["timestamp"] = self.timestamp.isoformat()
        if self.strategy_type:
            result["strategy_type"] = self.strategy_type
        if self.visual_group_id:
            result["visual_group_id"] = self.visual_group_id
        if self.root_entry_id is not None:
            result["root_entry_id"] = self.root_entry_id
        if self.parent_entry_id is not None:
            result["parent_entry_id"] = self.parent_entry_id
        if self.basket:
            result["basket"] = self.basket
        if self.step is not None:
            result["step"] = self.step
        if self.close_reason:
            result["close_reason"] = self.close_reason
        if self.validation_status:
            result["validation_status"] = self.validation_status
        if self.expected_interval_pips is not None:
            result["expected_interval_pips"] = str(self.expected_interval_pips)
        if self.actual_interval_pips is not None:
            result["actual_interval_pips"] = str(self.actual_interval_pips)
        if self.expected_tp_pips is not None:
            result["expected_tp_pips"] = str(self.expected_tp_pips)
        if self.actual_tp_pips is not None:
            result["actual_tp_pips"] = str(self.actual_tp_pips)
        if self.expected_exit_price is not None:
            result["expected_exit_price"] = str(self.expected_exit_price)
        if self.actual_exit_price is not None:
            result["actual_exit_price"] = str(self.actual_exit_price)
        if self.validation_tolerance_pips is not None:
            result["validation_tolerance_pips"] = str(self.validation_tolerance_pips)
        if self.tick_bid is not None:
            result["tick_bid"] = str(self.tick_bid)
        if self.tick_ask is not None:
            result["tick_ask"] = str(self.tick_ask)
        if self.tick_mid is not None:
            result["tick_mid"] = str(self.tick_mid)
        return result

    @classmethod
    def from_dict(cls, event_dict: dict[str, Any]) -> "StrategyEvent":
        """Create StrategyEvent from dictionary.

        This factory method creates the appropriate subclass based on event_type,
        using the event registry for automatic dispatch.

        Args:
            event_dict: Dictionary containing event data

        Returns:
            Appropriate StrategyEvent subclass instance
        """
        event_type_str = event_dict.get("event_type", "")
        event_cls = _EVENT_REGISTRY.get(event_type_str)
        if event_cls is not None:
            return event_cls.from_dict(event_dict)
        # Fallback for unknown/custom event types
        return GenericStrategyEvent.from_dict(event_dict)


@register_event(EventType.INITIAL_ENTRY)
@dataclass
class InitialEntryEvent(StrategyEvent):
    """Event for opening an initial position layer.

    Attributes:
        layer_number: Layer number being opened (1-based: L1, L2, ...)
        direction: Trade direction (Direction enum)
        price: Entry price
        units: Position size
        entry_time: Entry timestamp
        retracement_count: Retracement index (always 0 for initial entry = R0)

    Example:
        >>> from apps.trading.strategies.floor.enums import Direction
        >>> event = InitialEntryEvent(
        ...     event_type=EventType.INITIAL_ENTRY,
        ...     layer_number=1,
        ...     direction=Direction.LONG,
        ...     price=Decimal("150.25"),
        ...     units=1000,
        ...     entry_time=datetime.now(),
        ... )
    """

    layer_number: int = 1
    direction: str = ""  # Will be Direction enum value
    price: Decimal = Decimal("0")
    units: int = 0
    entry_time: datetime | None = None
    retracement_count: int = 0
    entry_id: int | None = None  # Strategy-internal entry ID for position tracking
    planned_exit_price: Decimal | None = None
    planned_exit_price_formula: str | None = None

    def __post_init__(self):
        if not self.event_type:
            self.event_type = EventType.INITIAL_ENTRY

    @property
    def category(self) -> str:
        return "entry"

    def activate(self, context: "EventContext") -> None:
        """Execute initial entry event logic.

        This method logs the initial entry action at INFO level.
        The actual position ordering will be handled by the EventExecutor.

        Args:
            context: Event context containing task, account, instrument info
        """
        import logging

        logger = logging.getLogger(__name__)
        logger.info(
            f"Initial entry: layer={self.layer_number}, direction={self.direction}, "
            f"price={self.price}, units={self.units}",
            extra={
                "task_id": str(context.task_id),
                "task_type": context.task_type.value,
                "instrument": context.instrument,
                "event_type": self.event_type.value,
                "layer_number": self.layer_number,
                "direction": self.direction,
                "price": str(self.price),
                "units": self.units,
                "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result.update(
            {
                "layer_number": self.layer_number,
                "direction": str(self.direction),
                "price": str(self.price),
                "units": self.units,
                "retracement_count": self.retracement_count,
            }
        )
        if self.entry_id is not None:
            result["entry_id"] = self.entry_id
        if self.entry_time:
            result["entry_time"] = self.entry_time.isoformat()
        if self.planned_exit_price is not None:
            result["planned_exit_price"] = str(self.planned_exit_price)
        if self.planned_exit_price_formula is not None:
            result["planned_exit_price_formula"] = self.planned_exit_price_formula
        return result

    @classmethod
    def from_dict(cls, event_dict: dict[str, Any]) -> "InitialEntryEvent":
        return cls(
            event_type=EventType.INITIAL_ENTRY,
            timestamp=parse_datetime(event_dict.get("timestamp")),
            layer_number=int(event_dict.get("layer_number", 1)),
            direction=str(event_dict.get("direction", "")),
            price=parse_decimal(event_dict.get("price", "0")),
            units=int(event_dict.get("units", 0)),
            entry_time=parse_datetime(event_dict.get("entry_time")),
            retracement_count=int(event_dict.get("retracement_count", 0)),
            entry_id=event_dict.get("entry_id"),
            planned_exit_price=parse_optional_decimal(event_dict.get("planned_exit_price")),
            planned_exit_price_formula=event_dict.get("planned_exit_price_formula"),
        )


@register_event(EventType.RETRACEMENT)
@dataclass
class RetracementEvent(StrategyEvent):
    """Event for opening a retracement position.

    Attributes:
        layer_number: Layer number being retracted (1-based: L1, L2, ...)
        direction: Trade direction (Direction enum)
        price: Entry price
        units: Position size
        entry_time: Entry timestamp
        retracement_count: Retracement index (0-based: R0=initial, R1=first retracement, ...)

    Example:
        >>> from apps.trading.strategies.floor.enums import Direction
        >>> event = RetracementEvent(
        ...     event_type=EventType.RETRACEMENT,
        ...     layer_number=1,
        ...     direction=Direction.LONG,
        ...     price=Decimal("150.15"),
        ...     units=500,
        ...     entry_time=datetime.now(),
        ...     retracement_count=1,
        ... )
    """

    layer_number: int = 1
    direction: str = ""  # Will be Direction enum value
    price: Decimal = Decimal("0")
    units: int = 0
    entry_time: datetime | None = None
    retracement_count: int = 0
    entry_id: int | None = None  # Strategy-internal entry ID for position tracking
    planned_exit_price: Decimal | None = None
    planned_exit_price_formula: str | None = None

    def __post_init__(self):
        if not self.event_type:
            self.event_type = EventType.RETRACEMENT

    @property
    def category(self) -> str:
        return "entry"

    def activate(self, context: "EventContext") -> None:
        """Execute retracement event logic.

        This method logs the retracement action at INFO level.
        The actual position addition will be handled by the EventExecutor.

        Args:
            context: Event context containing task, account, instrument info
        """
        import logging

        logger = logging.getLogger(__name__)
        logger.info(
            f"Retracement: layer={self.layer_number}, direction={self.direction}, "
            f"price={self.price}, units={self.units}, count={self.retracement_count}",
            extra={
                "task_id": str(context.task_id),
                "task_type": context.task_type.value,
                "instrument": context.instrument,
                "event_type": self.event_type.value,
                "layer_number": self.layer_number,
                "direction": self.direction,
                "price": str(self.price),
                "units": self.units,
                "retracement_count": self.retracement_count,
                "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result.update(
            {
                "layer_number": self.layer_number,
                "direction": str(self.direction),
                "price": str(self.price),
                "units": self.units,
                "retracement_count": self.retracement_count,
            }
        )
        if self.entry_id is not None:
            result["entry_id"] = self.entry_id
        if self.entry_time:
            result["entry_time"] = self.entry_time.isoformat()
        if self.planned_exit_price is not None:
            result["planned_exit_price"] = str(self.planned_exit_price)
        if self.planned_exit_price_formula is not None:
            result["planned_exit_price_formula"] = self.planned_exit_price_formula
        return result

    @classmethod
    def from_dict(cls, event_dict: dict[str, Any]) -> "RetracementEvent":
        return cls(
            event_type=EventType.RETRACEMENT,
            timestamp=parse_datetime(event_dict.get("timestamp")),
            layer_number=int(event_dict.get("layer_number", 1)),
            direction=str(event_dict.get("direction", "")),
            price=parse_decimal(event_dict.get("price", "0")),
            units=int(event_dict.get("units", 0)),
            entry_time=parse_datetime(event_dict.get("entry_time")),
            retracement_count=int(event_dict.get("retracement_count", 0)),
            entry_id=event_dict.get("entry_id"),
            planned_exit_price=parse_optional_decimal(event_dict.get("planned_exit_price")),
            planned_exit_price_formula=event_dict.get("planned_exit_price_formula"),
        )


@register_event(EventType.TAKE_PROFIT)
@dataclass
class TakeProfitEvent(StrategyEvent):
    """Event for closing a position with profit.

    Attributes:
        layer_number: Layer number being closed
        direction: Trade direction (Direction enum)
        entry_price: Original entry price
        exit_price: Exit price
        units: Position size
        pnl: Profit/loss in account currency
        pips: Profit/loss in pips
        entry_time: Entry timestamp (optional)
        exit_time: Exit timestamp (optional)
        retracement_count: Number of retracements (optional)

    Example:
        >>> from apps.trading.strategies.floor.enums import Direction
        >>> event = TakeProfitEvent(
        ...     event_type=EventType.TAKE_PROFIT,
        ...     layer_number=1,
        ...     direction=Direction.LONG,
        ...     entry_price=Decimal("150.25"),
        ...     exit_price=Decimal("150.35"),
        ...     units=1000,
        ...     pnl=Decimal("100.00"),
        ...     pips=Decimal("10.0"),
        ...     entry_time=datetime.now(),
        ...     exit_time=datetime.now(),
        ... )
    """

    layer_number: int = 1
    direction: str = ""  # Will be Direction enum value
    entry_price: Decimal = Decimal("0")
    exit_price: Decimal = Decimal("0")
    units: int = 0
    pnl: Decimal = Decimal("0")
    pips: Decimal = Decimal("0")
    entry_time: datetime | None = None
    exit_time: datetime | None = None
    retracement_count: int = 0
    entry_id: int | None = None  # Strategy-internal entry ID
    position_id: str | None = None  # Position UUID for direct targeting

    def __post_init__(self):
        if not self.event_type:
            self.event_type = EventType.TAKE_PROFIT

    @property
    def category(self) -> str:
        return "exit"

    def activate(self, context: "EventContext") -> None:
        """Execute take profit event logic.

        This method logs the take profit action at INFO level.
        The actual position closing will be handled by the EventExecutor.

        Args:
            context: Event context containing task, account, instrument info
        """
        import logging

        logger = logging.getLogger(__name__)
        logger.info(
            f"Take profit: layer={self.layer_number}, direction={self.direction}, "
            f"entry={self.entry_price}, exit={self.exit_price}, units={self.units}, "
            f"pnl={self.pnl}, pips={self.pips}",
            extra={
                "task_id": str(context.task_id),
                "task_type": context.task_type.value,
                "instrument": context.instrument,
                "event_type": self.event_type.value,
                "layer_number": self.layer_number,
                "direction": self.direction,
                "entry_price": str(self.entry_price),
                "exit_price": str(self.exit_price),
                "units": self.units,
                "pnl": str(self.pnl),
                "pips": str(self.pips),
                "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result.update(
            {
                "layer_number": self.layer_number,
                "direction": str(self.direction),
                "entry_price": str(self.entry_price),
                "exit_price": str(self.exit_price),
                "units": self.units,
                "pnl": str(self.pnl),
                "pips": str(self.pips),
                "retracement_count": self.retracement_count,
            }
        )
        if self.entry_id is not None:
            result["entry_id"] = self.entry_id
        if self.position_id is not None:
            result["position_id"] = self.position_id
        if self.entry_time:
            result["entry_time"] = self.entry_time.isoformat()
        if self.exit_time:
            result["exit_time"] = self.exit_time.isoformat()
        return result

    @classmethod
    def from_dict(cls, event_dict: dict[str, Any]) -> "TakeProfitEvent":
        return cls(
            event_type=EventType.TAKE_PROFIT,
            timestamp=parse_datetime(event_dict.get("timestamp")),
            layer_number=int(event_dict.get("layer_number", 1)),
            direction=str(event_dict.get("direction", "")),
            entry_price=parse_decimal(event_dict.get("entry_price", "0")),
            exit_price=parse_decimal(event_dict.get("exit_price", "0")),
            units=int(event_dict.get("units", 0)),
            pnl=parse_decimal(event_dict.get("pnl", "0")),
            pips=parse_decimal(event_dict.get("pips", "0")),
            entry_time=parse_datetime(event_dict.get("entry_time")),
            exit_time=parse_datetime(event_dict.get("exit_time")),
            retracement_count=int(event_dict.get("retracement_count", 0)),
            entry_id=event_dict.get("entry_id"),
            position_id=event_dict.get("position_id"),
        )


@register_event(EventType.OPEN_POSITION)
@dataclass
class OpenPositionEvent(StrategyEvent):
    """Generic trading event for opening a position."""

    layer_number: int = 1
    direction: str = ""
    price: Decimal = Decimal("0")
    planned_entry_price: Decimal | None = None
    units: int = 0
    entry_time: datetime | None = None
    retracement_count: int = 0
    entry_id: int | None = None
    strategy_event_type: str = ""
    planned_exit_price: Decimal | None = None
    planned_exit_price_formula: str | None = None
    planned_exit_price_bound: Decimal | None = None
    planned_exit_price_bound_mode: str = ""
    stop_loss_price: Decimal | None = None
    description: str = ""
    merge_with_existing: bool = False

    def __post_init__(self):
        if not self.event_type:
            self.event_type = EventType.OPEN_POSITION

    @property
    def category(self) -> str:
        return "entry"

    def activate(self, context: "EventContext") -> None:
        import logging

        logger = logging.getLogger(__name__)
        logger.info(
            "Open position: layer=%s, direction=%s, units=%s",
            self.layer_number,
            self.direction,
            self.units,
            extra={
                "task_id": str(context.task_id),
                "task_type": context.task_type.value,
                "instrument": context.instrument,
                "event_type": self.event_type.value,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result.update(
            {
                "layer_number": self.layer_number,
                "direction": str(self.direction),
                "price": str(self.price),
                "units": self.units,
                "retracement_count": self.retracement_count,
            }
        )
        if self.planned_entry_price is not None:
            result["planned_entry_price"] = str(self.planned_entry_price)
        if self.entry_id is not None:
            result["entry_id"] = self.entry_id
        if self.strategy_event_type:
            result["strategy_event_type"] = self.strategy_event_type
        if self.entry_time:
            result["entry_time"] = self.entry_time.isoformat()
        if self.planned_exit_price is not None:
            result["planned_exit_price"] = str(self.planned_exit_price)
        if self.planned_exit_price_formula:
            result["planned_exit_price_formula"] = self.planned_exit_price_formula
        if self.planned_exit_price_bound is not None:
            result["planned_exit_price_bound"] = str(self.planned_exit_price_bound)
        if self.planned_exit_price_bound_mode:
            result["planned_exit_price_bound_mode"] = self.planned_exit_price_bound_mode
        if self.stop_loss_price is not None:
            result["stop_loss_price"] = str(self.stop_loss_price)
        if self.description:
            result["description"] = self.description
        if self.merge_with_existing:
            result["merge_with_existing"] = True
        return result

    @classmethod
    def from_dict(cls, event_dict: dict[str, Any]) -> "OpenPositionEvent":
        instance = cls(
            event_type=EventType.OPEN_POSITION,
            timestamp=parse_datetime(event_dict.get("timestamp")),
            layer_number=int(event_dict.get("layer_number", 1)),
            direction=str(event_dict.get("direction", "")),
            price=parse_decimal(event_dict.get("price", "0")),
            planned_entry_price=parse_optional_decimal(event_dict.get("planned_entry_price")),
            units=int(event_dict.get("units", 0)),
            entry_time=parse_datetime(event_dict.get("entry_time")),
            retracement_count=int(event_dict.get("retracement_count", 0)),
            entry_id=event_dict.get("entry_id"),
            strategy_event_type=str(event_dict.get("strategy_event_type", "")),
            planned_exit_price=parse_optional_decimal(event_dict.get("planned_exit_price")),
            planned_exit_price_formula=event_dict.get("planned_exit_price_formula"),
            planned_exit_price_bound=parse_optional_decimal(
                event_dict.get("planned_exit_price_bound")
            ),
            planned_exit_price_bound_mode=str(
                event_dict.get("planned_exit_price_bound_mode") or ""
            ),
            stop_loss_price=parse_optional_decimal(event_dict.get("stop_loss_price")),
            description=str(event_dict.get("description", "")),
            merge_with_existing=parse_bool(event_dict.get("merge_with_existing")),
        )
        instance.actual_interval_pips = parse_optional_decimal(
            event_dict.get("actual_interval_pips")
        )
        return instance


@register_event(EventType.REBUILD_POSITION)
@dataclass
class RebuildPositionEvent(StrategyEvent):
    """Event for rebuilding a previously stop-loss-closed position.

    Instead of creating a new Position record, the handler re-opens the
    original closed Position by clearing its exit fields and marking it
    as a rebuild.
    """

    layer_number: int = 1
    direction: str = ""
    price: Decimal = Decimal("0")
    planned_entry_price: Decimal | None = None
    units: int = 0
    retracement_count: int = 0
    entry_id: int | None = None
    strategy_event_type: str = ""
    planned_exit_price: Decimal | None = None
    planned_exit_price_formula: str | None = None
    planned_exit_price_bound: Decimal | None = None
    planned_exit_price_bound_mode: str = ""
    stop_loss_price: Decimal | None = None
    description: str = ""
    original_position_id: str | None = None

    def __post_init__(self):
        if not self.event_type:
            self.event_type = EventType.REBUILD_POSITION

    @property
    def category(self) -> str:
        return "entry"

    def activate(self, context: "EventContext") -> None:
        import logging

        logger = logging.getLogger(__name__)
        logger.info(
            "Rebuild position: layer=%s, direction=%s, units=%s, original=%s",
            self.layer_number,
            self.direction,
            self.units,
            self.original_position_id,
            extra={
                "task_id": str(context.task_id),
                "task_type": context.task_type.value,
                "instrument": context.instrument,
                "event_type": self.event_type.value,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result.update(
            {
                "layer_number": self.layer_number,
                "direction": str(self.direction),
                "price": str(self.price),
                "units": self.units,
                "retracement_count": self.retracement_count,
            }
        )
        if self.planned_entry_price is not None:
            result["planned_entry_price"] = str(self.planned_entry_price)
        if self.entry_id is not None:
            result["entry_id"] = self.entry_id
        if self.strategy_event_type:
            result["strategy_event_type"] = self.strategy_event_type
        if self.planned_exit_price is not None:
            result["planned_exit_price"] = str(self.planned_exit_price)
        if self.planned_exit_price_formula:
            result["planned_exit_price_formula"] = self.planned_exit_price_formula
        if self.planned_exit_price_bound is not None:
            result["planned_exit_price_bound"] = str(self.planned_exit_price_bound)
        if self.planned_exit_price_bound_mode:
            result["planned_exit_price_bound_mode"] = self.planned_exit_price_bound_mode
        if self.stop_loss_price is not None:
            result["stop_loss_price"] = str(self.stop_loss_price)
        if self.description:
            result["description"] = self.description
        if self.original_position_id:
            result["original_position_id"] = self.original_position_id
        return result

    @classmethod
    def from_dict(cls, event_dict: dict[str, Any]) -> "RebuildPositionEvent":
        return cls(
            event_type=EventType.REBUILD_POSITION,
            timestamp=parse_datetime(event_dict.get("timestamp")),
            layer_number=int(event_dict.get("layer_number", 1)),
            direction=str(event_dict.get("direction", "")),
            price=parse_decimal(event_dict.get("price", "0")),
            planned_entry_price=parse_optional_decimal(event_dict.get("planned_entry_price")),
            units=int(event_dict.get("units", 0)),
            retracement_count=int(event_dict.get("retracement_count", 0)),
            entry_id=event_dict.get("entry_id"),
            strategy_event_type=str(event_dict.get("strategy_event_type", "")),
            planned_exit_price=parse_optional_decimal(event_dict.get("planned_exit_price")),
            planned_exit_price_formula=event_dict.get("planned_exit_price_formula"),
            planned_exit_price_bound=parse_optional_decimal(
                event_dict.get("planned_exit_price_bound")
            ),
            planned_exit_price_bound_mode=str(
                event_dict.get("planned_exit_price_bound_mode") or ""
            ),
            stop_loss_price=parse_optional_decimal(event_dict.get("stop_loss_price")),
            description=str(event_dict.get("description", "")),
            original_position_id=event_dict.get("original_position_id"),
        )


@register_event(EventType.CLOSE_POSITION)
@dataclass
class ClosePositionEvent(StrategyEvent):
    """Generic trading event for closing a position."""

    layer_number: int = 1
    direction: str = ""
    entry_price: Decimal = Decimal("0")
    exit_price: Decimal = Decimal("0")
    units: int = 0
    pnl: Decimal = Decimal("0")
    pips: Decimal = Decimal("0")
    entry_time: datetime | None = None
    exit_time: datetime | None = None
    retracement_count: int = 0
    entry_id: int | None = None
    position_id: str | None = None
    strategy_event_type: str = ""
    description: str = ""
    force_instrument_close: bool = False

    def __post_init__(self):
        if not self.event_type:
            self.event_type = EventType.CLOSE_POSITION

    @property
    def category(self) -> str:
        return "exit"

    def activate(self, context: "EventContext") -> None:
        import logging

        logger = logging.getLogger(__name__)
        logger.info(
            "Close position: layer=%s, units=%s",
            self.layer_number,
            self.units,
            extra={
                "task_id": str(context.task_id),
                "task_type": context.task_type.value,
                "instrument": context.instrument,
                "event_type": self.event_type.value,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result.update(
            {
                "layer_number": self.layer_number,
                "direction": str(self.direction),
                "entry_price": str(self.entry_price),
                "exit_price": str(self.exit_price),
                "units": self.units,
                "pnl": str(self.pnl),
                "pips": str(self.pips),
                "retracement_count": self.retracement_count,
            }
        )
        if self.entry_id is not None:
            result["entry_id"] = self.entry_id
        if self.position_id is not None:
            result["position_id"] = self.position_id
        if self.strategy_event_type:
            result["strategy_event_type"] = self.strategy_event_type
        if self.description:
            result["description"] = self.description
        if self.force_instrument_close:
            result["force_instrument_close"] = True
        if self.entry_time:
            result["entry_time"] = self.entry_time.isoformat()
        if self.exit_time:
            result["exit_time"] = self.exit_time.isoformat()
        return result

    @classmethod
    def from_dict(cls, event_dict: dict[str, Any]) -> "ClosePositionEvent":
        inst = cls(
            event_type=EventType.CLOSE_POSITION,
            timestamp=parse_datetime(event_dict.get("timestamp")),
            layer_number=int(event_dict.get("layer_number", 1)),
            direction=str(event_dict.get("direction", "")),
            entry_price=parse_decimal(event_dict.get("entry_price", "0")),
            exit_price=parse_decimal(event_dict.get("exit_price", "0")),
            units=int(event_dict.get("units", 0)),
            pnl=parse_decimal(event_dict.get("pnl", "0")),
            pips=parse_decimal(event_dict.get("pips", "0")),
            entry_time=parse_datetime(event_dict.get("entry_time")),
            exit_time=parse_datetime(event_dict.get("exit_time")),
            retracement_count=int(event_dict.get("retracement_count", 0)),
            entry_id=event_dict.get("entry_id"),
            position_id=event_dict.get("position_id"),
            strategy_event_type=str(event_dict.get("strategy_event_type", "")),
            description=str(event_dict.get("description", "")),
            force_instrument_close=parse_bool(event_dict.get("force_instrument_close")),
        )
        # Restore base-class fields that are not part of the constructor
        # but are serialised into the event dict.
        if event_dict.get("close_reason"):
            inst.close_reason = str(event_dict["close_reason"])
        if event_dict.get("validation_status"):
            inst.validation_status = str(event_dict["validation_status"])
        raw_margin = event_dict.get("margin_ratio")
        if raw_margin is not None:
            inst.margin_ratio = parse_decimal(raw_margin)
        return inst


@register_event(EventType.ADD_LAYER)
@dataclass
class AddLayerEvent(StrategyEvent):
    """Event for adding a new layer to the strategy.

    Attributes:
        layer_number: Layer number being added
        add_time: Time when layer was added

    Example:
        >>> event = AddLayerEvent(
        ...     event_type=EventType.ADD_LAYER,
        ...     layer_number=2,
        ...     add_time=datetime.now(),
        ... )
    """

    layer_number: int = 1
    add_time: datetime | None = None

    def __post_init__(self):
        if not self.event_type:
            self.event_type = EventType.ADD_LAYER

    def activate(self, context: "EventContext") -> None:
        """Execute add layer event logic.

        This method logs the add layer action at INFO level.
        The actual layer creation will be handled by the EventExecutor.

        Args:
            context: Event context containing task, account, instrument info
        """
        import logging

        logger = logging.getLogger(__name__)
        logger.info(
            f"Add layer: layer_number={self.layer_number}",
            extra={
                "task_id": str(context.task_id),
                "task_type": context.task_type.value,
                "instrument": context.instrument,
                "event_type": self.event_type.value,
                "layer_number": self.layer_number,
                "add_time": self.add_time.isoformat() if self.add_time else None,
                "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["layer_number"] = self.layer_number
        if self.add_time:
            result["add_time"] = self.add_time.isoformat()
        return result

    @classmethod
    def from_dict(cls, event_dict: dict[str, Any]) -> "AddLayerEvent":
        return cls(
            event_type=EventType.ADD_LAYER,
            timestamp=parse_datetime(event_dict.get("timestamp")),
            layer_number=int(event_dict.get("layer_number", 1)),
            add_time=parse_datetime(event_dict.get("add_time")),
        )


@register_event(EventType.REMOVE_LAYER)
@dataclass
class RemoveLayerEvent(StrategyEvent):
    """Event for removing a layer from the strategy.

    Attributes:
        layer_number: Layer number being removed
        add_time: Time when layer was originally added
        remove_time: Time when layer was removed

    Example:
        >>> event = RemoveLayerEvent(
        ...     event_type=EventType.REMOVE_LAYER,
        ...     layer_number=3,
        ...     add_time=datetime.now(),
        ...     remove_time=datetime.now(),
        ... )
    """

    layer_number: int = 1
    add_time: datetime | None = None
    remove_time: datetime | None = None

    def __post_init__(self):
        if not self.event_type:
            self.event_type = EventType.REMOVE_LAYER

    def activate(self, context: "EventContext") -> None:
        """Execute remove layer event logic.

        This method logs the remove layer action at INFO level.
        The actual layer closing will be handled by the EventExecutor.

        Args:
            context: Event context containing task, account, instrument info
        """
        import logging

        logger = logging.getLogger(__name__)
        logger.info(
            f"Remove layer: layer_number={self.layer_number}",
            extra={
                "task_id": str(context.task_id),
                "task_type": context.task_type.value,
                "instrument": context.instrument,
                "event_type": self.event_type.value,
                "layer_number": self.layer_number,
                "add_time": self.add_time.isoformat() if self.add_time else None,
                "remove_time": self.remove_time.isoformat() if self.remove_time else None,
                "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["layer_number"] = self.layer_number
        if self.add_time:
            result["add_time"] = self.add_time.isoformat()
        if self.remove_time:
            result["remove_time"] = self.remove_time.isoformat()
        return result

    @classmethod
    def from_dict(cls, event_dict: dict[str, Any]) -> "RemoveLayerEvent":
        return cls(
            event_type=EventType.REMOVE_LAYER,
            timestamp=parse_datetime(event_dict.get("timestamp")),
            layer_number=int(event_dict.get("layer_number", 1)),
            add_time=parse_datetime(event_dict.get("add_time")),
            remove_time=parse_datetime(event_dict.get("remove_time")),
        )


@register_event(EventType.VOLATILITY_LOCK)
@dataclass
class VolatilityLockEvent(StrategyEvent):
    """Event for strategy locked due to high volatility.

    Attributes:
        reason: Reason for the lock
        atr_value: ATR value that triggered the lock (optional)
        threshold: ATR threshold (optional)

    Example:
        >>> event = VolatilityLockEvent(
        ...     event_type=EventType.VOLATILITY_LOCK,
        ...     timestamp=datetime.now(),
        ...     reason="ATR exceeded threshold",
        ...     atr_value=Decimal("0.25"),
        ...     threshold=Decimal("0.20"),
        ... )
    """

    reason: str = ""
    atr_value: Decimal | None = None
    threshold: Decimal | None = None

    def __post_init__(self):
        if not self.event_type:
            self.event_type = EventType.VOLATILITY_LOCK

    @property
    def category(self) -> str:
        return "risk"

    def activate(self, context: "EventContext") -> None:
        """Execute volatility lock event logic.

        This method logs the volatility lock action at INFO level.
        The actual position closing will be handled by the EventExecutor.

        Args:
            context: Event context containing task, account, instrument info
        """
        import logging

        logger = logging.getLogger(__name__)
        logger.info(
            f"Volatility lock: reason={self.reason}, atr={self.atr_value}, threshold={self.threshold}",
            extra={
                "task_id": str(context.task_id),
                "task_type": context.task_type.value,
                "instrument": context.instrument,
                "event_type": self.event_type.value,
                "reason": self.reason,
                "atr_value": str(self.atr_value) if self.atr_value else None,
                "threshold": str(self.threshold) if self.threshold else None,
                "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["reason"] = self.reason
        if self.atr_value is not None:
            result["atr_value"] = str(self.atr_value)
        if self.threshold is not None:
            result["threshold"] = str(self.threshold)
        return result

    @classmethod
    def from_dict(cls, event_dict: dict[str, Any]) -> "VolatilityLockEvent":
        inst = cls(
            event_type=EventType.VOLATILITY_LOCK,
            timestamp=parse_datetime(event_dict.get("timestamp")),
            reason=str(event_dict.get("reason", "")),
            atr_value=parse_optional_decimal(event_dict.get("atr_value")),
            threshold=parse_optional_decimal(event_dict.get("threshold")),
        )
        inst.tick_bid = parse_optional_decimal(event_dict.get("tick_bid"))
        inst.tick_ask = parse_optional_decimal(event_dict.get("tick_ask"))
        inst.tick_mid = parse_optional_decimal(event_dict.get("tick_mid"))
        return inst


@register_event(EventType.VOLATILITY_HEDGE_NEUTRALIZE)
@dataclass
class VolatilityHedgeNeutralizeEvent(StrategyEvent):
    """Event emitted when hedging-mode volatility lock neutralizes positions.

    Instead of closing all positions, this event instructs the handler to open
    opposite hedge positions for each existing open position so that the net
    exposure becomes zero.  The strategy then pauses until volatility subsides.

    Attributes:
        reason: Human-readable description of why the neutralization was triggered.
        atr_value: Current ATR value that triggered the event.
        threshold: ATR threshold that was exceeded.
        hedge_instructions: List of dicts describing each hedge to open.
            Each dict contains: ``direction``, ``units``, ``layer_index``,
            ``source_entry_id``.
    """

    reason: str = ""
    atr_value: Decimal | None = None
    threshold: Decimal | None = None
    hedge_instructions: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        if not self.event_type:
            self.event_type = EventType.VOLATILITY_HEDGE_NEUTRALIZE

    @property
    def category(self) -> str:
        return "risk"

    def activate(self, context: "EventContext") -> None:
        import logging

        logger = logging.getLogger(__name__)
        logger.info(
            "Volatility hedge neutralize: reason=%s, hedges=%d",
            self.reason,
            len(self.hedge_instructions),
            extra={
                "task_id": str(context.task_id),
                "task_type": context.task_type.value,
                "instrument": context.instrument,
                "event_type": self.event_type.value,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["reason"] = self.reason
        if self.atr_value is not None:
            result["atr_value"] = str(self.atr_value)
        if self.threshold is not None:
            result["threshold"] = str(self.threshold)
        result["hedge_instructions"] = self.hedge_instructions
        return result

    @classmethod
    def from_dict(cls, event_dict: dict[str, Any]) -> "VolatilityHedgeNeutralizeEvent":
        inst = cls(
            event_type=EventType.VOLATILITY_HEDGE_NEUTRALIZE,
            timestamp=parse_datetime(event_dict.get("timestamp")),
            reason=str(event_dict.get("reason", "")),
            atr_value=parse_optional_decimal(event_dict.get("atr_value")),
            threshold=parse_optional_decimal(event_dict.get("threshold")),
            hedge_instructions=list(event_dict.get("hedge_instructions", [])),
        )
        inst.tick_bid = parse_optional_decimal(event_dict.get("tick_bid"))
        inst.tick_ask = parse_optional_decimal(event_dict.get("tick_ask"))
        inst.tick_mid = parse_optional_decimal(event_dict.get("tick_mid"))
        return inst


@register_event(EventType.MARGIN_PROTECTION)
@dataclass
class MarginProtectionEvent(StrategyEvent):
    """Event for margin protection triggered.

    Attributes:
        reason: Reason for margin protection
        current_margin: Current margin level (optional)
        threshold: Margin threshold (optional)
        positions_closed: Number of positions closed (optional)
        units_to_close: Number of units to close (optional)

    Example:
        >>> event = MarginProtectionEvent(
        ...     event_type=EventType.MARGIN_PROTECTION,
        ...     timestamp=datetime.now(),
        ...     reason="Margin threshold exceeded",
        ...     current_margin=Decimal("0.05"),
        ...     threshold=Decimal("0.10"),
        ...     positions_closed=2,
        ... )
    """

    reason: str = ""
    current_margin: Decimal | None = None
    threshold: Decimal | None = None
    positions_closed: int | None = None
    units_to_close: int | None = None

    def __post_init__(self):
        if not self.event_type:
            self.event_type = EventType.MARGIN_PROTECTION

    @property
    def category(self) -> str:
        return "risk"

    def activate(self, context: "EventContext") -> None:
        """Execute margin protection event logic.

        This method logs the margin protection action at INFO level.
        The actual position closing will be handled by the EventExecutor.

        Args:
            context: Event context containing task, account, instrument info
        """
        import logging

        logger = logging.getLogger(__name__)
        logger.info(
            f"Margin protection: reason={self.reason}, current={self.current_margin}, "
            f"threshold={self.threshold}, closed={self.positions_closed}, "
            f"units_to_close={self.units_to_close}",
            extra={
                "task_id": str(context.task_id),
                "task_type": context.task_type.value,
                "instrument": context.instrument,
                "event_type": self.event_type.value,
                "reason": self.reason,
                "current_margin": str(self.current_margin) if self.current_margin else None,
                "threshold": str(self.threshold) if self.threshold else None,
                "positions_closed": self.positions_closed,
                "units_to_close": self.units_to_close,
                "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["reason"] = self.reason
        if self.current_margin is not None:
            result["current_margin"] = str(self.current_margin)
        if self.threshold is not None:
            result["threshold"] = str(self.threshold)
        if self.positions_closed is not None:
            result["positions_closed"] = self.positions_closed
        if self.units_to_close is not None:
            result["units_to_close"] = self.units_to_close
        return result

    @classmethod
    def from_dict(cls, event_dict: dict[str, Any]) -> "MarginProtectionEvent":
        inst = cls(
            event_type=EventType.MARGIN_PROTECTION,
            timestamp=parse_datetime(event_dict.get("timestamp")),
            reason=str(event_dict.get("reason", "")),
            current_margin=parse_optional_decimal(event_dict.get("current_margin")),
            threshold=parse_optional_decimal(event_dict.get("threshold")),
            positions_closed=event_dict.get("positions_closed"),
            units_to_close=event_dict.get("units_to_close"),
        )
        inst.tick_bid = parse_optional_decimal(event_dict.get("tick_bid"))
        inst.tick_ask = parse_optional_decimal(event_dict.get("tick_ask"))
        inst.tick_mid = parse_optional_decimal(event_dict.get("tick_mid"))
        return inst


@dataclass
class GenericStrategyEvent(StrategyEvent):
    """Generic event for custom or unknown event types.

    This class is used for event types that don't have a specific class,
    allowing flexibility for custom strategies while maintaining type safety.

    Attributes:
        data: Event-specific data dictionary

    Example:
        >>> event = GenericStrategyEvent(
        ...     event_type=EventType.STRATEGY_SIGNAL,
        ...     timestamp=datetime.now(),
        ...     data={"signal": "buy", "confidence": 0.85},
        ... )
    """

    data: dict[str, Any] = field(default_factory=dict)

    def activate(self, context: "EventContext") -> None:
        """Execute generic event logic.

        For generic events, this logs the event at an appropriate level based on event type.
        Lifecycle events log at INFO or DEBUG, error events at WARNING or ERROR.

        Args:
            context: Event context containing task, account, instrument info
        """
        import logging

        logger = logging.getLogger(__name__)

        # Determine log level based on event type
        from apps.trading.enums import EventType

        if self.event_type == EventType.TICK_RECEIVED:
            log_level = logging.DEBUG
        elif self.event_type in {
            EventType.STRATEGY_STARTED,
            EventType.STRATEGY_PAUSED,
            EventType.STRATEGY_RESUMED,
            EventType.STRATEGY_STOPPED,
        }:
            log_level = logging.INFO
        elif self.event_type == EventType.STATUS_CHANGED:
            log_level = logging.WARNING
        elif self.event_type == EventType.ERROR_OCCURRED:
            log_level = logging.ERROR
        else:
            log_level = logging.INFO

        logger.log(
            log_level,
            f"Event: {self.event_type.value}",
            extra={
                "task_id": str(context.task_id),
                "task_type": context.task_type.value,
                "instrument": context.instrument,
                "event_type": self.event_type.value,
                "event_data": self.data,
                "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result.update(self.data)
        return result

    @classmethod
    def from_dict(cls, event_dict: dict[str, Any]) -> "GenericStrategyEvent":
        event_type_str = event_dict.get("event_type", "")
        try:
            event_type = EventType(event_type_str)
        except ValueError:
            event_type = event_type_str

        data = {k: v for k, v in event_dict.items() if k not in {"event_type", "timestamp"}}

        return cls(
            event_type=event_type,
            timestamp=parse_datetime(event_dict.get("timestamp")),
            data=data,
        )
