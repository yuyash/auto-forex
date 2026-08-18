from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from autoforex.core import Account, AccountId, AccountSummary, CurrencyPair, MarginRate, Metadata

import autoforex.oanda.models as om
from autoforex.oanda import OANDA_PROVIDER
from autoforex.oanda.accounts import OandaAccountManager
from tests.support import FakeResponse


class TestAccounts:
    def test_account_manager_delegates_account_reads_to_gateway_and_mapper(self) -> None:
        accounts = Mock()
        mapper = Mock()
        account = Account(id=AccountId.of("001"), provider=OANDA_PROVIDER)
        summary = AccountSummary.model_validate({"account_id": "001", "currency": "USD"})
        accounts.list_accounts.return_value = FakeResponse(
            200,
            {"accounts": [SimpleNamespace(id="001")]},
        )
        accounts.get_account.return_value = FakeResponse(
            200, {"account": SimpleNamespace(id="001")}
        )
        accounts.get_account_summary.return_value = FakeResponse(200, {"account": {}})
        mapper.account_from_properties.return_value = account
        mapper.summary_from_response.return_value = summary
        account_id = AccountId.of("001")
        manager = OandaAccountManager(accounts=accounts, mapper=mapper)

        assert manager.list_accounts() == (account,)
        assert manager.get_account(account_id) == account
        assert manager.get_account_summary(account_id) == summary
        accounts.list_accounts.assert_called_once_with()
        accounts.get_account.assert_called_once_with("001")
        accounts.get_account_summary.assert_called_once_with("001")

    def test_account_manager_builds_instruments_and_configuration_requests(self) -> None:
        accounts = Mock()
        mapper = Mock()
        accounts.get_account_instruments.return_value = FakeResponse(
            200,
            {
                "instruments": [
                    SimpleNamespace(name="USD_JPY"),
                    SimpleNamespace(name="EUR_USD"),
                ]
            },
        )
        accounts.configure_account.return_value = FakeResponse(
            200,
            {"lastTransactionID": "10"},
        )
        account_id = AccountId.of("001")
        manager = OandaAccountManager(accounts=accounts, mapper=mapper)

        instruments = manager.get_account_instruments(account_id)
        configured = manager.configure_account(
            account_id,
            alias="primary",
            margin_rate=MarginRate("0.03"),
        )

        assert instruments == (CurrencyPair.of("USD_JPY"), CurrencyPair.of("EUR_USD"))
        accounts.get_account_instruments.assert_called_once_with("001")
        accounts.configure_account.assert_called_once_with(
            "001",
            om.ConfigureAccountRequest.model_validate({"alias": "primary", "marginRate": "0.03"}),
            retry=True,
        )
        assert configured.provider == OANDA_PROVIDER
        assert configured.metadata == Metadata.of(lastTransactionID="10")

    def test_account_manager_get_account_changes_returns_metadata(self) -> None:
        accounts = Mock()
        mapper = Mock()
        accounts.get_account_changes.return_value = FakeResponse(
            200,
            {"lastTransactionID": "11", "state": {"NAV": "1000"}},
        )
        account_id = AccountId.of("001")
        manager = OandaAccountManager(accounts=accounts, mapper=mapper)

        changes = manager.get_account_changes(account_id, since_transaction_id="10")

        accounts.get_account_changes.assert_called_once_with(
            "001",
            om.AccountChangesRequest.model_validate({"sinceTransactionID": "10"}),
        )
        assert changes["lastTransactionID"] == "11"
