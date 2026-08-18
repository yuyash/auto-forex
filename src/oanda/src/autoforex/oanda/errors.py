"""OANDA adapter exceptions and response classification."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

RETRYABLE_STATUSES = frozenset({408, 429, 500, 502, 503, 504})


class OandaAdapterError(RuntimeError):
    """Base exception raised by the OANDA adapter."""


class OandaTransportError(OandaAdapterError):
    """Raised when the adapter cannot complete the HTTP transport operation."""

    def __init__(self, message: str, *, url: str = "") -> None:
        self.url = url
        super().__init__(message)


class OandaConnectionError(OandaTransportError):
    """Raised when connecting to OANDA fails."""


class OandaTimeoutError(OandaTransportError):
    """Raised when an OANDA request times out."""

    def __init__(self, message: str, *, url: str = "", timeout_type: str = "") -> None:
        self.timeout_type = timeout_type
        super().__init__(message, url=url)


class OandaApiError(OandaAdapterError):
    """Raised when OANDA returns an unsuccessful response."""

    def __init__(
        self,
        *,
        status: int | str | None,
        reason: str = "",
        error_code: str = "",
        error_message: str = "",
    ) -> None:
        self.status = status
        self.reason = reason
        self.error_code = error_code
        self.error_message = error_message
        message = f"OANDA API request failed with status {status}"
        if error_code:
            message = f"{message} ({error_code})"
        if error_message:
            message = f"{message}: {error_message}"
        elif reason:
            message = f"{message}: {reason}"
        super().__init__(message)

    @classmethod
    def from_response(cls, response: Any) -> OandaApiError:
        """Create an API error from an OANDA response object."""
        body = getattr(response, "body", None) or {}
        error_code = cls._extract_error_code(body)
        error_message = cls._extract_error_message(body)
        return cls(
            status=getattr(response, "status", None),
            reason=str(getattr(response, "reason", "") or ""),
            error_code=str(error_code or ""),
            error_message=str(error_message or ""),
        )

    @classmethod
    def _extract_error_code(cls, body: Any) -> Any:
        direct_code = cls._get(body, "errorCode", "")
        if direct_code:
            return direct_code
        return cls._extract_transaction_reason(body)

    @classmethod
    def _extract_error_message(cls, body: Any) -> Any:
        direct_message = cls._get(body, "errorMessage", "")
        if direct_message:
            return direct_message
        return cls._extract_transaction_reason(body)

    @classmethod
    def _extract_transaction_reason(cls, body: Any) -> Any:
        for key in (
            "orderRejectTransaction",
            "longOrderRejectTransaction",
            "shortOrderRejectTransaction",
            "tradeClientExtensionsModifyRejectTransaction",
            "orderClientExtensionsModifyRejectTransaction",
            "transaction",
        ):
            transaction = cls._get(body, key)
            reason = cls._get(transaction, "reason", "")
            if reason:
                return reason
        return ""

    @classmethod
    def _get(cls, data: Any, key: str, default: Any = None) -> Any:
        if isinstance(data, Mapping):
            if key in data:
                return data[key]
            return data.get(cls._snake(key), default)
        if hasattr(data, key):
            return getattr(data, key)
        return getattr(data, cls._snake(key), default)

    @staticmethod
    def _snake(name: str) -> str:
        value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
        value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
        return value.lower()


class OandaClientError(OandaApiError):
    """Raised when OANDA rejects a client-side request."""


class OandaBadRequestError(OandaClientError):
    """Raised when OANDA returns HTTP 400."""


class OandaAuthenticationError(OandaClientError):
    """Raised when OANDA returns HTTP 401."""


class OandaAuthorizationError(OandaClientError):
    """Raised when OANDA returns HTTP 403."""


class OandaNotFoundError(OandaClientError):
    """Raised when OANDA returns HTTP 404."""


class OandaRetryableApiError(OandaApiError):
    """Raised when OANDA returns an API error that can be retried."""


class OandaRateLimitError(OandaRetryableApiError):
    """Raised when OANDA returns HTTP 429."""


class OandaServerError(OandaRetryableApiError):
    """Raised when OANDA returns a 5xx response."""


class OandaResponsePolicy:
    """Classify OANDA HTTP responses and enforce expected statuses."""

    retryable_statuses = RETRYABLE_STATUSES

    @classmethod
    def ensure_success(cls, response: Any, *statuses: int) -> Any:
        """Return response when its status matches one of the expected statuses."""
        status = cls.status_code(response)
        if statuses:
            expected = set(statuses)
            if status not in expected:
                raise cls.error_from_response(response)
            return response
        if status is None or status < 200 or status >= 300:
            raise cls.error_from_response(response)
        return response

    @classmethod
    def error_from_response(cls, response: Any) -> OandaApiError:
        """Create the most specific adapter exception for an OANDA response."""
        status = cls.status_code(response)
        if status == 400:
            return OandaBadRequestError.from_response(response)
        if status == 401:
            return OandaAuthenticationError.from_response(response)
        if status == 403:
            return OandaAuthorizationError.from_response(response)
        if status == 404:
            return OandaNotFoundError.from_response(response)
        if status == 429:
            return OandaRateLimitError.from_response(response)
        if status is not None and 500 <= status < 600:
            return OandaServerError.from_response(response)
        if cls.is_retryable_status(status):
            return OandaRetryableApiError.from_response(response)
        return OandaApiError.from_response(response)

    @classmethod
    def is_retryable_status(cls, status: int | None) -> bool:
        """Return whether an HTTP response status should be retried."""
        return status in cls.retryable_statuses

    @classmethod
    def status_code(cls, response: Any) -> int | None:
        """Return a response status as an integer when possible."""
        try:
            return int(getattr(response, "status", ""))
        except TypeError, ValueError:
            return None
