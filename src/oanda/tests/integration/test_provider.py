from __future__ import annotations

from typing import cast

from autoforex.oanda.accounts import OandaAccountManager
from autoforex.oanda.broker import OandaBroker
from autoforex.oanda.gateway import OandaGateway
from autoforex.oanda.provider import OandaProvider
from autoforex.oanda.source import OandaDataSource
from tests.integration.fakes import IntegrationGateway


class TestProvider:
    def test_provider_integrates_account_broker_and_source_services_without_http(self) -> None:
        gateway = IntegrationGateway()
        provider = OandaProvider(account_id="001", gateway=cast(OandaGateway, gateway))

        assert isinstance(provider.account_manager, OandaAccountManager)
        assert isinstance(provider.broker, OandaBroker)
        assert isinstance(provider.data, OandaDataSource)
        assert provider.account_manager.accounts is gateway.accounts
        assert provider.broker.gateway is gateway
        assert provider.data.pricing is gateway.pricing
