"""Server application composition and built-in component registration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

from autoforex.core import CSVDataSource, DataSource, Strategy, StrategyParameters, TaskRegistry
from autoforex.snowball import SnowballStrategy

from autoforex.server.components import (
    ComponentName,
    DataSourceRegistry,
    StrategyRegistry,
    TaskDependencyResolver,
    TradingProviderRegistry,
)
from autoforex.server.discovery import (
    CloudMapServiceRegistry,
    ServiceRegistry,
)
from autoforex.server.dynamodb import DynamoDbServerPersistence
from autoforex.server.execution import ExecutionJournalStore
from autoforex.server.optional import require_optional_dependency
from autoforex.server.persistence import SqlPersistence
from autoforex.server.recovery import TaskRecoveryStore
from autoforex.server.settings import (
    CsvDataSourceSettings,
    PersistenceBackend,
    ServerSettings,
    ServiceDiscoveryBackend,
)
from autoforex.server.supervisor import TaskSupervisor

if TYPE_CHECKING:
    from autoforex.oanda import OandaProvider, OandaSettings


class PersistenceResources(Protocol):
    """Persistence services owned by the server process."""

    def create_schema(self) -> None:
        """Create required persistence structures."""

    def task_registry(self) -> TaskRegistry:
        """Return the Core task registry."""

    def recovery_store(self) -> TaskRecoveryStore:
        """Return task recovery metadata storage."""

    def execution_store(self) -> ExecutionJournalStore:
        """Return durable broker execution journal storage."""

    def service_registry(self) -> ServiceRegistry:
        """Return shared server service discovery storage."""

    def is_healthy(self) -> bool:
        """Return whether persistence is reachable."""

    def close(self) -> None:
        """Release persistence resources."""


class SnowballStrategyFactory:
    """Create isolated Snowball strategies for task executions."""

    def __call__(self, parameters: StrategyParameters) -> Strategy:
        return SnowballStrategy(parameters=parameters)


@dataclass(frozen=True, slots=True)
class OandaProviderFactory:
    """Create isolated OANDA provider bundles from validated settings."""

    settings: OandaSettings

    def __call__(self) -> OandaProvider:
        module = require_optional_dependency(
            "autoforex.oanda",
            extra="oanda",
            feature="OANDA provider support",
        )
        provider_type = module.__dict__["OandaProvider"]
        return cast("OandaProvider", provider_type.from_settings(self.settings))


@dataclass(frozen=True, slots=True)
class CsvDataSourceFactory:
    """Create CSV sources from immutable deployment configuration."""

    settings: CsvDataSourceSettings

    def __call__(self) -> DataSource:
        return CSVDataSource(
            tick_paths=self.settings.tick_paths,
            candle_paths=self.settings.candle_paths,
            encoding=self.settings.encoding,
        )


class AthenaDataSourceFactory:
    """Create the optional AWS Athena data source without a hard dependency."""

    def __call__(self) -> DataSource:
        module = require_optional_dependency(
            "autoforex.aws",
            extra="aws",
            feature="Athena data-source support",
        )
        source_type = module.__dict__["AthenaDataSource"]
        return cast(DataSource, source_type.from_env())


@dataclass(frozen=True, slots=True)
class ServerComponentCatalog:
    """All explicitly registered execution components."""

    strategies: StrategyRegistry
    data_sources: DataSourceRegistry
    providers: TradingProviderRegistry

    @classmethod
    def from_settings(cls, settings: ServerSettings) -> ServerComponentCatalog:
        """Create built-in component registries from process settings."""
        strategies = StrategyRegistry()
        data_sources = DataSourceRegistry()
        providers = TradingProviderRegistry()

        strategies.register(ComponentName.of("snowball"), SnowballStrategyFactory())
        for name, csv_settings in settings.csv_data_sources.items():
            data_sources.register(
                ComponentName.of(name),
                CsvDataSourceFactory(csv_settings),
            )
        if settings.enable_oanda:
            module = require_optional_dependency(
                "autoforex.oanda",
                extra="oanda",
                feature="OANDA provider support",
            )
            settings_type = module.__dict__["OandaSettings"]
            providers.register(
                ComponentName.of(settings.oanda_provider_name),
                OandaProviderFactory(settings_type()),
            )
        if settings.enable_athena:
            require_optional_dependency(
                "autoforex.aws",
                extra="aws",
                feature="Athena data-source support",
            )
            data_sources.register(
                ComponentName.of(settings.athena_data_source_name),
                AthenaDataSourceFactory(),
            )
        return cls(
            strategies=strategies,
            data_sources=data_sources,
            providers=providers,
        )

    def resolver(self) -> TaskDependencyResolver:
        """Create a resolver over this catalog."""
        return TaskDependencyResolver(
            strategies=self.strategies,
            data_sources=self.data_sources,
            providers=self.providers,
        )


class PersistenceFactory:
    """Create the configured durable persistence implementation."""

    def create(self, settings: ServerSettings) -> PersistenceResources:
        """Create SQL or optional DynamoDB persistence resources."""
        if settings.persistence_backend in {
            PersistenceBackend.SQLITE,
            PersistenceBackend.POSTGRESQL,
        }:
            return SqlPersistence(
                settings.database_url,
                echo=settings.database_echo,
            )

        return DynamoDbServerPersistence(
            table_name=settings.dynamodb_table_name,
            region_name=settings.dynamodb_region_name,
            endpoint_url=settings.dynamodb_endpoint_url,
            consistent_reads=settings.dynamodb_consistent_reads,
            enable_point_in_time_recovery=settings.dynamodb_enable_point_in_time_recovery,
        )


class ServiceRegistryFactory:
    """Create the configured service discovery registry."""

    def create(
        self,
        settings: ServerSettings,
        persistence: PersistenceResources,
    ) -> ServiceRegistry:
        """Use shared persistence or optional AWS Cloud Map."""
        if settings.service_discovery_backend == ServiceDiscoveryBackend.PERSISTENCE:
            return persistence.service_registry()
        service_id = settings.cloud_map_service_id
        namespace_name = settings.cloud_map_namespace_name
        service_name = settings.cloud_map_service_name
        if service_id is None or namespace_name is None or service_name is None:
            raise ValueError("AWS Cloud Map service discovery settings are incomplete")
        return CloudMapServiceRegistry.create(
            service_id=service_id,
            namespace_name=namespace_name,
            service_name=service_name,
            region_name=settings.cloud_map_region_name,
            endpoint_url=settings.cloud_map_endpoint_url,
        )


@dataclass(slots=True)
class ServerApplication:
    """Fully composed server application services."""

    settings: ServerSettings
    persistence: PersistenceResources
    service_registry: ServiceRegistry
    supervisor: TaskSupervisor

    @classmethod
    def build(
        cls,
        settings: ServerSettings,
        *,
        catalog: ServerComponentCatalog | None = None,
        persistence_factory: PersistenceFactory | None = None,
        service_registry_factory: ServiceRegistryFactory | None = None,
    ) -> ServerApplication:
        """Build persistence and task supervision from settings."""
        persistence = (persistence_factory or PersistenceFactory()).create(settings)
        persistence.create_schema()
        components = catalog or ServerComponentCatalog.from_settings(settings)
        registry = persistence.task_registry()
        recovery_store = persistence.recovery_store()
        execution_store = persistence.execution_store()
        service_registry = (service_registry_factory or ServiceRegistryFactory()).create(
            settings,
            persistence,
        )
        supervisor = TaskSupervisor.create(
            registry=registry,
            recovery_store=recovery_store,
            execution_store=execution_store,
            dependency_resolver=components.resolver(),
            max_workers=settings.task_workers,
            heartbeat_interval_seconds=settings.heartbeat_interval_seconds,
            lease_duration_seconds=settings.lease_duration_seconds,
            lease_renewal_seconds=settings.lease_renewal_seconds,
            reconciliation_interval_seconds=settings.reconciliation_interval_seconds,
        )
        return cls(
            settings=settings,
            persistence=persistence,
            service_registry=service_registry,
            supervisor=supervisor,
        )

    def close(self) -> None:
        """Stop task execution and close persistence."""
        try:
            self.supervisor.shutdown()
        finally:
            try:
                self.service_registry.close()
            finally:
                self.persistence.close()
