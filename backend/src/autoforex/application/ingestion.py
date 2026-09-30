"""Price-stream ingestion use case."""

import asyncio
from collections.abc import AsyncIterator

from autoforex.domain.price import Price
from autoforex.ports.prices import PricePublisher


class IngestionService:
    def __init__(self, publisher: PricePublisher) -> None:
        self._publisher = publisher

    async def consume(self, prices: AsyncIterator[Price]) -> None:
        async for price in prices:
            await asyncio.to_thread(self._publisher.publish, price)
