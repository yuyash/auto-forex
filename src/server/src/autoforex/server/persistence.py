"""SQL-backed task state and recovery persistence."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from threading import RLock
from typing import Any, cast
from uuid import UUID

from autoforex.core import ExecutableTask, TaskNotFoundError, TaskStatus
from autoforex.core.tasks.context import ContextStore
from sqlalchemy import (
    DateTime,
    Engine,
    Integer,
    String,
    Text,
    create_engine,
    delete,
    func,
    select,
    text,
    update,
)
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from autoforex.server.components import TaskBinding, TaskBindingCodec
from autoforex.server.discovery import ServiceInstance, ServiceRegistry
from autoforex.server.execution import (
    ExecutionBatch,
    ExecutionBatchConflictError,
    ExecutionBatchNotFoundError,
    ExecutionBatchState,
    ExecutionJournalStore,
)
from autoforex.server.lease import TaskLeaseLostError, TaskLeaseToken
from autoforex.server.optional import require_optional_dependency
from autoforex.server.recovery import (
    TaskBindingConflictError,
    TaskExecutionDisposition,
    TaskExecutionIntent,
    TaskIntentConflictError,
    TaskRecoveryRecordNotFoundError,
)


class PersistenceBase(DeclarativeBase):
    """Declarative base for server persistence rows."""


class TaskRow(PersistenceBase):
    """Serialized Core task snapshot with queryable lifecycle columns."""

    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    definition_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)


class TaskBindingRow(PersistenceBase):
    """Serialized runtime component binding keyed by task definition."""

    __tablename__ = "task_bindings"

    definition_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)


class TaskIntentRow(PersistenceBase):
    """Serialized desired execution state keyed by executable task."""

    __tablename__ = "task_execution_intents"

    task_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    disposition: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)


class ExecutionBatchRow(PersistenceBase):
    """Serialized durable broker execution batch."""

    __tablename__ = "execution_batches"

    batch_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)


class ExecutionRequestRow(PersistenceBase):
    """Lookup from strategy request id to its execution batch."""

    __tablename__ = "execution_requests"

    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)


class SchemaMigrationRow(PersistenceBase):
    """Applied server schema migration."""

    __tablename__ = "schema_migrations"

    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    description: Mapped[str] = mapped_column(String(120), nullable=False)


class ServerInstanceRow(PersistenceBase):
    """Discoverable server instance with an indexed expiration time."""

    __tablename__ = "server_instances"

    instance_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    payload: Mapped[str] = mapped_column(Text, nullable=False)


class SqlSchemaMigrator:
    """Apply ordered, idempotent SQL schema migrations."""

    LATEST_VERSION = 2

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def migrate(self) -> None:
        """Bring the database schema to the latest supported version."""
        PersistenceBase.metadata.create_all(
            self.engine,
            tables=[cast(Any, SchemaMigrationRow.__table__)],
            checkfirst=True,
        )
        with Session(self.engine) as session:
            current = session.scalar(select(func.max(SchemaMigrationRow.version))) or 0
        if current > self.LATEST_VERSION:
            raise RuntimeError(
                f"database schema version {current} is newer than server version "
                f"{self.LATEST_VERSION}"
            )
        if current < 1:
            PersistenceBase.metadata.create_all(
                self.engine,
                tables=[
                    cast(Any, TaskRow.__table__),
                    cast(Any, TaskBindingRow.__table__),
                    cast(Any, TaskIntentRow.__table__),
                    cast(Any, ExecutionBatchRow.__table__),
                    cast(Any, ExecutionRequestRow.__table__),
                ],
            )
            with Session(self.engine) as session, session.begin():
                session.add(
                    SchemaMigrationRow(
                        version=1,
                        description="initial durable task and execution schema",
                    )
                )
            current = 1
        if current < 2:
            PersistenceBase.metadata.create_all(
                self.engine,
                tables=[cast(Any, ServerInstanceRow.__table__)],
            )
            with Session(self.engine) as session, session.begin():
                session.add(
                    SchemaMigrationRow(
                        version=2,
                        description="server service discovery registry",
                    )
                )


class SqlPersistence:
    """Composition root for SQL task persistence."""

    def __init__(self, database_url: str, *, echo: bool = False) -> None:
        engine_options: dict[str, object] = {"echo": echo}
        if database_url.startswith(("postgresql://", "postgresql+psycopg://")):
            require_optional_dependency(
                "psycopg",
                extra="postgresql",
                feature="PostgreSQL persistence",
            )
        if database_url.startswith("sqlite"):
            engine_options["connect_args"] = {"check_same_thread": False}
        if database_url in {"sqlite://", "sqlite:///:memory:"}:
            engine_options["poolclass"] = StaticPool
        self.engine: Engine = create_engine(database_url, **engine_options)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self._lock = RLock()

    def create_schema(self) -> None:
        """Apply server-owned schema migrations."""
        SqlSchemaMigrator(self.engine).migrate()

    def close(self) -> None:
        """Dispose the SQL connection pool."""
        self.engine.dispose()

    def task_registry(self) -> SqlTaskRegistry:
        """Create a Core TaskRegistry backed by this database."""
        return SqlTaskRegistry(sessions=self.sessions, lock=self._lock)

    def recovery_store(self) -> SqlTaskRecoveryStore:
        """Create a recovery store backed by this database."""
        return SqlTaskRecoveryStore(sessions=self.sessions, lock=self._lock)

    def execution_store(self) -> ExecutionJournalStore:
        """Create a durable execution journal backed by this database."""
        return SqlExecutionJournalStore(sessions=self.sessions, lock=self._lock)

    def service_registry(self) -> ServiceRegistry:
        """Create a service registry backed by this database."""
        return SqlServiceRegistry(sessions=self.sessions, lock=self._lock)

    def is_healthy(self) -> bool:
        """Return whether the database can execute a trivial query."""
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except Exception:
            return False


class SqlTaskRegistry:
    """Thread-safe SQL implementation of Core's TaskRegistry contract."""

    def __init__(
        self,
        *,
        sessions: sessionmaker[Session],
        lock: RLock | None = None,
    ) -> None:
        self._sessions = sessions
        self._lock = lock or RLock()
        self._contexts = ContextStore(task_getter=self.get, task_saver=self.save)
        self._fence_token_resolver: Callable[[UUID], TaskLeaseToken] | None = None

    def save(self, task: ExecutableTask) -> ExecutableTask:
        """Insert or update a serialized task snapshot."""
        with self._lock, self._sessions.begin() as session:
            task_id = str(task.id)
            intent = self._assert_fence(session, task.id)
            row = session.get(TaskRow, task_id)
            if (
                row is not None
                and intent is not None
                and intent.disposition != TaskExecutionDisposition.RUNNING
                and self._is_active_status(task.status)
            ):
                return ExecutableTask.model_validate_json(row.payload)
            if row is None:
                row = TaskRow(task_id=task_id)
                session.add(row)
            row.definition_id = str(task.definition_id)
            row.task_type = task.task_type.value
            row.status = task.status.value
            row.payload = task.model_dump_json(round_trip=True)
        return task

    def configure_fencing(
        self,
        *,
        token_resolver: Callable[[UUID], TaskLeaseToken],
        intent_namespace: str,
    ) -> None:
        """Require an atomic lease check for every task write."""
        _ = intent_namespace
        self._fence_token_resolver = token_resolver

    def get(self, task_id: UUID) -> ExecutableTask:
        """Return a task snapshot by id."""
        with self._lock, self._sessions() as session:
            row = session.get(TaskRow, str(task_id))
            if row is None:
                msg = f"task not found: {task_id}"
                raise TaskNotFoundError(msg)
            return ExecutableTask.model_validate_json(row.payload)

    def list(self, *, status: TaskStatus | None = None) -> Sequence[ExecutableTask]:
        """List task snapshots in creation order."""
        statement = select(TaskRow)
        if status is not None:
            statement = statement.where(TaskRow.status == status.value)
        statement = statement.order_by(TaskRow.task_id)
        with self._lock, self._sessions() as session:
            rows = session.scalars(statement).all()
            return tuple(ExecutableTask.model_validate_json(row.payload) for row in rows)

    def initialize_context(self, task: ExecutableTask, *, strategy_name: str):
        """Initialize execution context for the current task run."""
        return self._contexts.initialize(task, strategy_name=strategy_name)

    def current_context(self, task_id: UUID):
        """Return the current in-process strategy context."""
        return self._contexts.current(task_id)

    def stage_context(self, context):
        """Stage strategy context before event publication."""
        return self._contexts.stage(context)

    def save_context(self, context):
        """Persist strategy state from a runtime context."""
        return self._contexts.save(context)

    def apply_execution_response(self, response) -> None:
        """Apply an execution response to runtime accounting state."""
        self._contexts.apply_execution_response(response)

    def _assert_fence(
        self,
        session: Session,
        task_id: UUID,
    ) -> TaskExecutionIntent | None:
        if self._fence_token_resolver is None:
            return None
        token = self._fence_token_resolver(task_id)
        row = session.scalar(
            select(TaskIntentRow).where(TaskIntentRow.task_id == str(task_id)).with_for_update()
        )
        if row is None:
            raise TaskLeaseLostError(f"task execution intent not found: {task_id}")
        intent = TaskExecutionIntent.model_validate_json(row.payload)
        if not token.matches(intent) or not intent.lease_is_valid():
            raise TaskLeaseLostError(f"stale task fencing token: {task_id}")
        return intent

    @staticmethod
    def _is_active_status(status: TaskStatus) -> bool:
        return status not in {
            TaskStatus.PAUSED,
            TaskStatus.STOPPED,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
        }


