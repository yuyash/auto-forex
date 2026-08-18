"""Account mapping between OANDA payloads and Core domain models."""

from __future__ import annotations

from autoforex.core import Account, AccountId, AccountSummary, Currency, MarginRate, Money

import autoforex.oanda.models as om
from autoforex.oanda.payload import OandaPayload as payload
from autoforex.oanda.snapshots import OandaAccount, OandaAccountSummary


class OandaAccountMapper:
    """Map OANDA account objects into Core value objects."""

    @staticmethod
    def account_from_properties(item: object) -> Account:
        """Convert OANDA account properties into a normalized account."""
        return OandaAccount(
            account=Account(
                id=AccountId.of(str(payload.get(item, "id"))),
                alias=payload.get(item, "alias"),
            ),
            mt4_account_id=payload.get(item, "mt4AccountID"),
            tags=tuple(payload.get(item, "tags", ()) or ()),
        ).account

    @staticmethod
    def summary_from_response(
        response: om.OandaResponse[om.AccountSummaryResponse],
    ) -> AccountSummary:
        """Convert an OANDA account summary response into a normalized summary."""
        body = payload.body(response)
        account = payload.get(body, "account")
        currency = Currency.of(str(payload.get(account, "currency")))
        return OandaAccountSummary(
            summary=AccountSummary(
                account_id=AccountId.of(str(payload.get(account, "id"))),
                currency=currency,
                alias=payload.get(account, "alias"),
                balance=Money.of(payload.get(account, "balance"), currency),
                nav=Money.of(payload.get(account, "NAV"), currency),
                margin_used=Money.of(payload.get(account, "marginUsed"), currency),
                margin_available=Money.of(payload.get(account, "marginAvailable"), currency),
                margin_rate=MarginRate.of(payload.decimal(payload.get(account, "marginRate")))
                if payload.get(account, "marginRate") is not None
                else None,
                open_trade_count=payload.get(account, "openTradeCount"),
                open_position_count=payload.get(account, "openPositionCount"),
                pending_order_count=payload.get(account, "pendingOrderCount"),
                last_transaction_id=payload.get(body, "lastTransactionID"),
                created_at=payload.parse_time(payload.get(account, "createdTime"))
                if payload.get(account, "createdTime") is not None
                else None,
            ),
            financing_mode=payload.get(account, "financingMode"),
            hedging_enabled=payload.get(account, "hedgingEnabled"),
            position_aggregation_mode=payload.get(account, "positionAggregationMode"),
            guaranteed_stop_loss_order_mode=payload.get(account, "guaranteedStopLossOrderMode"),
            withdrawal_limit=Money.of(payload.get(account, "withdrawalLimit"), currency)
            if payload.get(account, "withdrawalLimit") is not None
            else None,
        ).summary

    @staticmethod
    def account_currency_from_response(
        response: om.OandaResponse[om.AccountSummaryResponse],
    ) -> Currency:
        """Return the account home currency from an account summary response."""
        account = payload.get(payload.body(response), "account")
        currency = payload.get(account, "currency")
        if currency is None:
            msg = "OANDA account summary response does not include account currency"
            raise ValueError(msg)
        return Currency.of(str(currency))
