"""Typed wrappers around OANDA HTTP responses and streams."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OandaHttpResponse:
    """Raw HTTP response metadata used by OandaResponse."""

    status: int
    reason: str
    headers: dict[str, str]
    body: Any
    raw_body: bytes
    url: str
    content_type: str | None = None


@dataclass(frozen=True)
class OandaStreamResponse:
    """Streaming HTTP response wrapper."""

    status: int
    reason: str
    headers: dict[str, str]
    stream: Any
    url: str
    content_type: str | None = None
    stream_kind: str = "pricing"

    def parts(self) -> Iterator[tuple[str, Any]]:
        """Yield typed stream parts from newline-delimited OANDA JSON objects."""
        from autoforex.oanda.models import (
            ClientPrice,
            PricingHeartbeat,
            Transaction,
            TransactionHeartbeat,
        )

        for line in self.stream:
            if not line:
                continue
            payload = line.decode("utf-8").strip() if isinstance(line, bytes) else str(line).strip()
            if not payload:
                continue
            data = json.loads(payload)
            item_type = data.get("type")
            if item_type == "HEARTBEAT":
                if self.stream_kind == "transactions":
                    yield "TransactionHeartbeat", TransactionHeartbeat.model_validate(data)
                else:
                    yield "PricingHeartbeat", PricingHeartbeat.model_validate(data)
            elif self.stream_kind == "transactions":
                yield "Transaction", Transaction.model_validate(data)
            else:
                yield "ClientPrice", ClientPrice.model_validate(data)


@dataclass(frozen=True)
class OandaResponse[TBody]:
    """Typed response wrapper retaining raw HTTP metadata."""

    raw: OandaHttpResponse | OandaStreamResponse
    body: TBody

    @property
    def status(self) -> int:
        return self.raw.status

    @property
    def reason(self) -> str:
        return self.raw.reason

    @property
    def content_type(self) -> str | None:
        return self.raw.content_type

    @property
    def raw_body(self) -> bytes:
        return getattr(self.raw, "raw_body", b"")

    def parts(self) -> Iterator[tuple[str, Any]]:
        """Delegate streaming parts to the underlying stream response."""
        if isinstance(self.raw, OandaStreamResponse):
            yield from self.raw.parts()
