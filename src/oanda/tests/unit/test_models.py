from __future__ import annotations

from decimal import Decimal

from autoforex.oanda.models import (
    AccountsResponse,
    ClientPrice,
    HomeConversionFactors,
    OandaHttpResponse,
    OandaResponse,
    OandaStreamResponse,
    PricingHeartbeat,
    Transaction,
    TransactionHeartbeat,
)
from tests.support import FakeStream


class TestModels:
    def test_oanda_model_accepts_aliases_and_extra_fields(self) -> None:
        response = AccountsResponse.model_validate(
            {"accounts": [{"id": "001", "mt4AccountID": 123, "unknown": "kept"}]}
        )

        assert response.accounts[0].id == "001"
        assert response.accounts[0].mt4_account_id == 123
        assert response.accounts[0].model_dump()["unknown"] == "kept"

    def test_home_conversion_factors_accept_conversion_factor_objects(self) -> None:
        factors = HomeConversionFactors.model_validate(
            {
                "gainQuoteHome": {"factor": "1"},
                "lossQuoteHome": {"factor": "0.998"},
                "gainBaseHome": {"factor": "149.25"},
                "lossBaseHome": {"factor": "149.20"},
            }
        )

        assert factors.gain_quote_home is not None
        assert factors.gain_quote_home.factor == Decimal("1")
        assert factors.loss_quote_home is not None
        assert factors.loss_quote_home.factor == Decimal("0.998")
        assert factors.gain_base_home is not None
        assert factors.gain_base_home.factor == Decimal("149.25")
        assert factors.loss_base_home is not None
        assert factors.loss_base_home.factor == Decimal("149.20")

    def test_response_wrapper_exposes_raw_response_fields(self) -> None:
        raw = OandaHttpResponse(
            status=200,
            reason="OK",
            headers={"Content-Type": "application/json"},
            body={"ok": True},
            raw_body=b'{"ok": true}',
            url="https://api.example.test",
            content_type="application/json",
        )
        response = OandaResponse(raw=raw, body={"ok": True})

        assert response.status == 200
        assert response.reason == "OK"
        assert response.content_type == "application/json"
        assert response.raw_body == b'{"ok": true}'

    def test_stream_response_yields_pricing_parts(self) -> None:
        raw = OandaStreamResponse(
            status=200,
            reason="OK",
            headers={},
            stream=FakeStream(
                [
                    {"type": "HEARTBEAT", "time": "2026-01-01T00:00:00Z"},
                    {
                        "type": "PRICE",
                        "instrument": "USD_JPY",
                        "time": "2026-01-01T00:00:00Z",
                        "bids": [{"price": "150.10"}],
                        "asks": [{"price": "150.12"}],
                    },
                ]
            ),
            url="https://stream.example.test",
            stream_kind="pricing",
        )

        parts = tuple(raw.parts())

        assert parts[0][0] == "PricingHeartbeat"
        assert isinstance(parts[0][1], PricingHeartbeat)
        assert parts[1][0] == "ClientPrice"
        assert isinstance(parts[1][1], ClientPrice)

    def test_stream_response_yields_transaction_parts(self) -> None:
        raw = OandaStreamResponse(
            status=200,
            reason="OK",
            headers={},
            stream=FakeStream(
                [
                    {"type": "HEARTBEAT", "lastTransactionID": "10"},
                    {"id": "11", "type": "ORDER_FILL"},
                ]
            ),
            url="https://stream.example.test",
            stream_kind="transactions",
        )

        parts = tuple(raw.parts())

        assert isinstance(parts[0][1], TransactionHeartbeat)
        assert isinstance(parts[1][1], Transaction)
