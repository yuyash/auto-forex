"""Event handler for executing orders based on strategy events."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from logging import Logger, getLogger
from typing import Any

from django.utils import timezone as dj_timezone

from apps.trading.dataclasses import EntryExecutionBinding, EventExecutionResult
from apps.trading.enums import Direction, EventType
from apps.trading.events import (
    ClosePositionEvent,
    MarginProtectionEvent,
    OpenPositionEvent,
    RebuildPositionEvent,
    StrategyEvent,
    VolatilityHedgeNeutralizeEvent,
    VolatilityLockEvent,
)
from apps.trading.models import Order, Position, Trade, TradingEvent
from apps.trading.order import OrderService, OrderServiceError
from apps.trading.utils import Instrument

logger: Logger = getLogger(name=__name__)
lifecycle_logger: Logger = getLogger(name="position.lifecycle")


class CycleResolutionError(Exception):
    """Raised when a rebuild cannot resolve its parent cycle.

    This indicates corrupt or inconsistent strategy state — the task
    must stop because continuing would create orphaned positions.
    """


class ClosePositionResolutionError(Exception):
    """Raised when a close event cannot identify its exact target position.

    Closing an arbitrary same-layer position corrupts realized P/L and cycle
    attribution.  The task must stop instead of continuing with a guessed target.
    """


EventDispatchFn = Callable[[StrategyEvent], EventExecutionResult]


class PositionExecutionCache:
    """Own in-memory position lookup state for one execution handler."""

    def __init__(self, *, order_service: OrderService, instrument: str) -> None:
        self.order_service = order_service
        self.instrument = instrument
        self.position_map: dict[int, Position] = {}
        self.layer_position_ids: dict[int, list[str]] = defaultdict(list)
        self.position_cache: dict[str, Position] = {}

    @property
    def task_pk(self):
        """Return the task primary key for ORM scoping."""
        return self.order_service.task.id

    @property
    def execution_id(self):
        """Return the current execution id for ORM scoping."""
        return self.order_service.execution_id

    def cache_position(self, layer_number: int, position: Position) -> None:
        """Cache a position by id and by layer."""
        pos_id = str(position.id)
        if pos_id not in self.layer_position_ids[layer_number]:
            self.layer_position_ids[layer_number].append(pos_id)
        self.position_cache[pos_id] = position
        self.position_map[layer_number] = position

    def get_open_position_by_id(self, position_id: str) -> Position | None:
        """Return a cached or persisted open position by id."""
        cached = self.position_cache.get(position_id)
        if cached and cached.is_open:
            return cached
        position = (
            Position.objects.filter(
                id=position_id,
                task_type=self.order_service.task_type,
                task_id=self.task_pk,
                execution_id=self.execution_id,
                is_open=True,
            )
            .order_by("-entry_time")
            .first()
        )
        if position:
            self.position_cache[position_id] = position
        return position

    def rehydrate_layer_positions(self, layer_number: int) -> None:
        """Load layer positions from storage when the in-memory stack is empty."""
        if self.layer_position_ids.get(layer_number):
            return
        open_positions = list(
            Position.objects.filter(
                task_type=self.order_service.task_type,
                task_id=self.task_pk,
                execution_id=self.execution_id,
                instrument=self.instrument,
                is_open=True,
                layer_index=layer_number,
            ).order_by("entry_time", "created_at")
        )
        if not open_positions:
            return
        self.layer_position_ids[layer_number] = [str(p.id) for p in open_positions]
        for position in open_positions:
            self.position_cache[str(position.id)] = position
        self.position_map[layer_number] = open_positions[-1]

    def prune_closed_position(self, layer_number: int, position: Position) -> None:
        """Remove a closed position from every in-memory index."""
        pos_id = str(position.id)
        if position.is_open:
            self.position_cache[pos_id] = position
            self.position_map[layer_number] = position
            return

        self.position_cache.pop(pos_id, None)
        ids = self.layer_position_ids.get(layer_number, [])
        if pos_id in ids:
            ids.remove(pos_id)
        if not ids:
            self.layer_position_ids.pop(layer_number, None)
            self.position_map.pop(layer_number, None)
            return
        replacement = self.get_open_position_by_id(ids[-1])
        if replacement:
            self.position_map[layer_number] = replacement
        else:
            self.position_map.pop(layer_number, None)


class EventHandler:
    """Handles strategy events by executing corresponding orders.

    This class bridges the gap between strategy events (trading signals)
    and actual order execution through the OrderService.

    Attributes:
        order_service: Service for executing orders
        instrument: Trading instrument
        position_map: Maps layer numbers to Position instances
    """

    _PROTECTION_CLOSE_REASONS = frozenset(
        {"shrink", "volatility_lock", "margin_protection", "stop_loss"}
    )

    def __init__(self, order_service: OrderService, instrument: str):
        """Initialize event handler.

        Args:
            order_service: OrderService instance for executing trades
            instrument: Trading instrument (e.g., 'EUR_USD')
        """
        self.order_service = order_service
        self.instrument = instrument
        self.positions = PositionExecutionCache(
            order_service=order_service,
            instrument=instrument,
        )
        self.position_map = self.positions.position_map
        self.layer_position_ids = self.positions.layer_position_ids
        self._position_cache = self.positions.position_cache
        self._event_dispatch: dict[str, EventDispatchFn] = {
            "open_position": self._dispatch_open_position,
            "close_position": self._dispatch_close_position,
            "rebuild_position": self._dispatch_rebuild_position,
            "volatility_lock": self._dispatch_volatility_lock,
            "volatility_hedge_neutralize": self._dispatch_volatility_hedge_neutralize,
            "margin_protection": self._dispatch_margin_protection,
        }
        self._category_dispatch: dict[str, EventDispatchFn] = {
            "info": self._dispatch_informational,
            "entry": self._dispatch_unhandled_category,
            "exit": self._dispatch_unhandled_category,
            "risk": self._dispatch_unhandled_category,
        }
        # Maps strategy-internal entry_id → Trade.cycle_id (UUID).
        # Populated by handle_open_position so that subsequent close
        # trades and child entries can inherit the correct cycle_id.
        self._entry_id_to_cycle_id: dict[int, str] = {}
        # Maps strategy-internal entry_id -> Position.id for exact close
        # targeting within one execution batch.  This covers open/rebuild and
        # close events emitted on the same tick before strategy state is rebound.
        self._entry_id_to_position_id: dict[int, str] = {}
        # Sequence number from the current TradingEvent being processed.
        self._current_sequence_number: int = 0
        self._current_replay_mode = False
        self._affected_refs = self._new_affected_refs()
        self._current_oanda_response_seconds: list[Decimal] = []
        self._current_oanda_response_order_ids: set[str] = set()

    @staticmethod
    def _event_type_key(strategy_event: StrategyEvent) -> str:
        event_type = getattr(strategy_event, "event_type", "")
        return str(getattr(event_type, "value", event_type))

    def register_event_handler(self, event_type: str, handler: EventDispatchFn) -> None:
        """Register/override a handler for a specific event_type."""
        key = str(event_type).strip()
        if not key:
            raise ValueError("event_type must be non-empty")
        self._event_dispatch[key] = handler

    def register_category_handler(self, category: str, handler: EventDispatchFn) -> None:
        """Register/override a handler for an event category."""
        key = str(category).strip()
        if not key:
            raise ValueError("category must be non-empty")
        self._category_dispatch[key] = handler

    @property
    def _task_pk(self):
        return self.order_service.task.id

    @property
    def _execution_id(self):
        return self.order_service.execution_id

    @property
    def _account_currency(self) -> str:
        task = getattr(self.order_service, "task", None)
        return str(
            getattr(task, "account_currency", "")
            or getattr(getattr(self.order_service, "account", None), "currency", "")
            or ""
        ).upper()

    @property
    def _quote_currency(self) -> str:
        return Instrument(self.instrument).quote_currency

    def _cache_position(self, layer_number: int, position: Position) -> None:
        self.positions.cache_position(layer_number, position)

    def _get_open_position_by_id(self, position_id: str) -> Position | None:
        return self.positions.get_open_position_by_id(position_id)

    def _rehydrate_layer_positions(self, layer_number: int) -> None:
        self.positions.rehydrate_layer_positions(layer_number)

    def _find_close_position_target(self, event: ClosePositionEvent) -> Position | None:
        position_id = str(event.position_id or "").strip()
        source = "position_id"
        if not position_id:
            entry_id = getattr(event, "entry_id", None)
            if entry_id is not None:
                position_id = self._entry_id_to_position_id.get(int(entry_id), "")
                source = "entry_id"

        if not position_id:
            raise ClosePositionResolutionError(
                "ClosePositionEvent does not identify an open position: "
                f"entry_id={getattr(event, 'entry_id', None)}, "
                f"position_id={event.position_id}, layer={event.layer_number}, "
                f"direction={event.direction}. Refusing to close an inferred position."
            )

        candidate = self._get_open_position_by_id(position_id)
        if not candidate:
            raise ClosePositionResolutionError(
                "ClosePositionEvent target is missing or already closed: "
                f"{source}={position_id}, entry_id={getattr(event, 'entry_id', None)}, "
                f"layer={event.layer_number}, direction={event.direction}."
            )

        direction = Direction(event.direction)
        if candidate.direction != direction.value:
            raise ClosePositionResolutionError(
                "ClosePositionEvent target direction mismatch: "
                f"position_id={candidate.id}, position_direction={candidate.direction}, "
                f"event_direction={direction.value}."
            )
        if candidate.instrument != self.instrument:
            raise ClosePositionResolutionError(
                "ClosePositionEvent target instrument mismatch: "
                f"position_id={candidate.id}, position_instrument={candidate.instrument}, "
                f"handler_instrument={self.instrument}."
            )
        if candidate.layer_index is not None and candidate.layer_index != event.layer_number:
            raise ClosePositionResolutionError(
                "ClosePositionEvent target layer mismatch: "
                f"position_id={candidate.id}, position_layer={candidate.layer_index}, "
                f"event_layer={event.layer_number}."
            )
        return candidate

    def _prune_closed_position(self, layer_number: int, position: Position) -> None:
        self.positions.prune_closed_position(layer_number, position)

    def _ordered_positions_for_margin_close(self) -> list[Position]:
        open_positions = list(
            Position.objects.filter(
                task_type=self.order_service.task_type,
                task_id=self._task_pk,
                execution_id=self._execution_id,
                instrument=self.instrument,
                is_open=True,
            ).order_by("layer_index", "entry_time", "created_at")
        )
        for position in open_positions:
            self._cache_position(position.layer_index or 0, position)
        return open_positions

    def _record_trade(
        self,
        *,
        direction: Direction | None,
        units: int,
        instrument: str,
        price: Decimal,
        execution_method: str,
        timestamp,
        layer_index: int | None = None,
        retracement_count: int | None = None,
        oanda_trade_id: str | None = None,
        position: Position | None = None,
        order: Order | None = None,
        description: str = "",
        cycle_id: str | None = None,
        margin_ratio: Decimal | None = None,
        is_rebuild: bool = False,
    ) -> Trade:
        trade = Trade.objects.create(
            task_type=self.order_service.task_type.value,
            task_id=self._task_pk,
            execution_id=self._execution_id,
            timestamp=timestamp,
            direction=direction.value if direction else None,
            units=units,
            instrument=instrument,
            price=price,
            price_currency=Instrument(instrument).quote_currency,
            execution_method=execution_method,
            layer_index=layer_index,
            retracement_count=retracement_count,
            oanda_trade_id=oanda_trade_id,
            position=position,
            order=order,
            description=description,
            cycle_id=cycle_id,
            sequence_number=self._current_sequence_number,
            margin_ratio=margin_ratio,
            is_rebuild=is_rebuild,
        )
        return trade

    def _trade_execution_timestamp(
        self,
        *,
        fallback_timestamp: datetime | None,
        order: Order | None,
    ) -> datetime:
        filled_at = getattr(order, "filled_at", None)
        if not self.order_service.dry_run and isinstance(filled_at, datetime):
            return filled_at
        return fallback_timestamp or dj_timezone.now()

    def handle_event(self, trading_event: TradingEvent | Any) -> EventExecutionResult:
        """Handle a single trading event by executing appropriate order.

        Args:
            trading_event: TradingEvent instance from database

        Returns:
            EventExecutionResult: Realized pnl and optional entry-position binding

        Raises:
            OrderServiceError: If order execution fails
        """
        return self._handle_event(trading_event, replaying=False)

    def handle_event_with_replay(
        self, trading_event: TradingEvent | Any, *, replaying: bool
    ) -> EventExecutionResult:
        """Handle a single trading event with optional replay context."""
        return self._handle_event(trading_event, replaying=replaying)

    def _handle_event(
        self, trading_event: TradingEvent | Any, *, replaying: bool
    ) -> EventExecutionResult:
        strategy_event = getattr(trading_event, "_strategy_event", None)
        if not isinstance(strategy_event, StrategyEvent):
            strategy_event = StrategyEvent.from_dict(trading_event.details)
        if isinstance(trading_event.details, dict) and trading_event.details.get("strategy_type"):
            strategy_event.strategy_type = str(trading_event.details["strategy_type"])
        self._current_sequence_number = getattr(trading_event, "sequence_number", 0) or 0
        self._current_replay_mode = replaying
        self._affected_refs = self._new_affected_refs()
        self._current_oanda_response_seconds = []
        self._current_oanda_response_order_ids = set()
        # Restore cycle-tracking fields from TradingEvent model columns
        # (these are not stored in the details JSON).
        if trading_event.root_entry_id is not None:
            strategy_event.root_entry_id = trading_event.root_entry_id
        if trading_event.parent_entry_id is not None:
            strategy_event.parent_entry_id = trading_event.parent_entry_id
        event_key = self._event_type_key(strategy_event)
        event_handler = self._event_dispatch.get(event_key)
        try:
            if event_handler:
                result = event_handler(strategy_event)
            else:
                category = str(getattr(strategy_event, "category", "info"))
                category_handler = self._category_dispatch.get(
                    category, self._dispatch_informational
                )
                result = category_handler(strategy_event)
            return replace(
                result,
                **self._snapshot_affected_refs(),
                oanda_response_seconds=(
                    *result.oanda_response_seconds,
                    *self._current_oanda_response_seconds,
                ),
            )
        finally:
            self._current_replay_mode = False

    def _dispatch_open_position(self, strategy_event: StrategyEvent) -> EventExecutionResult:
        if not isinstance(strategy_event, OpenPositionEvent):
            return self._dispatch_type_mismatch(strategy_event, OpenPositionEvent)
        position = self.handle_open_position(strategy_event)
        binding = EntryExecutionBinding(
            entry_id=strategy_event.entry_id,
            position_id=str(position.id),
            cycle_id=getattr(self, "_last_open_cycle_id", None),
            fill_price=getattr(self, "_last_open_fill_price", position.entry_price),
        )
        return EventExecutionResult(
            realized_pnl_delta=Decimal("0"),
            execution_price=getattr(self, "_last_open_fill_price", position.entry_price),
            executed_units=strategy_event.units,
            entry_binding=binding,
        )

    def _dispatch_close_position(self, strategy_event: StrategyEvent) -> EventExecutionResult:
        if not isinstance(strategy_event, ClosePositionEvent):
            return self._dispatch_type_mismatch(strategy_event, ClosePositionEvent)
        realized_delta, realized_delta_quote = self.handle_close_position(strategy_event)
        return EventExecutionResult(
            realized_pnl_delta=realized_delta,
            realized_pnl_delta_quote=realized_delta_quote,
            realized_pnl_delta_currency=self._account_currency,
            realized_pnl_delta_quote_currency=self._quote_currency,
            execution_price=getattr(self, "_last_close_execution_price", None),
            executed_units=getattr(self, "_last_close_executed_units", 0),
        )

    def _dispatch_rebuild_position(self, strategy_event: StrategyEvent) -> EventExecutionResult:
        if not isinstance(strategy_event, RebuildPositionEvent):
            return self._dispatch_type_mismatch(strategy_event, RebuildPositionEvent)
        position = self.handle_rebuild_position(strategy_event)
        binding = EntryExecutionBinding(
            entry_id=strategy_event.entry_id,
            position_id=str(position.id),
            cycle_id=getattr(self, "_last_open_cycle_id", None),
            fill_price=position.entry_price,
        )
        return EventExecutionResult(
            realized_pnl_delta=Decimal("0"),
            entry_binding=binding,
        )

    def _dispatch_volatility_lock(self, strategy_event: StrategyEvent) -> EventExecutionResult:
        if not isinstance(strategy_event, VolatilityLockEvent):
            return self._dispatch_type_mismatch(strategy_event, VolatilityLockEvent)
        realized_delta, realized_delta_quote = self.handle_volatility_lock(strategy_event)
        return EventExecutionResult(
            realized_pnl_delta=realized_delta,
            realized_pnl_delta_quote=realized_delta_quote,
            realized_pnl_delta_currency=self._account_currency,
            realized_pnl_delta_quote_currency=self._quote_currency,
        )

    def _dispatch_volatility_hedge_neutralize(
        self, strategy_event: StrategyEvent
    ) -> EventExecutionResult:
        if not isinstance(strategy_event, VolatilityHedgeNeutralizeEvent):
            return self._dispatch_type_mismatch(strategy_event, VolatilityHedgeNeutralizeEvent)
        return EventExecutionResult(
            realized_pnl_delta=self.handle_volatility_hedge_neutralize(strategy_event),
        )

    def _dispatch_margin_protection(self, strategy_event: StrategyEvent) -> EventExecutionResult:
        if not isinstance(strategy_event, MarginProtectionEvent):
            return self._dispatch_type_mismatch(strategy_event, MarginProtectionEvent)
        realized_delta, realized_delta_quote = self.handle_margin_protection(strategy_event)
        return EventExecutionResult(
            realized_pnl_delta=realized_delta,
            realized_pnl_delta_quote=realized_delta_quote,
            realized_pnl_delta_currency=self._account_currency,
            realized_pnl_delta_quote_currency=self._quote_currency,
        )

    def _dispatch_informational(self, strategy_event: StrategyEvent) -> EventExecutionResult:
        logger.debug(
            "Informational event ignored by execution handler: event_type=%s, category=%s",
            self._event_type_key(strategy_event),
            getattr(strategy_event, "category", "info"),
        )
        return EventExecutionResult(realized_pnl_delta=Decimal("0"))

    def _dispatch_unhandled_category(self, strategy_event: StrategyEvent) -> EventExecutionResult:
        logger.warning(
            "No execution handler registered for event category '%s' (event_type=%s)",
            getattr(strategy_event, "category", "unknown"),
            self._event_type_key(strategy_event),
        )
        return EventExecutionResult(realized_pnl_delta=Decimal("0"))

    def _dispatch_type_mismatch(
        self,
        strategy_event: StrategyEvent,
        expected_cls: type[StrategyEvent],
    ) -> EventExecutionResult:
        logger.error(
            "Event dispatch type mismatch for event_type=%s: expected %s, got %s",
            self._event_type_key(strategy_event),
            expected_cls.__name__,
            strategy_event.__class__.__name__,
        )
        return EventExecutionResult(realized_pnl_delta=Decimal("0"))

    def _resolve_cycle_id_for_open(
        self, event: OpenPositionEvent | RebuildPositionEvent
    ) -> str | None:
        """Determine the cycle_id for a new open trade.

        - If parent_entry_id is None this is a cycle-starting entry
          (Initial Entry or Trend re-entry).  The cycle_id will be the
          Trade.id of the trade we are about to create — the caller must
          back-fill it after creation.
        - Otherwise, look up the root_entry_id in the mapping to find
          the cycle_id of the cycle this entry belongs to.

        Returns None when the entry starts a new cycle (caller must
        set cycle_id = trade.id after creation).
        """
        root_eid = getattr(event, "root_entry_id", None)
        parent_eid = getattr(event, "parent_entry_id", None)

        if parent_eid is None:
            # New cycle — cycle_id will be this trade's own id.
            return None

        # Child entry — inherit cycle_id from root.
        if root_eid is not None and root_eid in self._entry_id_to_cycle_id:
            return self._entry_id_to_cycle_id[root_eid]

        # Fallback: try parent chain.
        if parent_eid in self._entry_id_to_cycle_id:
            return self._entry_id_to_cycle_id[parent_eid]

        # DB fallback: look up cycle_id from existing TradingEvent records.
        # This handles the case where the EventHandler was re-created (e.g.
        # after a task resume) and the in-memory mapping was lost.
        cycle_id = self._resolve_cycle_id_from_db(
            root_eid,
            parent_eid,
            direction=getattr(event, "direction", None),
        )
        if cycle_id is not None:
            # Cache for future lookups within this session.
            if root_eid is not None:
                self._entry_id_to_cycle_id[root_eid] = cycle_id
            if parent_eid is not None:
                self._entry_id_to_cycle_id[parent_eid] = cycle_id
            return cycle_id

        logger.warning(
            "Could not resolve cycle_id for entry_id=%s (root=%s, parent=%s)",
            event.entry_id,
            root_eid,
            parent_eid,
        )
        return None

    def _resolve_cycle_id_from_db(
        self,
        root_eid: int | None,
        parent_eid: int | None,
        *,
        direction: str | None = None,
    ) -> str | None:
        """Look up cycle_id from Trade records by matching entry_id in TradingEvent.

        Timestamp-only fallback is unsafe because long and short entries can share
        the same tick timestamp. Use the originating TradingEvent metadata to
        narrow the lookup.
        """
        try:
            for eid in (root_eid, parent_eid):
                if eid is None:
                    continue
                te = (
                    TradingEvent.objects.filter(
                        task_type=self.order_service.task_type,
                        task_id=self._task_pk,
                        execution_id=self._execution_id,
                        entry_id=eid,
                        event_type="open_position",
                    )
                    .values("event_timestamp", "sequence_number", "direction")
                    .first()
                )
                if te is None:
                    continue
                event_timestamp = te.get("event_timestamp")
                if event_timestamp is None:
                    continue
                event_direction = str(te.get("direction") or direction or "").strip().lower()
                trade_qs = Trade.objects.filter(
                    task_type=self.order_service.task_type.value,
                    task_id=self._task_pk,
                    execution_id=self._execution_id,
                    timestamp=event_timestamp,
                    execution_method="open_position",
                    cycle_id__isnull=False,
                    sequence_number=te.get("sequence_number", 0) or 0,
                )
                if event_direction:
                    trade_qs = trade_qs.filter(direction__iexact=event_direction)
                trade = trade_qs.values_list("cycle_id", flat=True).first()
                if trade is None and event_direction:
                    # Legacy compatibility: some older rows may not align on
                    # sequence_number, but we still must not cross directions.
                    trade = (
                        Trade.objects.filter(
                            task_type=self.order_service.task_type.value,
                            task_id=self._task_pk,
                            execution_id=self._execution_id,
                            timestamp=event_timestamp,
                            execution_method="open_position",
                            cycle_id__isnull=False,
                        )
                        .filter(direction__iexact=event_direction)
                        .values_list("cycle_id", flat=True)
                        .first()
                    )
                if trade is not None:
                    return str(trade)
        except (TypeError, ValueError):
            pass
        return None

    def handle_open_position(self, event: OpenPositionEvent) -> Position:
        """Open position for execution.

        Args:
            event: Open position event with position details

        Returns:
            Position: Created position

        Raises:
            OrderServiceError: If order execution fails
        """
        direction = Direction(event.direction)
        position, order = self.order_service.open_position(
            instrument=self.instrument,
            units=event.units,
            direction=direction,
            layer_index=event.layer_number,
            merge_with_existing=event.merge_with_existing,
            override_price=event.price if event.price else None,
            tick_timestamp=event.timestamp,
            retracement_count=event.retracement_count,
            planned_exit_price=event.planned_exit_price,
            planned_exit_price_formula=getattr(event, "planned_exit_price_formula", None),
        )

        cycle_id = self._resolve_cycle_id_for_open(event)

        # Persist adverse pips (distance from previous entry) on the position
        adverse = getattr(event, "actual_interval_pips", None)
        if adverse is not None:
            position.adverse_pips = adverse
            position.save(update_fields=["adverse_pips"])

        # Persist stop-loss price on the position
        sl_price = getattr(event, "stop_loss_price", None)
        if sl_price is not None:
            position.stop_loss_price = sl_price
            position.save(update_fields=["stop_loss_price"])

        self._mark_replay_records(position, order)
        order_fill_price = getattr(order, "fill_price", None)
        self._last_open_fill_price = (
            order_fill_price if isinstance(order_fill_price, Decimal) else position.entry_price
        )

        self._cache_position(event.layer_number, position)
        if event.entry_id is not None:
            self._entry_id_to_position_id[event.entry_id] = str(position.id)
        trade = self._record_trade(
            direction=direction,
            units=event.units,
            instrument=position.instrument,
            price=position.entry_price,
            execution_method=str(event.event_type.value),
            timestamp=self._trade_execution_timestamp(
                fallback_timestamp=event.timestamp,
                order=order,
            ),
            layer_index=event.layer_number,
            retracement_count=event.retracement_count,
            oanda_trade_id=position.oanda_trade_id,
            position=position,
            order=order,
            description=getattr(event, "description", ""),
            cycle_id=cycle_id,
            margin_ratio=event.margin_ratio,
        )
        self._mark_replay_records(trade)
        self._record_affected_entities(position=position, order=order, trade=trade)

        # New cycle: back-fill cycle_id = trade's own id.
        if cycle_id is None:
            trade.cycle_id = str(trade.id)
            trade.save(update_fields=["cycle_id"])
            cycle_id = str(trade.id)

        # Store for _dispatch_open_position to include in the binding.
        self._last_open_cycle_id = cycle_id

        # Register mapping so child entries and close events can look up
        # the cycle_id by their root_entry_id or entry_id.
        if event.entry_id is not None:
            self._entry_id_to_cycle_id[event.entry_id] = cycle_id

        logger.info(
            "Open position executed: layer=%s, direction=%s, units=%s, count=%s, position_id=%s",
            event.layer_number,
            direction,
            event.units,
            event.retracement_count,
            position.id,
        )

        lifecycle_logger.info(
            "POSITION_OPENED: %s %s %s units @ %s (layer=%s, retracement=%s, planned_exit=%s)",
            direction.value,
            position.instrument,
            event.units,
            position.entry_price,
            event.layer_number,
            event.retracement_count,
            position.planned_exit_price,
            extra={
                "position_id": str(position.id),
                "lifecycle_event": "OPENED",
                "direction": direction.value,
                "instrument": position.instrument,
                "units": event.units,
                "entry_price": str(position.entry_price),
                "entry_time": str(position.entry_time),
                "layer_index": event.layer_number,
                "retracement_count": event.retracement_count,
                "planned_exit_price": str(position.planned_exit_price)
                if position.planned_exit_price
                else None,
                "planned_exit_price_formula": position.planned_exit_price_formula,
                "oanda_trade_id": position.oanda_trade_id,
                "order_id": str(order.id),
            },
        )

        return position

    def _resolve_cycle_id_for_close(
        self,
        event: ClosePositionEvent,
        position: Position | None = None,
    ) -> str | None:
        """Look up cycle_id for a close trade from the entry being closed."""
        position_cycle_id = self._resolve_cycle_id_for_position(position) if position else None

        eid = getattr(event, "entry_id", None)
        event_cycle_id: str | None = None
        if eid is not None and eid in self._entry_id_to_cycle_id:
            event_cycle_id = self._entry_id_to_cycle_id[eid]

        root_eid = getattr(event, "root_entry_id", None)
        if (
            event_cycle_id is None
            and root_eid is not None
            and root_eid in self._entry_id_to_cycle_id
        ):
            event_cycle_id = self._entry_id_to_cycle_id[root_eid]

        # DB fallback: look up cycle_id from the open/rebuild trade that
        # created this position.  This covers edge cases where the
        # in-memory mapping was lost or overwritten.
        if event_cycle_id is None:
            event_cycle_id = self._resolve_cycle_id_from_db(
                root_eid,
                eid,
                direction=getattr(event, "direction", None),
            )

        if position_cycle_id and event_cycle_id and str(position_cycle_id) != str(event_cycle_id):
            raise CycleResolutionError(
                "ClosePositionEvent cycle mismatch: "
                f"position_id={getattr(position, 'id', None)}, "
                f"position_cycle_id={position_cycle_id}, event_cycle_id={event_cycle_id}, "
                f"entry_id={eid}."
            )

        cycle_id = position_cycle_id or event_cycle_id
        if cycle_id is not None:
            if eid is not None:
                self._entry_id_to_cycle_id[eid] = cycle_id
            if root_eid is not None:
                self._entry_id_to_cycle_id[root_eid] = cycle_id
            return cycle_id

        return None

    def _resolve_cycle_id_for_position(self, position: Position) -> str | None:
        """Look up cycle_id from the Trade that opened a position.

        Protection handlers (shrink, lock, margin) don't carry entry_id
        metadata, so we fall back to the Trade table to find which cycle
        the position belongs to.
        """
        pos_id = str(position.id)
        # Check in-memory cache first
        for eid, cid in self._entry_id_to_cycle_id.items():
            if cid and str(eid) == pos_id:
                return cid

        # DB lookup: find the open_position trade that created this position
        try:
            open_trade = (
                Trade.objects.filter(
                    task_type=self.order_service.task_type.value,
                    task_id=self._task_pk,
                    execution_id=self._execution_id,
                    position_id=position.id,
                    execution_method__in=["open_position", "rebuild_position"],
                    cycle_id__isnull=False,
                )
                .order_by("timestamp", "sequence_number", "created_at")
                .values_list("cycle_id", flat=True)
                .first()
            )
            return str(open_trade) if open_trade else None
        except Exception:
            return None

    def handle_rebuild_position(self, event: RebuildPositionEvent) -> Position:
        """Create a new position for a stop-loss rebuild.

        A rebuild always belongs to an existing cycle — the position being
        rebuilt was previously opened inside that cycle and then closed by
        stop-loss.  If the cycle_id cannot be resolved, something is
        seriously wrong and the task must stop.

        Instead of re-opening the original closed position (which would erase
        its exit_price and hide the stop-loss P&L from DB aggregation), we
        always create a fresh Position record.  The original closed position
        retains its exit data so that ``compute_task_summary`` correctly
        accounts for the stop-loss loss in realized P&L.

        Args:
            event: Rebuild position event with original position reference

        Returns:
            Position: The newly created position

        Raises:
            RuntimeError: If cycle_id cannot be resolved — indicates
                corrupt state that should stop the task.
        """
        # ---- Resolve cycle_id (mandatory for rebuilds) ----
        cycle_id = self._resolve_rebuild_cycle_id(event)
        if cycle_id is None:
            raise CycleResolutionError(
                f"Cannot resolve cycle_id for rebuild: "
                f"entry_id={event.entry_id}, root_entry_id={event.root_entry_id}, "
                f"original_position_id={event.original_position_id}. "
                f"This indicates corrupt strategy state — stopping task."
            )

        # Seed the mapping so handle_open_position and subsequent close
        # events resolve to the correct cycle.
        if event.root_entry_id is not None:
            self._entry_id_to_cycle_id[event.root_entry_id] = cycle_id
        if event.entry_id is not None:
            self._entry_id_to_cycle_id[event.entry_id] = cycle_id

        # ---- Create the position via handle_open_position ----
        open_event = OpenPositionEvent(
            event_type=EventType.OPEN_POSITION,
            timestamp=event.timestamp,
            layer_number=event.layer_number,
            direction=event.direction,
            price=event.price,
            units=event.units,
            retracement_count=event.retracement_count,
            entry_id=event.entry_id,
            strategy_event_type=event.strategy_event_type,
            planned_exit_price=event.planned_exit_price,
            stop_loss_price=event.stop_loss_price,
            description=event.description,
        )
        open_event.root_entry_id = event.root_entry_id
        open_event.parent_entry_id = event.parent_entry_id

        position = self.handle_open_position(open_event)
        position.is_rebuild = True
        position.save(update_fields=["is_rebuild"])

        # ---- Fix trade records ----
        # handle_open_position may have treated this as a new cycle
        # (parent_entry_id is None for R0 rebuilds).  Correct the
        # trade's cycle_id and re-seed the mapping.
        latest_trade = (
            Trade.objects.filter(
                task_type=self.order_service.task_type.value,
                task_id=self._task_pk,
                execution_id=self._execution_id,
                position_id=str(position.id),
            )
            .order_by("-created_at")
            .first()
        )
        if latest_trade:
            needs_save = False
            if str(latest_trade.cycle_id) != cycle_id:
                latest_trade.cycle_id = cycle_id
                needs_save = True
            if not latest_trade.is_rebuild:
                latest_trade.is_rebuild = True
                latest_trade.execution_method = str(event.event_type.value)
                needs_save = True
            if needs_save:
                latest_trade.save(update_fields=["cycle_id", "is_rebuild", "execution_method"])

        # Ensure the mapping is correct after handle_open_position
        # (which may have overwritten it with the trade's own id).
        self._last_open_cycle_id = cycle_id
        if event.entry_id is not None:
            self._entry_id_to_cycle_id[event.entry_id] = cycle_id
        if event.root_entry_id is not None:
            self._entry_id_to_cycle_id[event.root_entry_id] = cycle_id

        logger.info(
            "Rebuild position executed: layer=%s, direction=%s, units=%s, position_id=%s, cycle_id=%s",
            event.layer_number,
            event.direction,
            event.units,
            position.id,
            cycle_id,
        )

        lifecycle_logger.info(
            "POSITION_REBUILT: %s %s %s units @ %s (layer=%s, retracement=%s)",
            event.direction,
            position.instrument,
            event.units,
            event.price,
            event.layer_number,
            event.retracement_count,
            extra={
                "position_id": str(position.id),
                "lifecycle_event": "REBUILT",
                "direction": event.direction,
                "instrument": position.instrument,
                "units": event.units,
                "entry_price": str(event.price),
                "layer_index": event.layer_number,
                "retracement_count": event.retracement_count,
                "original_position_id": event.original_position_id,
                "cycle_id": cycle_id,
            },
        )

        return position

    def _resolve_rebuild_cycle_id(self, event: RebuildPositionEvent) -> str | None:
        """Resolve cycle_id for a rebuild event.

        Tries, in order:
        1. In-memory mapping via root_entry_id or entry_id.
        2. DB lookup via root_entry_id / parent_entry_id in TradingEvent.
        3. DB lookup via original_position_id in Trade.
        """
        root_eid = getattr(event, "root_entry_id", None)
        entry_eid = getattr(event, "entry_id", None)
        parent_eid = getattr(event, "parent_entry_id", None)

        # 1. In-memory mapping
        for eid in (root_eid, entry_eid, parent_eid):
            if eid is not None and eid in self._entry_id_to_cycle_id:
                return self._entry_id_to_cycle_id[eid]

        # 2. DB fallback via TradingEvent
        cycle_id = self._resolve_cycle_id_from_db(
            root_eid,
            parent_eid,
            direction=getattr(event, "direction", None),
        )
        if cycle_id is not None:
            return cycle_id

        # 3. DB fallback via original position's Trade record
        if event.original_position_id:
            existing = (
                Trade.objects.filter(
                    task_type=self.order_service.task_type.value,
                    task_id=self._task_pk,
                    execution_id=self._execution_id,
                    position_id=event.original_position_id,
                    cycle_id__isnull=False,
                )
                .values_list("cycle_id", flat=True)
                .first()
            )
            if existing is not None:
                return str(existing)

        return None

    def handle_close_position(self, event: ClosePositionEvent) -> tuple[Decimal, Decimal]:
        """Close the exact position referenced by a close event.

        ClosePositionEvent must identify one open position directly by
        ``position_id`` or by a same-batch ``entry_id`` binding.  It must not
        spill remaining units into another position.

        Args:
            event: Close position event with close details

        Returns:
            tuple[Decimal, Decimal]: realized PnL in account and quote currency.

        Raises:
            OrderServiceError: If order execution fails
        """
        override_price = event.exit_price if event.exit_price else None
        total_requested = event.units if event.units > 0 else None
        remaining = total_requested
        realized_delta_total = Decimal("0")
        realized_delta_quote_total = Decimal("0")
        latest_execution_price: Decimal | None = None
        total_closed_units = 0
        self._last_close_execution_price = None
        self._last_close_executed_units = 0

        while True:
            position = self._find_close_position_target(event)
            if not position:
                raise ClosePositionResolutionError(
                    "ClosePositionEvent did not resolve to an open position: "
                    f"entry_id={getattr(event, 'entry_id', None)}, "
                    f"position_id={event.position_id}, layer={event.layer_number}, "
                    f"direction={event.direction}."
                )

            pos_units = abs(position.units)
            if remaining is not None and remaining > pos_units:
                raise ClosePositionResolutionError(
                    "ClosePositionEvent requested more units than its exact target holds: "
                    f"position_id={position.id}, requested_units={remaining}, "
                    f"position_units={pos_units}."
                )

            if remaining is None:
                # Full close of this single position
                units_to_close = None
                closed_units = pos_units
            else:
                units_to_close = min(remaining, pos_units)
                closed_units = units_to_close

            closed_position, realized_delta, close_order = self.order_service.close_position(
                position=position,
                units=units_to_close,
                override_price=override_price,
                tick_timestamp=event.timestamp,
                force_instrument_close=event.force_instrument_close,
            )
            realized_delta_total += realized_delta
            total_closed_units += int(closed_units)

            # Compute quote-currency PnL from the actual close fill.  Partial
            # closes leave Position.exit_price empty because the net position
            # remains open, so the order fill is the authoritative exit price.
            close_fill_price = self._close_fill_price(
                close_order=close_order,
                closed_position=closed_position,
                override_price=override_price,
            )
            exit_px = close_fill_price
            latest_execution_price = exit_px
            entry_px = Decimal(str(position.entry_price))
            quote_delta = exit_px - entry_px
            if position.direction == "short":
                quote_delta = -quote_delta
            realized_delta_quote_total += quote_delta * Decimal(str(closed_units))

            trade = self._record_trade(
                direction=Direction(position.direction),
                units=closed_units,
                instrument=position.instrument,
                price=close_fill_price,
                execution_method=(
                    event.close_reason
                    if event.close_reason in self._PROTECTION_CLOSE_REASONS
                    else str(event.event_type.value)
                ),
                timestamp=self._trade_execution_timestamp(
                    fallback_timestamp=event.timestamp,
                    order=close_order,
                ),
                layer_index=position.layer_index,
                retracement_count=position.retracement_count,
                oanda_trade_id=position.oanda_trade_id,
                position=position,
                order=close_order,
                description=getattr(event, "description", ""),
                cycle_id=self._resolve_cycle_id_for_close(event, position),
                margin_ratio=event.margin_ratio,
                is_rebuild=bool(getattr(position, "is_rebuild", False)),
            )
            self._mark_replay_records(closed_position, close_order, trade)
            self._record_affected_entities(
                position=closed_position,
                order=close_order,
                trade=trade,
            )

            self._prune_closed_position(event.layer_number, closed_position)

            if not closed_position.is_open:
                logger.info(
                    "Close position executed (full close): layer=%s, pnl=%s, position_id=%s",
                    event.layer_number,
                    realized_delta,
                    closed_position.id,
                )
                lifecycle_logger.info(
                    "POSITION_CLOSED: %s %s (full close) exit @ %s, pnl=%s (layer=%s)",
                    closed_position.direction,
                    closed_position.instrument,
                    close_fill_price,
                    realized_delta,
                    event.layer_number,
                    extra={
                        "position_id": str(closed_position.id),
                        "lifecycle_event": "CLOSED",
                        "close_type": "full",
                        "direction": closed_position.direction,
                        "instrument": closed_position.instrument,
                        "units_closed": closed_units,
                        "entry_price": str(closed_position.entry_price),
                        "exit_price": str(close_fill_price),
                        "entry_time": str(closed_position.entry_time),
                        "exit_time": str(closed_position.exit_time),
                        "realized_pnl": str(realized_delta),
                        "layer_index": event.layer_number,
                        "retracement_count": event.retracement_count,
                        "close_reason": (event.close_reason or str(event.event_type.value)),
                        "description": getattr(event, "description", ""),
                        "oanda_trade_id": closed_position.oanda_trade_id,
                        "order_id": str(close_order.id) if close_order else None,
                    },
                )
            else:
                logger.info(
                    "Close position executed (partial close): layer=%s, units_closed=%s, remaining=%s, position_id=%s",
                    event.layer_number,
                    units_to_close,
                    abs(closed_position.units),
                    closed_position.id,
                )
                lifecycle_logger.info(
                    "POSITION_PARTIAL_CLOSE: %s %s, %s units closed, %s remaining (layer=%s, pnl=%s)",
                    closed_position.direction,
                    closed_position.instrument,
                    units_to_close,
                    abs(closed_position.units),
                    event.layer_number,
                    realized_delta,
                    extra={
                        "position_id": str(closed_position.id),
                        "lifecycle_event": "PARTIAL_CLOSE",
                        "close_type": "partial",
                        "direction": closed_position.direction,
                        "instrument": closed_position.instrument,
                        "units_closed": units_to_close,
                        "units_remaining": abs(closed_position.units),
                        "entry_price": str(closed_position.entry_price),
                        "exit_price": str(close_fill_price),
                        "realized_pnl": str(realized_delta),
                        "layer_index": event.layer_number,
                        "retracement_count": event.retracement_count,
                        "close_reason": (event.close_reason or str(event.event_type.value)),
                        "description": getattr(event, "description", ""),
                        "oanda_trade_id": closed_position.oanda_trade_id,
                        "order_id": str(close_order.id) if close_order else None,
                    },
                )

            # If no specific amount was requested, we only close one position
            if remaining is None:
                break

            remaining -= closed_units
            if remaining <= 0:
                break

        self._last_close_execution_price = latest_execution_price
        self._last_close_executed_units = total_closed_units
        return realized_delta_total, realized_delta_quote_total

    @staticmethod
    def _close_fill_price(
        *,
        close_order: Order | None,
        closed_position: Position,
        override_price: Decimal | None,
    ) -> Decimal:
        order_fill_price = getattr(close_order, "fill_price", None)
        if isinstance(order_fill_price, Decimal):
            return order_fill_price
        if closed_position.exit_price is not None:
            return Decimal(str(closed_position.exit_price))
        if override_price is not None:
            return override_price
        return Decimal("0")

    @staticmethod
    def _new_affected_refs() -> dict[str, set[str]]:
        return {
            "position_ids": set(),
            "order_ids": set(),
            "trade_ids": set(),
            "broker_order_ids": set(),
            "oanda_trade_ids": set(),
        }

    def _record_affected_entities(
        self,
        *,
        position: Position | None = None,
        order: Order | None = None,
        trade: Trade | None = None,
    ) -> None:
        """Track entities touched by the current event execution."""
        if position is not None:
            self._affected_refs["position_ids"].add(str(position.id))
            if position.oanda_trade_id:
                self._affected_refs["oanda_trade_ids"].add(str(position.oanda_trade_id))
        if order is not None:
            self._affected_refs["order_ids"].add(str(order.id))
            if order.broker_order_id:
                self._affected_refs["broker_order_ids"].add(str(order.broker_order_id))
            if order.oanda_trade_id:
                self._affected_refs["oanda_trade_ids"].add(str(order.oanda_trade_id))
            order_id = str(order.id)
            response_seconds = getattr(order, "oanda_response_seconds", None)
            if (
                response_seconds is not None
                and order_id not in self._current_oanda_response_order_ids
            ):
                try:
                    parsed_response_seconds = Decimal(str(response_seconds))
                except (InvalidOperation, TypeError, ValueError):
                    parsed_response_seconds = None
                if parsed_response_seconds is not None:
                    self._current_oanda_response_seconds.append(parsed_response_seconds)
                    self._current_oanda_response_order_ids.add(order_id)
        if trade is not None:
            self._affected_refs["trade_ids"].add(str(trade.id))
            if trade.oanda_trade_id:
                self._affected_refs["oanda_trade_ids"].add(str(trade.oanda_trade_id))

    def _snapshot_affected_refs(self) -> dict[str, tuple[str, ...]]:
        """Return a stable snapshot of affected entity IDs."""
        return {key: tuple(sorted(values)) for key, values in self._affected_refs.items()}

    def _mark_replay_records(self, *records: Position | Order | Trade | None) -> None:
        """Mark persisted records as touched by replay when applicable."""
        if not self._current_replay_mode:
            return

        replayed_at = dj_timezone.now()
        for record in records:
            if record is None:
                continue
            type(record).objects.filter(pk=record.pk).update(replayed_at=replayed_at)
            record.replayed_at = replayed_at

    def handle_volatility_lock(self, event: VolatilityLockEvent) -> tuple[Decimal, Decimal]:
        """Close all open positions due to volatility.

        Args:
            event: Volatility lock event

        Returns:
            tuple[Decimal, Decimal]: (realized_pnl_delta in account currency,
                realized_pnl_delta in quote currency)

        Raises:
            OrderServiceError: If order execution fails
        """
        closed_positions: list[Position] = []
        realized_delta_total = Decimal("0")
        realized_delta_quote_total = Decimal("0")

        logger.warning(
            "Volatility lock triggered: %s (closing %s positions)",
            event.reason,
            len(self.position_map),
        )

        for position in self._ordered_positions_for_margin_close():
            if not position.is_open:
                continue
            try:
                closed, realized_delta, close_order = self.order_service.close_position(
                    position,
                    tick_timestamp=event.timestamp,
                )
                closed_positions.append(closed)
                self._prune_closed_position(position.layer_index or 0, closed)
                realized_delta_total += realized_delta

                # Quote-currency PnL
                exit_px = closed.exit_price or Decimal("0")
                entry_px = Decimal(str(position.entry_price))
                q_delta = exit_px - entry_px
                if position.direction == "short":
                    q_delta = -q_delta
                realized_delta_quote_total += q_delta * Decimal(str(abs(position.units)))
                self._record_trade(
                    direction=Direction(position.direction),
                    units=abs(position.units),
                    instrument=position.instrument,
                    price=Decimal(str(closed.exit_price or position.entry_price)),
                    execution_method=str(event.event_type.value),
                    timestamp=self._trade_execution_timestamp(
                        fallback_timestamp=event.timestamp,
                        order=close_order,
                    ),
                    layer_index=position.layer_index,
                    oanda_trade_id=position.oanda_trade_id,
                    position=position,
                    order=close_order,
                    description=f"[PROTECTION] Volatility lock: close all positions ({event.reason})",
                    cycle_id=self._resolve_cycle_id_for_position(position),
                    margin_ratio=event.margin_ratio,
                )
                logger.info(
                    "Closed position due to volatility: layer=%s, position_id=%s, pnl=%s",
                    position.layer_index,
                    closed.id,
                    realized_delta,
                )
                lifecycle_logger.info(
                    "POSITION_CLOSED: %s %s (volatility lock) exit @ %s, pnl=%s (reason=%s)",
                    position.direction,
                    position.instrument,
                    closed.exit_price,
                    realized_delta,
                    event.reason,
                    extra={
                        "position_id": str(closed.id),
                        "lifecycle_event": "CLOSED",
                        "close_type": "full",
                        "direction": position.direction,
                        "instrument": position.instrument,
                        "units_closed": abs(position.units),
                        "entry_price": str(position.entry_price),
                        "exit_price": str(closed.exit_price),
                        "entry_time": str(position.entry_time),
                        "exit_time": str(closed.exit_time),
                        "realized_pnl": str(realized_delta),
                        "layer_index": position.layer_index,
                        "close_reason": "volatility_lock",
                        "description": f"Volatility lock: {event.reason}",
                        "oanda_trade_id": position.oanda_trade_id,
                        "order_id": str(close_order.id) if close_order else None,
                    },
                )
            except OrderServiceError as e:
                logger.error(
                    "Failed to process position %s during volatility lock: %s",
                    position.id,
                    e,
                )
                # Continue processing other positions

        self.position_map.clear()
        self.layer_position_ids.clear()
        self._position_cache.clear()

        logger.info("Volatility lock complete: closed %s positions", len(closed_positions))

        return realized_delta_total, realized_delta_quote_total

    def handle_volatility_hedge_neutralize(self, event: VolatilityHedgeNeutralizeEvent) -> Decimal:
        """Open hedge positions to neutralize net exposure during volatility spike.

        For each instruction in the event, opens an opposite-direction position
        that mirrors an existing open position.  No positions are closed, so
        realized PnL is always zero.

        Args:
            event: Hedge neutralize event with instructions.

        Returns:
            Decimal: Always ``Decimal("0")`` — no realized PnL.
        """
        logger.warning(
            "Volatility hedge neutralize triggered: %s (hedging %d positions)",
            event.reason,
            len(event.hedge_instructions),
        )

        for instr in event.hedge_instructions:
            direction_str = str(instr.get("direction", "long")).upper()
            direction = Direction.LONG if direction_str == "LONG" else Direction.SHORT
            units = abs(int(instr.get("units", 0)))
            layer_index = int(instr.get("layer_index", 0))
            if units <= 0:
                continue
            try:
                hedged, _order = self.order_service.open_position(
                    instrument=self.instrument,
                    units=units,
                    direction=direction,
                    layer_index=layer_index,
                    merge_with_existing=False,
                    tick_timestamp=event.timestamp,
                )
                self._cache_position(layer_index, hedged)
                logger.info(
                    "Opened hedge-neutralize position: layer=%s, direction=%s, "
                    "units=%s, hedge_id=%s, source_entry=%s",
                    layer_index,
                    direction_str,
                    units,
                    hedged.id,
                    instr.get("source_entry_id"),
                )
                lifecycle_logger.info(
                    "POSITION_OPENED: %s %s %s units @ %s (hedge neutralize, layer=%s)",
                    direction_str,
                    self.instrument,
                    units,
                    hedged.entry_price,
                    layer_index,
                    extra={
                        "position_id": str(hedged.id),
                        "lifecycle_event": "OPENED",
                        "direction": direction_str,
                        "instrument": self.instrument,
                        "units": units,
                        "entry_price": str(hedged.entry_price),
                        "entry_time": str(hedged.entry_time),
                        "layer_index": layer_index,
                        "open_reason": "volatility_hedge_neutralize",
                        "description": f"Hedge neutralize: {event.reason}",
                        "oanda_trade_id": hedged.oanda_trade_id,
                        "order_id": str(_order.id),
                    },
                )
            except OrderServiceError as e:
                logger.error(
                    "Failed to open hedge-neutralize position for source_entry %s: %s",
                    instr.get("source_entry_id"),
                    e,
                )

        logger.info(
            "Volatility hedge neutralize complete: %d hedge positions opened",
            len(event.hedge_instructions),
        )
        return Decimal("0")

    def handle_margin_protection(self, event: MarginProtectionEvent) -> tuple[Decimal, Decimal]:
        """Close all open positions due to margin protection.

        Args:
            event: Margin protection event

        Returns:
            tuple[Decimal, Decimal]: (realized_pnl_delta in account currency,
                realized_pnl_delta in quote currency)

        Raises:
            OrderServiceError: If order execution fails
        """
        closed_positions: list[Position] = []
        realized_delta_total = Decimal("0")
        realized_delta_quote_total = Decimal("0")

        logger.warning(
            "Margin protection triggered: %s (closing %s positions)",
            event.reason,
            len(self.position_map),
        )

        remaining_units = (
            int(event.units_to_close)
            if event.units_to_close and int(event.units_to_close) > 0
            else None
        )
        limit = (
            event.positions_closed
            if event.positions_closed and event.positions_closed > 0
            else None
        )
        touched_positions = 0
        for position in self._ordered_positions_for_margin_close():
            if remaining_units is not None and remaining_units <= 0:
                break
            if limit is not None and touched_positions >= limit:
                break
            if not position.is_open:
                continue
            try:
                units_to_close = None
                if remaining_units is not None:
                    units_to_close = min(abs(position.units), remaining_units)
                closed, realized_delta, close_order = self.order_service.close_position(
                    position,
                    units=units_to_close,
                    tick_timestamp=event.timestamp,
                )
                closed_positions.append(closed)
                self._prune_closed_position(position.layer_index or 0, closed)
                realized_delta_total += realized_delta

                # Quote-currency PnL
                exit_px = closed.exit_price or Decimal("0")
                entry_px = Decimal(str(position.entry_price))
                closed_units = units_to_close or abs(position.units)
                q_delta = exit_px - entry_px
                if position.direction == "short":
                    q_delta = -q_delta
                realized_delta_quote_total += q_delta * Decimal(str(closed_units))
                self._record_trade(
                    direction=Direction(position.direction),
                    units=units_to_close or abs(position.units),
                    instrument=position.instrument,
                    price=Decimal(str(closed.exit_price or position.entry_price)),
                    execution_method=str(event.event_type.value),
                    timestamp=self._trade_execution_timestamp(
                        fallback_timestamp=event.timestamp,
                        order=close_order,
                    ),
                    layer_index=position.layer_index,
                    oanda_trade_id=position.oanda_trade_id,
                    position=position,
                    order=close_order,
                    description=f"[PROTECTION] Margin protection: forced close ({event.reason})",
                    cycle_id=self._resolve_cycle_id_for_position(position),
                    margin_ratio=event.margin_ratio,
                )
                touched_positions += 1
                if remaining_units is not None:
                    remaining_units -= units_to_close or 0
                logger.info(
                    "Closed position due to margin protection: layer=%s, position_id=%s, "
                    "units_requested=%s, remaining_units=%s, realized_delta=%s",
                    position.layer_index,
                    closed.id,
                    units_to_close,
                    remaining_units,
                    realized_delta,
                )
                lifecycle_logger.info(
                    "POSITION_CLOSED: %s %s (margin protection) exit @ %s, pnl=%s (reason=%s)",
                    position.direction,
                    position.instrument,
                    closed.exit_price,
                    realized_delta,
                    event.reason,
                    extra={
                        "position_id": str(closed.id),
                        "lifecycle_event": "CLOSED",
                        "close_type": "full" if not closed.is_open else "partial",
                        "direction": position.direction,
                        "instrument": position.instrument,
                        "units_closed": units_to_close or abs(position.units),
                        "entry_price": str(position.entry_price),
                        "exit_price": str(closed.exit_price),
                        "entry_time": str(position.entry_time),
                        "exit_time": str(closed.exit_time) if closed.exit_time else None,
                        "realized_pnl": str(realized_delta),
                        "layer_index": position.layer_index,
                        "close_reason": "margin_protection",
                        "description": f"Margin protection: {event.reason}",
                        "oanda_trade_id": position.oanda_trade_id,
                        "order_id": str(close_order.id) if close_order else None,
                    },
                )
            except OrderServiceError as e:
                logger.error(
                    "Failed to close position %s during margin protection: %s",
                    position.id,
                    e,
                )
                # Continue closing other positions

        # Remove stale/closed ids from cache structures
        stale_layers: list[int] = []
        for layer_number, ids in self.layer_position_ids.items():
            open_ids = [pid for pid in ids if self._get_open_position_by_id(pid)]
            self.layer_position_ids[layer_number] = open_ids
            if not open_ids:
                stale_layers.append(layer_number)
        for layer_number in stale_layers:
            self.layer_position_ids.pop(layer_number, None)
            self.position_map.pop(layer_number, None)

        logger.info("Margin protection complete: closed %s positions", len(closed_positions))

        return realized_delta_total, realized_delta_quote_total

    def get_open_positions(self) -> list[Position]:
        """Get all currently tracked open positions.

        Returns:
            list[Position]: List of open positions
        """
        return [p for p in self.position_map.values() if p.is_open]

    def clear_positions(self) -> None:
        """Clear the position map.

        Useful for cleanup or reset operations.
        """
        self.position_map.clear()
        self.layer_position_ids.clear()
        self._position_cache.clear()
        self._entry_id_to_cycle_id.clear()
        self._entry_id_to_position_id.clear()
        logger.debug("Position map cleared")
