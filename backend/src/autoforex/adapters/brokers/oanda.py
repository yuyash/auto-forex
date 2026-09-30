"""OANDA v20 price stream."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import httpx

from autoforex.domain.price import Price


class OandaPriceStream:
    _hosts = {
        "practice": "https://stream-fxpractice.oanda.com",
        "live": "https://stream-fxtrade.oanda.com",
    }

    def __init__(
        self,
        environment: str,
        account_id: str,
        symbols: tuple[str, ...],
        token: str,
    ) -> None:
        try:
            self._host = self._hosts[environment]
        except KeyError as error:
            raise ValueError("OANDA environment must be practice or live.") from error
        self._account_id = account_id
        self._symbols = symbols
        self._token = token

    async def prices(self) -> AsyncIterator[Price]:
        timeout = httpx.Timeout(connect=10, read=15, write=10, pool=10)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "GET",
                f"{self._host}/v3/accounts/{self._account_id}/pricing/stream",
                headers={"Authorization": f"Bearer {self._token}"},
                params={"instruments": ",".join(self._symbols), "snapshot": "true"},
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    event: dict[str, Any] = json.loads(line)
                    if event.get("type") != "PRICE" or not event.get("tradeable", False):
                        continue
                    bids = event.get("bids", [])
                    asks = event.get("asks", [])
                    if not bids or not asks:
                        continue
                    yield Price(
                        symbol=event["instrument"],
                        bid=Decimal(bids[0]["price"]),
                        ask=Decimal(asks[0]["price"]),
                        created_at=event["time"],
                    )
