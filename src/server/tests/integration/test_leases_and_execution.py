from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from autoforex.core import (
    BacktestTaskDefinition,
    Broker,
    BrokerExecutionUnresolvedError,
    BrokerMutation,
    BrokerReconciliation,
    BrokerReconciliationOutcome,
    CurrencyPair,
    ExecutableTask,
    Metadata,
    Money,
    Order,
    OrderSide,
    OrderStatus,
    Position,
    PositionSide,
    StrategyAction,
    StrategyEventRequest,
    StrategyExecutionResponse,
    Trade,
    TradeSide,
    Units,
    now,
)

from autoforex.server.execution import DurableExecutionBroker, ExecutionBatchState
from autoforex.server.lease import (
    FencedTaskRegistry,
    TaskLeaseCoordinator,
    TaskLeaseLostError,
)
from autoforex.server.persistence import SqlPersistence
from autoforex.server.recovery import TaskExecutionDisposition, TaskExecutionIntent


class SimulatedProcessCrash(BaseException):
    pass


class CrashAfterApplyBroker(Broker):
    def __init__(self) -> None:
        self.place_calls = 0
        self.applied_order: Order | None = None

    def place_order(self, order: Order) -> Order:
        self.place_calls += 1
        self.applied_order = order.evolve(
            status=OrderStatus.FILLED,
            filled_units=order.units,
            average_fill_price=order.price,
        )
        raise SimulatedProcessCrash

    def close_position(
        self,
        *,
        position: Position,
        side: PositionSide,
        units: Units | None = None,
    ) -> Order:
        raise NotImplementedError

    def positions(self, *, instrument: CurrencyPair | None = None):
        _ = instrument
        return ()

    def close_trade(self, trade: Trade, *, units: Units | None = None) -> Order:
        raise NotImplementedError

    def trades(self, *, instrument: CurrencyPair | None = None):
        _ = instrument
        return ()

    def capture_execution_cursor(self) -> str:
        return "100"

    def reconcile_execution(self, mutation: BrokerMutation) -> BrokerReconciliation:
        _ = mutation
        assert self.applied_order is not None
        return BrokerReconciliation(
            outcome=BrokerReconciliationOutcome.APPLIED,
            order=self.applied_order,
        )


class AmbiguousThenSuccessfulBroker(Broker):
    def __init__(self) -> None:
        self.place_calls = 0

    def place_order(self, order: Order) -> Order:
        self.place_calls += 1
        if self.place_calls == 1:
            raise TimeoutError("response was lost")
        return order.evolve(
            status=OrderStatus.FILLED,
            filled_units=order.units,
            average_fill_price=order.price,
        )

    def close_position(
        self,
        *,
        position: Position,
        side: PositionSide,
        units: Units | None = None,
    ) -> Order:
        raise NotImplementedError

    def positions(self, *, instrument: CurrencyPair | None = None):
        _ = instrument
        return ()

    def close_trade(self, trade: Trade, *, units: Units | None = None) -> Order:
        raise NotImplementedError

    def trades(self, *, instrument: CurrencyPair | None = None):
        _ = instrument
        return ()

    def capture_execution_cursor(self) -> str:
        return "100"

    def reconcile_execution(self, mutation: BrokerMutation) -> BrokerReconciliation:
        _ = mutation
        return BrokerReconciliation(
            outcome=BrokerReconciliationOutcome.NOT_APPLIED,
            details="no matching provider transaction",
        )


