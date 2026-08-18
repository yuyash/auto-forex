"""Distributed task leases and fenced persistence."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from threading import RLock
from typing import Any
from uuid import UUID

from autoforex.core import ExecutableTask, TaskRegistry, TaskStatus, Tick
from autoforex.core.strategies.base import StrategyContext
from autoforex.core.strategies.execution import StrategyExecutionResponse

from autoforex.server.recovery import (
    TaskExecutionDisposition,
    TaskExecutionIntent,
    TaskIntentConflictError,
    TaskRecoveryStore,
)


class TaskLeaseUnavailableError(RuntimeError):
    """Raised when another server owns a live task lease."""


class TaskLeaseLostError(RuntimeError):
    """Raised when a runner no longer owns its fencing generation."""


class TaskLeaseToken:
    """Immutable local proof of one acquired task lease."""

    __slots__ = ("fencing_token", "lease_id", "owner_id", "task_id")

    def __init__(self, intent: TaskExecutionIntent) -> None:
        self.task_id = intent.task_id
        self.owner_id = intent.owner_id
        self.lease_id = intent.lease_id
        self.fencing_token = intent.generation

    def matches(self, intent: TaskExecutionIntent) -> bool:
        """Return whether an intent still represents this lease."""
        return (
            intent.task_id == self.task_id
            and intent.owner_id == self.owner_id
            and intent.lease_id == self.lease_id
            and intent.generation == self.fencing_token
        )


class TaskLeaseRegistry:
    """Thread-safe registry of leases owned by this process."""

    def __init__(self) -> None:
        self._tokens: dict[UUID, TaskLeaseToken] = {}
        self._lock = RLock()

    def put(self, token: TaskLeaseToken) -> None:
        """Register an acquired lease."""
        with self._lock:
            self._tokens[token.task_id] = token

    def get(self, task_id: UUID) -> TaskLeaseToken:
        """Return the lease for a local task."""
        with self._lock:
            try:
                return self._tokens[task_id]
            except KeyError as exc:
                raise TaskLeaseLostError(f"no local lease for task {task_id}") from exc

    def remove(self, task_id: UUID) -> TaskLeaseToken | None:
        """Forget and return a local lease."""
        with self._lock:
            return self._tokens.pop(task_id, None)

    def remove_if_current(self, token: TaskLeaseToken) -> bool:
        """Remove a failed token only if it has not been replaced."""
        with self._lock:
            if self._tokens.get(token.task_id) is not token:
                return False
            del self._tokens[token.task_id]
            return True

    def values(self) -> tuple[TaskLeaseToken, ...]:
        """Return a stable snapshot of locally owned leases."""
        with self._lock:
            return tuple(self._tokens.values())

    def contains(self, task_id: UUID) -> bool:
        """Return whether this process currently owns a task lease."""
        with self._lock:
            return task_id in self._tokens


class TaskLeaseCoordinator:
    """Acquire and validate task ownership using optimistic persistence."""

    def __init__(
        self,
        store: TaskRecoveryStore,
        *,
        owner_id: str,
        duration_seconds: float,
        registry: TaskLeaseRegistry | None = None,
    ) -> None:
        if duration_seconds <= 0:
            raise ValueError("lease duration must be positive")
        self.store = store
        self.owner_id = owner_id
        self.duration = timedelta(seconds=duration_seconds)
        self.registry = registry or TaskLeaseRegistry()

    def acquire(self, task_id: UUID) -> TaskLeaseToken | None:
        """Acquire an expired or locally owned lease, returning none if held elsewhere."""
        for _ in range(5):
            intent = self.store.get_intent(task_id)
            if intent.disposition != TaskExecutionDisposition.RUNNING:
                return None
            if intent.lease_is_valid() and intent.owner_id != self.owner_id:
                return None
            acquired = intent.acquire(self.owner_id, duration=self.duration)
            try:
                saved = self.store.save_intent(acquired)
            except TaskIntentConflictError:
                continue
            token = TaskLeaseToken(saved)
            self.registry.put(token)
            return token
        raise TaskIntentConflictError(f"could not acquire task lease after retries: {task_id}")

    def register_new(self, intent: TaskExecutionIntent) -> TaskLeaseToken:
        """Register a newly inserted intent as locally owned."""
        token = TaskLeaseToken(intent)
        self.registry.put(token)
        return token

    def renew(self, token: TaskLeaseToken, *, tick: Tick | None = None) -> TaskLeaseToken:
        """Extend a lease if its fencing token is still current."""
        for _ in range(5):
            intent = self.store.get_intent(token.task_id)
            self._require_match(token, intent)
            try:
                saved = self.store.save_intent(intent.renew(duration=self.duration, tick=tick))
            except TaskIntentConflictError:
                continue
            renewed = TaskLeaseToken(saved)
            self.registry.put(renewed)
            return renewed
        raise TaskIntentConflictError(f"could not renew task lease after retries: {token.task_id}")

    def assert_current(self, token: TaskLeaseToken) -> TaskExecutionIntent:
        """Return the current intent or reject a stale/expired lease."""
        intent = self.store.get_intent(token.task_id)
        self._require_match(token, intent)
        if not intent.lease_is_valid():
            raise TaskLeaseLostError(f"task lease expired: {token.task_id}")
        return intent

    def release(self, task_id: UUID) -> None:
        """Expire a locally owned lease without changing desired state."""
        token = self.registry.remove(task_id)
        if token is None:
            return
        for _ in range(3):
            intent = self.store.get_intent(task_id)
            if not token.matches(intent):
                return
            try:
                self.store.save_intent(intent.expire_lease())
                return
            except TaskIntentConflictError:
                continue

    @staticmethod
    def _require_match(token: TaskLeaseToken, intent: TaskExecutionIntent) -> None:
        if not token.matches(intent):
            raise TaskLeaseLostError(f"task lease fencing token is stale: {token.task_id}")


class FencedTaskRegistry:
    """Task registry decorator that rejects writes from stale runners."""

    def __init__(
        self,
        delegate: TaskRegistry,
        *,
        leases: TaskLeaseCoordinator,
    ) -> None:
        self.delegate = delegate
        self.leases = leases
        configure_fencing = getattr(delegate, "configure_fencing", None)
        if callable(configure_fencing):
            configure_fencing(
                token_resolver=self.leases.registry.get,
                intent_namespace="task-execution-intents",
            )

    def save(self, task: ExecutableTask) -> ExecutableTask:
        """Persist a task after validating its lease."""
        self._guard(task.id)
        return self.delegate.save(task)

    def get(self, task_id: UUID) -> ExecutableTask:
        """Return a task snapshot."""
        return self.delegate.get(task_id)

    def list(self, *, status: TaskStatus | None = None) -> Sequence[ExecutableTask]:
        """List task snapshots."""
        return self.delegate.list(status=status)

    def initialize_context(self, task: ExecutableTask, *, strategy_name: str) -> StrategyContext:
        """Initialize an in-process strategy context."""
        self._guard(task.id)
        return self.delegate.initialize_context(task, strategy_name=strategy_name)

    def current_context(self, task_id: UUID) -> StrategyContext:
        """Return a current in-process strategy context."""
        return self.delegate.current_context(task_id)

    def stage_context(self, context: StrategyContext) -> StrategyContext:
        """Stage strategy context after validating its lease."""
        self._guard(context.task_id)
        return self.delegate.stage_context(context)

    def save_context(self, context: StrategyContext) -> ExecutableTask:
        """Persist strategy context after validating its lease."""
        self._guard(context.task_id)
        return self.delegate.save_context(context)

    def apply_execution_response(self, response: StrategyExecutionResponse) -> None:
        """Apply a broker response after validating its lease."""
        self._guard(response.event.task_id)
        self.delegate.apply_execution_response(response)

    def _guard(self, task_id: UUID) -> None:
        token = self.leases.registry.get(task_id)
        self.leases.assert_current(token)


class UnfencedTaskRegistry:
    """Read-only escape hatch for supervisor control-plane operations."""

    def __init__(self, delegate: TaskRegistry) -> None:
        self.delegate = delegate

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)
