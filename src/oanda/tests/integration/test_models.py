from __future__ import annotations

from autoforex.oanda.models import ClientPrice, OandaResponse, OandaStreamResponse
from tests.support import FakeStream


class TestModels:
    def test_response_parts_delegate_to_stream_response_generated_models(self) -> None:
        stream = OandaStreamResponse(
            status=200,
            reason="OK",
            headers={},
            stream=FakeStream(
                [
                    {
                        "type": "PRICE",
                        "instrument": "USD_JPY",
                        "time": "2026-01-01T00:00:00Z",
                        "bids": [{"price": "150.10"}],
                        "asks": [{"price": "150.12"}],
                    }
                ]
            ),
            url="https://stream.example.test",
            stream_kind="pricing",
        )
        response = OandaResponse(raw=stream, body=None)

        parts = tuple(response.parts())

        assert parts[0][0] == "ClientPrice"
        assert isinstance(parts[0][1], ClientPrice)
