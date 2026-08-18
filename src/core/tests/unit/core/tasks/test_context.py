from datetime import UTC, datetime

from autoforex.core import (
    BacktestTaskDefinition,
    CurrencyPair,
    ExecutableTask,
    InMemoryTaskRegistry,
    Money,
    StrategyState,
)


def task() -> ExecutableTask:
    definition = BacktestTaskDefinition(
        name="Context hierarchy",
        instrument=CurrencyPair.of("EUR_USD"),
        start_at=datetime(2026, 1, 1, tzinfo=UTC),
        end_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    return ExecutableTask.from_definition(definition).start()


class TestTaskRegistryContext:
    def test_task_registry_exposes_context_operations(self) -> None:
        current_task = task()
        registry = InMemoryTaskRegistry((current_task,))

        context = registry.initialize_context(current_task, strategy_name="test")

        assert registry.current_context(current_task.id) == context

    def test_task_registry_resets_runtime_context_for_a_new_task_run(self) -> None:
        current_task = task()
        registry = InMemoryTaskRegistry((current_task,))
        context = registry.initialize_context(current_task, strategy_name="test")
        registry.save_context(
            context.with_account_balance(Money.of("12000", "USD")).with_state(
                StrategyState.of(active=True)
            )
        )

        restarted = registry.save(registry.get(current_task.id).stop().restart())
        restarted_context = registry.initialize_context(restarted, strategy_name="test")

        assert restarted_context.account_balance == Money.of("10000", "USD")
        assert restarted_context.state == StrategyState()
