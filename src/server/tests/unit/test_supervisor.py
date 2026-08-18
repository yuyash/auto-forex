from __future__ import annotations

from threading import Event
from typing import Any, cast
from uuid import uuid4

import pytest
from autoforex.core import ExecutableTask, Tick

import autoforex.server.supervisor as supervisor_module
from autoforex.server.lease import TaskLeaseCoordinator
from autoforex.server.supervisor import (
    TaskHeartbeatObserver,
    TaskIntentReconciliationService,
    TaskLeaseRenewalService,
    TaskRecoveryError,
    TaskRecoveryFailure,
    TaskRecoveryReport,
)


class RecordingLeaseRegistry:
    def get(self, task_id):
        return f"token:{task_id}"


class RecordingLeases:
    def __init__(self) -> None:
        self.registry = RecordingLeaseRegistry()
        self.renewals: list[tuple[Any, Tick | None]] = []

    def renew(self, token: Any, *, tick: Tick | None = None) -> None:
        self.renewals.append((token, tick))


class TestTaskHeartbeatObserver:
    def test_throttles_tick_heartbeats_and_resets_after_task_completion(
        self,
        executable_task: ExecutableTask,
        market_ticks: tuple[Tick, Tick],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        times = iter((1.0, 1.5, 2.5))
        monkeypatch.setattr(supervisor_module, "monotonic", lambda: next(times))
        leases = RecordingLeases()
        observer = TaskHeartbeatObserver(
            cast(TaskLeaseCoordinator, cast(Any, leases)),
            interval_seconds=1.0,
        )

        observer.on_tick(executable_task, market_ticks[0])
        observer.on_tick(executable_task, market_ticks[1])
        observer.on_task_finished(executable_task)
        observer.on_tick(executable_task, market_ticks[1])

        assert leases.renewals == [
            (f"token:{executable_task.id}", market_ticks[0]),
            (f"token:{executable_task.id}", market_ticks[1]),
        ]


class TestTaskRecoveryReport:
    def test_accepts_complete_recovery_and_describes_every_failure(self) -> None:
        TaskRecoveryReport(recovered_task_ids=(uuid4(),)).require_complete()
        first = uuid4()
        second = uuid4()
        report = TaskRecoveryReport(
            failures=(
                TaskRecoveryFailure(task_id=first, reason="missing strategy"),
                TaskRecoveryFailure(task_id=second, reason="database unavailable"),
            )
        )

        with pytest.raises(TaskRecoveryError) as raised:
            report.require_complete()

        assert str(first) in str(raised.value)
        assert "missing strategy" in str(raised.value)
        assert str(second) in str(raised.value)


class TestBackgroundSupervisionServices:
    def test_rejects_non_positive_worker_intervals(self) -> None:
        with pytest.raises(ValueError, match="renewal"):
            TaskLeaseRenewalService(
                cast(TaskLeaseCoordinator, cast(Any, RecordingLeases())),
                interval_seconds=0,
                on_lease_lost=lambda task_id: None,
            )
        with pytest.raises(ValueError, match="reconciliation"):
            TaskIntentReconciliationService(lambda: None, interval_seconds=0)

    def test_reconciliation_health_recovers_after_a_successful_cycle(self) -> None:
        first_cycle = Event()
        second_cycle = Event()
        attempts = 0

        def reconcile() -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                first_cycle.set()
                raise RuntimeError("temporary database failure")
            second_cycle.set()

        service = TaskIntentReconciliationService(
            reconcile,
            interval_seconds=0.01,
        )
        service.start()
        try:
            assert first_cycle.wait(timeout=1)
            assert second_cycle.wait(timeout=1)
            assert service.healthy
            service.start()
        finally:
            service.stop()
