from __future__ import annotations

from typing import cast

from autoforex.core import AccountId, CurrencyPair, MarginRate, Money

from autoforex.oanda.accounts import OandaAccountClient, OandaAccountManager
from tests.integration.fakes import IntegrationGateway


class TestAccounts:
    def test_account_manager_integrates_gateway_and_mappers_without_http(self) -> None:
        gateway = IntegrationGateway()
        account_id = AccountId.of("001")
        manager = OandaAccountManager(accounts=cast(OandaAccountClient, gateway.accounts))

        accounts = manager.list_accounts()
        summary = manager.get_account_summary(account_id)
        instruments = manager.get_account_instruments(account_id)
        configured = manager.configure_account(
            account_id, alias="primary", margin_rate=MarginRate("0.03")
        )
        changes = manager.get_account_changes(account_id, since_transaction_id="10")

        assert accounts[0].id.value == "001"
        assert summary.balance == Money.of("1000.00", "USD")
        assert instruments == (CurrencyPair.of("USD_JPY"),)
        assert configured.metadata["lastTransactionID"] == "11"
        assert changes["lastTransactionID"] == "12"
