from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from autoforex.core import TaskNotFoundError
from sqlalchemy.orm import Session

import autoforex.server.persistence as persistence_module
from autoforex.server.discovery import ServiceInstance
from autoforex.server.execution import ExecutionBatchNotFoundError
from autoforex.server.optional import OptionalDependencyError
from autoforex.server.persistence import (
    SchemaMigrationRow,
    SqlPersistence,
    SqlSchemaMigrator,
)
from autoforex.server.recovery import TaskRecoveryRecordNotFoundError


class TestSqlSchemaMigrator:
    def test_rejects_database_schema_newer_than_the_running_server(self) -> None:
        persistence = SqlPersistence("sqlite://")
        persistence.create_schema()
        with Session(persistence.engine) as session, session.begin():
            session.add(
                SchemaMigrationRow(
                    version=SqlSchemaMigrator.LATEST_VERSION + 1,
                    description="future schema",
                )
            )

        with pytest.raises(RuntimeError, match="newer"):
            persistence.create_schema()

        persistence.close()


class TestSqlPersistenceResources:
    def test_reports_the_postgresql_extra_when_the_driver_is_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def missing_driver(*args: object, **kwargs: object) -> None:
            raise OptionalDependencyError(
                'PostgreSQL persistence requires `pip install "auto-forex-server[postgresql]"`'
            )

        monkeypatch.setattr(
            persistence_module,
            "require_optional_dependency",
            missing_driver,
        )

        with pytest.raises(
            OptionalDependencyError,
            match=r"auto-forex-server\[postgresql\]",
        ):
            SqlPersistence("postgresql+psycopg://user:password@localhost/autoforex")

    def test_exposes_independent_contract_adapters_over_one_database(self) -> None:
        persistence = SqlPersistence("sqlite://")
        persistence.create_schema()

        tasks = persistence.task_registry()
        recovery = persistence.recovery_store()
        journal = persistence.execution_store()
        discovery = persistence.service_registry()

        assert tasks is not persistence.task_registry()
        assert recovery is not persistence.recovery_store()
        assert journal is not persistence.execution_store()
        assert discovery is not persistence.service_registry()
        assert persistence.is_healthy()
        persistence.close()

    def test_service_registry_filters_expired_instances_and_deregisters(self) -> None:
        persistence = SqlPersistence("sqlite://")
        persistence.create_schema()
        registry = persistence.service_registry()
        current = datetime.now(UTC)
        live = ServiceInstance(
            instance_id="live",
            host="127.0.0.1",
            port=50051,
            transport_security="plaintext",
            version="0.1.1",
            started_at=current,
            heartbeat_at=current,
            expires_at=current + timedelta(seconds=30),
        )
        expired = live.evolve(
            instance_id="expired",
            started_at=current - timedelta(seconds=60),
            heartbeat_at=current - timedelta(seconds=30),
            expires_at=current - timedelta(seconds=1),
        )

        registry.register(live)
        registry.register(expired)

        assert registry.list_instances() == (live,)
        assert registry.is_healthy()
        registry.deregister(live.instance_id)
        assert registry.list_instances() == ()
        persistence.close()

    def test_missing_records_raise_contract_specific_errors(self) -> None:
        persistence = SqlPersistence("sqlite://")
        persistence.create_schema()
        identifier = uuid4()

        with pytest.raises(TaskNotFoundError):
            persistence.task_registry().get(identifier)
        with pytest.raises(TaskRecoveryRecordNotFoundError):
            persistence.recovery_store().get_intent(identifier)
        with pytest.raises(ExecutionBatchNotFoundError):
            persistence.execution_store().get_batch(identifier)

        persistence.close()
