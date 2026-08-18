"""Core Broker implementation backed by OANDA v20."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from decimal import Decimal

from autoforex.core import (
    Broker,
    BrokerMutation,
    BrokerMutationOperation,
    BrokerOrderId,
    BrokerReconciliation,
    BrokerReconciliationOutcome,
    Currency,
    CurrencyPair,
    Metadata,
    Money,
    Order,
    OrderSide,
    OrderStatus,
    Position,
    PositionSide,
    Trade,
    Transaction,
    Units,
)

from autoforex.oanda.config import OandaSettings
from autoforex.oanda.errors import OandaNotFoundError, OandaResponsePolicy
from autoforex.oanda.gateway import OandaGateway
from autoforex.oanda.mappers import (
    OandaAccountMapper,
    OandaOrderMapper,
    OandaPositionMapper,
    OandaTradeMapper,
    OandaTransactionMapper,
)
from autoforex.oanda.services.orders import OandaOrderService
from autoforex.oanda.services.positions import OandaPositionService
from autoforex.oanda.services.trades import OandaTradeService
from autoforex.oanda.services.transactions import OandaTransactionService


class OandaBroker(Broker):
    """Broker port implementation that executes orders through OANDA v20."""

    def __init__(
        self,
        *,
        account_id: str,
        gateway: OandaGateway,
        account_mapper: OandaAccountMapper | None = None,
        order_mapper: OandaOrderMapper | None = None,
    ) -> None:
        self.account_id = account_id
        self.gateway = gateway
        self.account_mapper = account_mapper or OandaAccountMapper()
        self.order_mapper = order_mapper or OandaOrderMapper()
        self._account_currency: Currency | None = None
        self._orders = OandaOrderService(
            account_id=account_id,
            orders=gateway.orders,
            positions=gateway.positions,
            order_mapper=self.order_mapper,
        )
        self._positions = OandaPositionService(
            account_id=account_id,
            positions=gateway.positions,
            account_currency=lambda: self.account_currency,
            position_mapper_factory=OandaPositionMapper,
        )
        self._trades = OandaTradeService(
            account_id=account_id,
            trades=gateway.trades,
            account_currency=lambda: self.account_currency,
            trade_mapper_factory=OandaTradeMapper,
            order_mapper=self.order_mapper,
        )
        self._transactions = OandaTransactionService(
            account_id=account_id,
            transactions=gateway.transactions,
            time_formatter=gateway.transport,
            account_currency=lambda: self.account_currency,
            transaction_mapper_factory=OandaTransactionMapper,
        )

    @classmethod
    def from_settings(cls, settings: OandaSettings) -> OandaBroker:
        """Create an OANDA broker from settings."""
        return cls(
            account_id=settings.account_id,
            gateway=OandaGateway.from_settings(settings),
        )

    @property
    def account_currency(self) -> Currency:
        """Return the OANDA account home currency, loaded from account summary."""
        if self._account_currency is None:
            response = OandaResponsePolicy.ensure_success(
                self.gateway.accounts.get_account_summary(self.account_id), 200
            )
            self._account_currency = self.account_mapper.account_currency_from_response(response)
        return self._account_currency

    def place_order(self, order: Order) -> Order:
        """Place an order through OANDA."""
        return self._orders.place_order(order)

    def close_position(
        self,
        *,
        position: Position,
        side: PositionSide,
        units: Units | None = None,
    ) -> Order:
        """Close all or part of an OANDA position."""
        return self._orders.close_position(position=position, side=side, units=units)

    def positions(self, *, instrument: CurrencyPair | None = None) -> Sequence[Position]:
        """Return open OANDA positions."""
        return self._positions.positions(instrument=instrument)

    def trades(self, *, instrument: CurrencyPair | None = None) -> Sequence[Trade]:
        """Return OANDA trades."""
        trades = self._trades.list_trades()
        if instrument is None:
            return trades
        return tuple(trade for trade in trades if trade.instrument == instrument)

    def open_trades(self, *, instrument: CurrencyPair | None = None) -> Sequence[Trade]:
        """Return open OANDA trades."""
        trades = self._trades.list_open_trades()
        if instrument is None:
            return trades
        return tuple(trade for trade in trades if trade.instrument == instrument)

    def list_orders(self, **filters: object) -> Sequence[Metadata]:
        """Return OANDA orders as raw metadata snapshots."""
        return self._orders.list_orders(**filters)

    def list_pending_orders(self) -> Sequence[Metadata]:
        """Return OANDA pending orders as raw metadata snapshots."""
        return self._orders.list_pending_orders()

    def get_order(self, order_id: str) -> Metadata:
        """Return one OANDA order as raw metadata."""
        return self._orders.get_order(order_id)

    def replace_order(self, order_id: str, order: Order) -> Order:
        """Replace one OANDA order."""
        return self._orders.replace_order(order_id, order)

    def cancel_order(self, order_id: str) -> Metadata:
        """Cancel one OANDA order."""
        return self._orders.cancel_order(order_id)

    def set_order_client_extensions(
        self,
        order_id: str,
        *,
        client_id: str | None = None,
        tag: str | None = None,
        comment: str | None = None,
    ) -> Metadata:
        """Set OANDA order client extensions."""
        return self._orders.set_order_client_extensions(
            order_id,
            client_id=client_id,
            tag=tag,
            comment=comment,
        )

    def list_trades(self, **filters: object) -> Sequence[Trade]:
        """Return OANDA trades."""
        return self._trades.list_trades(**filters)

    def list_open_trades(self) -> Sequence[Trade]:
        """Return OANDA open trades."""
        return self._trades.list_open_trades()

    def get_trade(self, trade_id: str) -> Trade:
        """Return one OANDA trade."""
        return self._trades.get_trade(trade_id)

    def close_trade(self, trade: Trade, *, units: Units | None = None) -> Order:
        """Close all or part of an OANDA trade."""
        return self._trades.close_trade(trade, units=units)

    def set_trade_client_extensions(
        self,
        trade_id: str,
        *,
        client_id: str | None = None,
        tag: str | None = None,
        comment: str | None = None,
    ) -> Metadata:
        """Set OANDA trade client extensions."""
        return self._trades.set_trade_client_extensions(
            trade_id,
            client_id=client_id,
            tag=tag,
            comment=comment,
        )

    def set_trade_dependent_orders(self, trade_id: str, **orders: object) -> Metadata:
        """Set OANDA dependent orders for a trade."""
        return self._trades.set_trade_dependent_orders(trade_id, **orders)

    def list_positions(self) -> Sequence[Position]:
        """Return all OANDA positions."""
        return self._positions.list_positions()

    def list_open_positions(self) -> Sequence[Position]:
        """Return open OANDA positions."""
        return self._positions.list_open_positions()

    def get_position(self, instrument: CurrencyPair) -> Position:
        """Return one OANDA position."""
        return self._positions.get_position(instrument)

    def list_transactions(
        self,
        *,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        page_size: int | None = None,
        types: Iterable[str] | None = None,
    ) -> Metadata:
        """Return OANDA transaction page metadata."""
        return self._transactions.list_transactions(
            from_time=from_time,
            to_time=to_time,
            page_size=page_size,
            types=types,
        )

    def get_transaction(self, transaction_id: str) -> Transaction:
        """Return one OANDA transaction."""
        return self._transactions.get_transaction(transaction_id)

    def get_transaction_range(
        self,
        *,
        from_id: str | None = None,
        to_id: str | None = None,
        types: Iterable[str] | None = None,
    ) -> Sequence[Transaction]:
        """Return OANDA transactions by ID range."""
        return self._transactions.get_transaction_range(
            from_id=from_id,
            to_id=to_id,
            types=types,
        )

    def get_transactions_since(
        self,
        transaction_id: str,
        *,
        types: Iterable[str] | None = None,
    ) -> Sequence[Transaction]:
        """Return OANDA transactions since one transaction ID."""
        return self._transactions.get_transactions_since(transaction_id, types=types)

    def stream_transactions(self) -> Iterable[Transaction]:
        """Yield OANDA transaction stream updates."""
        return self._transactions.stream_transactions()

    def capture_execution_cursor(self) -> str | None:
        """Return the latest OANDA transaction id before a mutation."""
        page = self.list_transactions(page_size=1)
        value = page.get("lastTransactionID")
        return None if value is None else str(value)

    def reconcile_execution(self, mutation: BrokerMutation) -> BrokerReconciliation:
        """Reconcile an interrupted mutation against OANDA's transaction log."""
        cursor = mutation.provider_cursor
        if cursor is None:
            return BrokerReconciliation(
                outcome=BrokerReconciliationOutcome.INDETERMINATE,
                details="OANDA reconciliation requires a pre-dispatch transaction cursor",
            )
        transactions = self.get_transactions_since(cursor)
        if mutation.operation == BrokerMutationOperation.PLACE_ORDER:
            return self._reconcile_place_order(mutation, transactions)
        if mutation.operation == BrokerMutationOperation.CLOSE_TRADE:
            return self._reconcile_close_trade(mutation, transactions)
        if mutation.operation == BrokerMutationOperation.CLOSE_POSITION:
            return self._reconcile_close_position(mutation, transactions)
        return BrokerReconciliation(
            outcome=BrokerReconciliationOutcome.INDETERMINATE,
            details=f"unsupported OANDA reconciliation operation: {mutation.operation}",
        )

    def _reconcile_place_order(
        self,
        mutation: BrokerMutation,
        transactions: Sequence[Transaction],
    ) -> BrokerReconciliation:
        order = mutation.order
        if order is None:
            return self._indeterminate("place-order reconciliation requires the original order")
        execution_id = str(order.metadata.get("event_id") or mutation.command_id)
        matched = self._transactions_for_client_id(transactions, execution_id)
        if matched:
            transaction_order = self._order_from_transactions(order, matched)
            if transaction_order is not None:
                return BrokerReconciliation(
                    outcome=BrokerReconciliationOutcome.APPLIED,
                    order=transaction_order,
                )
        try:
            snapshot = self.get_order(f"@{execution_id}")
        except OandaNotFoundError:
            return BrokerReconciliation(
                outcome=BrokerReconciliationOutcome.NOT_APPLIED,
                details=f"OANDA client order id was not found: {execution_id}",
            )
        return BrokerReconciliation(
            outcome=BrokerReconciliationOutcome.APPLIED,
            order=self.order_mapper.order_from_snapshot(snapshot, order),
        )

    def _reconcile_close_trade(
        self,
        mutation: BrokerMutation,
        transactions: Sequence[Transaction],
    ) -> BrokerReconciliation:
        trade = mutation.trade
        if trade is None:
            return self._indeterminate("close-trade reconciliation requires the original trade")
        candidates = tuple(
            transaction
            for transaction in transactions
            if self._transaction_closes_trade(transaction, str(trade.id))
        )
        if len(candidates) != 1:
            return self._indeterminate(
                f"expected one OANDA close transaction for trade {trade.id}, "
                f"found {len(candidates)}"
            )
        planned_units = mutation.units or trade.units
        order = Order(
            instrument=trade.instrument,
            side=OrderSide.SELL if trade.side == PositionSide.LONG else OrderSide.BUY,
            units=planned_units,
            metadata=trade.metadata,
        )
        reconciled = self._order_from_transactions(order, candidates)
        if reconciled is None:
            return self._indeterminate(f"OANDA close transaction was incomplete: {trade.id}")
        return BrokerReconciliation(
            outcome=BrokerReconciliationOutcome.APPLIED,
            order=reconciled,
        )

    def _reconcile_close_position(
        self,
        mutation: BrokerMutation,
        transactions: Sequence[Transaction],
    ) -> BrokerReconciliation:
        position = mutation.position
        side = mutation.position_side
        if position is None or side is None:
            return self._indeterminate(
                "close-position reconciliation requires the original position and side"
            )
        planned_units = mutation.units or position.require_side(side).units
        candidates = tuple(
            transaction
            for transaction in transactions
            if self._transaction_matches_position_close(
                transaction,
                instrument=position.instrument,
                side=side,
                units=planned_units,
            )
        )
        if len(candidates) != 1:
            return self._indeterminate(
                f"expected one OANDA position-close transaction for {position.instrument}, "
                f"found {len(candidates)}"
            )
        order = Order(
            instrument=position.instrument,
            side=OrderSide.SELL if side == PositionSide.LONG else OrderSide.BUY,
            units=planned_units,
        )
        reconciled = self._order_from_transactions(order, candidates)
        if reconciled is None:
            return self._indeterminate(
                f"OANDA position-close transaction was incomplete: {position.instrument}"
            )
        return BrokerReconciliation(
            outcome=BrokerReconciliationOutcome.APPLIED,
            order=reconciled,
        )

    @staticmethod
    def _transactions_for_client_id(
        transactions: Sequence[Transaction],
        client_id: str,
    ) -> tuple[Transaction, ...]:
        matched_batch_ids: set[str] = set()
        matched_order_ids: set[str] = set()
        direct: list[Transaction] = []
        for transaction in transactions:
            metadata = transaction.metadata
            extensions = metadata.get("clientExtensions") or {}
            extension_id = extensions.get("id") if isinstance(extensions, Mapping) else None
            if str(extension_id or metadata.get("clientOrderID") or "") != client_id:
                continue
            direct.append(transaction)
            if metadata.get("batchID") is not None:
                matched_batch_ids.add(str(metadata["batchID"]))
            if transaction.order_id is not None:
                matched_order_ids.add(str(transaction.order_id))
            if metadata.get("id") is not None:
                matched_order_ids.add(str(metadata["id"]))
        return tuple(
            transaction
            for transaction in transactions
            if transaction in direct
            or str(transaction.metadata.get("batchID") or "") in matched_batch_ids
            or str(transaction.order_id or "") in matched_order_ids
        )

    @staticmethod
    def _transaction_closes_trade(transaction: Transaction, trade_id: str) -> bool:
        metadata = transaction.metadata
        closed = metadata.get("tradesClosed") or ()
        for item in closed:
            if (
                isinstance(item, Mapping)
                and str(item.get("tradeID") or item.get("id") or "") == trade_id
            ):
                return True
        reduced = metadata.get("tradeReduced")
        return isinstance(reduced, Mapping) and str(reduced.get("tradeID") or "") == trade_id

    @staticmethod
    def _transaction_matches_position_close(
        transaction: Transaction,
        *,
        instrument: CurrencyPair,
        side: PositionSide,
        units: Units,
    ) -> bool:
        if transaction.instrument != instrument or "FILL" not in transaction.type.upper():
            return False
        raw_units = transaction.metadata.get("units")
        if raw_units is None:
            return False
        value = Units.of(abs(Decimal(str(raw_units))))
        if value != units:
            return False
        signed = Decimal(str(raw_units))
        return signed < 0 if side == PositionSide.LONG else signed > 0

    @staticmethod
    def _order_from_transactions(
        order: Order,
        transactions: Sequence[Transaction],
    ) -> Order | None:
        fill = next(
            (transaction for transaction in transactions if "FILL" in transaction.type.upper()),
            None,
        )
        reject = next(
            (transaction for transaction in transactions if "REJECT" in transaction.type.upper()),
            None,
        )
        cancel = next(
            (transaction for transaction in transactions if "CANCEL" in transaction.type.upper()),
            None,
        )
        selected = fill or reject or cancel or (transactions[0] if transactions else None)
        if selected is None:
            return None
        metadata = selected.metadata
        status = (
            OrderStatus.FILLED
            if fill is not None
            else OrderStatus.REJECTED
            if reject is not None
            else OrderStatus.CANCELLED
            if cancel is not None
            else OrderStatus.ACCEPTED
        )
        raw_units = metadata.get("units")
        filled_units = (
            Units.of(min(abs(Decimal(str(raw_units))), order.units))
            if fill is not None and raw_units is not None
            else Units("0")
        )
        raw_price = metadata.get("price")
        fill_price = (
            Money.of(raw_price, order.instrument.quote)
            if fill is not None and raw_price is not None
            else None
        )
        broker_order_id = selected.order_id or (
            BrokerOrderId.of(str(metadata["orderID"]))
            if metadata.get("orderID") is not None
            else None
        )
        return order.evolve(
            broker_order_id=broker_order_id,
            status=status,
            filled_units=filled_units,
            average_fill_price=fill_price,
            metadata=order.metadata.merge(metadata),
        )

    @staticmethod
    def _indeterminate(details: str) -> BrokerReconciliation:
        return BrokerReconciliation(
            outcome=BrokerReconciliationOutcome.INDETERMINATE,
            details=details,
        )
