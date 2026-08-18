from __future__ import annotations

from unittest.mock import Mock
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest
from requests import Response, Session
from requests.exceptions import ConnectTimeout, ReadTimeout

from autoforex.oanda.transport import OandaTransport
from autoforex.oanda.transport_http import OandaPersistentOpener


def response(status: int = 200, body: bytes = b"{}") -> Response:
    value = Response()
    value.status_code = status
    value.reason = "OK" if status < 400 else "Unauthorized"
    value.headers["Content-Type"] = "application/json"
    value._content = body
    return value


class TestOandaPersistentOpener:
    def test_default_transport_uses_persistent_opener(self) -> None:
        transport = OandaTransport(
            access_token="token",
            hostname="api.example.test",
            stream_hostname="stream.example.test",
        )

        assert isinstance(transport.opener, OandaPersistentOpener)
        transport.opener.close()

    def test_reuses_one_session_for_multiple_requests(self) -> None:
        session = Mock(spec=Session)
        session.request.side_effect = [response(), response()]
        opener = OandaPersistentOpener(session=session)
        request = Request(
            "https://api.example.test/v3/accounts",
            headers={"Authorization": "Bearer token"},
        )

        first = opener.open(request, timeout=10)
        second = opener.open(request, timeout=10)
        opener.close()

        assert first.read() == b"{}"
        assert second.read() == b"{}"
        assert session.request.call_count == 2
        assert all(call.kwargs["stream"] is True for call in session.request.call_args_list)
        session.close.assert_called_once_with()

    def test_converts_http_error_to_urllib_error(self) -> None:
        session = Mock(spec=Session)
        session.request.return_value = response(401, b'{"errorMessage":"unauthorized"}')
        opener = OandaPersistentOpener(session=session)

        with pytest.raises(HTTPError) as exc_info:
            opener.open(Request("https://api.example.test/v3/accounts"), timeout=10)

        assert exc_info.value.code == 401
        assert exc_info.value.read() == b'{"errorMessage":"unauthorized"}'

    def test_converts_read_timeout_to_builtin_timeout(self) -> None:
        session = Mock(spec=Session)
        session.request.side_effect = ReadTimeout("read timed out")
        opener = OandaPersistentOpener(session=session)

        with pytest.raises(TimeoutError, match="read timed out"):
            opener.open(Request("https://api.example.test/v3/accounts"), timeout=10)

    def test_converts_connect_timeout_to_url_error(self) -> None:
        session = Mock(spec=Session)
        session.request.side_effect = ConnectTimeout("connect timed out")
        opener = OandaPersistentOpener(session=session)

        with pytest.raises(URLError) as exc_info:
            opener.open(Request("https://api.example.test/v3/accounts"), timeout=10)

        assert isinstance(exc_info.value.reason, TimeoutError)
