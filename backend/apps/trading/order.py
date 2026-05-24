"""Order execution service for trading operations."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from logging import Logger, getLogger
from time import monotonic
from typing import TYPE_CHECKING

from django.utils import timezone

from apps.market.models import OandaAccounts
from apps.market.services.oanda import (
    MarketOrder as OandaMarketOrder,
)
from apps.market.services.oanda import (
    MarketOrderRequest,
    OandaService,
    OrderDirection,
)
from apps.market.services.oanda import (
    Position as OandaPosition,
)
from apps.market.services.oanda_retry import OandaRetryPolicy
from apps.trading.broker_gateway import BrokerGateway, OandaBrokerGateway
from apps.trading.enums import Direction, TaskType
from apps.trading.money import AccountCurrency
from apps.trading.models import Order, Position
from apps.trading.models.orders import OrderType
from apps.trading.order_client_ids import TradingOrderClientIdFactory
from apps.trading.order_repositories import OrderRepository, PositionRepository
from apps.trading.utils import Instrument, Units

if TYPE_CHECKING:
    from apps.trading.models import BacktestTask, TradingTask

logger: Logger = getLogger(__name__)


class OrderServiceError(Exception):
    """Exception raised when order service operations fail."""


class OrderService:
    """
    Service for executing orders and managing positions.

    Handles order submission to OANDA and database persistence.
    Supports both live trading and dry-run (backtest) modes.
    """

    def __init__(
        self,
        account: OandaAccounts | None,
        task: BacktestTask | TradingTask,
        dry_run: bool = False,
    ):
        """
        Initialize order service.

        Args:
            account: OANDA account to use for trading (optional for dry_run mode)
            task: Trading or backtest task
            dry_run: If True, simulate orders without actual execution
        """
        self.account = account
        self.task = task
        self.dry_run = dry_run
        broker_service = OandaService(
            account=account,
            dry_run=dry_run,
            retry_policy=OandaRetryPolicy.from_task(task),
            task=task,
        )
        self.broker_gateway: BrokerGateway = OandaBrokerGateway(broker_service)
        # Backward-compatible attribute for callers that still refer to the
        # old OANDA service member.
        self.oanda_service = self.broker_gateway
        self.execution_id = getattr(task, "execution_id", None)
        self.client_order_ids = TradingOrderClientIdFactory()

        # execution_id is required for all Position/Order/Trade records
        if not self.execution_id:
            raise OrderServiceError(
                "Task must have an execution_id before OrderService can be used"
            )

        # Determine task type
        if hasattr(task, "__class__"):
            task_class_name = task.__class__.__name__
            if "Backtest" in task_class_name:
                self.task_type = TaskType.BACKTEST
            else:
                self.task_type = TaskType.TRADING
        else:
            self.task_type = TaskType.TRADING

        self.order_repository = OrderRepository(
            task_type=self.task_type,
            task_id=task.id,
            execution_id=self.execution_id,
            dry_run=dry_run,
            order_model=Order,
        )
        self.position_repository = PositionRepository(
            task_type=self.task_type,
            task_id=task.id,
            execution_id=self.execution_id,
            position_model=Position,
        )

        account_id = account.account_id if account else "DRY-RUN"
        logger.info(
            "OrderService initialized (account=%s, task=%s, task_type=%s, dry_run=%s)",
            account_id,
            task.id,
            self.task_type,
            dry_run,
        )

    def _account_currency(self) -> AccountCurrency:
        """Return the currency used for account-balance PnL deltas."""
        account_currency = getattr(self.account, "currency", "") if self.account else ""
        if not account_currency:
            account_currency = getattr(self.task, "account_currency", "")
        return AccountCurrency(str(account_currency or ""))

    def _broker_request_started_at(self) -> float | None:
        """Return a monotonic start timestamp for real broker requests."""
        if self.dry_run:
            return None
        return monotonic()

    @staticmethod
    def _broker_response_seconds(started_at: float | None) -> Decimal | None:
        """Return elapsed seconds for a broker request, preserving microsecond precision."""
        if started_at is None:
            return None
        elapsed = max(monotonic() - started_at, 0)
        return Decimal(str(elapsed)).quantize(Decimal("0.000001"))

    def open_position(
        self,
        instrument: str,
        units: int,
        direction: Direction,
        take_profit: Decimal | None = None,
        stop_loss: Decimal | None = None,
        *,
        layer_index: int | None = None,
        merge_with_existing: bool = True,
        override_price: Decimal | None = None,
        tick_timestamp: datetime | None = None,
        retracement_count: int | None = None,
        planned_exit_price: Decimal | None = None,
        planned_exit_price_formula: str | None = None,
    ) -> tuple[Position, Order]:
        """
        Open a new position with specified direction.

        Args:
            instrument: Trading instrument (e.g., 'EUR_USD')
            units: Number of units (positive integer)
            direction: Position direction (Direction.LONG or Direction.SHORT)
            take_profit: Optional take profit price
            stop_loss: Optional stop loss price
            layer_index: Optional strategy-specific layer index
            merge_with_existing: Whether to merge into existing same-direction position
            override_price: Optional price to use for dry-run open instead of latest tick data.
            tick_timestamp: Optional tick timestamp to use for position/order times instead of wall clock.

        Returns:
            tuple[Position, Order]: Created or updated position and the order record

        Raises:
            OrderServiceError: If order execution fails

        Example:
            # Open long position
            long_pos, order = service.open_position("EUR_USD", 10000, Direction.LONG)

            # Open short position
            short_pos, order = service.open_position("USD_JPY", 5000, Direction.SHORT)
        """
        requested_units = Units.coerce(units)
        if requested_units.value <= 0:
            raise OrderServiceError("Units must be positive")

        side_sign = 1 if direction == Direction.LONG else -1
        signed_units = requested_units.absolute * side_sign

        return self._execute_market_order(
            instrument=instrument,
            units=signed_units,
            direction=direction,
            take_profit=take_profit,
            stop_loss=stop_loss,
            layer_index=layer_index,
            merge_with_existing=merge_with_existing,
            override_price=override_price,
            tick_timestamp=tick_timestamp,
            retracement_count=retracement_count,
            planned_exit_price=planned_exit_price,
            planned_exit_price_formula=planned_exit_price_formula,
        )

    def close_position(
        self,
        position: Position,
        units: int | None = None,
        override_price: Decimal | None = None,
        tick_timestamp: datetime | None = None,
        force_instrument_close: bool = False,
    ) -> tuple[Position, Decimal, Order | None]:
        """
        Close an existing position (full or partial).

        This closes a position by executing the opposite trade:
        - LONG position: Executes a sell order to close
        - SHORT position: Executes a buy order to close

        Args:
            position: Position to close
            units: Optional number of units to close (if None, closes all)
            override_price: Optional price to use for dry-run close instead of latest tick data.
            tick_timestamp: Optional tick timestamp to use for position/order times instead of wall clock.

        Returns:
            tuple[Position, Decimal, Order | None]: Updated position, realized pnl delta, and the order record

        Raises:
            OrderServiceError: If position close fails

        Example:
            # Close a long position (sells to close)
            long_position, _ = order_service.buy("EUR_USD", 10000)
            order_service.close_position(long_position)

            # Close a short position (buys to close)
            short_position, _ = order_service.sell("USD_JPY", 5000)
            order_service.close_position(short_position)
        """
        if not position.is_open:
            raise OrderServiceError(f"Position {position.id} is already closed")

        if units is not None and units <= 0:
            raise OrderServiceError("Units must be positive for position close")

        if units is not None and units > abs(position.units):
            raise OrderServiceError(
                f"Cannot close {units} units, position only has {abs(position.units)} units"
            )

        oanda_response_seconds: Decimal | None = None
        try:
            # Determine close units
            close_units_int = units if units is not None else abs(position.units)
            close_units_decimal = Decimal(str(close_units_int))

            # Use trade ID-based close when available (required for hedging accounts)
            if position.oanda_trade_id and not self.dry_run and not force_instrument_close:
                from apps.market.services.oanda import OpenTrade, OrderDirection

                oanda_direction = (
                    OrderDirection.LONG
                    if position.direction == Direction.LONG
                    else OrderDirection.SHORT
                )
                trade = OpenTrade(
                    trade_id=position.oanda_trade_id,
                    instrument=position.instrument,
                    direction=oanda_direction,
                    units=Decimal(str(abs(position.units))),
                    entry_price=position.entry_price,
                    unrealized_pnl=Decimal("0"),
                    open_time=position.entry_time,
                    state="OPEN",
                    account_id=str(self.account.account_id) if self.account else "",
                )
                started_at = self._broker_request_started_at()
                try:
                    oanda_order = self.oanda_service.close_trade(
                        trade=trade,
                        units=close_units_decimal if units is not None else None,
                    )
                finally:
                    oanda_response_seconds = self._broker_response_seconds(started_at)
            else:
                # Fallback: instrument-based close (dry-run or legacy positions without trade ID)
                oanda_position = self._position_to_oanda_position(position)
                started_at = self._broker_request_started_at()
                try:
                    oanda_order = self.oanda_service.close_position(
                        position=oanda_position,
                        units=close_units_decimal if units is not None else None,
                        override_price=override_price,
                    )
                finally:
                    oanda_response_seconds = self._broker_response_seconds(started_at)

            # Create order record for the closing trade
            order = self._create_order_record(
                instrument=position.instrument,
                order_type=OrderType.MARKET,
                direction=Direction(position.direction),
                units=close_units_int,
                oanda_order=oanda_order,
                requested_price=override_price,
                tick_timestamp=tick_timestamp,
                oanda_trade_id=position.oanda_trade_id,
                position=position,
                layer_index=position.layer_index,
                retracement_count=position.retracement_count,
                oanda_response_seconds=oanda_response_seconds,
            )

            execution_time = self._order_execution_time(
                oanda_order=oanda_order,
                tick_timestamp=tick_timestamp,
            )

            # Update position
            if units is None or units >= abs(position.units):
                # Full close
                original_units = abs(position.units)
                position.close(
                    exit_price=oanda_order.price or Decimal("0"),
                    exit_time=execution_time,  # type: ignore[arg-type]
                )
                position.save()

                logger.info(
                    "Position fully closed: %s %s position, %s units of %s @ %s (order=%s, dry_run=%s)",
                    position.direction,
                    position.id,
                    abs(position.units),
                    position.instrument,
                    oanda_order.price,
                    order.id,
                    self.dry_run,
                )
                realized_delta = (oanda_order.price or Decimal("0")) - position.entry_price
                if position.direction == Direction.SHORT:
                    realized_delta = -realized_delta
                conv = Instrument(position.instrument).quote_to_account_rate(
                    oanda_order.price or position.entry_price,
                    self._account_currency(),
                )
                realized_delta = realized_delta * Decimal(original_units) * conv
            else:
                # Partial close - reduce units
                close_price = oanda_order.price or Decimal("0")
                close_units_decimal = Decimal(units)
                realized_delta = close_price - position.entry_price
                if position.direction == Direction.SHORT:
                    realized_delta = -realized_delta
                conv = Instrument(position.instrument).quote_to_account_rate(
                    close_price or position.entry_price,
                    self._account_currency(),
                )
                realized_delta = realized_delta * close_units_decimal * conv

                position.units = position.units - units

                # If partial close reduced units to zero, treat as full close
                if position.units == 0:
                    position.close(
                        exit_price=close_price,
                        exit_time=execution_time,  # type: ignore[arg-type]
                    )

                position.save()

                logger.info(
                    "Position partially closed: %s units of %s %s position (remaining: %s, "
                    "realized_delta=%s, order=%s, dry_run=%s)",
                    units,
                    position.direction,
                    position.instrument,
                    abs(position.units),
                    realized_delta,
                    order.id,
                    self.dry_run,
                )

            return position, realized_delta, order

        except Exception as e:
            error_msg = "Failed to close position"
            logger.error(
                "Failed to close position %s: %s",
                position.id,
                str(e),
                exc_info=True,
            )
            # Record the rejected order so the failure is visible in the UI
            close_units = units if units is not None else abs(position.units)
            try:
                self.order_repository.create_rejected_market(
                    instrument=position.instrument,
                    direction=Direction(position.direction),
                    units=close_units,
                    public_error_message=error_msg,
                    requested_price=override_price,
                    oanda_trade_id=position.oanda_trade_id,
                    position=position,
                    oanda_response_seconds=oanda_response_seconds,
                )
            except Exception:
                logger.warning(
                    "Failed to persist rejected order record for closing position %s",
                    position.id,
                    exc_info=True,
                )
            raise OrderServiceError(error_msg) from e

    def _execute_market_order(
        self,
        instrument: str,
        units: int,
        direction: Direction,
        take_profit: Decimal | None = None,
        stop_loss: Decimal | None = None,
        *,
        layer_index: int | None = None,
        merge_with_existing: bool = True,
        override_price: Decimal | None = None,
        tick_timestamp: datetime | None = None,
        retracement_count: int | None = None,
        planned_exit_price: Decimal | None = None,
        planned_exit_price_formula: str | None = None,
    ) -> tuple[Position, Order]:
        """
        Execute a market order and create/update position.

        Args:
            instrument: Trading instrument
            units: Signed units (positive for long, negative for short)
            direction: Order direction
            take_profit: Optional take profit price
            stop_loss: Optional stop loss price

        Returns:
            tuple[Position, Order]: Created or updated position and the order record

        Raises:
            OrderServiceError: If order execution fails
        """
        oanda_response_seconds: Decimal | None = None
        try:
            instrument_obj = Instrument(instrument)
            units_obj = Units.coerce(units)
            # Create market order request
            request = MarketOrderRequest(
                instrument=instrument_obj.name,
                units=Decimal(str(units_obj.value)),
                take_profit=take_profit,
                stop_loss=stop_loss,
                client_order_id=self.client_order_ids.open_position_id(
                    task_id=self.task.id,
                    execution_id=self.execution_id,
                    instrument=instrument_obj.name,
                    units=units_obj.value,
                    direction=direction,
                    layer_index=layer_index,
                    retracement_count=retracement_count,
                    tick_timestamp=tick_timestamp,
                    planned_exit_price=planned_exit_price,
                    stop_loss=stop_loss,
                ),
            )

            # Execute via OANDA service
            started_at = self._broker_request_started_at()
            try:
                oanda_order = self.oanda_service.create_market_order(
                    request, override_price=override_price
                )
            finally:
                oanda_response_seconds = self._broker_response_seconds(started_at)

            # Create or update position first so we can link the order to it
            entry_time = self._order_execution_time(
                oanda_order=oanda_order,
                tick_timestamp=tick_timestamp,
            )
            position = self._create_or_update_position(
                instrument=instrument_obj.name,
                direction=direction,
                units=units_obj.absolute,
                entry_price=oanda_order.price or Decimal("0"),
                entry_time=entry_time,
                layer_index=layer_index,
                merge_with_existing=merge_with_existing,
                oanda_trade_id=getattr(oanda_order, "trade_id", None),
                retracement_count=retracement_count,
                planned_exit_price=planned_exit_price,
                planned_exit_price_formula=planned_exit_price_formula,
            )

            # Create order record linked to the position
            order = self._create_order_record(
                instrument=instrument_obj.name,
                order_type=OrderType.MARKET,
                direction=direction,
                units=units_obj.value,
                oanda_order=oanda_order,
                requested_price=override_price,
                stop_loss=stop_loss,
                tick_timestamp=tick_timestamp,
                oanda_trade_id=getattr(oanda_order, "trade_id", None),
                position=position,
                layer_index=layer_index,
                retracement_count=retracement_count,
                oanda_response_seconds=oanda_response_seconds,
            )

            logger.info(
                "Market order executed: %s %s %s @ %s (order=%s, position=%s, dry_run=%s)",
                direction,
                units_obj.absolute,
                instrument_obj.name,
                oanda_order.price,
                order.id,
                position.id,
                self.dry_run,
            )

            return position, order

        except Exception as e:
            error_msg = "Failed to execute market order"
            logger.error(
                "Failed to execute market order: %s %s %s - %s",
                direction,
                abs(units),
                instrument,
                str(e),
                exc_info=True,
            )
            # Record the rejected order so the failure is visible in the UI
            try:
                self.order_repository.create_rejected_market(
                    instrument=instrument,
                    direction=direction,
                    units=units,
                    public_error_message=error_msg,
                    requested_price=override_price,
                    stop_loss=stop_loss,
                    oanda_response_seconds=oanda_response_seconds,
                )
            except Exception:
                logger.warning(
                    "Failed to persist rejected order record for %s %s %s",
                    direction,
                    abs(units),
                    instrument,
                    exc_info=True,
                )
            raise OrderServiceError(error_msg) from e

    def _create_order_record(
        self,
        instrument: str,
        order_type: OrderType,
        direction: Direction | None,
        units: int,
        oanda_order: OandaMarketOrder,
        requested_price: Decimal | None = None,
        stop_loss: Decimal | None = None,
        tick_timestamp: datetime | None = None,
        oanda_trade_id: str | None = None,
        position: Position | None = None,
        layer_index: int | None = None,
        retracement_count: int | None = None,
        oanda_response_seconds: Decimal | None = None,
    ) -> Order:
        """Create order database record."""
        return self.order_repository.create_filled(
            instrument=instrument,
            order_type=order_type,
            direction=direction,
            units=units,
            oanda_order=oanda_order,
            filled_at=self._order_execution_time(
                oanda_order=oanda_order,
                tick_timestamp=tick_timestamp,
            ),
            requested_price=requested_price,
            stop_loss=stop_loss,
            oanda_trade_id=oanda_trade_id,
            position=position,
            layer_index=layer_index,
            retracement_count=retracement_count,
            oanda_response_seconds=oanda_response_seconds,
        )

    def _order_execution_time(
        self,
        *,
        oanda_order: OandaMarketOrder,
        tick_timestamp: datetime | None,
    ) -> datetime:
        """Resolve the persisted execution timestamp for an order.

        Backtests and dry-run trading intentionally use the strategy tick time
        so simulations remain reproducible. Broker-bound orders must use the
        broker fill time; otherwise a delayed tick/event can make a real order
        look filled before it was submitted.
        """
        if self.dry_run and tick_timestamp is not None:
            return tick_timestamp
        if isinstance(oanda_order.fill_time, datetime):
            return oanda_order.fill_time
        if isinstance(oanda_order.create_time, datetime):
            return oanda_order.create_time
        return timezone.now()

    def _create_or_update_position(
        self,
        instrument: str,
        direction: Direction,
        units: int,
        entry_price: Decimal,
        entry_time: datetime,
        *,
        layer_index: int | None = None,
        merge_with_existing: bool = True,
        oanda_trade_id: str | None = None,
        retracement_count: int | None = None,
        planned_exit_price: Decimal | None = None,
        planned_exit_price_formula: str | None = None,
    ) -> Position:
        """Create new position or update existing one."""
        return self.position_repository.create_or_update(
            instrument=instrument,
            direction=direction,
            units=units,
            entry_price=entry_price,
            entry_time=entry_time,
            layer_index=layer_index,
            merge_with_existing=merge_with_existing,
            oanda_trade_id=oanda_trade_id,
            retracement_count=retracement_count,
            planned_exit_price=planned_exit_price,
            planned_exit_price_formula=planned_exit_price_formula,
        )

    def _position_to_oanda_position(self, position: Position) -> OandaPosition:
        """Convert database Position to OANDA Position."""
        from apps.market.services.oanda import Position as OandaPosition

        oanda_direction = (
            OrderDirection.LONG if position.direction == Direction.LONG else OrderDirection.SHORT
        )

        account_id = str(self.account.account_id) if self.account else "DRY-RUN-ACCOUNT"

        return OandaPosition(
            instrument=position.instrument,
            direction=oanda_direction,
            units=Decimal(str(abs(position.units))),
            average_price=position.entry_price,
            unrealized_pnl=Decimal("0"),
            trade_ids=[],
            account_id=account_id,
        )

    def get_open_positions(self, instrument: str | None = None) -> list[Position]:
        """
        Get all open positions for this task.

        Args:
            instrument: Optional filter by instrument

        Returns:
            List of open positions
        """
        return self.position_repository.open_positions(instrument=instrument)

    def get_order_history(self, instrument: str | None = None, limit: int = 100) -> list[Order]:
        """
        Get order history for this task.

        Args:
            instrument: Optional filter by instrument
            limit: Maximum number of orders to return

        Returns:
            List of orders
        """
        return self.order_repository.history(instrument=instrument, limit=limit)
