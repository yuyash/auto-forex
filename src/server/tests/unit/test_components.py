from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime

import pytest
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
    Position,
    PositionSide,
    Strategy,
    StrategyContext,
    StrategyParameters,
    StrategyResult,
    Tick,
    Trade,
    TradingProvider,
    Units,
)

from autoforex.server.components import (
    BacktestTaskBinding,
    ComponentName,
    ComponentNotFoundError,
    DataSourceReference,
    DataSourceRegistry,
    ProviderReference,
    StrategyReference,
    StrategyRegistry,
    TaskBindingCodec,
    TaskDependencyResolver,
    TradingProviderRegistry,
    TradingTaskBinding,
)


class EmptyDataSource(DataSource):
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


class HoldStrategy(Strategy):
    def on_tick(self, tick: Tick, context: StrategyContext) -> StrategyResult:
        _ = tick
        _ = context
        return StrategyResult()


class EmptyBroker(Broker):
    def place_order(self, order: Order) -> Order:
        return order

    def close_position(
        self,
        *,
        position: Position,
        side: PositionSide,
        units: Units | None = None,
    ) -> Order:
        _ = position
        _ = side
        _ = units
        raise NotImplementedError

    def positions(self, *, instrument: CurrencyPair | None = None) -> Sequence[Position]:
        _ = instrument
        return ()

    def trades(self, *, instrument: CurrencyPair | None = None) -> Sequence[Trade]:
        _ = instrument
        return ()

    def close_trade(self, trade: Trade, *, units: Units | None = None) -> Order:
        _ = trade
        _ = units
        raise NotImplementedError


class EmptyAccountManager(AccountManager):
    def list_accounts(self) -> tuple[Account, ...]:
        return ()

    def get_account(self, account_id: AccountId) -> Account:
        return Account(id=account_id)

    def get_account_summary(self, account_id: AccountId) -> AccountSummary:
        _ = account_id
        raise NotImplementedError

    def get_account_instruments(self, account_id: AccountId) -> tuple[CurrencyPair, ...]:
        _ = account_id
        return ()

    def configure_account(
        self,
        account_id: AccountId,
        *,
        alias: str | None = None,
        margin_rate: MarginRate | None = None,
    ) -> Account:
        _ = alias
        _ = margin_rate
        return Account(id=account_id)

    def get_account_changes(
        self,
        account_id: AccountId,
        *,
        since_transaction_id: str,
    ) -> Metadata:
        _ = account_id
        _ = since_transaction_id
        return Metadata()


class TestComponents:
    def test_component_name_normalizes_and_validates(self) -> None:
        assert ComponentName.of(" SnowBall ").value == "snowball"

        with pytest.raises(ValueError):
            ComponentName.of("invalid name")

    def test_binding_codec_round_trips_concrete_binding_type(self) -> None:
        binding = BacktestTaskBinding(
            strategy=StrategyReference(
                name=ComponentName.of("hold"),
                parameters=StrategyParameters.of(window="20"),
            ),
            data_source=DataSourceReference(name=ComponentName.of("csv")),
        )

        restored = TaskBindingCodec.from_json(TaskBindingCodec.to_json(binding))

        assert restored == binding
        assert isinstance(restored, BacktestTaskBinding)

    def test_dependency_resolver_creates_backtest_dependencies(self) -> None:
        strategies = StrategyRegistry()
        sources = DataSourceRegistry()
        providers = TradingProviderRegistry()
        strategies.register(
            ComponentName.of("hold"),
            lambda parameters: HoldStrategy(name="hold", parameters=parameters),
        )
        sources.register(ComponentName.of("memory"), EmptyDataSource)
        resolver = TaskDependencyResolver(
            strategies=strategies,
            data_sources=sources,
            providers=providers,
        )

        dependencies = resolver.resolve(
            BacktestTaskBinding(
                strategy=StrategyReference(name=ComponentName.of("hold")),
                data_source=DataSourceReference(name=ComponentName.of("memory")),
            )
        )

        assert isinstance(dependencies.strategy, HoldStrategy)
        assert isinstance(dependencies.data_source, EmptyDataSource)
        assert dependencies.broker is None

    def test_dependency_resolver_uses_provider_bundle_for_trading(self) -> None:
        strategies = StrategyRegistry()
        sources = DataSourceRegistry()
        providers = TradingProviderRegistry()
        strategies.register(
            ComponentName.of("hold"),
            lambda parameters: HoldStrategy(name="hold", parameters=parameters),
        )
        providers.register(
            ComponentName.of("paper"),
            lambda: TradingProvider(
                provider=AccountProvider.of("paper"),
                account_manager=EmptyAccountManager(),
                broker=EmptyBroker(),
                data=EmptyDataSource(),
            ),
        )
        resolver = TaskDependencyResolver(
            strategies=strategies,
            data_sources=sources,
            providers=providers,
        )

        dependencies = resolver.resolve(
            TradingTaskBinding(
                strategy=StrategyReference(name=ComponentName.of("hold")),
                provider=ProviderReference(name=ComponentName.of("paper")),
            )
        )

        assert isinstance(dependencies.data_source, EmptyDataSource)
        assert isinstance(dependencies.broker, EmptyBroker)

    def test_registry_rejects_unknown_component(self) -> None:
        with pytest.raises(ComponentNotFoundError, match="strategy"):
            StrategyRegistry().create(StrategyReference(name=ComponentName.of("missing")))