class TestDistributedTaskLease:
    def test_only_one_server_owns_a_live_lease_and_stale_writes_are_fenced(
        self,
        sqlite_persistence: SqlPersistence,
    ) -> None:
        recovery = sqlite_persistence.recovery_store()
        task_id = uuid4()
        definition_id = uuid4()
        first = TaskLeaseCoordinator(
            recovery,
            owner_id="server-a",
            duration_seconds=30,
        )
        second = TaskLeaseCoordinator(
            recovery,
            owner_id="server-b",
            duration_seconds=30,
        )
        saved = recovery.save_intent(
            TaskExecutionIntent(
                task_id=task_id,
                definition_id=definition_id,
                disposition=TaskExecutionDisposition.RUNNING,
                owner_id="server-a",
                lease_expires_at=now() + timedelta(seconds=30),
            )
        )
        first_token = first.register_new(saved)

        assert second.acquire(task_id) is None
        first.release(task_id)
        second_token = second.acquire(task_id)

        assert second_token is not None
        assert second_token.fencing_token > first_token.fencing_token
        with pytest.raises(TaskLeaseLostError):
            first.assert_current(first_token)

    def test_fenced_registry_rejects_a_runner_after_lease_takeover(
        self,
        sqlite_persistence: SqlPersistence,
    ) -> None:
        recovery = sqlite_persistence.recovery_store()
        base_registry = sqlite_persistence.task_registry()
        task_id = uuid4()
        definition = BacktestTaskDefinition(
            id=uuid4(),
            name="Fenced",
            instrument=CurrencyPair.of("EUR_USD"),
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        task = ExecutableTask.from_definition(definition, task_id=task_id)
        saved = recovery.save_intent(
            TaskExecutionIntent(
                task_id=task_id,
                definition_id=definition.id,
                disposition=TaskExecutionDisposition.RUNNING,
                owner_id="server-a",
                lease_expires_at=now() + timedelta(seconds=30),
            )
        )
        first = TaskLeaseCoordinator(
            recovery,
            owner_id="server-a",
            duration_seconds=30,
        )
        first.register_new(saved)
        fenced = FencedTaskRegistry(base_registry, leases=first)
        fenced.save(task)
        first.release(task_id)

        with pytest.raises(TaskLeaseLostError):
            fenced.save(task.start(at=definition.start_at))

    def test_sql_task_write_atomically_rejects_a_stale_local_token(
        self,
        sqlite_persistence: SqlPersistence,
    ) -> None:
        recovery = sqlite_persistence.recovery_store()
        base_registry = sqlite_persistence.task_registry()
        task_id = uuid4()
        definition = BacktestTaskDefinition(
            id=uuid4(),
            name="Atomic fence",
            instrument=CurrencyPair.of("EUR_USD"),
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        task = ExecutableTask.from_definition(definition, task_id=task_id)
        saved = recovery.save_intent(
            TaskExecutionIntent(
                task_id=task_id,
                definition_id=definition.id,
                disposition=TaskExecutionDisposition.RUNNING,
                owner_id="server-a",
                lease_expires_at=now() + timedelta(seconds=30),
            )
        )
        first = TaskLeaseCoordinator(
            recovery,
            owner_id="server-a",
            duration_seconds=30,
        )
        first.register_new(saved)
        FencedTaskRegistry(base_registry, leases=first)
        base_registry.save(task)
        recovery.save_intent(saved.expire_lease())
        second = TaskLeaseCoordinator(
            recovery,
            owner_id="server-b",
            duration_seconds=30,
        )
        assert second.acquire(task_id) is not None

        with pytest.raises(TaskLeaseLostError):
            base_registry.save(task.start(at=definition.start_at))


class TestDurableBrokerExecution:
    def test_reconciles_a_crash_after_provider_apply_without_duplicate_submission(
        self,
        sqlite_persistence: SqlPersistence,
    ) -> None:
        recovery = sqlite_persistence.recovery_store()
        journal = sqlite_persistence.execution_store()
        task_id = uuid4()
        saved = recovery.save_intent(
            TaskExecutionIntent(
                task_id=task_id,
                definition_id=uuid4(),
                disposition=TaskExecutionDisposition.RUNNING,
                owner_id="server-a",
                lease_expires_at=now() + timedelta(seconds=30),
            )
        )
        first_leases = TaskLeaseCoordinator(
            recovery,
            owner_id="server-a",
            duration_seconds=30,
        )
        first_token = first_leases.register_new(saved)
        provider = CrashAfterApplyBroker()
        first = DurableExecutionBroker(
            provider,
            store=journal,
            leases=first_leases,
            lease=first_token,
        )
        request = self._request(task_id)
        first.prepare((request,), checkpoint_at=request.timestamp)
        order = self._order(request)

        with pytest.raises(SimulatedProcessCrash), first.execution_scope(request):
            first.place_order(order)

        first_leases.release(task_id)
        second_leases = TaskLeaseCoordinator(
            recovery,
            owner_id="server-b",
            duration_seconds=30,
        )
        second_token = second_leases.acquire(task_id)
        assert second_token is not None
        second = DurableExecutionBroker(
            provider,
            store=journal,
            leases=second_leases,
            lease=second_token,
        )

        assert len(second.pending(task_id)) == 1
        with second.execution_scope(request):
            reconciled = second.place_order(self._order(request))
        response = StrategyExecutionResponse(event=request, order=reconciled)
        second.response_applied(response)
        second.complete((request,))
        second.checkpointed((request,))

        assert provider.place_calls == 1
        assert reconciled.status == OrderStatus.FILLED
        assert journal.list_pending_batches(task_id) == ()
        batch = journal.find_batch(request.id)
        assert batch.state == ExecutionBatchState.CHECKPOINTED

    def test_requires_review_before_retrying_an_ambiguous_not_applied_command(
        self,
        sqlite_persistence: SqlPersistence,
    ) -> None:
        recovery = sqlite_persistence.recovery_store()
        journal = sqlite_persistence.execution_store()
        task_id = uuid4()
        saved = recovery.save_intent(
            TaskExecutionIntent(
                task_id=task_id,
                definition_id=uuid4(),
                disposition=TaskExecutionDisposition.RUNNING,
                owner_id="server-a",
                lease_expires_at=now() + timedelta(seconds=30),
            )
        )
        leases = TaskLeaseCoordinator(
            recovery,
            owner_id="server-a",
            duration_seconds=30,
        )
        token = leases.register_new(saved)
        provider = AmbiguousThenSuccessfulBroker()
        broker = DurableExecutionBroker(
            provider,
            store=journal,
            leases=leases,
            lease=token,
        )
        request = self._request(task_id)
        order = self._order(request)
        broker.prepare((request,), checkpoint_at=request.timestamp)

        with (
            pytest.raises(BrokerExecutionUnresolvedError),
            broker.execution_scope(request),
        ):
            broker.place_order(order)

        review = journal.find_batch(request.id)
        assert review.state == ExecutionBatchState.REVIEW_REQUIRED
        with broker.execution_scope(request):
            retried = broker.place_order(order)
        response = StrategyExecutionResponse(event=request, order=retried)
        broker.response_applied(response)
        broker.complete((request,))
        broker.checkpointed((request,))

        assert provider.place_calls == 2
        assert retried.status == OrderStatus.FILLED
        assert journal.find_batch(request.id).state == ExecutionBatchState.CHECKPOINTED

    @staticmethod
    def _request(task_id):
        return StrategyEventRequest(
            task_id=task_id,
            action=StrategyAction.OPEN_TRADE,
            instrument=CurrencyPair.of("EUR_USD"),
            side=TradeSide.BUY,
            units=Units("10"),
            price=Money.of("1.10", "USD"),
        )

    @staticmethod
    def _order(request: StrategyEventRequest) -> Order:
        return Order(
            instrument=request.instrument,
            side=OrderSide.BUY,
            units=request.units or Units("10"),
            price=request.price,
            metadata=Metadata.of(event_id=str(request.id)),
        )
