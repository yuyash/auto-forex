from __future__ import annotations

from autoforex.core import AccountId

from autoforex.oanda import OandaProvider, OandaSettings


class TestProviderLive:
    def test_live_provider_bundles_services_and_reaches_account_summary(
        self,
        oanda_provider: OandaProvider,
        oanda_settings: OandaSettings,
    ) -> None:
        summary = oanda_provider.accounts.get_account_summary(
            AccountId.of(oanda_settings.account_id)
        )
        account_manager = oanda_provider.account_manager
        broker = oanda_provider.broker
        data_source = oanda_provider.data

        assert account_manager.accounts is broker.gateway.accounts
        assert data_source.pricing is broker.gateway.pricing
        assert summary.account_id.value == oanda_settings.account_id
