from importlib.metadata import version

from autoforex.core import (
    Account,
    AccountId,
    AccountProvider,
    AccountSummary,
    CSVDataSource,
    CurrencyPair,
    Event,
    EventType,
    LogLevel,
    TaskAction,
    TaskStateMachine,
    TaskStatus,
    TradingProvider,
    __version__,
)


class TestInit:
    def test_core_exports_public_api(self) -> None:
        assert __version__ == version("auto-forex-core")
        assert Account.of(Account(id=AccountId.of("001"))).id.value == "001"
        assert AccountProvider.of("paper").value == "paper"
        assert (
            AccountSummary.model_validate({"account_id": "001", "currency": "USD"}).account_id.value
            == "001"
        )
        assert CurrencyPair.of("USD_JPY").symbol == "USD_JPY"
        assert CSVDataSource.__name__ == "CSVDataSource"
        assert LogLevel.WARNING.value == "WARNING"
        assert Event(type=EventType.TASK_STARTED).type == EventType.TASK_STARTED
        assert TaskStateMachine.default().can(TaskStatus.CREATED, TaskAction.START)
        assert TradingProvider.__name__ == "TradingProvider"
