"""Server-specific recovery metadata adapter over the optional AWS store."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID

from autoforex.core import TaskRegistry

from autoforex.server.components import TaskBinding, TaskBindingCodec
from autoforex.server.discovery import ServiceInstance, ServiceRegistry
from autoforex.server.execution import (
    ExecutionBatch,
    ExecutionBatchConflictError,
    ExecutionBatchNotFoundError,
    ExecutionBatchState,
    ExecutionJournalStore,
)
from autoforex.server.optional import require_optional_dependency
from autoforex.server.recovery import (
    TaskBindingConflictError,
    TaskExecutionDisposition,
    TaskExecutionIntent,
    TaskIntentConflictError,
    TaskRecoveryRecordNotFoundError,
    TaskRecoveryStore,
)

_BINDING_NAMESPACE = "task-bindings"
_INTENT_NAMESPACE = "task-execution-intents"
_EXECUTION_BATCH_NAMESPACE = "execution-batches"
_EXECUTION_REQUEST_NAMESPACE = "execution-requests"
_SERVER_INSTANCE_NAMESPACE = "server-instances"
_SCHEMA_NAMESPACE = "schema"
_SCHEMA_VERSION_KEY = "version"
_SCHEMA_VERSION = 2


class StoredDocument(Protocol):
    """Shape returned by the AWS generic document store."""

    namespace: str
    key: str
    payload: str
    revision: int


class DocumentStore(TaskRegistry, Protocol):
    """Task registry extended with versioned JSON document operations."""

    def create_schema(self) -> None: ...

    def close(self) -> None: ...

    def put_document(
        self,
        document: object,
        *,
        expected_revision: int | None = None,
    ) -> bool: ...

    def get_document(self, namespace: str, key: str) -> StoredDocument | None: ...

    def list_documents(self, namespace: str) -> Sequence[StoredDocument]: ...

    def delete_document(self, namespace: str, key: str) -> None: ...


class DynamoDbTaskRecoveryStore:
    """Persist server task bindings and intents in DynamoDB documents."""

    def __init__(self, store: DocumentStore, document_type: type) -> None:
        self.store = store
        self.document_type = document_type

    def save_binding(self, definition_id: UUID, binding: TaskBinding) -> TaskBinding:
        """Insert an immutable task binding or accept an identical retry."""
        payload = TaskBindingCodec.to_json(binding)
        document = self.document_type(
            namespace=_BINDING_NAMESPACE,
            key=str(definition_id),
            payload=payload,
            revision=1,
        )
        if self.store.put_document(document, expected_revision=0):
            return binding
        persisted = self.store.get_document(_BINDING_NAMESPACE, str(definition_id))
        if persisted is None:
            raise TaskBindingConflictError(
                f"task binding insert conflicted but no value exists: {definition_id}"
            )
        if persisted.payload != payload:
            raise TaskBindingConflictError(f"task binding is immutable: {definition_id}")
        return binding

    def get_binding(self, definition_id: UUID) -> TaskBinding:
        """Return a persisted task binding."""
        document = self.store.get_document(_BINDING_NAMESPACE, str(definition_id))
        if document is None:
            msg = f"task binding not found: {definition_id}"
            raise TaskRecoveryRecordNotFoundError(msg)
        return TaskBindingCodec.from_json(document.payload)

    def delete_binding(self, definition_id: UUID) -> None:
        """Delete a task binding."""
        self.store.delete_document(_BINDING_NAMESPACE, str(definition_id))

    def save_intent(self, intent: TaskExecutionIntent) -> TaskExecutionIntent:
        """Persist intent with an optimistic revision condition."""
        saved = intent.evolve(revision=intent.revision + 1)
        document = self.document_type(
            namespace=_INTENT_NAMESPACE,
            key=str(intent.task_id),
            payload=saved.model_dump_json(round_trip=True),
            revision=saved.revision,
            attributes={
                "disposition": saved.disposition.value,
                "owner_id": saved.owner_id,
                "lease_id": str(saved.lease_id),
                "fencing_token": saved.generation,
                "lease_expires_at": saved.lease_expires_at.astimezone(UTC).isoformat(
                    timespec="microseconds"
                ),
            },
        )
        written = self.store.put_document(
            document,
            expected_revision=intent.revision,
        )
        if not written:
            msg = f"stale task intent revision for {intent.task_id}: {intent.revision}"
            raise TaskIntentConflictError(msg)
        return saved

    def get_intent(self, task_id: UUID) -> TaskExecutionIntent:
        """Return execution intent by task id."""
        document = self.store.get_document(_INTENT_NAMESPACE, str(task_id))
        if document is None:
            msg = f"task execution intent not found: {task_id}"
            raise TaskRecoveryRecordNotFoundError(msg)
        return TaskExecutionIntent.model_validate_json(document.payload)

    def list_intents(
        self,
        *,
        disposition: TaskExecutionDisposition | None = None,
    ) -> Sequence[TaskExecutionIntent]:
        """List execution intents, optionally filtering desired state."""
        intents = tuple(
            TaskExecutionIntent.model_validate_json(document.payload)
            for document in self.store.list_documents(_INTENT_NAMESPACE)
        )
        if disposition is None:
            return intents
        return tuple(item for item in intents if item.disposition == disposition)

    def delete_intent(self, task_id: UUID) -> None:
        """Delete execution intent."""
        self.store.delete_document(_INTENT_NAMESPACE, str(task_id))

    def is_healthy(self) -> bool:
        """Return whether the DynamoDB table is reachable."""
        try:
            self.store.get_document(_SCHEMA_NAMESPACE, _SCHEMA_VERSION_KEY)
            return True
        except Exception:
            return False


class DynamoDbExecutionJournalStore:
    """DynamoDB implementation of durable execution batches."""

    def __init__(self, store: DocumentStore, document_type: type) -> None:
        self.store = store
        self.document_type = document_type

    def save_batch(self, batch: ExecutionBatch) -> ExecutionBatch:
        """Insert or compare-and-swap one execution batch."""
        saved = batch.evolve(revision=batch.revision + 1)
        document = self.document_type(
            namespace=_EXECUTION_BATCH_NAMESPACE,
            key=str(batch.batch_id),
            payload=saved.model_dump_json(round_trip=True),
            revision=saved.revision,
        )
        if not self.store.put_document(document, expected_revision=batch.revision):
            raise ExecutionBatchConflictError(f"stale execution batch revision: {batch.batch_id}")
        if batch.revision == 0:
            for request in saved.requests:
                request_document = self.document_type(
                    namespace=_EXECUTION_REQUEST_NAMESPACE,
                    key=str(request.id),
                    payload=str(saved.batch_id),
                    revision=1,
                )
                if not self.store.put_document(request_document, expected_revision=0):
                    raise ExecutionBatchConflictError(
                        f"execution request already belongs to a batch: {request.id}"
                    )
        return saved

    def get_batch(self, batch_id: UUID) -> ExecutionBatch:
        """Return an execution batch by id."""
        document = self.store.get_document(_EXECUTION_BATCH_NAMESPACE, str(batch_id))
        if document is None:
            raise ExecutionBatchNotFoundError(f"execution batch not found: {batch_id}")
        return ExecutionBatch.model_validate_json(document.payload)

    def find_batch(self, request_id: UUID) -> ExecutionBatch:
        """Return the batch containing one strategy request."""
        document = self.store.get_document(_EXECUTION_REQUEST_NAMESPACE, str(request_id))
        if document is None:
            raise ExecutionBatchNotFoundError(f"execution batch request not found: {request_id}")
        return self.get_batch(UUID(document.payload))

    def list_pending_batches(self, task_id: UUID) -> Sequence[ExecutionBatch]:
        """Return incomplete batches for a task."""
        batches = tuple(
            ExecutionBatch.model_validate_json(document.payload)
            for document in self.store.list_documents(_EXECUTION_BATCH_NAMESPACE)
        )
        return tuple(
            batch
            for batch in batches
            if batch.task_id == task_id and batch.state != ExecutionBatchState.CHECKPOINTED
        )

    def is_healthy(self) -> bool:
        """Return whether execution documents can be queried."""
        try:
            self.store.list_documents(_EXECUTION_BATCH_NAMESPACE)
            return True
        except Exception:
            return False


class DynamoDbServiceRegistry:
    """DynamoDB document implementation of the server service registry."""

    def __init__(self, store: DocumentStore, document_type: type) -> None:
        self.store = store
        self.document_type = document_type

    def register(self, instance: ServiceInstance) -> None:
        """Create or refresh one instance registration."""
        key = instance.instance_id
        for _ in range(5):
            current = self.store.get_document(_SERVER_INSTANCE_NAMESPACE, key)
            revision = 0 if current is None else current.revision
            document = self.document_type(
                namespace=_SERVER_INSTANCE_NAMESPACE,
                key=key,
                payload=instance.model_dump_json(round_trip=True),
                revision=revision + 1,
                attributes={
                    "expires_at": instance.expires_at.astimezone(UTC).isoformat(
                        timespec="microseconds"
                    ),
                    "status": instance.status.value,
                },
            )
            if self.store.put_document(document, expected_revision=revision):
                return
        raise RuntimeError(f"could not refresh server instance registration: {key}")

    def deregister(self, instance_id: str) -> None:
        """Remove one instance registration."""
        self.store.delete_document(_SERVER_INSTANCE_NAMESPACE, instance_id)

    def list_instances(self) -> Sequence[ServiceInstance]:
        """Return active instance registrations."""
        current = datetime.now(UTC)
        instances = (
            ServiceInstance.model_validate_json(document.payload)
            for document in self.store.list_documents(_SERVER_INSTANCE_NAMESPACE)
        )
        return tuple(
            sorted(
                (instance for instance in instances if instance.is_active(at=current)),
                key=lambda instance: instance.instance_id,
            )
        )

    def is_healthy(self) -> bool:
        """Return whether server registrations can be queried."""
        try:
            self.store.list_documents(_SERVER_INSTANCE_NAMESPACE)
            return True
        except Exception:
            return False

    def close(self) -> None:
        """Leave resource ownership with DynamoDbServerPersistence."""


class DynamoDbServerPersistence:
    """Compose the optional AWS task store for server use."""

    def __init__(
        self,
        *,
        table_name: str,
        region_name: str | None,
        endpoint_url: str | None,
        consistent_reads: bool,
        enable_point_in_time_recovery: bool = True,
    ) -> None:
        module = require_optional_dependency(
            "autoforex.aws",
            extra="aws",
            feature="DynamoDB persistence",
        )
        store_type = module.__dict__["DynamoDbTaskStore"]
        document_type = module.__dict__["DynamoDbDocument"]
        self.store = cast(
            DocumentStore,
            store_type.from_table_name(
                table_name,
                region_name=region_name,
                endpoint_url=endpoint_url,
                consistent_reads=consistent_reads,
                enable_point_in_time_recovery=enable_point_in_time_recovery,
            ),
        )
        self._recovery_store = DynamoDbTaskRecoveryStore(
            self.store,
            document_type,
        )
        self._execution_store = DynamoDbExecutionJournalStore(
            self.store,
            document_type,
        )
        self._service_registry = DynamoDbServiceRegistry(
            self.store,
            document_type,
        )
        self._document_type = document_type

    def create_schema(self) -> None:
        """Create the table and record the current logical schema version."""
        self.store.create_schema()
        current = self.store.get_document(_SCHEMA_NAMESPACE, _SCHEMA_VERSION_KEY)
        if current is None:
            self.store.put_document(
                self._document_type(
                    namespace=_SCHEMA_NAMESPACE,
                    key=_SCHEMA_VERSION_KEY,
                    payload=str(_SCHEMA_VERSION),
                    revision=1,
                ),
                expected_revision=0,
            )
        elif int(current.payload) < _SCHEMA_VERSION:
            updated = self.store.put_document(
                self._document_type(
                    namespace=_SCHEMA_NAMESPACE,
                    key=_SCHEMA_VERSION_KEY,
                    payload=str(_SCHEMA_VERSION),
                    revision=current.revision + 1,
                ),
                expected_revision=current.revision,
            )
            if not updated:
                current = self.store.get_document(_SCHEMA_NAMESPACE, _SCHEMA_VERSION_KEY)
                if current is None or int(current.payload) != _SCHEMA_VERSION:
                    raise RuntimeError("DynamoDB schema migration conflicted")
        elif int(current.payload) > _SCHEMA_VERSION:
            raise RuntimeError(
                f"DynamoDB schema version {current.payload} is newer than server version "
                f"{_SCHEMA_VERSION}"
            )

    def task_registry(self) -> TaskRegistry:
        """Return the DynamoDB Core task registry."""
        return self.store

    def recovery_store(self) -> TaskRecoveryStore:
        """Return DynamoDB task recovery storage."""
        return self._recovery_store

    def execution_store(self) -> ExecutionJournalStore:
        """Return DynamoDB execution journal storage."""
        return self._execution_store

    def service_registry(self) -> ServiceRegistry:
        """Return DynamoDB service discovery storage."""
        return self._service_registry

    def is_healthy(self) -> bool:
        """Return whether the DynamoDB table is reachable."""
        return self._recovery_store.is_healthy()

    def close(self) -> None:
        """Release DynamoDB store resources."""
        self.store.close()