class SqlServiceRegistry:
    """SQL implementation of the server service registry."""

    def __init__(
        self,
        *,
        sessions: sessionmaker[Session],
        lock: RLock | None = None,
    ) -> None:
        self._sessions = sessions
        self._lock = lock or RLock()

    def register(self, instance: ServiceInstance) -> None:
        """Create or refresh one instance registration."""
        with self._lock, self._sessions.begin() as session:
            row = session.get(ServerInstanceRow, instance.instance_id)
            if row is None:
                row = ServerInstanceRow(instance_id=instance.instance_id)
                session.add(row)
            row.expires_at = instance.expires_at.astimezone(UTC)
            row.payload = instance.model_dump_json(round_trip=True)

    def deregister(self, instance_id: str) -> None:
        """Remove one instance registration."""
        with self._lock, self._sessions.begin() as session:
            session.execute(
                delete(ServerInstanceRow).where(ServerInstanceRow.instance_id == instance_id)
            )

    def list_instances(self) -> Sequence[ServiceInstance]:
        """Return active instance registrations."""
        current = datetime.now(UTC)
        statement = (
            select(ServerInstanceRow)
            .where(ServerInstanceRow.expires_at > current)
            .order_by(ServerInstanceRow.instance_id)
        )
        with self._lock, self._sessions() as session:
            rows = session.scalars(statement).all()
        return tuple(
            instance
            for row in rows
            if (instance := ServiceInstance.model_validate_json(row.payload)).is_active(at=current)
        )

    def is_healthy(self) -> bool:
        """Return whether server registrations can be queried."""
        try:
            with self._lock, self._sessions() as session:
                session.execute(select(ServerInstanceRow.instance_id).limit(1))
            return True
        except Exception:
            return False

    def close(self) -> None:
        """Leave connection ownership with SqlPersistence."""


