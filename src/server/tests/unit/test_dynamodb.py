from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, ClassVar, cast
from uuid import uuid4

import pytest

import autoforex.server.dynamodb as dynamodb_module
from autoforex.server.components import BacktestTaskBinding
from autoforex.server.discovery import ServiceInstance
from autoforex.server.dynamodb import (
    DocumentStore,
    DynamoDbExecutionJournalStore,
    DynamoDbServerPersistence,
    DynamoDbServiceRegistry,
    DynamoDbTaskRecoveryStore,
)
from autoforex.server.execution import (
    ExecutionBatch,
    ExecutionBatchConflictError,
    ExecutionBatchState,
)
from autoforex.server.recovery import (
    TaskBindingConflictError,
    TaskExecutionDisposition,
    TaskExecutionIntent,
    TaskIntentConflictError,
    TaskRecoveryRecordNotFoundError,
)


@dataclass(frozen=True, slots=True)
class FakeDocument:
    namespace: str
    key: str
    payload: str
    revision: int
    attributes: dict[str, Any] = field(default_factory=dict)


class FakeDocumentStore:
    last_factory_arguments: ClassVar[dict[str, Any]] = {}

    def __init__(self) -> None:
        self.documents: dict[tuple[str, str], FakeDocument] = {}
        self.created = False
        self.closed = False
        self.fail_reads = False

    @classmethod
    def from_table_name(cls, table_name: str, **kwargs: Any) -> FakeDocumentStore:
        cls.last_factory_arguments = {"table_name": table_name, **kwargs}
        return cls()

    def create_schema(self) -> None:
        self.created = True

    def close(self) -> None:
        self.closed = True

    def put_document(
        self,
        document: FakeDocument,
        *,
        expected_revision: int | None = None,
    ) -> bool:
        key = (document.namespace, document.key)
        current = self.documents.get(key)
        current_revision = 0 if current is None else current.revision
        if expected_revision is not None and expected_revision != current_revision:
            return False
        self.documents[key] = document
        return True

    def get_document(self, namespace: str, key: str) -> FakeDocument | None:
        if self.fail_reads:
            raise RuntimeError("DynamoDB unavailable")
        return self.documents.get((namespace, key))

    def list_documents(self, namespace: str) -> tuple[FakeDocument, ...]:
        if self.fail_reads:
            raise RuntimeError("DynamoDB unavailable")
        return tuple(
            document
            for (document_namespace, _), document in self.documents.items()
            if document_namespace == namespace
        )

    def delete_document(self, namespace: str, key: str) -> None:
        self.documents.pop((namespace, key), None)


class TestDynamoDbTaskRecoveryStore:
    def test_round_trips_immutable_binding_and_versioned_intent(
        self,
        backtest_binding: BacktestTaskBinding,
    ) -> None:
        documents = FakeDocumentStore()
        store = DynamoDbTaskRecoveryStore(
            cast(DocumentStore, cast(Any, documents)),
            FakeDocument,
        )
        definition_id = uuid4()
        intent = TaskExecutionIntent(
            task_id=uuid4(),
            definition_id=definition_id,
            disposition=TaskExecutionDisposition.RUNNING,
            owner_id="server-a",
        )

        store.save_binding(definition_id, backtest_binding)
        store.save_binding(definition_id, backtest_binding)
        saved_intent = store.save_intent(intent)
        persisted_intent = documents.get_document(
            "task-execution-intents",
            str(intent.task_id),
        )

        assert store.get_binding(definition_id) == backtest_binding
        assert store.get_intent(intent.task_id) == saved_intent
        assert store.list_intents(disposition=TaskExecutionDisposition.RUNNING) == (saved_intent,)
        assert saved_intent.revision == 1
        assert persisted_intent is not None
        assert persisted_intent.attributes["lease_expires_at"].endswith("+00:00")

    def test_rejects_conflicting_binding_and_stale_intent(
        self,
        backtest_binding: BacktestTaskBinding,
    ) -> None:
        documents = FakeDocumentStore()
        store = DynamoDbTaskRecoveryStore(
            cast(DocumentStore, cast(Any, documents)),
            FakeDocument,
        )
        definition_id = uuid4()
        conflicting = backtest_binding.evolve(
            data_source=backtest_binding.data_source.evolve(name={"value": "other"})
        )
        intent = TaskExecutionIntent(
            task_id=uuid4(),
            definition_id=definition_id,
            disposition=TaskExecutionDisposition.RUNNING,
            owner_id="server-a",
        )

        store.save_binding(definition_id, backtest_binding)
        store.save_intent(intent)

        with pytest.raises(TaskBindingConflictError):
            store.save_binding(definition_id, conflicting)
        with pytest.raises(TaskIntentConflictError):
            store.save_intent(intent)

    def test_delete_missing_and_health_failure_are_explicit(
        self,
        backtest_binding: BacktestTaskBinding,
    ) -> None:
        documents = FakeDocumentStore()
        store = DynamoDbTaskRecoveryStore(
            cast(DocumentStore, cast(Any, documents)),
            FakeDocument,
        )
        definition_id = uuid4()
        store.save_binding(definition_id, backtest_binding)

        store.delete_binding(definition_id)

        with pytest.raises(TaskRecoveryRecordNotFoundError):
            store.get_binding(definition_id)
        documents.fail_reads = True
        assert not store.is_healthy()


