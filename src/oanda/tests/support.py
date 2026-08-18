from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any


class FakeResponse:
    def __init__(self, status: int, body: Any, reason: str = "OK") -> None:
        self.status = status
        self.body = body
        self.reason = reason


class FakeHeaders(dict[str, str]):
    def items(self) -> Any:
        return super().items()


class FakeHTTPResponse:
    def __init__(
        self,
        status: int,
        body: Any,
        *,
        reason: str = "OK",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.code = status
        self.reason = reason
        self.headers = FakeHeaders({"Content-Type": "application/json", **(headers or {})})
        self._body = json.dumps(body).encode()

    def read(self) -> bytes:
        return self._body

    def close(self) -> None:
        return None


class FakeOpener:
    def __init__(self, responses: list[FakeHTTPResponse]) -> None:
        self.responses = responses
        self.requests: list[Any] = []
        self.closed = False

    @property
    def calls(self) -> int:
        return len(self.requests)

    def open(self, request: Any, timeout: int) -> FakeHTTPResponse:
        _ = timeout
        self.requests.append(request)
        return self.responses.pop(0)

    def close(self) -> None:
        self.closed = True


class FakeStream:
    def __init__(self, lines: list[dict[str, Any]]) -> None:
        self.lines = lines

    def __iter__(self) -> Any:
        for line in self.lines:
            yield json.dumps(line).encode()


def namespace_response(status: int = 200, **body: Any) -> FakeResponse:
    return FakeResponse(status, body)


def price_namespace(instrument: str = "USD_JPY") -> SimpleNamespace:
    return SimpleNamespace(
        instrument=instrument,
        time="2026-01-01T00:00:00.000000000Z",
        status="tradeable",
        tradeable=True,
        bids=[SimpleNamespace(price="150.10", liquidity=1_000_000)],
        asks=[SimpleNamespace(price="150.12", liquidity=1_000_000)],
        closeoutBid="150.09",
        closeoutAsk="150.13",
    )


def candle_namespace() -> SimpleNamespace:
    return SimpleNamespace(
        time="2026-01-01T00:00:00.000000000Z",
        mid=SimpleNamespace(o="150.00", h="150.20", l="149.90", c="150.10"),
        volume=120,
        complete=True,
    )