class SqlTaskRecoveryStore:
    """SQL persistence for runtime bindings and desired execution state."""

    def __init__(
        self,
        *,
        sessions: sessionmaker[Session],
        lock: RLock | None = None,
    ) -> None:
        self._sessions = sessions
        self._lock = lock or RLock()

    def save_binding(self, definition_id: UUID, binding: TaskBinding) -> TaskBinding:
        """Insert an immutable task binding or accept an identical retry."""
        key = str(definition_id)
        payload = TaskBindingCodec.to_json(binding)
        try:
            with self._lock, self._sessions.begin() as session:
                row = session.get(TaskBindingRow, key)
                if row is not None:
                    self._require_same_binding(definition_id, row.payload, payload)
                    return binding
                session.add(TaskBindingRow(definition_id=key, payload=payload))
                session.flush()
        except IntegrityError:
            with self._lock, self._sessions() as session:
                row = session.get(TaskBindingRow, key)
                if row is None:
                    raise
                self._require_same_binding(definition_id, row.payload, payload)
        return binding

    def get_binding(self, definition_id: UUID) -> TaskBinding:
        """Return a persisted task binding."""
        with self._lock, self._sessions() as session:
            row = session.get(TaskBindingRow, str(definition_id))
            if row is None:
                msg = f"task binding not found: {definition_id}"
                raise TaskRecoveryRecordNotFoundError(msg)
            return TaskBindingCodec.from_json(row.payload)

    def delete_binding(self, definition_id: UUID) -> None:
        """Delete a task binding."""
        with self._lock, self._sessions.begin() as session:
            session.execute(
                delete(TaskBindingRow).where(TaskBindingRow.definition_id == str(definition_id))
            )

    def save_intent(self, intent: TaskExecutionIntent) -> TaskExecutionIntent:
        """Insert or update task execution intent."""
        key = str(intent.task_id)
        saved = intent.evolve(revision=intent.revision + 1)
        try:
            with self._lock, self._sessions.begin() as session:
                if intent.revision == 0:
                    session.add(
                        TaskIntentRow(
                            task_id=key,
                            disposition=saved.disposition.value,
                            revision=saved.revision,
                            payload=saved.model_dump_json(round_trip=True),
                        )
                    )
                    session.flush()
                else:
                    result = cast(
                        CursorResult[Any],
                        session.execute(
                            update(TaskIntentRow)
                            .where(
                                TaskIntentRow.task_id == key,
                                TaskIntentRow.revision == intent.revision,
                            )
                            .values(
                                disposition=saved.disposition.value,
                                revision=saved.revision,
                                payload=saved.model_dump_json(round_trip=True),
                            )
                        ),
                    )
                    if result.rowcount != 1:
                        msg = f"stale task intent revision for {intent.task_id}: {intent.revision}"
                        raise TaskIntentConflictError(msg)
        except IntegrityError as exc:
            msg = f"task execution intent already exists: {intent.task_id}"
            raise TaskIntentConflictError(msg) from exc
        return saved

    def get_intent(self, task_id: UUID) -> TaskExecutionIntent:
        """Return execution intent by task id."""
        with self._lock, self._sessions() as session:
            row = session.get(TaskIntentRow, str(task_id))
            if row is None:
                msg = f"task execution intent not found: {task_id}"
                raise TaskRecoveryRecordNotFoundError(msg)
            return TaskExecutionIntent.model_validate_json(row.payload)

    def list_intents(
        self,
        *,
        disposition: TaskExecutionDisposition | None = None,
    ) -> Sequence[TaskExecutionIntent]:
        """List execution intents."""
        statement = select(TaskIntentRow)
        if disposition is not None:
            statement = statement.where(TaskIntentRow.disposition == disposition.value)
        statement = statement.order_by(TaskIntentRow.task_id)
        with self._lock, self._sessions() as session:
            rows = session.scalars(statement).all()
            return tuple(TaskExecutionIntent.model_validate_json(row.payload) for row in rows)

    def delete_intent(self, task_id: UUID) -> None:
        """Delete execution intent."""
        with self._lock, self._sessions.begin() as session:
            session.execute(delete(TaskIntentRow).where(TaskIntentRow.task_id == str(task_id)))

    def is_healthy(self) -> bool:
        """Return whether recovery metadata can be queried."""
        try:
            with self._lock, self._sessions() as session:
                session.execute(select(TaskIntentRow.task_id).limit(1))
            return True
        except Exception:
            return False

    @staticmethod
    def _require_same_binding(
        definition_id: UUID,
        persisted: str,
        candidate: str,
    ) -> None:
        if persisted != candidate:
            raise TaskBindingConflictError(f"task binding is immutable: {definition_id}")


