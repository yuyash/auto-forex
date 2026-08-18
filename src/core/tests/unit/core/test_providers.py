from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime

from autoforex.core import (
    Account,
    AccountId,
    AccountManager,
    AccountProvider,
    AccountSummary,
    Broker,
    CurrencyPair,
    DataSource,
    MarginRate,
    Metadata,
    Order,
    OrderSide,
    Position,
    PositionSide,
    Tick,
    Trade,
    TradingProvider,
    Units,
)

PAPER_PROVIDER = AccountProvider.of("paper")


class MemoryAccountManager(AccountManager):
    def __init__(self) -> None:
        self.closed = False

    def list_accounts(self) -> tuple[Account, ...]:
        return (Account(id=AccountId.of("001"), provider=PAPER_PROVIDER),)

    def get_account(self, account_id: AccountId) -> Account:
        return Account(id=account_id, provider=PAPER_PROVIDER)

    def get_account_summary(self, account_id: AccountId) -> AccountSummary:
        return AccountSummary.model_validate({"account_id": account_id, "currency": "USD"})

    def get_account_instruments(
        self,
        account_id: AccountId,
    ) -> tuple[CurrencyPair, ...]:
        _ = account_id
        return (CurrencyPair.of("USD_JPY"),)

    def configure_account(
        self,
        account_id: AccountId,
        *,
        alias: str | None = None,
        margin_rate: MarginRate | None = None,
    ) -> Account:
        _ = margin_rate
        return Account(id=account_id, provider=PAPER_PROVIDER, alias=alias)

    def get_account_changes(
        self,
        account_id: AccountId,
        *,
        since_transaction_id: str,
    ) -> Metadata:
        _ = account_id
        return Metadata.of(since_transaction_id=since_transaction_id)

    def close(self) -> None:
        self.closed = True


class MemoryBroker(Broker):
    def __init__(self) -> None:
        self.closed = False

    def place_order(self, order: Order) -> Order:
        return order

    def close_position(
        self,
        *,
        position: Position,
        side: PositionSide,
        units: Units | None = None,
    ) -> Order:
        _ = side
        _ = units
        return Order(
            instrument=position.instrument,
            side=OrderSide.SELL,
            units=Units("0.1"),
        )

    def positions(self, *, instrument: CurrencyPair | None = None) -> Sequence[Position]:
        _ = instrument
        return ()

    def trades(self, *, instrument: CurrencyPair | None = None) -> Sequence[Trade]:
        _ = instrument
        return ()

    def close_trade(self, trade: Trade, *, units: Units | None = None) -> Order:
        _ = units
        return Order(
            instrument=trade.instrument,
            side=OrderSide.SELL if trade.side == PositionSide.LONG else OrderSide.BUY,
            units=trade.units,
        )

    def close(self) -> None:
        self.closed = True


class MemoryDataSource(DataSource):
    def __init__(self) -> None:
        self.closed = False

    def _raw_ticks(
        self,
        *,
        instrument: CurrencyPair,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Tick]:
        _ = instrument
        _ = start_at
        _ = end_at
        return ()

    def close(self) -> None:
        self.closed = True


class TestProviders:
    def test_trading_provider_bundles_provider_services(self) -> None:
        account_manager = MemoryAccountManager()
        broker = MemoryBroker()
        data_source = MemoryDataSource()

        provider = TradingProvider(
            provider=PAPER_PROVIDER,
            account_manager=account_manager,
            broker=broker,
            data=data_source,
        )

        assert provider.provider == PAPER_PROVIDER
        assert provider.accounts is account_manager
        assert provider.account_manager is account_manager
        assert provider.broker is broker
        assert provider.data is data_source

        provider.close()

        assert account_manager.closed
        assert broker.closed
        assert data_source.closed
