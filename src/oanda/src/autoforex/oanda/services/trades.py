"""OANDA trade service."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from autoforex.core import Metadata, Order, Trade, Units

import autoforex.oanda.models as om
from autoforex.oanda.errors import OandaResponsePolicy
from autoforex.oanda.payload import OandaPayload as payload
from autoforex.oanda.services.policies import OandaMutationResponsePolicy
from autoforex.oanda.services.protocols import (
    AccountCurrencyProvider,
    MapperFactory,
    OandaTradeClient,
)


class OandaTradeService:
    """Trade operations for one OANDA account."""

    def __init__(
        self,
        *,
        account_id: str,
        trades: OandaTradeClient,
        account_currency: AccountCurrencyProvider,
        trade_mapper_factory: MapperFactory,
        order_mapper: Any,
    ) -> None:
        self.account_id = account_id
        self.trades = trades
        self._account_currency = account_currency
        self._trade_mapper_factory = trade_mapper_factory
        self.order_mapper = order_mapper

    def list_trades(self, **filters: object) -> Sequence[Trade]:
        """Return OANDA trades."""
        response = OandaResponsePolicy.ensure_success(
            self.trades.list_trades(
                self.account_id,
                om.TradesRequest.model_validate(payload.clean(filters)),
            ),
            200,
        )
        return self.mapper().trades_from_response(response)

    def list_open_trades(self) -> Sequence[Trade]:
        """Return OANDA open trades."""
        response = OandaResponsePolicy.ensure_success(
            self.trades.list_open_trades(self.account_id), 200
        )
        return self.mapper().trades_from_response(response)

    def get_trade(self, trade_id: str) -> Trade:
        """Return one OANDA trade."""
        response = OandaResponsePolicy.ensure_success(
            self.trades.get_trade(self.account_id, trade_id), 200
        )
        return self.mapper().trade_from_response(response)

    def close_trade(self, trade: Trade, *, units: Units | None = None) -> Order:
        """Close all or part of an OANDA trade."""
        planned_units = Units.of((units or trade.units).copy_abs())
        request = (
            om.CloseTradeRequest.model_validate({"units": str(planned_units)})
            if units is not None
            else None
        )
        response = self.trades.close_trade(self.account_id, str(trade.id), request, retry=True)
        OandaMutationResponsePolicy.raise_for_unexpected(response)
        return self.order_mapper.order_from_trade_close_response(
            response,
            trade=trade,
            planned_units=planned_units,
        )

    def set_trade_client_extensions(
        self,
        trade_id: str,
        *,
        client_id: str | None = None,
        tag: str | None = None,
        comment: str | None = None,
    ) -> Metadata:
        """Set OANDA trade client extensions."""
        request = payload.client_extensions(client_id=client_id, tag=tag, comment=comment)
        response = self.trades.set_trade_client_extensions(
            self.account_id,
            trade_id,
            om.SetTradeClientExtensionsRequest.model_validate(
                {"clientExtensions": request["clientExtensions"]}
            ),
            retry=True,
        )
        OandaMutationResponsePolicy.raise_for_unexpected(response)
        return payload.metadata(response.body)

    def set_trade_dependent_orders(self, trade_id: str, **orders: object) -> Metadata:
        """Set OANDA dependent orders for a trade."""
        response = self.trades.set_trade_dependent_orders(
            self.account_id,
            trade_id,
            om.SetTradeDependentOrdersRequest.model_validate(payload.clean(orders)),
            retry=True,
        )
        OandaMutationResponsePolicy.raise_for_unexpected(response)
        return payload.metadata(response.body)

    def mapper(self) -> Any:
        """Create the mapper with the current account currency."""
        return self._trade_mapper_factory(account_currency=self._account_currency())
