from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest

import autoforex.oanda.provider as provider_module
from autoforex.oanda import OANDA_PROVIDER
from autoforex.oanda.config import OandaSettings
from autoforex.oanda.gateway import OandaGateway
from autoforex.oanda.provider import OandaProvider


@dataclass
class AccountManagerFake:
    accounts: object


@dataclass
class AccountBoundServiceFake:
    account_id: str
    gateway: object


@dataclass
class DataSourceFake:
    account_id: str
    pricing: object
    time_formatter: object
    session: object


class TestProvider:
    def test_oanda_provider_bundles_mocked_services(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(provider_module, "OandaAccountManager", AccountManagerFake)
        monkeypatch.setattr(provider_module, "OandaBroker", AccountBoundServiceFake)
        monkeypatch.setattr(provider_module, "OandaDataSource", DataSourceFake)
        gateway = SimpleNamespace(accounts=object(), pricing=object(), transport=object())

        provider = OandaProvider(account_id="001", gateway=cast(OandaGateway, gateway))

        assert provider.provider == OANDA_PROVIDER
        assert provider.account_id == "001"
        assert provider.gateway is gateway
        assert isinstance(provider.account_manager, AccountManagerFake)
        assert isinstance(provider.broker, AccountBoundServiceFake)
        assert isinstance(provider.data, DataSourceFake)
        assert provider.account_manager.accounts is gateway.accounts
        assert provider.broker.gateway is gateway
        assert provider.data.pricing is gateway.pricing
        assert provider.data.time_formatter is gateway.transport
        assert provider.data.session is gateway.transport

    def test_oanda_provider_from_settings_uses_gateway_factory(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(provider_module, "OandaAccountManager", AccountManagerFake)
        monkeypatch.setattr(provider_module, "OandaBroker", AccountBoundServiceFake)
        monkeypatch.setattr(provider_module, "OandaDataSource", DataSourceFake)
        gateway = SimpleNamespace(accounts=object(), pricing=object(), transport=object())
        gateway_cls = Mock()
        gateway_cls.from_settings.return_value = gateway
        monkeypatch.setattr(provider_module, "OandaGateway", gateway_cls)
        settings = cast(OandaSettings, SimpleNamespace(account_id="001"))

        provider = OandaProvider.from_settings(settings)

        assert provider.gateway is gateway
        gateway_cls.from_settings.assert_called_once_with(settings)
