"""Account management implementation backed by OANDA v20."""

from __future__ import annotations

from typing import Protocol

from autoforex.core import (
    Account,
    AccountId,
    AccountManager,
    AccountSummary,
    CurrencyPair,
    MarginRate,
    Metadata,
)

import autoforex.oanda.models as om
from autoforex.oanda.config import OandaSettings
from autoforex.oanda.constants import OANDA_PROVIDER
from autoforex.oanda.errors import OandaResponsePolicy
from autoforex.oanda.gateway import OandaGateway
from autoforex.oanda.mappers import OandaAccountMapper, OandaInstrumentMapper
from autoforex.oanda.payload import OandaPayload as payload


class OandaAccountClient(Protocol):
    """OANDA account endpoint methods required by the account manager."""

    def list_accounts(self) -> om.OandaResponse[om.AccountsResponse]: ...
    def get_account(self, account_id: str) -> om.OandaResponse[om.AccountResponse]: ...
    def get_account_summary(
        self,
        account_id: str,
    ) -> om.OandaResponse[om.AccountSummaryResponse]: ...
    def get_account_instruments(
        self,
        account_id: str,
        request: om.AccountInstrumentsRequest | None = None,
    ) -> om.OandaResponse[om.AccountInstrumentsResponse]: ...
    def configure_account(
        self,
        account_id: str,
        request: om.ConfigureAccountRequest,
        *,
        retry: bool = False,
    ) -> om.OandaResponse[om.ConfigureAccountResponse]: ...
    def get_account_changes(
        self,
        account_id: str,
        request: om.AccountChangesRequest,
    ) -> om.OandaResponse[om.AccountChangesResponse]: ...


class OandaAccountManager(AccountManager):
    """Account manager port implementation backed by OANDA v20."""

    def __init__(
        self,
        *,
        accounts: OandaAccountClient,
        mapper: OandaAccountMapper | None = None,
    ) -> None:
        self.accounts = accounts
        self.mapper = mapper or OandaAccountMapper()

    @classmethod
    def from_settings(cls, settings: OandaSettings) -> OandaAccountManager:
        """Create an OANDA account manager from settings."""
        gateway = OandaGateway.from_settings(settings)
        return cls(
            accounts=gateway.accounts,
        )

    def list_accounts(self) -> tuple[Account, ...]:
        """Return accounts authorized for the configured token."""
        response = OandaResponsePolicy.ensure_success(self.accounts.list_accounts(), 200)
        accounts = payload.get(response.body, "accounts", ()) or ()
        return tuple(self.mapper.account_from_properties(account) for account in accounts)

    def get_account(self, account_id: AccountId) -> Account:
        """Return a full OANDA account as a Core account reference."""
        response = OandaResponsePolicy.ensure_success(
            self.accounts.get_account(str(account_id)), 200
        )
        account = payload.get(response.body, "account")
        return self.mapper.account_from_properties(account)

    def get_account_summary(self, account_id: AccountId) -> AccountSummary:
        """Return an OANDA account summary as a Core account summary."""
        response = OandaResponsePolicy.ensure_success(
            self.accounts.get_account_summary(str(account_id)),
            200,
        )
        return self.mapper.summary_from_response(response)

    def get_account_instruments(self, account_id: AccountId) -> tuple[CurrencyPair, ...]:
        """Return tradable instruments for an account."""
        response = OandaResponsePolicy.ensure_success(
            self.accounts.get_account_instruments(str(account_id)),
            200,
        )
        items = payload.get(response.body, "instruments", ()) or ()
        return tuple(
            pair
            for item in items
            if (pair := OandaInstrumentMapper.to_core_or_none(payload.get(item, "name")))
            is not None
        )

    def configure_account(
        self,
        account_id: AccountId,
        *,
        alias: str | None = None,
        margin_rate: MarginRate | None = None,
    ) -> Account:
        """Update OANDA account alias or margin rate."""
        request: dict[str, str] = {}
        if alias is not None:
            request["alias"] = alias
        if margin_rate is not None:
            request["marginRate"] = str(margin_rate)
        response = OandaResponsePolicy.ensure_success(
            self.accounts.configure_account(
                str(account_id),
                om.ConfigureAccountRequest.model_validate(request),
                retry=True,
            ),
            200,
        )
        body = payload.metadata(response.body)
        return Account(
            id=account_id,
            provider=OANDA_PROVIDER,
            alias=alias,
            metadata=body,
        )

    def get_account_changes(
        self,
        account_id: AccountId,
        *,
        since_transaction_id: str,
    ) -> Metadata:
        """Return raw OANDA account changes metadata."""
        response = OandaResponsePolicy.ensure_success(
            self.accounts.get_account_changes(
                str(account_id),
                om.AccountChangesRequest.model_validate(
                    {"sinceTransactionID": since_transaction_id}
                ),
            ),
            200,
        )
        return payload.metadata(response.body)
