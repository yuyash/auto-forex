from __future__ import annotations

import pytest

from autoforex.oanda.errors import (
    OandaAuthenticationError,
    OandaBadRequestError,
    OandaRateLimitError,
    OandaResponsePolicy,
    OandaServerError,
)
from tests.support import FakeResponse


class TestErrors:
    def test_ensure_success_returns_expected_status_and_raises_specific_errors(self) -> None:
        ok = FakeResponse(200, {"ok": True})
        auth = FakeResponse(401, {"errorCode": "UNAUTHORIZED", "errorMessage": "bad token"})

        assert OandaResponsePolicy.ensure_success(ok, 200) is ok
        with pytest.raises(OandaAuthenticationError, match="UNAUTHORIZED"):
            OandaResponsePolicy.ensure_success(auth, 200)

    def test_error_from_response_classifies_statuses(self) -> None:
        assert isinstance(
            OandaResponsePolicy.error_from_response(FakeResponse(400, {})), OandaBadRequestError
        )
        assert isinstance(
            OandaResponsePolicy.error_from_response(FakeResponse(429, {})), OandaRateLimitError
        )
        assert isinstance(
            OandaResponsePolicy.error_from_response(FakeResponse(500, {})), OandaServerError
        )

    def test_error_from_response_extracts_transaction_reject_reason(self) -> None:
        error = OandaResponsePolicy.error_from_response(
            FakeResponse(
                400,
                {"orderRejectTransaction": {"reason": "INSUFFICIENT_MARGIN"}},
            )
        )

        assert error.error_code == "INSUFFICIENT_MARGIN"
        assert "INSUFFICIENT_MARGIN" in str(error)

    def test_retryable_status_and_status_parsing(self) -> None:
        assert OandaResponsePolicy.is_retryable_status(503)
        assert not OandaResponsePolicy.is_retryable_status(404)
        assert OandaResponsePolicy.status_code(FakeResponse(200, {})) == 200
        assert OandaResponsePolicy.status_code(object()) is None
