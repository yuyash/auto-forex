from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from autoforex.core import CSVDataSource, DataSource, StrategyParameters

import autoforex.server.composition as composition_module
from autoforex.server.components import (
    ComponentName,
    ComponentNotFoundError,
    DataSourceReference,
    ProviderReference,
    StrategyReference,
)
from autoforex.server.composition import (
    AthenaDataSourceFactory,
    CsvDataSourceFactory,
    PersistenceFactory,
    ServerApplication,
    ServerComponentCatalog,
    ServiceRegistryFactory,
    SnowballStrategyFactory,
)
from autoforex.server.settings import (
    CsvDataSourceSettings,
    PersistenceBackend,
    ServerSettings,
    ServiceDiscoveryBackend,
)


class FakeAthenaDataSource(DataSource):
    @classmethod
    def from_env(cls) -> FakeAthenaDataSource:
        return cls()

    def _raw_ticks(self, **kwargs: Any):
        _ = kwargs
        return iter(())


class RecordingPersistence:
    def __init__(self) -> None:
        self.schema_created = False
        self.closed = False
        self.registry = object()
        self.recovery = object()
        self.execution = object()
        self.discovery = RecordingServiceRegistry()

    def create_schema(self) -> None:
        self.schema_created = True

    def task_registry(self) -> object:
        return self.registry

    def recovery_store(self) -> object:
        return self.recovery

    def execution_store(self) -> object:
        return self.execution

    def service_registry(self) -> RecordingServiceRegistry:
        return self.discovery

    def close(self) -> None:
        self.closed = True


class RecordingSupervisor:
    def __init__(self) -> None:
        self.shutdown_called = False

    def shutdown(self) -> None:
        self.shutdown_called = True