class TestDynamoDbExecutionJournalStore:
    def test_round_trips_indexes_and_filters_execution_batches(
        self,
        execution_batch: ExecutionBatch,
    ) -> None:
        documents = FakeDocumentStore()
        store = DynamoDbExecutionJournalStore(
            cast(DocumentStore, cast(Any, documents)),
            FakeDocument,
        )

        prepared = store.save_batch(execution_batch)
        completed = store.save_batch(prepared.evolve(state=ExecutionBatchState.COMPLETED))

        assert store.get_batch(prepared.batch_id) == completed
        assert store.find_batch(prepared.requests[0].id) == completed
        assert store.list_pending_batches(prepared.task_id) == (completed,)
        assert store.is_healthy()

    def test_rejects_stale_batch_and_reports_unhealthy_store(
        self,
        execution_batch: ExecutionBatch,
    ) -> None:
        documents = FakeDocumentStore()
        store = DynamoDbExecutionJournalStore(
            cast(DocumentStore, cast(Any, documents)),
            FakeDocument,
        )
        store.save_batch(execution_batch)

        with pytest.raises(ExecutionBatchConflictError):
            store.save_batch(execution_batch)
        documents.fail_reads = True
        assert not store.is_healthy()


class TestDynamoDbServiceRegistry:
    def test_round_trips_active_instances_and_removes_registration(self) -> None:
        documents = FakeDocumentStore()
        registry = DynamoDbServiceRegistry(
            cast(DocumentStore, cast(Any, documents)),
            FakeDocument,
        )
        current = datetime.now(UTC)
        instance = ServiceInstance(
            instance_id="server-a",
            host="10.0.0.5",
            port=50051,
            transport_security="plaintext",
            version="0.1.1",
            started_at=current,
            heartbeat_at=current,
            expires_at=current + timedelta(seconds=30),
        )

        registry.register(instance)
        registry.register(
            instance.evolve(
                heartbeat_at=current + timedelta(seconds=1),
                expires_at=current + timedelta(seconds=31),
            )
        )

        assert registry.list_instances()[0].heartbeat_at == current + timedelta(seconds=1)
        assert registry.is_healthy()
        registry.deregister(instance.instance_id)
        assert registry.list_instances() == ()


class TestDynamoDbServerPersistence:
    def test_composes_optional_aws_store_and_creates_schema_marker(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake_module = SimpleNamespace(
            DynamoDbTaskStore=FakeDocumentStore,
            DynamoDbDocument=FakeDocument,
        )
        monkeypatch.setattr(
            dynamodb_module,
            "require_optional_dependency",
            lambda *args, **kwargs: fake_module,
        )
        persistence = DynamoDbServerPersistence(
            table_name="tasks",
            region_name="us-west-2",
            endpoint_url="http://localhost:8000",
            consistent_reads=True,
            enable_point_in_time_recovery=False,
        )

        persistence.create_schema()

        fake_store = cast(FakeDocumentStore, cast(Any, persistence.store))
        schema = fake_store.get_document("schema", "version")
        assert fake_store.created
        assert schema is not None
        assert schema.payload == "2"
        assert persistence.task_registry() is persistence.store
        assert persistence.recovery_store().is_healthy()
        assert persistence.execution_store().is_healthy()
        assert persistence.service_registry().is_healthy()
        assert persistence.is_healthy()
        assert FakeDocumentStore.last_factory_arguments["table_name"] == "tasks"
        persistence.close()
        assert fake_store.closed

    def test_upgrades_the_logical_schema_marker(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake_module = SimpleNamespace(
            DynamoDbTaskStore=FakeDocumentStore,
            DynamoDbDocument=FakeDocument,
        )
        monkeypatch.setattr(
            dynamodb_module,
            "require_optional_dependency",
            lambda *args, **kwargs: fake_module,
        )
        persistence = DynamoDbServerPersistence(
            table_name="tasks",
            region_name=None,
            endpoint_url=None,
            consistent_reads=True,
        )
        persistence.store.put_document(
            FakeDocument(namespace="schema", key="version", payload="1", revision=1),
            expected_revision=0,
        )

        persistence.create_schema()

        schema = persistence.store.get_document("schema", "version")
        assert schema is not None
        assert schema.payload == "2"
        assert schema.revision == 2

    def test_rejects_schema_created_by_a_newer_server(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake_module = SimpleNamespace(
            DynamoDbTaskStore=FakeDocumentStore,
            DynamoDbDocument=FakeDocument,
        )
        monkeypatch.setattr(
            dynamodb_module,
            "require_optional_dependency",
            lambda *args, **kwargs: fake_module,
        )
        persistence = DynamoDbServerPersistence(
            table_name="tasks",
            region_name=None,
            endpoint_url=None,
            consistent_reads=True,
        )
        persistence.store.put_document(
            FakeDocument(namespace="schema", key="version", payload="3", revision=1),
            expected_revision=0,
        )

        with pytest.raises(RuntimeError, match="newer"):
            persistence.create_schema()
