"""OANDA transaction service."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from autoforex.core import Metadata, Transaction

import autoforex.oanda.models as om
from autoforex.oanda.errors import OandaResponsePolicy
from autoforex.oanda.payload import OandaPayload as payload
from autoforex.oanda.services.protocols import (
    AccountCurrencyProvider,
    MapperFactory,
    OandaTimeFormatter,
    OandaTransactionClient,
)


class OandaTransactionService:
    """Transaction operations for one OANDA account."""

    def __init__(
        self,
        *,
        account_id: str,
        transactions: OandaTransactionClient,
        time_formatter: OandaTimeFormatter,
        account_currency: AccountCurrencyProvider,
        transaction_mapper_factory: MapperFactory,
    ) -> None:
        self.account_id = account_id
        self.transactions = transactions
        self.time_formatter = time_formatter
        self._account_currency = account_currency
        self._transaction_mapper_factory = transaction_mapper_factory

    def list_transactions(
        self,
        *,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        page_size: int | None = None,
        types: Iterable[str] | None = None,
    ) -> Metadata:
        """Return OANDA transaction page metadata."""
        response = OandaResponsePolicy.ensure_success(
            self.transactions.list_transactions(
                self.account_id,
                om.TransactionsRequest.model_validate(
                    payload.clean(
                        {
                            "from": self.format_time(from_time),
                            "to": self.format_time(to_time),
                            "pageSize": page_size,
                            "type": tuple(types) if types is not None else None,
                        }
                    )
                ),
            ),
            200,
        )
        return payload.metadata(response.body)

    def get_transaction(self, transaction_id: str) -> Transaction:
        """Return one OANDA transaction."""
        response = OandaResponsePolicy.ensure_success(
            self.transactions.get_transaction(self.account_id, transaction_id), 200
        )
        return self.mapper().transaction_from_response(response)

    def get_transaction_range(
        self,
        *,
        from_id: str | None = None,
        to_id: str | None = None,
        types: Iterable[str] | None = None,
    ) -> Sequence[Transaction]:
        """Return OANDA transactions by ID range."""
        response = OandaResponsePolicy.ensure_success(
            self.transactions.get_transaction_range(
                self.account_id,
                om.TransactionRangeRequest.model_validate(
                    payload.clean(
                        {
                            "from": from_id,
                            "to": to_id,
                            "type": tuple(types) if types is not None else None,
                        }
                    )
                ),
            ),
            200,
        )
        return self.mapper().transactions_from_response(response)

    def get_transactions_since(
        self,
        transaction_id: str,
        *,
        types: Iterable[str] | None = None,
    ) -> Sequence[Transaction]:
        """Return OANDA transactions since one transaction ID."""
        response = OandaResponsePolicy.ensure_success(
            self.transactions.get_transactions_since(
                self.account_id,
                om.TransactionsSinceRequest.model_validate(
                    payload.clean(
                        {
                            "id": transaction_id,
                            "type": tuple(types) if types is not None else None,
                        }
                    )
                ),
            ),
            200,
        )
        return self.mapper().transactions_from_response(response)

    def stream_transactions(self) -> Iterable[Transaction]:
        """Yield OANDA transaction stream updates."""
        response = self.transactions.stream_transactions(self.account_id)
        mapper = self.mapper()
        for part_type, value in response.parts():
            if part_type.endswith("Heartbeat"):
                continue
            yield mapper.transaction_from_oanda(value)

    def format_time(self, value: datetime | None) -> str | None:
        """Format an optional datetime for OANDA transaction queries."""
        if value is None:
            return None
        return self.time_formatter.datetime_to_str(value)

    def mapper(self) -> Any:
        """Create the mapper with the current account currency."""
        return self._transaction_mapper_factory(account_currency=self._account_currency())
