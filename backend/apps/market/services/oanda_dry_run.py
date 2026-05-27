"""Dry-run execution simulator for OANDA order operations."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from logging import getLogger

from apps.market.models import OandaAccounts
from apps.market.services.oanda_types import (
    MarketOrder,
    MarketOrderRequest,
    OandaAPIError,
    OrderDirection,
    OrderState,
    OrderType,
    Position,
)

logger = getLogger(__name__)


class OandaDryRunSimulator:
    """Stateful simulator for market fills and position closes."""

    def __init__(self, account: OandaAccounts | None = None) -> None:
        self.account = account
        self.order_counter = 0
        self.positions: dict[str, Position] = {}

    def simulate_market_order(
        self,
        request: MarketOrderRequest,
        direction: OrderDirection,
        abs_units: Decimal,
        override_price: Decimal | None = None,
    ) -> MarketOrder:
        """Simulate market order execution for dry-run mode."""
        self.order_counter += 1
        order_id = f"DRY-{self.order_counter}"
        trade_id = f"DRY-TRADE-{self.order_counter}"
        now = datetime.now(UTC)

        # Dry-run fills must be supplied by the execution tick.  Falling back
        # to the database's latest tick would mix wall-clock state into a
        # historical simulation and can create impossible fills.
        if override_price is not None:
            fill_price = override_price
        else:
            raise OandaAPIError("Dry-run market order requires an explicit override_price")

        # Update dry-run position tracking
        position_key = f"{request.instrument}_{direction.value}"
        account_id = str(self.account.account_id) if self.account else "DRY-RUN-ACCOUNT"

        if position_key in self.positions:
            existing = self.positions[position_key]
            # Update weighted average price
            total_units = existing.units + abs_units
            new_avg_price = (
                existing.average_price * existing.units + fill_price * abs_units
            ) / total_units
            self.positions[position_key] = Position(
                instrument=request.instrument,
                direction=direction,
                units=total_units,
                average_price=new_avg_price,
                unrealized_pnl=Decimal("0"),
                trade_ids=[order_id],
                account_id=account_id,
            )
        else:
            self.positions[position_key] = Position(
                instrument=request.instrument,
                direction=direction,
                units=abs_units,
                average_price=fill_price,
                unrealized_pnl=Decimal("0"),
                trade_ids=[order_id],
                account_id=account_id,
            )

        logger.info(
            "[DRY-RUN] Market order simulated: %s %s %s @ %s",
            direction.value,
            abs_units,
            request.instrument,
            fill_price,
        )

        return MarketOrder(
            order_id=order_id,
            instrument=str(request.instrument),
            order_type=OrderType.MARKET,
            direction=direction,
            units=abs_units,
            price=fill_price,
            state=OrderState.FILLED,
            time_in_force="FOK",
            create_time=now,
            fill_time=now,
            trade_id=trade_id,
        )

    def simulate_position_close(
        self,
        position: Position,
        units: Decimal | None,
        override_price: Decimal | None = None,
    ) -> MarketOrder:
        """Simulate position close for dry-run mode."""
        self.order_counter += 1
        order_id = f"DRY-CLOSE-{self.order_counter}"
        now = datetime.now(UTC)

        # Dry-run closes must be supplied by the execution tick.  Falling back
        # to the database's latest tick would mix wall-clock state into a
        # historical simulation and can create impossible fills.
        if override_price is not None:
            close_price = override_price
        else:
            raise OandaAPIError("Dry-run position close requires an explicit override_price")

        # Determine closed units even when the position is not tracked locally.
        close_units = position.units if units is None else min(units, position.units)

        # Update dry-run position tracking
        position_key = f"{position.instrument}_{position.direction.value}"
        if position_key in self.positions:
            if close_units >= position.units:
                # Close entire position
                del self.positions[position_key]
            else:
                # Partial close
                remaining_units = position.units - close_units
                self.positions[position_key] = Position(
                    instrument=position.instrument,
                    direction=position.direction,
                    units=remaining_units,
                    average_price=position.average_price,
                    unrealized_pnl=Decimal("0"),
                    trade_ids=position.trade_ids,
                    account_id=position.account_id,
                )

        logger.info(
            "[DRY-RUN] Position close simulated: %s %s %s @ %s",
            position.direction.value,
            close_units,
            position.instrument,
            close_price,
        )

        return MarketOrder(
            order_id=order_id,
            instrument=position.instrument,
            order_type=OrderType.MARKET,
            direction=position.direction,
            units=close_units,
            price=close_price,
            state=OrderState.FILLED,
            time_in_force="FOK",
            create_time=now,
            fill_time=now,
        )
