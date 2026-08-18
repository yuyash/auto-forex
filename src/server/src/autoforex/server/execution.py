"""Durable, recoverable broker execution."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from enum import StrEnum
from threading import RLock
from typing import Never, Protocol, cast
from uuid import UUID, uuid5

from autoforex.core import (
    Broker,
    BrokerExecutionUnresolvedError,
    BrokerMutation,
    BrokerMutationOperation,
    BrokerMutationReconciler,
    BrokerReconciliationOutcome,
    CurrencyPair,
    DomainModel,
    ExecutionRecoveryBatch,
    Metadata,
    Order,
    Position,
    PositionSide,
    StrategyEventRequest,
    StrategyExecutionResponse,
    Trade,
    Units,
    now,
)
from pydantic import AwareDatetime, Field

from autoforex.server.lease import TaskLeaseCoordinator, TaskLeaseToken


class ExecutionCommandState(StrEnum):
    """Durable state of one external broker mutation."""

    PREPARED = "prepared"
    DISPATCHING = "dispatching"
    ACKNOWLEDGED = "acknowledged"
    APPLIED = "applied"
    FAILED = "failed"
    UNKNOWN = "unknown"
    REVIEW_REQUIRED = "review_required"


class ExecutionBatchState(StrEnum):
    """Durable state of a strategy callback's broker requests."""

    PREPARED = "prepared"
    COMPLETED = "completed"
    CHECKPOINTED = "checkpointed"
    REVIEW_REQUIRED = "review_required"


class ExecutionCommand(DomainModel):
    """One idempotent broker mutation inside an execution batch."""

    command_id: UUID
    request_id: UUID
    mutation: BrokerMutation
    state: ExecutionCommandState = ExecutionCommandState.PREPARED
    response: Order | None = None
    error: str = ""
    fencing_token: int = Field(ge=1)
    dispatched_at: AwareDatetime | None = None
    acknowledged_at: AwareDatetime | None = None
    applied_at: AwareDatetime | None = None


class ExecutionBatch(DomainModel):
    """Durable write-ahead record for a group of strategy requests."""

    batch_id: UUID
    task_id: UUID
    requests: tuple[StrategyEventRequest, ...]
    checkpoint_at: AwareDatetime | None = None
    state: ExecutionBatchState = ExecutionBatchState.PREPARED
    commands: tuple[ExecutionCommand, ...] = ()
    revision: int = Field(default=0, ge=0)
    created_at: AwareDatetime = Field(default_factory=now)
    updated_at: AwareDatetime = Field(default_factory=now)

    def command(self, command_id: UUID) -> ExecutionCommand | None:
        """Return a command by id."""
        return next((item for item in self.commands if item.command_id == command_id), None)

    def with_command(self, command: ExecutionCommand) -> ExecutionBatch:
        """Return a batch with one command inserted or replaced."""
        commands = tuple(
            command if item.command_id == command.command_id else item for item in self.commands
        )
        if not any(item.command_id == command.command_id for item in self.commands):
            commands = (*commands, command)
        return self.evolve(commands=commands, updated_at=now())


class ExecutionBatchConflictError(RuntimeError):
    """Raised when an execution batch revision is stale."""


class ExecutionBatchNotFoundError(KeyError):
    """Raised when a prepared execution batch cannot be found."""


class ExecutionJournalStore(Protocol):
    """Persistence boundary for durable execution batches."""

    def save_batch(self, batch: ExecutionBatch) -> ExecutionBatch:
        """Insert or compare-and-swap an execution batch."""

    def get_batch(self, batch_id: UUID) -> ExecutionBatch:
        """Return a batch by id."""

    def find_batch(self, request_id: UUID) -> ExecutionBatch:
        """Return the batch containing one strategy request."""

    def list_pending_batches(self, task_id: UUID) -> Sequence[ExecutionBatch]:
        """Return incomplete batches for a task."""

    def is_healthy(self) -> bool:
        """Return whether the journal backend is reachable."""


