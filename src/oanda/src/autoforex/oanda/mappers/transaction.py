"""Transaction mapping between OANDA payloads and Core domain models."""

from __future__ import annotations

from autoforex.core import (
    AccountId,
    BrokerOrderId,
    BrokerTransactionId,
    Currency,
    CurrencyPair,
    Money,
    Transaction,
)

import autoforex.oanda.models as om
from autoforex.oanda.payload import OandaPayload as payload
from autoforex.oanda.snapshots import OandaTransaction


class OandaTransactionMapper:
    """Map OANDA transaction objects into Core transaction snapshots."""

    def __init__(self, *, account_currency: Currency) -> None:
        self.account_currency = account_currency

    def transaction_from_response(
        self,
        response: om.OandaResponse[om.TransactionResponse],
    ) -> Transaction:
        """Convert an OANDA transaction response into one Core transaction."""
        return self.transaction_from_oanda(payload.get(payload.body(response), "transaction"))

    def transactions_from_response(
        self,
        response: om.OandaResponse[om.TransactionsResponse],
    ) -> tuple[Transaction, ...]:
        """Convert an OANDA transactions response into Core transactions."""
        transactions = payload.get(payload.body(response), "transactions", ()) or ()
        return tuple(self.transaction_from_oanda(item) for item in transactions)

    def transaction_from_oanda(self, item: object) -> Transaction:
        """Convert one OANDA transaction into a Core transaction."""
        instrument = payload.get(item, "instrument")
        account_id = payload.get(item, "accountID")
        order_id = payload.get(item, "orderID")
        amount = payload.first(item, "amount", "pl", "financing", "commission")
        transaction = Transaction(
            id=BrokerTransactionId.of(str(payload.get(item, "id"))),
            account_id=AccountId.of(str(account_id)) if account_id is not None else None,
            time=payload.parse_time(payload.get(item, "time"))
            if payload.get(item, "time") is not None
            else None,
            type=str(payload.get(item, "type", "UNKNOWN")),
            instrument=CurrencyPair.of(str(instrument)) if instrument is not None else None,
            order_id=BrokerOrderId.of(str(order_id)) if order_id is not None else None,
            amount=Money.of(amount, self.account_currency) if amount is not None else None,
            metadata=payload.metadata(item),
        )
        return OandaTransaction(
            transaction=transaction,
            user_id=payload.get(item, "userID"),
            batch_id=payload.get(item, "batchID"),
            request_id=payload.get(item, "requestID"),
            reason=payload.get(item, "reason"),
            reject_reason=payload.get(item, "rejectReason"),
            related_transaction_ids=tuple(payload.get(item, "relatedTransactionIDs", ()) or ()),
        ).transaction