class SqlExecutionJournalStore:
    """SQL implementation of durable broker execution batches."""

    def __init__(
        self,
        *,
        sessions: sessionmaker[Session],
        lock: RLock | None = None,
    ) -> None:
        self._sessions = sessions
        self._lock = lock or RLock()

    def save_batch(self, batch: ExecutionBatch) -> ExecutionBatch:
        """Insert or compare-and-swap one execution batch."""
        saved = batch.evolve(revision=batch.revision + 1)
        key = str(batch.batch_id)
        try:
            with self._lock, self._sessions.begin() as session:
                if batch.revision == 0:
                    session.add(
                        ExecutionBatchRow(
                            batch_id=key,
                            task_id=str(saved.task_id),
                            state=saved.state.value,
                            revision=saved.revision,
                            payload=saved.model_dump_json(round_trip=True),
                        )
                    )
                    for request in saved.requests:
                        session.add(
                            ExecutionRequestRow(
                                request_id=str(request.id),
                                batch_id=key,
                            )
                        )
                    session.flush()
                else:
                    result = cast(
                        CursorResult[Any],
                        session.execute(
                            update(ExecutionBatchRow)
                            .where(
                                ExecutionBatchRow.batch_id == key,
                                ExecutionBatchRow.revision == batch.revision,
                            )
                            .values(
                                state=saved.state.value,
                                revision=saved.revision,
                                payload=saved.model_dump_json(round_trip=True),
                            )
                        ),
                    )
                    if result.rowcount != 1:
                        raise ExecutionBatchConflictError(
                            f"stale execution batch revision: {batch.batch_id}"
                        )
        except IntegrityError as exc:
            raise ExecutionBatchConflictError(
                f"execution batch already exists: {batch.batch_id}"
            ) from exc
        return saved

    def get_batch(self, batch_id: UUID) -> ExecutionBatch:
        """Return an execution batch by id."""
        with self._lock, self._sessions() as session:
            row = session.get(ExecutionBatchRow, str(batch_id))
            if row is None:
                raise ExecutionBatchNotFoundError(f"execution batch not found: {batch_id}")
            return ExecutionBatch.model_validate_json(row.payload)

    def find_batch(self, request_id: UUID) -> ExecutionBatch:
        """Return the batch containing one strategy request."""
        with self._lock, self._sessions() as session:
            request = session.get(ExecutionRequestRow, str(request_id))
            if request is None:
                raise ExecutionBatchNotFoundError(
                    f"execution batch request not found: {request_id}"
                )
            row = session.get(ExecutionBatchRow, request.batch_id)
            if row is None:
                raise ExecutionBatchNotFoundError(f"execution batch not found: {request.batch_id}")
            return ExecutionBatch.model_validate_json(row.payload)

    def list_pending_batches(self, task_id: UUID) -> Sequence[ExecutionBatch]:
        """Return incomplete batches for a task in creation order."""
        statement = (
            select(ExecutionBatchRow)
            .where(
                ExecutionBatchRow.task_id == str(task_id),
                ExecutionBatchRow.state != ExecutionBatchState.CHECKPOINTED.value,
            )
            .order_by(ExecutionBatchRow.batch_id)
        )
        with self._lock, self._sessions() as session:
            rows = session.scalars(statement).all()
            return tuple(ExecutionBatch.model_validate_json(row.payload) for row in rows)

    def is_healthy(self) -> bool:
        """Return whether journal rows can be queried."""
        try:
            with self._lock, self._sessions() as session:
                session.execute(select(ExecutionBatchRow.batch_id).limit(1))
            return True
        except Exception:
            return False