class InMemoryExecutionJournalStore:
    """Thread-safe execution journal for local composition and tests."""

    def __init__(self) -> None:
        self._batches: dict[UUID, ExecutionBatch] = {}
        self._requests: dict[UUID, UUID] = {}
        self._lock = RLock()

    def save_batch(self, batch: ExecutionBatch) -> ExecutionBatch:
        """Insert or compare-and-swap one execution batch."""
        with self._lock:
            current = self._batches.get(batch.batch_id)
            current_revision = 0 if current is None else current.revision
            if current_revision != batch.revision:
                raise ExecutionBatchConflictError(
                    f"stale execution batch revision: {batch.batch_id}"
                )
            for request in batch.requests:
                existing = self._requests.get(request.id)
                if existing is not None and existing != batch.batch_id:
                    raise ExecutionBatchConflictError(
                        f"execution request already belongs to a batch: {request.id}"
                    )
            saved = batch.evolve(revision=batch.revision + 1)
            self._batches[batch.batch_id] = saved
            for request in saved.requests:
                self._requests[request.id] = saved.batch_id
            return saved

    def get_batch(self, batch_id: UUID) -> ExecutionBatch:
        """Return an execution batch by id."""
        with self._lock:
            try:
                return self._batches[batch_id]
            except KeyError as exc:
                raise ExecutionBatchNotFoundError(f"execution batch not found: {batch_id}") from exc

    def find_batch(self, request_id: UUID) -> ExecutionBatch:
        """Return the batch containing one strategy request."""
        with self._lock:
            try:
                return self._batches[self._requests[request_id]]
            except KeyError as exc:
                raise ExecutionBatchNotFoundError(
                    f"execution batch request not found: {request_id}"
                ) from exc

    def list_pending_batches(self, task_id: UUID) -> Sequence[ExecutionBatch]:
        """Return incomplete batches for a task."""
        with self._lock:
            return tuple(
                batch
                for batch in self._batches.values()
                if batch.task_id == task_id and batch.state != ExecutionBatchState.CHECKPOINTED
            )

    def is_healthy(self) -> bool:
        """Return true for an in-process journal."""
        return True


