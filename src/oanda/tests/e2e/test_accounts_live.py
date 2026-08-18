from __future__ import annotations

from autoforex.core import AccountId

from autoforex.oanda import OandaProvider, OandaSettings
from tests.e2e.coverage import covers_endpoints


class TestAccountsLive:
    @covers_endpoints("accounts.list_accounts")
    def test_live_list_accounts(
        self,
        oanda_provider: OandaProvider,
        oanda_settings: OandaSettings,
    ) -> None:
        accounts = oanda_provider.accounts.list_accounts()

        assert any(item.id.value == oanda_settings.account_id for item in accounts)

    @covers_endpoints("accounts.get_account")
    def test_live_get_account(
        self,
        oanda_provider: OandaProvider,
        oanda_settings: OandaSettings,
    ) -> None:
        account = oanda_provider.accounts.get_account(AccountId.of(oanda_settings.account_id))

        assert account.id.value == oanda_settings.account_id

    @covers_endpoints("accounts.get_account_summary")
    def test_live_get_account_summary(
        self,
        oanda_provider: OandaProvider,
        oanda_settings: OandaSettings,
    ) -> None:
        summary = oanda_provider.accounts.get_account_summary(
            AccountId.of(oanda_settings.account_id)
        )

        assert summary.account_id.value == oanda_settings.account_id

    @covers_endpoints("accounts.get_account_instruments")
    def test_live_get_account_instruments(
        self,
        oanda_provider: OandaProvider,
        oanda_settings: OandaSettings,
    ) -> None:
        instruments = oanda_provider.accounts.get_account_instruments(
            AccountId.of(oanda_settings.account_id)
        )

        assert instruments

    @covers_endpoints("accounts.get_account_changes")
    def test_live_get_account_changes(
        self,
        oanda_provider: OandaProvider,
        oanda_settings: OandaSettings,
    ) -> None:
        account_id = AccountId.of(oanda_settings.account_id)
        account = oanda_provider.accounts.get_account(account_id)
        summary = oanda_provider.accounts.get_account_summary(account_id)
        changes = oanda_provider.accounts.get_account_changes(
            account_id,
            since_transaction_id=summary.last_transaction_id or "1",
        )

        assert account.id.value == oanda_settings.account_id
        assert "lastTransactionID" in changes
