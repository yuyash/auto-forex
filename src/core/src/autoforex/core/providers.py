"""Provider service bundle abstractions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from autoforex.core.models import AccountProvider
from autoforex.core.ports import AccountManager, Broker
from autoforex.core.sources import DataSource


@dataclass(frozen=True, slots=True)
class TradingProvider:
    """Bundle of provider-specific services."""

    _provider: AccountProvider
    _account_manager: AccountManager
    _broker: Broker
    _data: DataSource

    def __init__(
        self,
        *,
        provider: AccountProvider,
        account_manager: AccountManager,
        broker: Broker,
        data: DataSource,
    ) -> None:
        object.__setattr__(self, "_provider", provider)
        object.__setattr__(self, "_account_manager", account_manager)
        object.__setattr__(self, "_broker", broker)
        object.__setattr__(self, "_data", data)

    @property
    def provider(self) -> AccountProvider:
        """Return the provider identifier."""
        return self._provider

    @property
    def accounts(self) -> AccountManager:
        """Alias for account-related operations."""
        return self._account_manager

    @property
    def account_manager(self) -> AccountManager:
        """Return the account service."""
        return self._account_manager

    @property
    def broker(self) -> Broker:
        """Return the broker service."""
        return self._broker

    @property
    def data(self) -> DataSource:
        """Return the market-data service."""
        return self._data

    def close(self) -> None:
        """Close bundled services that expose a ``close`` method."""
        for service in (self._data, self._broker, self._account_manager):
            close = getattr(service, "close", None)
            if callable(close):
                close_fn: Callable[[], Any] = close
                close_fn()
