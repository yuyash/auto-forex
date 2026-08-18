"""Market data mapping between OANDA payloads and Core domain models."""

from __future__ import annotations

from collections.abc import Iterable

from autoforex.core import Candle, CandleGranularity, CurrencyPair, Metadata, Money, Tick

from autoforex.oanda.payload import OandaPayload as payload


class OandaMarketDataMapper:
    """Map OANDA price and candle objects into Core market data models."""

    def tick_from_price(self, price: object) -> Tick:
        """Convert an OANDA ClientPrice/Price object into a Core tick."""
        instrument = CurrencyPair.of(str(payload.get(price, "instrument")))
        bids = tuple(payload.get(price, "bids", ()) or ())
        asks = tuple(payload.get(price, "asks", ()) or ())
        if not bids or not asks:
            msg = f"OANDA price for {instrument} does not contain bid/ask liquidity"
            raise ValueError(msg)
        bid = payload.get(bids[0], "price")
        ask = payload.get(asks[0], "price")
        return Tick(
            instrument=instrument,
            timestamp=payload.parse_time(payload.get(price, "time")),
            bid=Money.of(bid, instrument.quote),
            ask=Money.of(ask, instrument.quote),
            metadata=Metadata.model_validate(
                {
                    "oanda_status": payload.get(price, "status"),
                    "oanda_tradeable": payload.get(price, "tradeable"),
                    "oanda_closeout_bid": payload.get(price, "closeoutBid"),
                    "oanda_closeout_ask": payload.get(price, "closeoutAsk"),
                }
            ),
        )

    def ticks_from_prices(self, prices: Iterable[object]) -> tuple[Tick, ...]:
        """Convert OANDA price objects into Core ticks."""
        return tuple(self.tick_from_price(price) for price in prices)

    def candle_from_oanda(
        self,
        item: object,
        *,
        instrument: CurrencyPair,
        granularity: CandleGranularity,
    ) -> Candle:
        """Convert an OANDA candlestick into a Core candle."""
        data = payload.get(item, "mid")
        if data is None:
            bid = payload.get(item, "bid")
            ask = payload.get(item, "ask")
            data = payload.average_candle_data(bid, ask)
        return Candle(
            instrument=instrument,
            timestamp=payload.parse_time(payload.get(item, "time")),
            granularity=granularity,
            open=Money.of(payload.get(data, "o"), instrument.quote),
            high=Money.of(payload.get(data, "h"), instrument.quote),
            low=Money.of(payload.get(data, "l"), instrument.quote),
            close=Money.of(payload.get(data, "c"), instrument.quote),
            volume=int(payload.get(item, "volume", 0) or 0),
            complete=bool(payload.get(item, "complete", True)),
            metadata=Metadata.model_validate(
                {"oanda_complete": payload.get(item, "complete", True)}
            ),
        )

    def candles_from_response(
        self,
        response: object,
        *,
        instrument: CurrencyPair,
        granularity: CandleGranularity,
    ) -> tuple[Candle, ...]:
        """Convert a candles response into Core candles."""
        candles = payload.get(payload.body(response), "candles", ()) or ()
        return tuple(
            self.candle_from_oanda(item, instrument=instrument, granularity=granularity)
            for item in candles
        )
