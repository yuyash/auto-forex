from __future__ import annotations

from typing import Any, cast

import pytest

from autoforex.oanda.errors import OandaAuthenticationError
from autoforex.oanda.gateway import OandaGateway
from tests.support import FakeHTTPResponse


class AuthErrorOpener:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    def open(self, request: Any, timeout: int) -> Any:
        from urllib.error import HTTPError

        _ = timeout
        self.requests.append(request)
        response = FakeHTTPResponse(
            401,
            {"errorCode": "UNAUTHORIZED", "errorMessage": "bad token"},
            reason="Unauthorized",
        )
        raise HTTPError(
            url="https://api.example.test/v3/accounts",
            code=401,
            msg="Unauthorized",
            hdrs=cast(Any, response.headers),
            fp=cast(Any, response),
        )


class TestErrors:
    def test_gateway_http_error_integrates_with_error_classification(self) -> None:
        gateway = OandaGateway(
            access_token="token",
            hostname="api.example.test",
            stream_hostname="stream.example.test",
            opener=AuthErrorOpener(),
        )

        with pytest.raises(OandaAuthenticationError):
            gateway.accounts.list_accounts()
