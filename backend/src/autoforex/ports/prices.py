"""Interfaces for normalized price publication."""

from typing import Protocol

from autoforex.domain.price import Price


class PricePublisher(Protocol):
    def publish(self, price: Price) -> None: ...
