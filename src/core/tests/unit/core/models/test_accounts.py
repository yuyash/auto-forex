import pytest
from pydantic import ValidationError

from autoforex.core import Account, AccountId, AccountProvider, AccountSummary, Metadata, Money


class TestModels:
    def test_account_id_normalizes_non_empty_identifier(self) -> None:
        account_id = AccountId.of(" 001 ")

        assert account_id.value == "001"
        assert str(account_id) == "001"

    def test_account_models_broker_neutral_account_reference(self) -> None:
        account = Account(
            id=AccountId.of(" 001 "),
            provider=AccountProvider.of(" oanda "),
            alias=" primary ",
            metadata=Metadata.of(environment="practice"),
        )

        assert account.id == AccountId.of("001")
        assert account.provider == AccountProvider.of("oanda")
        assert account.alias == "primary"
        assert account.metadata == Metadata.of(environment="practice")
        assert str(account) == "oanda:001"
        assert account.model_dump(mode="json")["provider"] == "oanda"

    def test_account_rejects_blank_identifier(self) -> None:
        with pytest.raises(ValidationError, match="account identifier must not be blank"):
            Account(id=AccountId.of(" "))

    def test_account_rejects_blank_provider(self) -> None:
        with pytest.raises(ValidationError):
            Account(id=AccountId.of("001"), provider=AccountProvider.of(" "))

    def test_account_summary_normalizes_money_fields(self) -> None:
        summary = AccountSummary.model_validate(
            {
                "account_id": "001",
                "currency": "USD",
                "alias": " primary ",
                "balance": "1000.25",
                "nav": "1001.50",
                "margin_used": "10",
                "margin_available": "990",
                "margin_rate": "0.02",
                "open_trade_count": 1,
                "open_position_count": 1,
                "pending_order_count": 0,
                "last_transaction_id": " 123 ",
            }
        )

        assert summary.account_id == AccountId.of("001")
        assert summary.alias == "primary"
        assert summary.balance == Money.of("1000.25", "USD")
        assert summary.nav == Money.of("1001.50", "USD")
        assert summary.last_transaction_id == "123"
