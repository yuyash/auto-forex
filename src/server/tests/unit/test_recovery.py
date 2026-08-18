from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from autoforex.core import TaskStatus, Tick, now

from autoforex.server.recovery import (
    TaskExecutionDisposition,
    TaskExecutionIntent,
    TaskStatusDispositionMapper,
)


class TestTaskExecutionIntent:
    def test_acquire_renew_and_expire_define_the_lease_lifecycle(
        self,
        market_ticks: tuple[Tick, Tick],
    ) -> None:
        original = TaskExecutionIntent(
            task_id=uuid4(),
            definition_id=uuid4(),
            disposition=TaskExecutionDisposition.RUNNING,
            owner_id="server-a",
        )

        acquired = original.acquire("server-b", duration=timedelta(seconds=30))
        renewed = acquired.renew(duration=timedelta(seconds=30), tick=market_ticks[0])
        expired = renewed.expire_lease()

        assert acquired.owner_id == "server-b"
        assert acquired.generation == original.generation + 1
        assert acquired.lease_id != original.lease_id
        assert renewed.last_processed_at == market_ticks[0].timestamp
        assert renewed.lease_expires_at > renewed.heartbeat_at
        assert not expired.lease_is_valid(at=expired.lease_expires_at)

    def test_transition_can_fence_the_previous_owner(self) -> None:
        original = TaskExecutionIntent(
            task_id=uuid4(),
            definition_id=uuid4(),
            disposition=TaskExecutionDisposition.RUNNING,
            owner_id="server-a",
            lease_expires_at=now() + timedelta(seconds=30),
        )

        paused = original.transition(
            TaskExecutionDisposition.PAUSED,
            owner_id="server-b",
            increment_generation=True,
            expire_lease=True,
        )

        assert paused.disposition == TaskExecutionDisposition.PAUSED
        assert paused.owner_id == "server-b"
        assert paused.generation == original.generation + 1
        assert not paused.lease_is_valid()


class TestTaskStatusDispositionMapper:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (TaskStatus.PAUSED, TaskExecutionDisposition.PAUSED),
            (TaskStatus.STOPPED, TaskExecutionDisposition.STOPPED),
            (TaskStatus.COMPLETED, TaskExecutionDisposition.COMPLETED),
            (TaskStatus.FAILED, TaskExecutionDisposition.FAILED),
            (TaskStatus.RUNNING, None),
            (TaskStatus.STARTING, None),
        ],
    )
    def test_maps_only_durable_control_and_terminal_states(
        self,
        status: TaskStatus,
        expected: TaskExecutionDisposition | None,
    ) -> None:
        assert TaskStatusDispositionMapper.terminal_disposition(status) == expected
