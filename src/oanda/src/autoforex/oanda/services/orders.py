"""OANDA order service."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from autoforex.core import Metadata, Order, OrderType, Position, PositionSide, Units

import autoforex.oanda.models as om
from autoforex.oanda.errors import OandaResponsePolicy
from autoforex.oanda.mappers.instrument import OandaInstrumentMapper
from autoforex.oanda.payload import OandaPayload as payload
from autoforex.oanda.services.policies import OandaMutationResponsePolicy
from autoforex.oanda.services.protocols import OandaOrderClient, OandaPositionClient


class OandaOrderRequestFactory:
    """Build OANDA order request payloads from Core orders."""

    def __init__(self, order_mapper: Any) -> None:
        self.order_mapper = order_mapper

    def request(self, order: Order) -> om.OrderRequestPayload:
        """Return the OANDA order request payload for a Core order."""
        values = {
            **self.order_mapper.order_kwargs(order),
            "type": self.order_type(order.order_type),
        }
        if order.order_type == OrderType.MARKET:
            return om.MarketOrderRequest.model_validate(values)
        if order.order_type == OrderType.LIMIT:
            return om.LimitOrderRequest.model_validate(values)
        if order.order_type == OrderType.STOP:
            return om.StopOrderRequest.model_validate(values)
        msg = f"unsupported OANDA order type: {order.order_type}"
        raise ValueError(msg)

    @classmethod
    def order_type(cls, order_type_: OrderType) -> str:
        """Map Core order type to OANDA order type text."""
        if order_type_ == OrderType.MARKET:
            return "MARKET"
        if order_type_ == OrderType.LIMIT:
            return "LIMIT"
        if order_type_ == OrderType.STOP:
            return "STOP"
        msg = f"unsupported OANDA order type: {order_type_}"
        raise ValueError(msg)


class OandaPositionCloseRequestFactory:
    """Build OANDA close-position payload fragments."""

    @classmethod
    def kwargs(cls, *, side: PositionSide, units: Units) -> dict[str, str]:
        """Build OANDA side-specific close-position units."""
        amount = str(units)
        if side == PositionSide.LONG:
            return {"longUnits": amount, "shortUnits": "NONE"}
        return {"longUnits": "NONE", "shortUnits": amount}


class OandaOrderService:
    """Order operations for one OANDA account."""

    def __init__(
        self,
        *,
        account_id: str,
        orders: OandaOrderClient,
        positions: OandaPositionClient,
        order_mapper: Any,
    ) -> None:
        self.account_id = account_id
        self.orders = orders
        self.positions = positions
        self.order_mapper = order_mapper
        self.request_factory = OandaOrderRequestFactory(order_mapper)

    def place_order(self, order: Order) -> Order:
        """Place an order through OANDA."""
        response = self.orders.create_order(
            self.account_id,
            om.CreateOrderRequest(order=self.request_factory.request(order)),
            retry=True,
        )
        OandaMutationResponsePolicy.raise_for_unexpected(response)
        return self.order_mapper.order_from_order_response(response, order)

    def close_position(
        self,
        *,
        position: Position,
        side: PositionSide,
        units: Units | None = None,
    ) -> Order:
        """Close all or part of an OANDA position."""
        state = position.require_side(side)
        source_units = units if units is not None else state.units
        planned_units = Units.of(source_units.copy_abs())
        kwargs = OandaPositionCloseRequestFactory.kwargs(side=side, units=planned_units)
        response = self.positions.close_position(
            self.account_id,
            OandaInstrumentMapper.to_oanda(position.instrument),
            om.ClosePositionRequest.model_validate(kwargs),
        )
        OandaMutationResponsePolicy.raise_for_unexpected(response)
        return self.order_mapper.order_from_position_close_response(
            response,
            position=position,
            side=side,
            planned_units=planned_units,
        )

    def list_orders(self, **filters: object) -> Sequence[Metadata]:
        """Return OANDA orders as raw metadata snapshots."""
        response = OandaResponsePolicy.ensure_success(
            self.orders.list_orders(
                self.account_id,
                om.OrdersRequest.model_validate(payload.clean(filters)),
            ),
            200,
        )
        orders = payload.get(response.body, "orders", ()) or ()
        return tuple(payload.metadata(order) for order in orders)

    def list_pending_orders(self) -> Sequence[Metadata]:
        """Return OANDA pending orders as raw metadata snapshots."""
        response = OandaResponsePolicy.ensure_success(
            self.orders.list_pending_orders(self.account_id), 200
        )
        orders = payload.get(response.body, "orders", ()) or ()
        return tuple(payload.metadata(order) for order in orders)

    def get_order(self, order_id: str) -> Metadata:
        """Return one OANDA order as raw metadata."""
        response = OandaResponsePolicy.ensure_success(
            self.orders.get_order(self.account_id, order_id), 200
        )
        return self.order_mapper.metadata_from_order_response(response)

    def replace_order(self, order_id: str, order: Order) -> Order:
        """Replace one OANDA order."""
        response = self.orders.replace_order(
            self.account_id,
            order_id,
            om.ReplaceOrderRequest(order=self.request_factory.request(order)),
            retry=True,
        )
        OandaMutationResponsePolicy.raise_for_unexpected(response)
        return self.order_mapper.order_from_order_response(response, order)

    def cancel_order(self, order_id: str) -> Metadata:
        """Cancel one OANDA order."""
        response = self.orders.cancel_order(self.account_id, order_id, retry=True)
        OandaMutationResponsePolicy.raise_for_unexpected(response)
        return payload.metadata(response.body)

    def set_order_client_extensions(
        self,
        order_id: str,
        *,
        client_id: str | None = None,
        tag: str | None = None,
        comment: str | None = None,
    ) -> Metadata:
        """Set OANDA order client extensions."""
        request = payload.client_extensions(client_id=client_id, tag=tag, comment=comment)
        response = self.orders.set_order_client_extensions(
            self.account_id,
            order_id,
            om.SetOrderClientExtensionsRequest.model_validate(
                {"clientExtensions": request["clientExtensions"]}
            ),
            retry=True,
        )
        OandaMutationResponsePolicy.raise_for_unexpected(response)
        return payload.metadata(response.body)
