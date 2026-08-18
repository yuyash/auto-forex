"""Named runtime component references and dependency registries."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Lock
from typing import Literal, Self

from autoforex.core import (
    Broker,
    DataSource,
    DomainModel,
    Strategy,
    StrategyParameters,
    TaskType,
    TradingProvider,
)
from pydantic import Field, TypeAdapter, model_validator


class ComponentName(DomainModel):
    """Stable deployment-local name for a configured runtime component."""

    value: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")

    @classmethod
    def of(cls, value: ComponentName | str) -> Self:
        """Create a normalized component name."""
        return cls.model_validate(value)

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, value: object) -> object:
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return {"value": value.strip().lower()}
        return value

    def __str__(self) -> str:
        return self.value


class StrategyReference(DomainModel):
    """Reference to a registered strategy factory and its parameters."""

    name: ComponentName
    parameters: StrategyParameters = Field(default_factory=StrategyParameters)


class DataSourceReference(DomainModel):
    """Reference to a registered market-data source factory."""

    name: ComponentName


class ProviderReference(DomainModel):
    """Reference to a registered trading-provider factory."""

    name: ComponentName


class BacktestTaskBinding(DomainModel):
    """Runtime component bindings needed to execute a backtest."""

    task_type: Literal[TaskType.BACKTEST] = TaskType.BACKTEST
    strategy: StrategyReference
    data_source: DataSourceReference
    broker_provider: ProviderReference | None = None


class TradingTaskBinding(DomainModel):
    """Runtime component bindings needed to execute a live trading task."""

    task_type: Literal[TaskType.TRADING] = TaskType.TRADING
    strategy: StrategyReference
    provider: ProviderReference


type TaskBinding = BacktestTaskBinding | TradingTaskBinding


class TaskBindingCodec:
    """Serialize and validate the discriminated task-binding union."""

    _adapter = TypeAdapter(TaskBinding)

    @classmethod
    def to_json(cls, binding: TaskBinding) -> str:
        """Serialize a binding for persistence."""
        return cls._adapter.dump_json(binding).decode()

    @classmethod
    def from_json(cls, payload: str) -> TaskBinding:
        """Restore a binding from persistence."""
        return cls._adapter.validate_json(payload)


type StrategyFactory = Callable[[StrategyParameters], Strategy]
type DataSourceFactory = Callable[[], DataSource]
type TradingProviderFactory = Callable[[], TradingProvider]


class ComponentNotFoundError(LookupError):
    """Raised when a task references an unregistered runtime component."""


class StrategyRegistry:
    """Registry of explicitly allowed strategy factories."""

    def __init__(self) -> None:
        self._factories: dict[ComponentName, StrategyFactory] = {}

    def register(self, name: ComponentName, factory: StrategyFactory) -> None:
        """Register a strategy factory."""
        self._factories[name] = factory

    def create(self, reference: StrategyReference) -> Strategy:
        """Create a strategy from a registered reference."""
        try:
            factory = self._factories[reference.name]
        except KeyError as exc:
            msg = f"strategy is not registered: {reference.name}"
            raise ComponentNotFoundError(msg) from exc
        return factory(reference.parameters)


class DataSourceRegistry:
    """Registry of configured market-data source factories."""

    def __init__(self) -> None:
        self._factories: dict[ComponentName, DataSourceFactory] = {}

    def register(self, name: ComponentName, factory: DataSourceFactory) -> None:
        """Register a data-source factory."""
        self._factories[name] = factory

    def create(self, reference: DataSourceReference) -> DataSource:
        """Create a data source from a registered reference."""
        try:
            factory = self._factories[reference.name]
        except KeyError as exc:
            msg = f"data source is not registered: {reference.name}"
            raise ComponentNotFoundError(msg) from exc
        return factory()


class TradingProviderRegistry:
    """Registry of configured provider factories."""

    def __init__(self) -> None:
        self._factories: dict[ComponentName, TradingProviderFactory] = {}

    def register(self, name: ComponentName, factory: TradingProviderFactory) -> None:
        """Register a provider factory."""
        self._factories[name] = factory

    def create(self, reference: ProviderReference) -> TradingProvider:
        """Create a provider from a registered reference."""
        try:
            factory = self._factories[reference.name]
        except KeyError as exc:
            msg = f"trading provider is not registered: {reference.name}"
            raise ComponentNotFoundError(msg) from exc
        return factory()


@dataclass(slots=True)
class ResolvedTaskDependencies:
    """Concrete runtime dependencies owned by one task execution."""

    data_source: DataSource
    strategy: Strategy
    broker: Broker | None
    resources: tuple[object, ...]
    _closed: bool = field(default=False, init=False, repr=False)
    _close_lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def close(self) -> None:
        """Close each owned resource once."""
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            closed: set[int] = set()
            for resource in reversed(self.resources):
                identity = id(resource)
                if identity in closed:
                    continue
                closed.add(identity)
                close = getattr(resource, "close", None)
                if callable(close):
                    close()


class TaskDependencyResolver:
    """Resolve persisted component references into one execution bundle."""

    def __init__(
        self,
        *,
        strategies: StrategyRegistry,
        data_sources: DataSourceRegistry,
        providers: TradingProviderRegistry,
    ) -> None:
        self.strategies = strategies
        self.data_sources = data_sources
        self.providers = providers

    def resolve(self, binding: TaskBinding) -> ResolvedTaskDependencies:
        """Resolve dependencies for a backtest or trading task."""
        strategy = self.strategies.create(binding.strategy)
        if isinstance(binding, TradingTaskBinding):
            provider = self.providers.create(binding.provider)
            return ResolvedTaskDependencies(
                data_source=provider.data,
                strategy=strategy,
                broker=provider.broker,
                resources=(provider,),
            )

        data_source = self.data_sources.create(binding.data_source)
        if binding.broker_provider is None:
            return ResolvedTaskDependencies(
                data_source=data_source,
                strategy=strategy,
                broker=None,
                resources=(data_source,),
            )

        provider = self.providers.create(binding.broker_provider)
        return ResolvedTaskDependencies(
            data_source=data_source,
            strategy=strategy,
            broker=provider.broker,
            resources=(data_source, provider),
        )
