"""Provider-neutral price model."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256

_SYMBOL = re.compile(r"^[A-Z0-9]{2,12}_[A-Z0-9]{2,12}$")


@dataclass(frozen=True, slots=True)
class Price:
    symbol: str
    ask: Decimal
    bid: Decimal
    created_at: str

    def __post_init__(self) -> None:
        if not _SYMBOL.fullmatch(self.symbol):
            raise ValueError(f"Invalid OANDA symbol: {self.symbol}")
        if self.ask <= 0 or self.bid <= 0:
            raise ValueError("Prices must be positive.")
        if not self.created_at:
            raise ValueError("created_at is required.")

    @property
    def mid(self) -> Decimal:
        return (self.ask + self.bid) / Decimal(2)

    def message(self) -> dict[str, str]:
        return {
            "symbol": self.symbol,
            "ask": str(self.ask),
            "bid": str(self.bid),
            "mid": str(self.mid),
            "created_at": self.created_at,
        }

    def message_body(self) -> str:
        return json.dumps(self.message(), separators=(",", ":"), sort_keys=True)

    def deduplication_id(self) -> str:
        return sha256(self.message_body().encode()).hexdigest()
