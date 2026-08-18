"""Position mapping between OANDA payloads and Core domain models."""

from __future__ import annotations

from autoforex.core import (
    BrokerPositionId,
    Currency,
    CurrencyPair,
    Metadata,
    Money,
    Position,
    PositionSide,
    PositionSideState,
    Units,
)

import autoforex.oanda.models as om
from autoforex.oanda.payload import OandaPayload as payload
from autoforex.oanda.snapshots import OandaPosition


class OandaPositionMapper:
    """Map OANDA position objects into Core two-sided positions."""

    def __init__(self, *, account_currency: Currency) -> None:
        self.account_currency = account_currency

    def positions_from_response(
        self, response: om.OandaResponse[om.PositionsResponse]
    ) -> tuple[Position, ...]:
        """Convert an OANDA positions response into Core positions."""
        body = payload.body(response)
        positions = payload.get(body, "positions", ()) or ()
        return tuple(
            position
            for item in positions
            if (position := self.position_from_oanda(item)) is not None
        )

    def position_from_oanda(self, item: object) -> Position | None:
        """Convert a net OANDA position into one Core two-sided position."""
        instrument = CurrencyPair.of(str(payload.get(item, "instrument")))
        long_state = self._position_side(instrument, PositionSide.LONG, payload.get(item, "long"))
        short_state = self._position_side(
            instrument, PositionSide.SHORT, payload.get(item, "short")
        )
        if long_state is None and short_state is None:
            return None
        position = Position(
            instrument=instrument,
            long=long_state,
            short=short_state,
            unrealized_pl=self._unrealized_pl(item),
            metadata=Metadata.model_validate(
                {
                    "oanda_instrument": payload.get(item, "instrument"),
                    "oanda_long_pl": payload.get(payload.get(item, "long"), "pl"),
                    "oanda_short_pl": payload.get(payload.get(item, "short"), "pl"),
                }
            ),
        )
        return OandaPosition(
            position=position,
            pl=Money.of(payload.get(item, "pl"), self.account_currency)
            if payload.get(item, "pl") is not None
            else None,
            resettable_pl=Money.of(payload.get(item, "resettablePL"), self.account_currency)
            if payload.get(item, "resettablePL") is not None
            else None,
            financing=Money.of(payload.get(item, "financing"), self.account_currency)
            if payload.get(item, "financing") is not None
            else None,
            margin_used=Money.of(payload.get(item, "marginUsed"), self.account_currency)
            if payload.get(item, "marginUsed") is not None
            else None,
            long_trade_ids=tuple(payload.get(payload.get(item, "long"), "tradeIDs", ()) or ()),
            short_trade_ids=tuple(payload.get(payload.get(item, "short"), "tradeIDs", ()) or ()),
        ).position

    def _position_side(
        self,
        instrument: CurrencyPair,
        side: PositionSide,
        position_side: object,
    ) -> PositionSideState | None:
        units = abs(payload.decimal(payload.get(position_side, "units", "0")))
        average_price = payload.get(position_side, "averagePrice")
        if units == 0 or average_price is None:
            return None
        return PositionSideState(
            side=side,
            units=Units.of(units),
            average_entry_price=Money.of(average_price, instrument.quote),
            broker_position_id=BrokerPositionId.of(f"{instrument.symbol}:{side.value}"),
            unrealized_pl=self._unrealized_pl(position_side),
            metadata=Metadata.model_validate(
                {
                    "oanda_trade_ids": tuple(payload.get(position_side, "tradeIDs", ()) or ()),
                    "oanda_pl": payload.get(position_side, "pl"),
                    "oanda_resettable_pl": payload.get(position_side, "resettablePL"),
                    "oanda_financing": payload.get(position_side, "financing"),
                }
            ),
        )

    def _unrealized_pl(self, position_side: object) -> Money | None:
        unrealized = payload.get(position_side, "unrealizedPL")
        if unrealized is None:
            return None
        return Money.of(unrealized, self.account_currency)
