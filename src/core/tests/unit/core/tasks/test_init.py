from autoforex.core.tasks import (
    BacktestTaskDefinition,
    TaskAction,
    TaskStateMachine,
    TaskStatus,
)


class TestInit:
    def test_tasks_package_exports_task_domain(self) -> None:
        assert BacktestTaskDefinition.__name__ == "BacktestTaskDefinition"
        assert TaskAction.START.value == "start"
        assert TaskStateMachine.default().can(TaskStatus.CREATED, TaskAction.START)
