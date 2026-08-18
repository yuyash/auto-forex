import pytest

from autoforex.core.tasks import TaskAction, TaskStateError, TaskStateMachine, TaskStatus


class TestState:
    def test_task_state_machine_models_transitions(self) -> None:
        state_machine = TaskStateMachine.default()

        assert state_machine.can(TaskStatus.CREATED, TaskAction.START)
        assert state_machine.next_status(TaskStatus.CREATED, TaskAction.START) == TaskStatus.RUNNING
        assert (
            state_machine.next_status(TaskStatus.RUNNING, TaskAction.COMPLETE)
            == TaskStatus.COMPLETED
        )
        assert TaskAction.RESTART in state_machine.allowed_actions(TaskStatus.COMPLETED)
        assert state_machine.next_status(TaskStatus.COMPLETED, TaskAction.FAIL) == TaskStatus.FAILED
        assert any(
            transition.source == TaskStatus.RUNNING
            and transition.action == TaskAction.FAIL
            and transition.target == TaskStatus.FAILED
            for transition in state_machine.transitions
        )

        with pytest.raises(TaskStateError):
            state_machine.next_status(TaskStatus.CREATED, TaskAction.PAUSE)