class DurableExecutionBroker(Broker):
    """Broker decorator providing write-ahead execution and reconciliation."""

    _current_request: ContextVar[StrategyEventRequest | None] = ContextVar(
        "auto_forex_execution_request",
        default=None,
    )

    def __init__(
        self,
        broker: Broker,
        *,
        store: ExecutionJournalStore,
        leases: TaskLeaseCoordinator,
        lease: TaskLeaseToken,
    ) -> None:
        self.broker = broker
        self.store = store
        self.leases = leases
        self.lease = lease

    def prepare(
        self,
        requests: Sequence[StrategyEventRequest],
        *,
        checkpoint_at: datetime | None,
    ) -> None:
        """Write broker-requiring requests before publishing them."""
        self.leases.assert_current(self.lease)
        broker_requests = tuple(request for request in requests if request.requires_broker)
        if not broker_requests:
            return
        batch_id = self._batch_id(broker_requests)
        try:
            existing = self.store.get_batch(batch_id)
        except ExecutionBatchNotFoundError:
            self.store.save_batch(
                ExecutionBatch(
                    batch_id=batch_id,
                    task_id=broker_requests[0].task_id,
                    requests=broker_requests,
                    checkpoint_at=checkpoint_at,
                )
            )
            return
        if existing.requests != broker_requests or existing.checkpoint_at != checkpoint_at:
            raise ExecutionBatchConflictError(f"execution batch identity collision: {batch_id}")

    def pending(self, task_id: UUID) -> Sequence[ExecutionRecoveryBatch]:
        """Return request batches that must be replayed during recovery."""
        return tuple(
            ExecutionRecoveryBatch(
                task_id=batch.task_id,
                requests=batch.requests,
                checkpoint_at=batch.checkpoint_at,
            )
            for batch in self.store.list_pending_batches(task_id)
        )

    def response_applied(self, response: StrategyExecutionResponse) -> None:
        """Mark the command carried by a response as applied."""
        command_value = response.metadata.get("execution_command_id")
        if command_value is None:
            return
        command_id = UUID(str(command_value))
        self._update_command(
            response.event.id,
            command_id,
            lambda command: command.evolve(
                state=ExecutionCommandState.APPLIED,
                applied_at=now(),
            ),
        )

    def complete(self, requests: Sequence[StrategyEventRequest]) -> None:
        """Mark a prepared batch complete after synchronous response application."""
        self.leases.assert_current(self.lease)
        broker_requests = tuple(request for request in requests if request.requires_broker)
        if not broker_requests:
            return
        for _ in range(5):
            batch = self.store.get_batch(self._batch_id(broker_requests))
            if any(
                command.state
                in {
                    ExecutionCommandState.DISPATCHING,
                    ExecutionCommandState.FAILED,
                    ExecutionCommandState.UNKNOWN,
                    ExecutionCommandState.REVIEW_REQUIRED,
                }
                for command in batch.commands
            ):
                raise BrokerExecutionUnresolvedError(
                    f"execution batch requires reconciliation: {batch.batch_id}"
                )
            completed = batch.evolve(
                state=(
                    ExecutionBatchState.CHECKPOINTED
                    if batch.checkpoint_at is None
                    else ExecutionBatchState.COMPLETED
                ),
                commands=tuple(
                    command.evolve(
                        state=(
                            ExecutionCommandState.APPLIED
                            if command.state == ExecutionCommandState.ACKNOWLEDGED
                            else command.state
                        ),
                        applied_at=(
                            now()
                            if command.state == ExecutionCommandState.ACKNOWLEDGED
                            else command.applied_at
                        ),
                    )
                    for command in batch.commands
                ),
                updated_at=now(),
            )
            try:
                self.leases.assert_current(self.lease)
                self.store.save_batch(completed)
                return
            except ExecutionBatchConflictError:
                continue
        raise ExecutionBatchConflictError("could not complete execution batch after retries")

    def checkpointed(self, requests: Sequence[StrategyEventRequest]) -> None:
        """Mark a completed batch covered by a durable task checkpoint."""
        self.leases.assert_current(self.lease)
        broker_requests = tuple(request for request in requests if request.requires_broker)
        if not broker_requests:
            return
        for _ in range(5):
            batch = self.store.get_batch(self._batch_id(broker_requests))
            if batch.state == ExecutionBatchState.CHECKPOINTED:
                return
            if batch.state != ExecutionBatchState.COMPLETED:
                raise ExecutionBatchConflictError(
                    f"execution batch is not complete: {batch.batch_id}"
                )
            try:
                self.leases.assert_current(self.lease)
                self.store.save_batch(
                    batch.evolve(
                        state=ExecutionBatchState.CHECKPOINTED,
                        updated_at=now(),
                    )
                )
                return
            except ExecutionBatchConflictError:
                continue
        raise ExecutionBatchConflictError("could not checkpoint execution batch after retries")

    @contextmanager
    def execution_scope(self, request: StrategyEventRequest):
        """Associate broker calls with one prepared strategy request."""
        token = self._current_request.set(request)
        try:
            yield
        finally:
            self._current_request.reset(token)

    def place_order(self, order: Order) -> Order:
        """Place or recover one broker order."""
        request = self._require_request()
        command_id = request.id
        mutation = BrokerMutation(
            command_id=command_id,
            task_id=request.task_id,
            operation=BrokerMutationOperation.PLACE_ORDER,
            order=order,
        )
        return self._execute(mutation, lambda: self.broker.place_order(order))

    def close_position(
        self,
        *,
        position: Position,
        side: PositionSide,
        units: Units | None = None,
    ) -> Order:
        """Close or recover one broker position mutation."""
        request = self._require_request()
        target = f"{position.instrument}:{side.value}:{units or 'all'}"
        command_id = uuid5(request.id, f"close-position:{target}")
        mutation = BrokerMutation(
            command_id=command_id,
            task_id=request.task_id,
            operation=BrokerMutationOperation.CLOSE_POSITION,
            position=position,
            position_side=side,
            units=units,
        )
        return self._execute(
            mutation,
            lambda: self.broker.close_position(position=position, side=side, units=units),
        )

    def positions(self, *, instrument: CurrencyPair | None = None) -> Sequence[Position]:
        """Delegate position reads."""
        return self.broker.positions(instrument=instrument)

    def close_trade(self, trade: Trade, *, units: Units | None = None) -> Order:
        """Close or recover one broker trade mutation."""
        request = self._require_request()
        command_id = uuid5(request.id, f"close-trade:{trade.id}:{units or 'all'}")
        mutation = BrokerMutation(
            command_id=command_id,
            task_id=request.task_id,
            operation=BrokerMutationOperation.CLOSE_TRADE,
            trade=trade,
            units=units,
        )
        return self._execute(
            mutation,
            lambda: self.broker.close_trade(trade, units=units),
        )

    def trades(self, *, instrument: CurrencyPair | None = None) -> Sequence[Trade]:
        """Delegate trade reads."""
        return self.broker.trades(instrument=instrument)

    def _execute(
        self,
        mutation: BrokerMutation,
        invoke: Callable[[], Order],
    ) -> Order:
        self.leases.assert_current(self.lease)
        request = self._require_request()
        batch = self.store.find_batch(request.id)
        command = batch.command(mutation.command_id)
        if command is None:
            command = ExecutionCommand(
                command_id=mutation.command_id,
                request_id=request.id,
                mutation=mutation,
                fencing_token=self.lease.fencing_token,
            )
            batch = self._save_command(batch, command)
            command = batch.command(mutation.command_id)
            assert command is not None

        if command.state == ExecutionCommandState.APPLIED:
            return self._annotated_response(command, already_applied=True)
        if command.state == ExecutionCommandState.ACKNOWLEDGED:
            return self._annotated_response(command)
        if command.state in {
            ExecutionCommandState.DISPATCHING,
            ExecutionCommandState.UNKNOWN,
            ExecutionCommandState.REVIEW_REQUIRED,
        }:
            return self._reconcile_or_dispatch(batch, command, invoke)
        if command.state == ExecutionCommandState.FAILED:
            raise RuntimeError(command.error or "broker execution previously failed")

        cursor = self._capture_cursor()
        command = command.evolve(
            mutation=command.mutation.evolve(provider_cursor=cursor),
            state=ExecutionCommandState.DISPATCHING,
            dispatched_at=now(),
            fencing_token=self.lease.fencing_token,
        )
        batch = self._save_command(batch, command)
        command = batch.command(command.command_id)
        assert command is not None
        return self._dispatch(batch, command, invoke)

    def _dispatch(
        self,
        batch: ExecutionBatch,
        command: ExecutionCommand,
        invoke: Callable[[], Order],
    ) -> Order:
        self.leases.assert_current(self.lease)
        try:
            response = self._annotate(invoke(), command.command_id)
        except Exception as exc:
            unknown = command.evolve(
                state=ExecutionCommandState.UNKNOWN,
                error=f"{exc.__class__.__name__}: {exc}",
            )
            batch = self._save_command(batch, unknown)
            current = batch.command(command.command_id)
            assert current is not None
            try:
                return self._reconcile_or_dispatch(batch, current, invoke, retry_absent=False)
            except BrokerExecutionUnresolvedError:
                raise
            except Exception:
                raise exc from None
        acknowledged = command.evolve(
            state=ExecutionCommandState.ACKNOWLEDGED,
            response=response,
            acknowledged_at=now(),
            error="",
        )
        self._save_command(batch, acknowledged)
        return response

    def _reconcile_or_dispatch(
        self,
        batch: ExecutionBatch,
        command: ExecutionCommand,
        invoke: Callable[[], Order],
        *,
        retry_absent: bool = True,
    ) -> Order:
        if not isinstance(self.broker, BrokerMutationReconciler):
            self._require_manual_review(batch, command, "broker does not support reconciliation")
        reconciler = cast(BrokerMutationReconciler, self.broker)
        try:
            result = reconciler.reconcile_execution(command.mutation)
        except Exception as exc:
            self._require_manual_review(
                batch,
                command,
                f"reconciliation failed: {exc.__class__.__name__}: {exc}",
            )
        if result.outcome == BrokerReconciliationOutcome.APPLIED and result.order is not None:
            response = self._annotate(result.order, command.command_id)
            acknowledged = command.evolve(
                state=ExecutionCommandState.ACKNOWLEDGED,
                response=response,
                acknowledged_at=now(),
                error="",
            )
            self._save_command(batch, acknowledged)
            return response
        if result.outcome == BrokerReconciliationOutcome.NOT_APPLIED:
            if retry_absent:
                prepared = command.evolve(
                    state=ExecutionCommandState.PREPARED,
                    error="",
                )
                updated = self._save_command(batch, prepared)
                current = updated.command(command.command_id)
                assert current is not None
                return self._execute(current.mutation, invoke)
            self._require_manual_review(
                batch,
                command,
                result.details
                or (
                    "provider reported not applied immediately after an "
                    "ambiguous dispatch; recovery confirmation is required"
                ),
            )
        self._require_manual_review(batch, command, result.details or "indeterminate execution")

    def _require_manual_review(
        self,
        batch: ExecutionBatch,
        command: ExecutionCommand,
        details: str,
    ) -> Never:
        review = command.evolve(
            state=ExecutionCommandState.REVIEW_REQUIRED,
            error=details,
        )
        updated = self._save_command(batch, review)
        for _ in range(5):
            current = self.store.get_batch(updated.batch_id)
            try:
                self.leases.assert_current(self.lease)
                self.store.save_batch(
                    current.evolve(
                        state=ExecutionBatchState.REVIEW_REQUIRED,
                        updated_at=now(),
                    )
                )
                break
            except ExecutionBatchConflictError:
                continue
        raise BrokerExecutionUnresolvedError(details)

    def _update_command(
        self,
        request_id: UUID,
        command_id: UUID,
        update: Callable[[ExecutionCommand], ExecutionCommand],
    ) -> None:
        for _ in range(5):
            batch = self.store.find_batch(request_id)
            command = batch.command(command_id)
            if command is None:
                return
            try:
                self._save_command(batch, update(command))
                return
            except ExecutionBatchConflictError:
                continue
        raise ExecutionBatchConflictError(f"could not update execution command: {command_id}")

    def _save_command(
        self,
        batch: ExecutionBatch,
        command: ExecutionCommand,
    ) -> ExecutionBatch:
        self.leases.assert_current(self.lease)
        return self.store.save_batch(batch.with_command(command))

    def _capture_cursor(self) -> str | None:
        if isinstance(self.broker, BrokerMutationReconciler):
            return self.broker.capture_execution_cursor()
        return None

    def _annotated_response(
        self,
        command: ExecutionCommand,
        *,
        already_applied: bool = False,
    ) -> Order:
        if command.response is None:
            raise BrokerExecutionUnresolvedError(
                f"execution command has no durable response: {command.command_id}"
            )
        response = command.response
        if already_applied:
            response = response.evolve(
                metadata=response.metadata.with_value("execution_response_applied", True)
            )
        return response

    @staticmethod
    def _annotate(order: Order, command_id: UUID) -> Order:
        return order.evolve(
            metadata=order.metadata.merge(Metadata.of(execution_command_id=str(command_id)))
        )

    def _require_request(self) -> StrategyEventRequest:
        request = self._current_request.get()
        if request is None:
            raise RuntimeError("broker mutation requires a strategy execution scope")
        return request

    @staticmethod
    def _batch_id(requests: Sequence[StrategyEventRequest]) -> UUID:
        first = requests[0]
        identity = ":".join(str(request.id) for request in requests)
        return uuid5(first.task_id, identity)
