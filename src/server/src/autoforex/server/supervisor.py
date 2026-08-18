"""Durable task supervision across server process lifecycles."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from concurrent.futures import Future
from dataclasses import dataclass
from threading import Event, RLock, Thread
from time import monotonic
from uuid import UUID, uuid4, uuid5

from autoforex.core import (
    BacktestTaskDefinition,
    ExecutableTask,
    TaskManager,
    TaskRegistry,
    TaskRun,
    TaskStatus,
    Tick,
    TradingTaskDefinition,
    new_uuid,
    now,
)

from autoforex.server.components import (
    BacktestTaskBinding,
    ResolvedTaskDependencies,
    TaskBinding,
    TaskDependencyResolver,
    TradingTaskBinding,
)
from autoforex.server.execution import (
    DurableExecutionBroker,
    ExecutionBatchState,
    ExecutionJournalStore,
    InMemoryExecutionJournalStore,
)
from autoforex.server.lease import (
    FencedTaskRegistry,
    TaskLeaseCoordinator,
    TaskLeaseLostError,
    TaskLeaseToken,
)
from autoforex.server.recovery import (
    TaskExecutionDisposition,
    TaskExecutionIntent,
    TaskIntentConflictError,
    TaskRecoveryRecordNotFoundError,
    TaskRecoveryStore,
    TaskStatusDispositionMapper,
)
from autoforex.server.submissions import (
    TaskSubmission,
    TaskSubmissionConflictError,
    TaskSubmissionId,
    TaskSubmissionInProgressError,
)

_LOGGER = logging.getLogger(__name__)


class TaskHeartbeatObserver:
    """Persist a throttled execution heartbeat after processed ticks."""

    def __init__(
        self,
        leases: TaskLeaseCoordinator,
        *,
        interval_seconds: float = 5.0,
    ) -> None:
        self.leases = leases
        self.interval_seconds = interval_seconds
        self._last_saved: dict[UUID, float] = {}
        self._lock = RLock()

    def on_tick(self, task: ExecutableTask, tick: Tick) -> None:
        """Refresh durable execution ownership and progress."""
        current = monotonic()
        with self._lock:
            previous = self._last_saved.get(task.id)
            if previous is not None and current - previous < self.interval_seconds:
                return
            self._last_saved[task.id] = current
        try:
            token = self.leases.registry.get(task.id)
            self.leases.renew(token, tick=tick)
        except TaskIntentConflictError, TaskLeaseLostError:
            return

    def on_task_finished(self, task: ExecutableTask) -> None:
        """Clear local throttle state when a terminal task finishes."""
        with self._lock:
            self._last_saved.pop(task.id, None)


class TaskLeaseRenewalService:
    """Renew active leases independently from market-data traffic."""

    def __init__(
        self,
        leases: TaskLeaseCoordinator,
        *,
        interval_seconds: float,
        on_lease_lost,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("lease renewal interval must be positive")
        self.leases = leases
        self.interval_seconds = interval_seconds
        self.on_lease_lost = on_lease_lost
        self._stop = Event()
        self._thread: Thread | None = None
        self._lock = RLock()

    def start(self) -> None:
        """Start the renewal worker once."""
        with self._lock:
            if self._thread is not None:
                return
            self._thread = Thread(
                target=self._run,
                name="auto-forex-task-lease-renewer",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """Stop and join the renewal worker."""
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=max(1.0, self.interval_seconds * 2))

    @property
    def healthy(self) -> bool:
        """Return whether the renewal worker is alive."""
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            for token in self.leases.registry.values():
                try:
                    self.leases.renew(token)
                except TaskIntentConflictError:
                    _LOGGER.debug(
                        "task lease renewal CAS conflict; retrying next cycle",
                        extra={"task_id": str(token.task_id)},
                    )
                except Exception:
                    _LOGGER.exception(
                        "task lease renewal failed; stopping local runner",
                        extra={"task_id": str(token.task_id)},
                    )
                    if self.leases.registry.remove_if_current(token):
                        self.on_lease_lost(token.task_id)


class TaskIntentReconciliationService:
    """Reconcile durable desired state across active server instances."""

    def __init__(self, reconcile, *, interval_seconds: float) -> None:
        if interval_seconds <= 0:
            raise ValueError("intent reconciliation interval must be positive")
        self.reconcile = reconcile
        self.interval_seconds = interval_seconds
        self._stop = Event()
        self._thread: Thread | None = None
        self._healthy = True
        self._lock = RLock()

    def start(self) -> None:
        """Start the reconciliation worker once."""
        with self._lock:
            if self._thread is not None:
                return
            self._thread = Thread(
                target=self._run,
                name="auto-forex-task-intent-reconciler",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """Stop and join the reconciliation worker."""
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=max(1.0, self.interval_seconds * 2))

    @property
    def healthy(self) -> bool:
        """Return whether the most recent reconciliation cycle succeeded."""
        with self._lock:
            return self._healthy

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.reconcile()
            except Exception:
                with self._lock:
                    self._healthy = False
                _LOGGER.exception("task intent reconciliation cycle failed")
            else:
                with self._lock:
                    self._healthy = True


@dataclass(frozen=True, slots=True)
class TaskRecoveryFailure:
    """One task that could not be reconstructed during server startup."""

    task_id: UUID
    reason: str


@dataclass(frozen=True, slots=True)
class TaskRecoveryReport:
    """Summary of startup task recovery."""

    recovered_task_ids: tuple[UUID, ...] = ()
    failures: tuple[TaskRecoveryFailure, ...] = ()

    def require_complete(self) -> None:
        """Raise when any desired-running task could not be recovered."""
        if not self.failures:
            return
        details = "; ".join(f"{item.task_id}: {item.reason}" for item in self.failures)
        raise TaskRecoveryError(f"failed to recover active tasks: {details}")


class TaskRecoveryError(RuntimeError):
    """Raised when durable active tasks cannot be resumed."""


class TaskSupervisor:
    """Coordinate task execution, desired state, resources, and recovery."""

    def __init__(
        self,
        *,
        manager: TaskManager,
        registry: TaskRegistry,
        recovery_store: TaskRecoveryStore,
        execution_store: ExecutionJournalStore,
        dependency_resolver: TaskDependencyResolver,
        leases: TaskLeaseCoordinator,
        server_id: str | None = None,
        lease_renewal_seconds: float = 10.0,
        reconciliation_interval_seconds: float = 1.0,
    ) -> None:
        self.manager = manager
        self.registry = registry
        self.recovery_store = recovery_store
        self.execution_store = execution_store
        self.dependency_resolver = dependency_resolver
        self.server_id = server_id or str(uuid4())
        self.leases = leases
        self._dependencies: dict[UUID, ResolvedTaskDependencies] = {}
        self._completion_events: dict[UUID, Event] = {}
        self._relaunching: set[UUID] = set()
        self._shutting_down = False
        self._lock = RLock()
        self._reconciliation_lock = RLock()
        self._lease_renewer = TaskLeaseRenewalService(
            leases,
            interval_seconds=lease_renewal_seconds,
            on_lease_lost=self._lease_lost,
        )
        self._lease_renewer.start()
        self._intent_reconciler = TaskIntentReconciliationService(
            self._reconcile_desired_state,
            interval_seconds=reconciliation_interval_seconds,
        )
        self._intent_reconciler.start()

    @classmethod
    def create(
        cls,
        *,
        registry: TaskRegistry,
        recovery_store: TaskRecoveryStore,
        dependency_resolver: TaskDependencyResolver,
        execution_store: ExecutionJournalStore | None = None,
        server_id: str | None = None,
        max_workers: int = 4,
        heartbeat_interval_seconds: float = 5.0,
        lease_duration_seconds: float = 30.0,
        lease_renewal_seconds: float = 10.0,
        reconciliation_interval_seconds: float = 1.0,
    ) -> TaskSupervisor:
        """Create a supervisor and its Core task manager."""
        resolved_server_id = server_id or str(uuid4())
        leases = TaskLeaseCoordinator(
            recovery_store,
            owner_id=resolved_server_id,
            duration_seconds=lease_duration_seconds,
        )
        fenced_registry = FencedTaskRegistry(registry, leases=leases)
        heartbeat = TaskHeartbeatObserver(
            leases,
            interval_seconds=heartbeat_interval_seconds,
        )
        manager = TaskManager(
            registry=fenced_registry,
            observers=(heartbeat,),
            max_workers=max_workers,
        )
        return cls(
            manager=manager,
            registry=fenced_registry,
            recovery_store=recovery_store,
            execution_store=execution_store or InMemoryExecutionJournalStore(),
            dependency_resolver=dependency_resolver,
            leases=leases,
            server_id=resolved_server_id,
            lease_renewal_seconds=lease_renewal_seconds,
            reconciliation_interval_seconds=reconciliation_interval_seconds,
        )

    def start_backtest(
        self,
        definition: BacktestTaskDefinition,
        binding: BacktestTaskBinding,
    ) -> TaskRun:
        """Persist and start a backtest."""
        if definition.parameters != binding.strategy.parameters:
            raise ValueError("definition and strategy binding parameters must match")
        return self._start(
            definition=definition,
            binding=binding,
        )

    def start_trading(
        self,
        definition: TradingTaskDefinition,
        binding: TradingTaskBinding,
    ) -> TaskRun:
        """Persist and start a live trading task."""
        if definition.parameters != binding.strategy.parameters:
            raise ValueError("definition and strategy binding parameters must match")
        return self._start(
            definition=definition,
            binding=binding,
        )

    def submit_backtest(
        self,
        definition: BacktestTaskDefinition,
        binding: BacktestTaskBinding,
        submission_id: TaskSubmissionId,
    ) -> ExecutableTask:
        """Idempotently submit a backtest start request."""
        if definition.parameters != binding.strategy.parameters:
            raise ValueError("definition and strategy binding parameters must match")
        return self._submit(definition, binding, submission_id)

    def submit_trading(
        self,
        definition: TradingTaskDefinition,
        binding: TradingTaskBinding,
        submission_id: TaskSubmissionId,
    ) -> ExecutableTask:
        """Idempotently submit a live-trading start request."""
        if definition.parameters != binding.strategy.parameters:
            raise ValueError("definition and strategy binding parameters must match")
        return self._submit(definition, binding, submission_id)

    def get(self, task_id: UUID) -> ExecutableTask:
        """Return the latest durable task snapshot."""
        return self.registry.get(task_id)

    def list(self, *, status: TaskStatus | None = None) -> Sequence[ExecutableTask]:
        """List durable task snapshots."""
        return self.registry.list(status=status)

    def binding_for(self, task: ExecutableTask) -> TaskBinding:
        """Return persisted runtime component bindings for a task."""
        return self.recovery_store.get_binding(task.definition_id)

    def intent_for(self, task_id: UUID) -> TaskExecutionIntent:
        """Return durable desired state for a task."""
        return self.recovery_store.get_intent(task_id)

    def pause(self, task_id: UUID) -> ExecutableTask:
        """Persist a paused desired state and request a graceful pause."""
        self._transition_intent(
            task_id,
            TaskExecutionDisposition.PAUSED,
        )
        runtime = self.manager.runtimes.current(task_id)
        if runtime is not None and not runtime.future.done():
            return self.manager.pause(task_id)
        return self.registry.get(task_id)

    def stop(self, task_id: UUID) -> ExecutableTask:
        """Persist a stopped desired state and request a graceful stop."""
        self._transition_intent(
            task_id,
            TaskExecutionDisposition.STOPPED,
        )
        runtime = self.manager.runtimes.current(task_id)
        if runtime is not None and not runtime.future.done():
            return self.manager.stop(task_id)
        return self.registry.get(task_id)

    def resume(self, task_id: UUID) -> TaskRun:
        """Resume a paused task from its durable checkpoint."""
        with self._reconciliation_lock:
            task = self.registry.get(task_id)
            if task.status != TaskStatus.PAUSED:
                msg = f"cannot resume task {task_id} while status is {task.status.value}"
                raise ValueError(msg)
            runtime = self.manager.runtimes.current(task_id)
            if runtime is not None and not runtime.future.done():
                runtime.future.result()
            self._wait_for_completion(task_id)
            self._transition_intent(
                task_id,
                TaskExecutionDisposition.RUNNING,
                owner_id=self.server_id,
                increment_generation=True,
                expire_lease=True,
            )
            lease = self.leases.acquire(task_id)
            if lease is None:
                raise TaskRecoveryError(f"task lease is owned by another server: {task_id}")
            return self._recover(task, lease)

    def restart(self, task_id: UUID) -> TaskRun:
        """Start a fresh run with newly constructed runtime dependencies."""
        with self._reconciliation_lock:
            with self._lock:
                self._relaunching.add(task_id)
            try:
                runtime = self.manager.runtimes.current(task_id)
                if runtime is not None and not runtime.future.done():
                    self.manager.stop(task_id)
                    runtime.future.result()
                self._wait_for_completion(task_id)
                self._transition_intent(
                    task_id,
                    TaskExecutionDisposition.RUNNING,
                    owner_id=self.server_id,
                    increment_generation=True,
                    expire_lease=True,
                )
                lease = self.leases.acquire(task_id)
                if lease is None:
                    raise TaskRecoveryError(f"task lease is owned by another server: {task_id}")
                task = self.registry.get(task_id)
                binding = self.recovery_store.get_binding(task.definition_id)
                dependencies: ResolvedTaskDependencies | None = None
                try:
                    dependencies = self._dependencies_for(binding, lease)
                    run = self.manager.restart_with_dependencies(
                        task_id,
                        data_source=dependencies.data_source,
                        strategy=dependencies.strategy,
                        broker=dependencies.broker,
                    )
                except Exception:
                    if dependencies is not None:
                        dependencies.close()
                    self.leases.release(task_id)
                    raise
                self._track(run, dependencies)
                return run
            finally:
                with self._lock:
                    self._relaunching.discard(task_id)

    def recover(self, task_id: UUID) -> TaskRun:
        """Retry provider reconciliation and continue the same interrupted run."""
        with self._reconciliation_lock:
            intent = self.recovery_store.get_intent(task_id)
            if intent.disposition != TaskExecutionDisposition.RECOVERY_REQUIRED:
                raise ValueError(f"task {task_id} does not require execution recovery")
            self._transition_intent(
                task_id,
                TaskExecutionDisposition.RUNNING,
                owner_id=self.server_id,
                increment_generation=True,
                expire_lease=True,
            )
            lease = self.leases.acquire(task_id)
            if lease is None:
                raise TaskRecoveryError(f"task lease is owned by another server: {task_id}")
            return self._recover(self.registry.get(task_id), lease)

    def recover_active(self) -> TaskRecoveryReport:
        """Recover every task whose durable desired state is running."""
        with self._reconciliation_lock:
            return self._recover_active()

    def _recover_active(self) -> TaskRecoveryReport:
        recovered: list[UUID] = []
        failures: list[TaskRecoveryFailure] = []
        intents = self.recovery_store.list_intents(disposition=TaskExecutionDisposition.RUNNING)
        for intent in intents:
            try:
                runtime = self.manager.runtimes.current(intent.task_id)
                if self.leases.registry.contains(intent.task_id) or (
                    runtime is not None and not runtime.future.done()
                ):
                    continue
                task = self.registry.get(intent.task_id)
                if task.status == TaskStatus.COMPLETED:
                    self._transition_intent(
                        task.id,
                        TaskExecutionDisposition.COMPLETED,
                    )
                    continue
                lease = self.leases.acquire(task.id)
                if lease is None:
                    continue
                self._recover(task, lease)
                recovered.append(task.id)
            except Exception as exc:
                failures.append(
                    TaskRecoveryFailure(
                        task_id=intent.task_id,
                        reason=f"{exc.__class__.__name__}: {exc}",
                    )
                )
        return TaskRecoveryReport(
            recovered_task_ids=tuple(recovered),
            failures=tuple(failures),
        )

    def shutdown(self, *, wait: bool = True) -> None:
        """Stop the local process while preserving desired-running intents."""
        with self._lock:
            self._shutting_down = True
            dependencies = tuple(self._dependencies.values())
        self._intent_reconciler.stop()
        self._lease_renewer.stop()
        for item in dependencies:
            item.close()
        self.manager.shutdown(wait=wait)
        for token in self.leases.registry.values():
            self.leases.release(token.task_id)
        with self._lock:
            remaining = tuple(self._dependencies.values())
            self._dependencies.clear()
        for item in remaining:
            item.close()

    def _start(
        self,
        *,
        definition: BacktestTaskDefinition | TradingTaskDefinition,
        binding: TaskBinding,
        task_id: UUID | None = None,
        submission: TaskSubmission | None = None,
    ) -> TaskRun:
        resolved_task_id = task_id or new_uuid()
        intent = TaskExecutionIntent(
            task_id=resolved_task_id,
            definition_id=definition.id,
            disposition=TaskExecutionDisposition.RUNNING,
            owner_id=self.server_id,
            lease_expires_at=now() + self.leases.duration,
            submission_id=(submission.id.value if submission is not None else None),
            submission_fingerprint=(submission.fingerprint if submission is not None else ""),
        )
        self.recovery_store.save_binding(definition.id, binding)
        saved_intent = self.recovery_store.save_intent(intent)
        lease = self.leases.register_new(saved_intent)
        dependencies: ResolvedTaskDependencies | None = None
        try:
            dependencies = self._dependencies_for(binding, lease)
            if isinstance(definition, BacktestTaskDefinition):
                run = self.manager.start_backtest(
                    definition,
                    data_source=dependencies.data_source,
                    strategy=dependencies.strategy,
                    broker=dependencies.broker,
                    task_id=resolved_task_id,
                )
            else:
                run = self.manager.start_trading(
                    definition,
                    data_source=dependencies.data_source,
                    strategy=dependencies.strategy,
                    broker=dependencies.broker,
                    task_id=resolved_task_id,
                )
        except Exception:
            if dependencies is not None:
                dependencies.close()
            self.leases.registry.remove(resolved_task_id)
            self.recovery_store.delete_intent(resolved_task_id)
            self.recovery_store.delete_binding(definition.id)
            raise
        self._track(run, dependencies)
        return run

    def _submit(
        self,
        definition: BacktestTaskDefinition | TradingTaskDefinition,
        binding: TaskBinding,
        submission_id: TaskSubmissionId,
    ) -> ExecutableTask:
        submission = TaskSubmission.create(
            submission_id,
            definition=definition,
            binding=binding,
        )
        task_id = uuid5(submission_id.value, "task")
        definition = definition.evolve(id=uuid5(submission_id.value, "definition"))
        try:
            existing = self.recovery_store.get_intent(task_id)
        except TaskRecoveryRecordNotFoundError:
            try:
                return self._start(
                    definition=definition,
                    binding=binding,
                    task_id=task_id,
                    submission=submission,
                ).task
            except TaskIntentConflictError:
                existing = self.recovery_store.get_intent(task_id)
        if (
            existing.submission_id != submission.id.value
            or existing.submission_fingerprint != submission.fingerprint
        ):
            raise TaskSubmissionConflictError(
                f"request_id {submission.id.value} was already used with another payload"
            )
        try:
            return self.registry.get(task_id)
        except Exception as exc:
            raise TaskSubmissionInProgressError(
                f"request_id {submission.id.value} is still being committed"
            ) from exc

    def _recover(self, task: ExecutableTask, lease: TaskLeaseToken) -> TaskRun:
        dependencies: ResolvedTaskDependencies | None = None
        try:
            binding = self.recovery_store.get_binding(task.definition_id)
            dependencies = self._dependencies_for(binding, lease)
            run = self.manager.recover(
                task.id,
                data_source=dependencies.data_source,
                strategy=dependencies.strategy,
                broker=dependencies.broker,
            )
        except Exception:
            if dependencies is not None:
                dependencies.close()
            self.leases.release(task.id)
            raise
        self._track(run, dependencies)
        return run

    def _track(
        self,
        run: TaskRun,
        dependencies: ResolvedTaskDependencies,
    ) -> None:
        with self._lock:
            self._dependencies[run.id] = dependencies
            self._completion_events[run.id] = Event()
        runtime = self.manager.runtimes.get(run.id)
        runtime.future.add_done_callback(
            lambda future, task_id=run.id: self._execution_finished(task_id, future)
        )

    def _execution_finished(
        self,
        task_id: UUID,
        future: Future[ExecutableTask],
    ) -> None:
        try:
            self._finalize_execution(task_id, future)
        finally:
            with self._lock:
                completion = self._completion_events.get(task_id)
            if completion is not None:
                completion.set()

    def _finalize_execution(
        self,
        task_id: UUID,
        future: Future[ExecutableTask],
    ) -> None:
        _ = future
        with self._lock:
            dependencies = self._dependencies.pop(task_id, None)
            preserve_running = self._shutting_down or task_id in self._relaunching
        if dependencies is not None:
            dependencies.close()
        try:
            task = self.registry.get(task_id)
            intent = self.recovery_store.get_intent(task_id)
        except Exception:
            return
        if preserve_running and intent.disposition == TaskExecutionDisposition.RUNNING:
            try:
                token = self.leases.registry.get(task_id)
                self.leases.renew(token)
            except TaskIntentConflictError, TaskLeaseLostError:
                pass
            return
        pending = self.execution_store.list_pending_batches(task_id)
        if any(batch.state == ExecutionBatchState.REVIEW_REQUIRED for batch in pending):
            self._transition_intent(
                task_id,
                TaskExecutionDisposition.RECOVERY_REQUIRED,
            )
            self.leases.release(task_id)
            return
        disposition = TaskStatusDispositionMapper.terminal_disposition(task.status)
        if disposition is not None:
            self._transition_intent(task_id, disposition)
            self.leases.release(task_id)

    def _wait_for_completion(self, task_id: UUID) -> None:
        with self._lock:
            completion = self._completion_events.get(task_id)
        if completion is not None:
            completion.wait()

    def _transition_intent(
        self,
        task_id: UUID,
        disposition: TaskExecutionDisposition,
        *,
        owner_id: str | None = None,
        increment_generation: bool = False,
        expire_lease: bool = False,
    ) -> TaskExecutionIntent:
        for _ in range(3):
            intent = self.recovery_store.get_intent(task_id)
            updated = intent.transition(
                disposition,
                owner_id=owner_id,
                increment_generation=increment_generation,
                expire_lease=expire_lease,
            )
            try:
                return self.recovery_store.save_intent(updated)
            except TaskIntentConflictError:
                continue
        msg = f"could not update task execution intent after retries: {task_id}"
        raise TaskIntentConflictError(msg)

    def is_healthy(self) -> bool:
        """Return whether persistence and lease renewal are operational."""
        return (
            not self._shutting_down
            and self.recovery_store.is_healthy()
            and self.execution_store.is_healthy()
            and self._lease_renewer.healthy
            and self._intent_reconciler.healthy
        )

    def _dependencies_for(
        self,
        binding: TaskBinding,
        lease: TaskLeaseToken,
    ) -> ResolvedTaskDependencies:
        dependencies = self.dependency_resolver.resolve(binding)
        if dependencies.broker is None:
            return dependencies
        return ResolvedTaskDependencies(
            data_source=dependencies.data_source,
            strategy=dependencies.strategy,
            broker=DurableExecutionBroker(
                dependencies.broker,
                store=self.execution_store,
                leases=self.leases,
                lease=lease,
            ),
            resources=dependencies.resources,
        )

    def _lease_lost(self, task_id: UUID) -> None:
        runtime = self.manager.runtimes.current(task_id)
        if runtime is not None and not runtime.future.done():
            runtime.control.request_stop()

    def _reconcile_desired_state(self) -> None:
        if self._shutting_down:
            return
        with self._reconciliation_lock:
            self._apply_remote_controls()
            self._recover_active()

    def _apply_remote_controls(self) -> None:
        for token in self.leases.registry.values():
            try:
                intent = self.recovery_store.get_intent(token.task_id)
            except Exception:
                continue
            runtime = self.manager.runtimes.current(token.task_id)
            active = runtime is not None and not runtime.future.done()
            if intent.disposition == TaskExecutionDisposition.PAUSED:
                if active:
                    self.manager.pause(token.task_id)
                else:
                    self.leases.release(token.task_id)
            elif intent.disposition == TaskExecutionDisposition.STOPPED:
                if active:
                    self.manager.stop(token.task_id)
                else:
                    self.leases.release(token.task_id)
            elif intent.disposition != TaskExecutionDisposition.RUNNING:
                if active:
                    runtime.control.request_stop()
                else:
                    self.leases.release(token.task_id)
