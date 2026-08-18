"""HTTP transport and retry policy for OANDA REST calls."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, TypeVar, cast, overload

from tenacity import (
    Retrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

import autoforex.oanda.models as om
from autoforex.oanda.config import OandaSettings
from autoforex.oanda.errors import (
    OandaConnectionError,
    OandaResponsePolicy,
    OandaRetryableApiError,
    OandaTimeoutError,
)
from autoforex.oanda.transport_codecs import OandaDuration, OandaTransportCodec
from autoforex.oanda.transport_http import (
    OandaHttpClient,
    OandaPersistentOpener,
    OandaRequestFactory,
    OandaUrlBuilder,
)

_LOGGER = logging.getLogger(__name__)
_RETRYABLE_EXCEPTIONS = (
    OandaConnectionError,
    OandaTimeoutError,
    OandaRetryableApiError,
)
_SUCCESS = (200,)

TModel = TypeVar("TModel", bound=om.OandaModel)


@dataclass(frozen=True, slots=True)
class OandaRetryPolicy:
    """Retry policy for retryable OANDA transport and API failures."""

    attempts: int = 3
    initial_delay: timedelta = timedelta(seconds=0.25)
    max_delay: timedelta = timedelta(seconds=4)
    multiplier: float = 2.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "initial_delay",
            OandaDuration.validate(
                self.initial_delay,
                name="retry initial delay",
                allow_zero=True,
            ),
        )
        object.__setattr__(
            self,
            "max_delay",
            OandaDuration.validate(
                self.max_delay,
                name="retry max delay",
                allow_zero=True,
            ),
        )
        if self.attempts < 1:
            msg = "retry attempts must be greater than or equal to 1"
            raise ValueError(msg)
        if self.multiplier < 1:
            msg = "retry multiplier must be greater than or equal to 1"
            raise ValueError(msg)

    @classmethod
    def from_settings(cls, settings: OandaSettings) -> OandaRetryPolicy:
        """Create a retry policy from OANDA settings."""
        return cls(
            attempts=settings.retry_attempts,
            initial_delay=settings.retry_initial_delay,
            max_delay=settings.retry_max_delay,
            multiplier=settings.retry_multiplier,
        )

    def retrying(self) -> Retrying:
        """Return a tenacity retry controller."""
        return Retrying(
            retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
            stop=stop_after_attempt(self.attempts),
            wait=wait_exponential(
                multiplier=self.initial_delay.total_seconds(),
                max=self.max_delay.total_seconds(),
                exp_base=self.multiplier,
            ),
            before_sleep=before_sleep_log(_LOGGER, logging.WARNING),
            reraise=True,
        )


class OandaTransport:
    """Low-level REST transport for the OANDA REST v20 API."""

    def __init__(
        self,
        *,
        access_token: str,
        hostname: str,
        stream_hostname: str,
        port: int = 443,
        ssl: bool = True,
        application: str = "AutoForexV2",
        poll_timeout: timedelta = timedelta(seconds=10),
        stream_timeout: timedelta = timedelta(seconds=60),
        retry_policy: OandaRetryPolicy | None = None,
        opener: Any | None = None,
        http_client: OandaHttpClient | None = None,
    ) -> None:
        self.access_token = access_token
        self.hostname = hostname
        self.stream_hostname = stream_hostname
        self.port = port
        self.ssl = ssl
        self.application = application
        self.poll_timeout = OandaDuration.validate(poll_timeout, name="poll_timeout")
        self.stream_timeout = OandaDuration.validate(stream_timeout, name="stream_timeout")
        self.retry_policy = retry_policy or OandaRetryPolicy()
        self.opener = opener or OandaPersistentOpener()
        self.urls = OandaUrlBuilder(
            hostname=hostname,
            stream_hostname=stream_hostname,
            port=port,
            ssl=ssl,
        )
        self.requests = OandaRequestFactory(
            access_token=access_token,
            application=application,
        )
        self.http = http_client or OandaHttpClient(
            opener=self.opener,
            urls=self.urls,
            requests=self.requests,
            poll_timeout=self.poll_timeout,
            stream_timeout=self.stream_timeout,
        )

    def datetime_to_str(self, value: Any) -> str:
        """Format a datetime value for OANDA query parameters."""
        return OandaTransportCodec.datetime_to_str(value)

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Any = None,
        body: Any = None,
        retry: bool = False,
    ) -> om.OandaResponse[dict[str, Any]]:
        """Execute a raw REST request and return a typed response wrapper."""
        return self.typed_request(
            method,
            path,
            dict,
            query=query,
            body=body,
            retry=retry,
        )

    @overload
    def typed_request(
        self,
        method: str,
        path: str,
        response_model: type[TModel],
        *,
        query: Any = None,
        body: Any = None,
        success_statuses: Iterable[int] = _SUCCESS,
        return_error_statuses: Iterable[int] = (),
        retry: bool = True,
    ) -> om.OandaResponse[TModel]: ...

    @overload
    def typed_request(
        self,
        method: str,
        path: str,
        response_model: type[dict[str, Any]],
        *,
        query: Any = None,
        body: Any = None,
        success_statuses: Iterable[int] = _SUCCESS,
        return_error_statuses: Iterable[int] = (),
        retry: bool = True,
    ) -> om.OandaResponse[dict[str, Any]]: ...

    def typed_request(
        self,
        method: str,
        path: str,
        response_model: type[TModel] | type[dict[str, Any]],
        *,
        query: Any = None,
        body: Any = None,
        success_statuses: Iterable[int] = _SUCCESS,
        return_error_statuses: Iterable[int] = (),
        retry: bool = True,
    ) -> om.OandaResponse[TModel] | om.OandaResponse[dict[str, Any]]:
        """Execute a REST request and parse the response into an OANDA model."""
        success = frozenset(success_statuses)
        allowed_errors = frozenset(return_error_statuses)

        def execute() -> om.OandaResponse[TModel] | om.OandaResponse[dict[str, Any]]:
            raw = self.http.send(method, path, query=query, body=body)
            if raw.status not in success and raw.status not in allowed_errors:
                raise OandaResponsePolicy.error_from_response(
                    om.OandaResponse(raw=raw, body=raw.body)
                )
            if response_model is dict:
                return om.OandaResponse(raw=raw, body=raw.body)
            model_cls = cast(type[TModel], response_model)
            return om.OandaResponse(raw=raw, body=model_cls.model_validate(raw.body))

        if retry:
            return self.retry(execute)
        return execute()

    def stream(
        self,
        method: str,
        path: str,
        *,
        query: Any = None,
        stream_kind: str,
    ) -> om.OandaResponse[None]:
        """Open a streaming request and return an OANDA stream wrapper."""

        def execute() -> om.OandaResponse[None]:
            raw = self.http.open_stream(method, path, query=query, stream_kind=stream_kind)
            if raw.status != 200:
                raise OandaResponsePolicy.error_from_response(om.OandaResponse(raw=raw, body={}))
            return om.OandaResponse(raw=raw, body=None)

        return self.retry(execute)

    def retry(self, operation: Callable[[], Any]) -> Any:
        """Execute an operation under the configured retry policy."""
        if self.retry_policy.attempts <= 1:
            return operation()
        return self.retry_policy.retrying()(operation)
