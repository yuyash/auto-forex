"""In-memory execution adapters for lightweight backtests."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from types import MethodType
from typing import Any

from django.utils import timezone

from apps.market.services.oanda import (
    MarketOrder as OandaMarketOrder,
    MarketOrderRequest,
    OandaAPIError,
    OpenTrade,
    OrderDirection,
    OrderState,
    OrderType as OandaOrderType,
    Position as OandaPosition,
)
from apps.trading.enums import Direction, TaskType
from apps.trading.events import (
    ClosePositionEvent,
    MarginProtectionEvent,
    OpenPositionEvent,
    RebuildPositionEvent,
    VolatilityLockEvent,
)
from apps.trading.events.handler import CycleResolutionError, EventHandler
from apps.trading.models import Order, Position, Trade
from apps.trading.models.orders import OrderStatus, OrderType
from apps.trading.order import OrderService
from apps.trading.utils import Instrument


def _disable_persistence(instance: Any) -> Any:
    """Make a Django model instance behave as a transient value object."""

    def _noop_save(self, *args, **kwargs) -> None:
        return None

    def _noop_refresh_from_db(self, *args, **kwargs) -> None:
        return None

    instance.save = MethodType(_noop_save, instance)
    instance.refresh_from_db = MethodType(_noop_refresh_from_db, instance)
    instance._in_memory = True
    return instance


class InMemoryBrokerGateway:
    """Minimal broker gateway for in-memory backtests with strategy-provided prices."""

    def __init__(self) -> None:
        self.order_counter = 0

    def create_market_order(
        self,
        request: MarketOrderRequest,
        *,
        override_price: Decimal | None = None,
    ) -> OandaMarketOrder:
        self.order_counter += 1
        direction = OrderDirection.LONG if request.units >= 0 else OrderDirection.SHORT
        now = datetime.now(UTC)
        if override_price is None:
            raise OandaAPIError("In-memory market order requires an explicit override_price")
        return OandaMarketOrder(
            order_id=f"MEM-{self.order_counter}",
            instrument=str(request.instrument),
            order_type=OandaOrderType.MARKET,
            direction=direction,
            units=abs(request.units),
            price=override_price,
            state=OrderState.FILLED,
            time_in_force="FOK",
            create_time=now,
            fill_time=now,
            trade_id=f"MEM-TRADE-{self.order_counter}",
        )

    def close_trade(
        self,
        *,
        trade: OpenTrade,
        units: Decimal | None = None,
    ) -> OandaMarketOrder:
        self.order_counter += 1
        now = datetime.now(UTC)
        return OandaMarketOrder(
            order_id=f"MEM-CLOSE-{self.order_counter}",
            instrument=trade.instrument,
            order_type=OandaOrderType.MARKET,
            direction=trade.direction,
            units=trade.units if units is None else min(units, trade.units),
            price=trade.entry_price,
            state=OrderState.FILLED,
            time_in_force="FOK",
            create_time=now,
            fill_time=now,
            trade_id=trade.trade_id,
        )

    def close_position(
        self,
        *,
        position: OandaPosition,
        units: Decimal | None = None,
        override_price: Decimal | None = None,
    ) -> OandaMarketOrder:
        self.order_counter += 1
        now = datetime.now(UTC)
        if override_price is None:
            raise OandaAPIError("In-memory position close requires an explicit override_price")
        return OandaMarketOrder(
            order_id=f"MEM-CLOSE-{self.order_counter}",
            instrument=position.instrument,
            order_type=OandaOrderType.MARKET,
            direction=position.direction,
            units=position.units if units is None else min(units, position.units),
            price=override_price,
            state=OrderState.FILLED,
            time_in_force="FOK",
            create_time=now,
            fill_time=now,
        )


class InMemoryOrderRepository:
    """Create transient order records without retaining order history."""

    def __init__(
        self,
        *,
        task_type: TaskType,
        task_id,
        execution_id,
        dry_run: bool,
    ) -> None:
        self.task_type = task_type
        self.task_id = task_id
        self.execution_id = execution_id
        self.dry_run = dry_run

    def create_filled(
        self,
        *,
        instrument: str,
        order_type: OrderType,
        direction: Direction | None,
        units: int,
        oanda_order: OandaMarketOrder,
        filled_at: datetime,
        requested_price: Decimal | None = None,
        stop_loss: Decimal | None = None,
        oanda_trade_id: str | None = None,
        position: Position | None = None,
        layer_index: int | None = None,
        retracement_count: int | None = None,
        oanda_response_seconds: Decimal | None = None,
    ) -> Order:
        order = Order(
            task_type=self.task_type.value,
            task_id=self.task_id,
            execution_id=self.execution_id,
            broker_order_id=oanda_order.order_id,
            oanda_trade_id=oanda_trade_id,
            instrument=instrument,
            order_type=order_type,
            direction=direction.value if isinstance(direction, Direction) else direction,
            units=units,
            requested_price=requested_price,
            fill_price=oanda_order.price,
            status=OrderStatus.FILLED,
            filled_at=filled_at,
            oanda_response_seconds=oanda_response_seconds,
            stop_loss=stop_loss,
            is_dry_run=self.dry_run,
            position=position,
            layer_index=layer_index,
            retracement_count=retracement_count,
        )
        now = timezone.now()
        order.submitted_at = now
        order.created_at = now
        order.updated_at = now
        return _disable_persistence(order)

    def create_rejected_market(
        self,
        *,
        instrument: str,
        direction: Direction | None,
        units: int,
        public_error_message: str,
        requested_price: Decimal | None = None,
        stop_loss: Decimal | None = None,
        oanda_trade_id: str | None = None,
        position: Position | None = None,
        oanda_response_seconds: Decimal | None = None,
    ) -> Order:
        order = Order(
            task_type=self.task_type.value,
            task_id=self.task_id,
            execution_id=self.execution_id,
            instrument=instrument,
            order_type=OrderType.MARKET,
            direction=direction.value if isinstance(direction, Direction) else direction,
            units=units,
            requested_price=requested_price,
            stop_loss=stop_loss,
            oanda_trade_id=oanda_trade_id,
            oanda_response_seconds=oanda_response_seconds,
            status=OrderStatus.REJECTED,
            error_message=public_error_message,
            is_dry_run=self.dry_run,
            position=position,
        )
        now = timezone.now()
        order.submitted_at = now
        order.created_at = now
        order.updated_at = now
        return _disable_persistence(order)

    def history(self, *, instrument: str | None = None, limit: int = 100) -> list[Order]:
        _ = instrument, limit
        return []


class InMemoryPositionRepository:
    """Keep only currently open positions for one in-memory execution."""

    def __init__(
        self,
        *,
        task_type: TaskType,
        task_id,
        execution_id,
    ) -> None:
        self.task_type = task_type
        self.task_id = task_id
        self.execution_id = execution_id
        self._open_positions: dict[str, Position] = {}

    def create_or_update(
        self,
        *,
        instrument: str,
        direction: Direction,
        units: int,
        entry_price: Decimal,
        entry_time: datetime,
        layer_index: int | None = None,
        merge_with_existing: bool = True,
        oanda_trade_id: str | None = None,
        retracement_count: int | None = None,
        planned_exit_price: Decimal | None = None,
        planned_exit_price_formula: str | None = None,
    ) -> Position:
        if merge_with_existing:
            existing = self.latest_open_position(instrument=instrument, direction=direction)
            if existing is not None:
                return self._merge_position(
                    position=existing,
                    units=units,
                    entry_price=entry_price,
                    layer_index=layer_index,
                    oanda_trade_id=oanda_trade_id,
                    retracement_count=retracement_count,
                    planned_exit_price=planned_exit_price,
                    planned_exit_price_formula=planned_exit_price_formula,
                )
        position = Position(
            task_type=self.task_type.value,
            task_id=self.task_id,
            execution_id=self.execution_id,
            instrument=instrument,
            direction=direction.value if isinstance(direction, Direction) else str(direction),
            units=units,
            entry_price=entry_price,
            entry_time=entry_time,
            is_open=True,
            unrealized_pnl_currency=Instrument(instrument).quote_currency,
            layer_index=layer_index,
            oanda_trade_id=oanda_trade_id,
            retracement_count=retracement_count,
            planned_exit_price=planned_exit_price,
            planned_exit_price_formula=planned_exit_price_formula,
        )
        now = timezone.now()
        position.created_at = now
        position.updated_at = now
        _disable_persistence(position)
        self._open_positions[str(position.id)] = position
        return position

    def latest_open_position(self, *, instrument: str, direction: Direction) -> Position | None:
        direction_value = direction.value if isinstance(direction, Direction) else str(direction)
        matches = [
            position
            for position in self._open_positions.values()
            if position.instrument == instrument
            and position.direction == direction_value
            and position.is_open
        ]
        if not matches:
            return None
        return max(matches, key=lambda position: position.entry_time)

    def open_positions(self, *, instrument: str | None = None) -> list[Position]:
        positions = [position for position in self._open_positions.values() if position.is_open]
        if instrument:
            positions = [position for position in positions if position.instrument == instrument]
        return sorted(positions, key=lambda position: position.entry_time, reverse=True)

    def prune_closed_positions(self) -> None:
        """Drop closed positions so completed cycles do not accumulate in memory."""
        self._open_positions = {
            position_id: position
            for position_id, position in self._open_positions.items()
            if position.is_open
        }

    def _merge_position(
        self,
        *,
        position: Position,
        units: int,
        entry_price: Decimal,
        layer_index: int | None,
        oanda_trade_id: str | None,
        retracement_count: int | None,
        planned_exit_price: Decimal | None,
        planned_exit_price_formula: str | None,
    ) -> Position:
        total_units = position.units + units
        new_avg_price = (
            (position.entry_price * position.units) + (entry_price * units)
        ) / total_units
        position.units = total_units
        position.entry_price = new_avg_price
        if layer_index is not None:
            position.layer_index = layer_index
        if oanda_trade_id is not None:
            position.oanda_trade_id = oanda_trade_id
        if retracement_count is not None:
            position.retracement_count = retracement_count
        if planned_exit_price is not None:
            position.planned_exit_price = planned_exit_price
        if planned_exit_price_formula is not None:
            position.planned_exit_price_formula = planned_exit_price_formula
        position.updated_at = timezone.now()
        return position


class InMemoryOrderService(OrderService):
    """Order service that simulates broker execution without DB order rows."""

    in_memory_mode = True

    def __init__(self, *, account: Any | None, task, dry_run: bool = True) -> None:
        super().__init__(account=account, task=task, dry_run=dry_run)
        self.broker_gateway = InMemoryBrokerGateway()
        self.oanda_service = self.broker_gateway
        self.order_repository = InMemoryOrderRepository(
            task_type=self.task_type,
            task_id=task.id,
            execution_id=self.execution_id,
            dry_run=dry_run,
        )
        self.position_repository = InMemoryPositionRepository(
            task_type=self.task_type,
            task_id=task.id,
            execution_id=self.execution_id,
        )

    def close_position(self, *args, **kwargs):
        result = super().close_position(*args, **kwargs)
        if isinstance(self.position_repository, InMemoryPositionRepository):
            self.position_repository.prune_closed_positions()
        return result


class InMemoryEventHandler(EventHandler):
    """Event handler that emits transient trades and prunes completed cycles."""

    def __init__(self, order_service: OrderService, instrument: str):
        super().__init__(order_service, instrument)
        self._position_id_to_cycle_id: dict[str, str] = {}
        self._cycle_id_to_position_ids: dict[str, set[str]] = defaultdict(set)
        self._cycle_id_to_entry_ids: dict[str, set[int]] = defaultdict(set)
        self._pending_rebuild_position_ids: dict[str, str] = {}
        self._last_recorded_trade: Trade | None = None

    def _resolve_cycle_id_from_db(
        self,
        root_eid: int | None,
        parent_eid: int | None,
        *,
        direction: str | None = None,
    ) -> str | None:
        _ = root_eid, parent_eid, direction
        return None

    def _resolve_cycle_id_for_position(self, position: Position) -> str | None:
        return self._position_id_to_cycle_id.get(str(position.id)) or getattr(
            position, "_cycle_id", None
        )

    def _ordered_positions_for_margin_close(self) -> list[Position]:
        return sorted(
            self.order_service.get_open_positions(instrument=self.instrument),
            key=lambda position: (
                position.layer_index or 0,
                position.entry_time,
                getattr(position, "created_at", position.entry_time),
            ),
        )

    def _record_trade(self, **kwargs) -> Trade:
        direction = kwargs.get("direction")
        direction_value = direction.value if isinstance(direction, Direction) else direction
        trade = Trade(
            task_type=self.order_service.task_type.value,
            task_id=self._task_pk,
            execution_id=self._execution_id,
            timestamp=kwargs["timestamp"],
            direction=direction_value,
            units=kwargs["units"],
            instrument=kwargs["instrument"],
            price=kwargs["price"],
            price_currency=Instrument(kwargs["instrument"]).quote_currency,
            execution_method=kwargs["execution_method"],
            layer_index=kwargs.get("layer_index"),
            retracement_count=kwargs.get("retracement_count"),
            oanda_trade_id=kwargs.get("oanda_trade_id"),
            position=kwargs.get("position"),
            order=kwargs.get("order"),
            description=kwargs.get("description", ""),
            cycle_id=kwargs.get("cycle_id"),
            sequence_number=self._current_sequence_number,
            margin_ratio=kwargs.get("margin_ratio"),
            is_rebuild=kwargs.get("is_rebuild", False),
        )
        now = timezone.now()
        trade.created_at = now
        trade.updated_at = now
        _disable_persistence(trade)
        self._last_recorded_trade = trade
        return trade

    def handle_open_position(self, event: OpenPositionEvent) -> Position:
        position = super().handle_open_position(event)
        cycle_id = getattr(self, "_last_open_cycle_id", None)
        if cycle_id:
            self._bind_position_to_cycle(position=position, cycle_id=cycle_id, event=event)
        return position

    def handle_rebuild_position(self, event: RebuildPositionEvent) -> Position:
        cycle_id = self._resolve_rebuild_cycle_id(event)
        if cycle_id is None:
            raise CycleResolutionError(
                f"Cannot resolve cycle_id for rebuild: "
                f"entry_id={event.entry_id}, root_entry_id={event.root_entry_id}, "
                f"original_position_id={event.original_position_id}. "
                f"This indicates corrupt strategy state — stopping task."
            )

        if event.root_entry_id is not None:
            self._entry_id_to_cycle_id[event.root_entry_id] = cycle_id
        if event.entry_id is not None:
            self._entry_id_to_cycle_id[event.entry_id] = cycle_id

        position = super().handle_rebuild_position(event)
        latest_trade = self._last_recorded_trade
        if latest_trade is not None:
            latest_trade.cycle_id = cycle_id
            latest_trade.is_rebuild = True
            latest_trade.execution_method = str(event.event_type.value)

        self._last_open_cycle_id = cycle_id
        self._bind_position_to_cycle(position=position, cycle_id=cycle_id, event=event)
        if event.original_position_id:
            self._pending_rebuild_position_ids.pop(str(event.original_position_id), None)
        return position

    def handle_close_position(self, event: ClosePositionEvent) -> tuple[Decimal, Decimal]:
        result = super().handle_close_position(event)
        if str(event.close_reason or "").lower() == "stop_loss":
            self._track_pending_rebuild_cycle(event)
        else:
            self._prune_completed_cycles()
        return result

    def handle_volatility_lock(self, event: VolatilityLockEvent) -> tuple[Decimal, Decimal]:
        result = super().handle_volatility_lock(event)
        self._prune_completed_cycles()
        return result

    def handle_margin_protection(self, event: MarginProtectionEvent) -> tuple[Decimal, Decimal]:
        result = super().handle_margin_protection(event)
        self._prune_completed_cycles()
        return result

    def _mark_replay_records(self, *records: Position | Order | Trade | None) -> None:
        _ = records

    def clear_positions(self) -> None:
        super().clear_positions()
        self._position_id_to_cycle_id.clear()
        self._cycle_id_to_position_ids.clear()
        self._cycle_id_to_entry_ids.clear()
        self._pending_rebuild_position_ids.clear()
        self._last_recorded_trade = None

    def _resolve_rebuild_cycle_id(self, event: RebuildPositionEvent) -> str | None:
        cycle_id = super()._resolve_rebuild_cycle_id(event)
        if cycle_id is not None:
            return cycle_id
        if event.original_position_id:
            position_id = str(event.original_position_id)
            return self._pending_rebuild_position_ids.get(
                position_id
            ) or self._position_id_to_cycle_id.get(position_id)
        return None

    def _bind_position_to_cycle(
        self,
        *,
        position: Position,
        cycle_id: str,
        event: OpenPositionEvent | RebuildPositionEvent,
    ) -> None:
        position_id = str(position.id)
        previous_cycle_id = self._position_id_to_cycle_id.get(position_id)
        if previous_cycle_id is not None and previous_cycle_id != cycle_id:
            self._cycle_id_to_position_ids[previous_cycle_id].discard(position_id)
            if not self._cycle_id_to_position_ids[previous_cycle_id]:
                self._cycle_id_to_position_ids.pop(previous_cycle_id, None)
                for entry_id in self._cycle_id_to_entry_ids.pop(previous_cycle_id, set()):
                    if self._entry_id_to_cycle_id.get(entry_id) == previous_cycle_id:
                        self._entry_id_to_cycle_id.pop(entry_id, None)

        setattr(position, "_cycle_id", cycle_id)
        self._position_id_to_cycle_id[position_id] = cycle_id
        self._cycle_id_to_position_ids[cycle_id].add(position_id)
        for entry_id in (
            getattr(event, "entry_id", None),
            getattr(event, "root_entry_id", None),
            getattr(event, "parent_entry_id", None),
        ):
            if entry_id is None:
                continue
            self._entry_id_to_cycle_id[entry_id] = cycle_id
            self._cycle_id_to_entry_ids[cycle_id].add(int(entry_id))

    def _track_pending_rebuild_cycle(self, event: ClosePositionEvent) -> None:
        cycle_id = self._resolve_cycle_id_for_closed_event(event)
        position_id = getattr(event, "position_id", None)
        if cycle_id is not None and position_id:
            self._pending_rebuild_position_ids[str(position_id)] = cycle_id

    def _resolve_cycle_id_for_closed_event(self, event: ClosePositionEvent) -> str | None:
        for entry_id in (
            getattr(event, "entry_id", None),
            getattr(event, "root_entry_id", None),
            getattr(event, "parent_entry_id", None),
        ):
            if entry_id is not None and entry_id in self._entry_id_to_cycle_id:
                return self._entry_id_to_cycle_id[entry_id]
        position_id = getattr(event, "position_id", None)
        if position_id:
            return self._position_id_to_cycle_id.get(str(position_id))
        return None

    def _prune_completed_cycles(self) -> None:
        open_position_ids = {
            str(position.id)
            for position in self.order_service.get_open_positions(instrument=self.instrument)
        }
        for position_id in list(self._position_id_to_cycle_id):
            cycle_id = self._position_id_to_cycle_id[position_id]
            if position_id in self._pending_rebuild_position_ids:
                continue
            if position_id not in open_position_ids:
                self._position_id_to_cycle_id.pop(position_id, None)

        pending_cycle_ids = set(self._pending_rebuild_position_ids.values())
        for cycle_id, position_ids in list(self._cycle_id_to_position_ids.items()):
            live_position_ids = position_ids & open_position_ids
            if live_position_ids:
                self._cycle_id_to_position_ids[cycle_id] = live_position_ids
                continue
            if cycle_id in pending_cycle_ids:
                continue
            self._cycle_id_to_position_ids.pop(cycle_id, None)
            for entry_id in self._cycle_id_to_entry_ids.pop(cycle_id, set()):
                if self._entry_id_to_cycle_id.get(entry_id) == cycle_id:
                    self._entry_id_to_cycle_id.pop(entry_id, None)