class RecordingServiceRegistry:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class TestBuiltInComponentFactories:
    def test_creates_snowball_and_csv_components_from_immutable_settings(
        self,
        tmp_path: Path,
    ) -> None:
        tick_path = tmp_path / "ticks.csv"
        strategy = SnowballStrategyFactory()(StrategyParameters())
        source = CsvDataSourceFactory(CsvDataSourceSettings(tick_paths=(tick_path,)))()

        assert strategy.name == "snowball"
        assert isinstance(source, CSVDataSource)

    def test_loads_athena_only_when_the_optional_factory_is_called(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake_module = SimpleNamespace(AthenaDataSource=FakeAthenaDataSource)
        monkeypatch.setattr(
            composition_module,
            "require_optional_dependency",
            lambda *args, **kwargs: fake_module,
        )

        source = AthenaDataSourceFactory()()

        assert isinstance(source, FakeAthenaDataSource)

    def test_catalog_registers_only_components_enabled_by_settings(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake_module = SimpleNamespace(AthenaDataSource=FakeAthenaDataSource)
        monkeypatch.setattr(
            composition_module,
            "require_optional_dependency",
            lambda *args, **kwargs: fake_module,
        )
        settings = ServerSettings(
            enable_athena=True,
            csv_data_sources={
                "historical": CsvDataSourceSettings(tick_paths=(tmp_path / "ticks.csv",))
            },
        )

        catalog = ServerComponentCatalog.from_settings(settings)

        assert (
            catalog.strategies.create(StrategyReference(name=ComponentName.of("snowball"))).name
            == "snowball"
        )
        assert isinstance(
            catalog.data_sources.create(DataSourceReference(name=ComponentName.of("historical"))),
            CSVDataSource,
        )
        assert isinstance(
            catalog.data_sources.create(DataSourceReference(name=ComponentName.of("athena"))),
            FakeAthenaDataSource,
        )
        with pytest.raises(ComponentNotFoundError):
            catalog.providers.create(ProviderReference(name=ComponentName.of("oanda")))


class TestPersistenceFactory:
    @pytest.mark.parametrize(
        "backend",
        [PersistenceBackend.SQLITE, PersistenceBackend.POSTGRESQL],
    )
    def test_selects_sql_persistence_for_relational_backends(
        self,
        backend: PersistenceBackend,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, Any] = {}

        class FakeSqlPersistence:
            def __init__(self, database_url: str, *, echo: bool) -> None:
                captured.update(database_url=database_url, echo=echo)

        monkeypatch.setattr(composition_module, "SqlPersistence", FakeSqlPersistence)
        database_url = (
            "sqlite:///tasks.db"
            if backend == PersistenceBackend.SQLITE
            else "postgresql+psycopg://user:pass@localhost/tasks"
        )

        persistence = PersistenceFactory().create(
            ServerSettings(
                persistence_backend=backend,
                database_url=database_url,
                database_echo=True,
            )
        )

        assert isinstance(persistence, FakeSqlPersistence)
        assert captured == {"database_url": database_url, "echo": True}

    def test_selects_optional_dynamodb_persistence_with_all_settings(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, Any] = {}

        class FakeDynamoPersistence:
            def __init__(self, **kwargs: Any) -> None:
                captured.update(kwargs)

        monkeypatch.setattr(
            composition_module,
            "DynamoDbServerPersistence",
            FakeDynamoPersistence,
        )

        persistence = PersistenceFactory().create(
            ServerSettings(
                persistence_backend=PersistenceBackend.DYNAMODB,
                dynamodb_table_name="tasks",
                dynamodb_region_name="us-west-2",
                dynamodb_endpoint_url="http://localhost:8000",
                dynamodb_consistent_reads=False,
                dynamodb_enable_point_in_time_recovery=False,
            )
        )

        assert isinstance(persistence, FakeDynamoPersistence)
        assert captured["table_name"] == "tasks"
        assert captured["endpoint_url"] == "http://localhost:8000"
        assert not captured["consistent_reads"]


class TestServiceRegistryFactory:
    def test_uses_the_registry_owned_by_shared_persistence(self) -> None:
        persistence = RecordingPersistence()

        registry = ServiceRegistryFactory().create(ServerSettings(), cast(Any, persistence))

        assert registry is persistence.discovery

    def test_builds_optional_cloud_map_registry(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        expected = object()
        captured: dict[str, Any] = {}

        def create(**kwargs: Any) -> object:
            captured.update(kwargs)
            return expected

        monkeypatch.setattr(
            composition_module.CloudMapServiceRegistry,
            "create",
            create,
        )
        settings = ServerSettings(
            service_discovery_enabled=True,
            service_discovery_backend=ServiceDiscoveryBackend.AWS_CLOUD_MAP,
            cloud_map_service_id="srv-123",
            cloud_map_namespace_name="internal.example",
            cloud_map_service_name="autoforex",
            cloud_map_region_name="us-west-2",
        )

        registry = ServiceRegistryFactory().create(
            settings,
            cast(Any, RecordingPersistence()),
        )

        assert registry is expected
        assert captured["service_id"] == "srv-123"
        assert captured["namespace_name"] == "internal.example"


class TestServerApplication:
    def test_builds_schema_before_supervisor_and_closes_owned_resources(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        persistence = RecordingPersistence()
        supervisor = RecordingSupervisor()
        factory = SimpleNamespace(create=lambda settings: persistence)
        captured: dict[str, Any] = {}

        def create_supervisor(**kwargs: Any) -> RecordingSupervisor:
            assert persistence.schema_created
            captured.update(kwargs)
            return supervisor

        monkeypatch.setattr(
            composition_module.TaskSupervisor,
            "create",
            create_supervisor,
        )
        settings = ServerSettings()

        application = ServerApplication.build(
            settings,
            persistence_factory=cast(PersistenceFactory, cast(Any, factory)),
        )
        application.close()

        assert captured["registry"] is persistence.registry
        assert captured["recovery_store"] is persistence.recovery
        assert captured["execution_store"] is persistence.execution
        assert application.service_registry is persistence.discovery
        assert supervisor.shutdown_called
        assert persistence.discovery.closed
        assert persistence.closed
