"""Facade for OANDA REST v20 endpoint clients."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from autoforex.oanda.config import OandaSettings
from autoforex.oanda.gateways.clients import (
    OandaAccountsApi,
    OandaOrdersApi,
    OandaPositionsApi,
    OandaPricingApi,
    OandaTradesApi,
    OandaTransactionsApi,
)
from autoforex.oanda.transport import OandaRetryPolicy, OandaTransport


class OandaGateway:
    """Facade that composes OANDA REST v20 endpoint clients."""

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
        transport: OandaTransport | None = None,
    ) -> None:
        self.transport = transport or OandaTransport(
            access_token=access_token,
            hostname=hostname,
            stream_hostname=stream_hostname,
            port=port,
            ssl=ssl,
            application=application,
            poll_timeout=poll_timeout,
            stream_timeout=stream_timeout,
            retry_policy=retry_policy,
            opener=opener,
        )
        self.accounts = OandaAccountsApi(self.transport)
        self.orders = OandaOrdersApi(self.transport)
        self.positions = OandaPositionsApi(self.transport)
        self.pricing = OandaPricingApi(self.transport)
        self.trades = OandaTradesApi(self.transport)
        self.transactions = OandaTransactionsApi(self.transport)

    @classmethod
    def from_settings(cls, settings: OandaSettings) -> OandaGateway:
        """Create a gateway from OANDA settings."""
        return cls(
            access_token=settings.access_token.get_secret_value(),
            hostname=settings.resolved_hostname,
            stream_hostname=settings.resolved_stream_hostname,
            port=settings.port,
            ssl=settings.ssl,
            application=settings.application,
            stream_timeout=settings.stream_timeout,
            poll_timeout=settings.poll_timeout,
            retry_policy=OandaRetryPolicy.from_settings(settings),
        )

    @property
    def access_token(self) -> str:
        """Return the configured OANDA access token."""
        return self.transport.access_token

    @property
    def hostname(self) -> str:
        """Return the REST API hostname."""
        return self.transport.hostname

    @property
    def stream_hostname(self) -> str:
        """Return the streaming API hostname."""
        return self.transport.stream_hostname

    @property
    def port(self) -> int:
        """Return the API port."""
        return self.transport.port

    @property
    def ssl(self) -> bool:
        """Return whether HTTPS is enabled."""
        return self.transport.ssl

    @property
    def application(self) -> str:
        """Return the User-Agent application name."""
        return self.transport.application

    @property
    def poll_timeout(self) -> timedelta:
        """Return the non-streaming request timeout."""
        return self.transport.poll_timeout

    @property
    def stream_timeout(self) -> timedelta:
        """Return the streaming request timeout."""
        return self.transport.stream_timeout

    @property
    def retry_policy(self) -> OandaRetryPolicy:
        """Return the retry policy."""
        return self.transport.retry_policy


__all__ = ["OandaGateway", "OandaRetryPolicy"]
