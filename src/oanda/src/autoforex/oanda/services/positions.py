"""OANDA position service."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from autoforex.core import CurrencyPair, Position

from autoforex.oanda.errors import OandaResponsePolicy
from autoforex.oanda.mappers.instrument import OandaInstrumentMapper
from autoforex.oanda.payload import OandaPayload as payload
from autoforex.oanda.services.protocols import (
    AccountCurrencyProvider,
    MapperFactory,
    OandaPositionClient,
)


class OandaPositionService:
    """Position operations for one OANDA account."""

    def __init__(
        self,
        *,
        account_id: str,
        positions: OandaPositionClient,
        account_currency: AccountCurrencyProvider,
        position_mapper_factory: MapperFactory,
    ) -> None:
        self.account_id = account_id
        self.positions_client = positions
        self._account_currency = account_currency
        self._position_mapper_factory = position_mapper_factory

    def positions(self, *, instrument: CurrencyPair | None = None) -> Sequence[Position]:
        """Return open OANDA positions."""
        response = OandaResponsePolicy.ensure_success(
            self.positions_client.list_open_positions(self.account_id), 200
        )
        positions = self.mapper().positions_from_response(response)
        if instrument is None:
            return positions
        return tuple(position for position in positions if position.instrument == instrument)

    def list_positions(self) -> Sequence[Position]:
        """Return all OANDA positions."""
        response = OandaResponsePolicy.ensure_success(
            self.positions_client.list_positions(self.account_id), 200
        )
        return self.mapper().positions_from_response(response)

    def list_open_positions(self) -> Sequence[Position]:
        """Return open OANDA positions."""
        return self.positions()

    def get_position(self, instrument: CurrencyPair) -> Position:
        """Return one OANDA position."""
        response = OandaResponsePolicy.ensure_success(
            self.positions_client.get_position(
                self.account_id, OandaInstrumentMapper.to_oanda(instrument)
            ),
            200,
        )
        position = self.mapper().position_from_oanda(payload.get(response.body, "position"))
        if position is None:
            msg = f"position not found: {instrument}"
            raise LookupError(msg)
        return position

    def mapper(self) -> Any:
        """Create the mapper with the current account currency."""
        return self._position_mapper_factory(account_currency=self._account_currency())
