"""Persistence collaborators for order execution services."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from logging import Logger, getLogger
from typing import Any

from apps.market.services.oanda import MarketOrder as OandaMarketOrder
from apps.trading.enums import Direction, TaskType
from apps.trading.models import Order, Position
from apps.trading.models.orders import OrderStatus, OrderType
from apps.trading.utils import Instrument

logger: Logger = getLogger(__name__)


class OrderRepository:
    """Persist and query order records for one task execution."""

    def __init__(
        self,
        *,
        task_type: TaskType,
        task_id,
        execution_id,
        dry_run: bool,
        order_model: Any = Order,
    ) -> None:
        """Bind the repository to a task execution scope."""
        self.task_type = task_type
        self.task_id = task_id
        self.execution_id = execution_id
        self.dry_run = dry_run
        self.order_model = order_model

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
        """Create a filled order database record."""
        return self.order_model.objects.create(
            task_type=self.task_type,
            task_id=self.task_id,
            execution_id=self.execution_id,
            broker_order_id=oanda_order.order_id,
            oanda_trade_id=oanda_trade_id,
            instrument=instrument,
            order_type=order_type,
            direction=direction,
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
        """Create a rejected market-order record with a public error message."""
        order = self.order_model.objects.create(
            task_type=self.task_type,
            task_id=self.task_id,
            execution_id=self.execution_id,
            instrument=instrument,
            order_type=OrderType.MARKET,
            direction=direction,
            units=units,
            requested_price=requested_price,
            stop_loss=stop_loss,
            oanda_trade_id=oanda_trade_id,
            oanda_response_seconds=oanda_response_seconds,
            status=OrderStatus.PENDING,
            is_dry_run=self.dry_run,
            position=position,
        )
        order.mark_rejected(public_error_message)
        order.save()
        return order

    def history(self, *, instrument: str | None = None, limit: int = 100) -> list[Order]:
        """Return recent orders for the bound task execution."""
        queryset = self.order_model.objects.filter(
            task_type=self.task_type,
            task_id=self.task_id,
            execution_id=self.execution_id,
        )

        if instrument:
            queryset = queryset.filter(instrument=instrument)

        return list(queryset.order_by("-submitted_at")[:limit])


class PositionRepository:
    """Persist and query position records for one task execution."""

    def __init__(
        self,
        *,
        task_type: TaskType,
        task_id,
        execution_id,
        position_model: Any = Position,
    ) -> None:
        """Bind the repository to a task execution scope."""
        self.task_type = task_type
        self.task_id = task_id
        self.execution_id = execution_id
        self.position_model = position_model

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
        """Create a new position or merge into the latest matching open one."""
        if merge_with_existing:
            existing_position = self.latest_open_position(
                instrument=instrument,
                direction=direction,
            )
            if existing_position:
                return self._merge_position(
                    position=existing_position,
                    units=units,
                    entry_price=entry_price,
                    layer_index=layer_index,
                    oanda_trade_id=oanda_trade_id,
                    retracement_count=retracement_count,
                    planned_exit_price=planned_exit_price,
                    planned_exit_price_formula=planned_exit_price_formula,
                )

        return self._create_position(
            instrument=instrument,
            direction=direction,
            units=units,
            entry_price=entry_price,
            entry_time=entry_time,
            layer_index=layer_index,
            oanda_trade_id=oanda_trade_id,
            retracement_count=retracement_count,
            planned_exit_price=planned_exit_price,
            planned_exit_price_formula=planned_exit_price_formula,
        )

    def latest_open_position(self, *, instrument: str, direction: Direction) -> Position | None:
        """Return the latest open position matching instrument and direction."""
        return (
            self.position_model.objects.filter(
                task_type=self.task_type,
                task_id=self.task_id,
                execution_id=self.execution_id,
                instrument=instrument,
                direction=direction,
                is_open=True,
            )
            .order_by("-entry_time")
            .first()
        )

    def open_positions(self, *, instrument: str | None = None) -> list[Position]:
        """Return open positions for the bound task execution."""
        queryset = self.position_model.objects.filter(
            task_type=self.task_type,
            task_id=self.task_id,
            execution_id=self.execution_id,
            is_open=True,
        )

        if instrument:
            queryset = queryset.filter(instrument=instrument)

        return list(queryset.order_by("-entry_time"))

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
        quote_currency = Instrument(position.instrument).quote_currency
        if quote_currency and position.unrealized_pnl_currency != quote_currency:
            position.unrealized_pnl_currency = quote_currency
        position.execution_id = self.execution_id
        position.save()

        logger.debug(
            "Updated existing position %s: %s units @ %s",
            position.id,
            total_units,
            new_avg_price,
        )
        return position

    def _create_position(
        self,
        *,
        instrument: str,
        direction: Direction,
        units: int,
        entry_price: Decimal,
        entry_time: datetime,
        layer_index: int | None,
        oanda_trade_id: str | None,
        retracement_count: int | None,
        planned_exit_price: Decimal | None,
        planned_exit_price_formula: str | None,
    ) -> Position:
        position = self.position_model.objects.create(
            task_type=self.task_type,
            task_id=self.task_id,
            execution_id=self.execution_id,
            instrument=instrument,
            direction=direction,
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

        logger.debug(
            "Created new position %s: %s %s units @ %s",
            position.id,
            direction,
            units,
            entry_price,
        )
        return position
