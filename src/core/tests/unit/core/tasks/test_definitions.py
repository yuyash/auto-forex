from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from autoforex.core import (
    Account,
    AccountId,
    CurrencyPair,
    StrategyParameters,
)
from autoforex.core.tasks import (
    BacktestTaskDefinition,
    TaskType,
    TradingTaskDefinition,
)


class TestDefinitions:
    def test_backtest_task_definition_models_required_period(self) -> None:
        definition = BacktestTaskDefinition.model_validate(
            {
                "name": "Backtest USD_JPY",
                "instrument": CurrencyPair.of("USD_JPY"),
                "parameters": {"risk_percent": Decimal("1.5")},
                "start_at": datetime(2026, 1, 1, tzinfo=UTC),
                "end_at": datetime(2026, 1, 2, tzinfo=UTC),
            }
        )

        assert definition.task_type == TaskType.BACKTEST
        assert definition.parameters == StrategyParameters.of(risk_percent=Decimal("1.5"))

    def test_backtest_task_definition_rejects_invalid_period(self) -> None:
        with pytest.raises(ValidationError, match="start_at must be earlier"):
            BacktestTaskDefinition(
                name="Invalid",
                instrument=CurrencyPair.of("USD_JPY"),
                start_at=datetime(2026, 1, 2, tzinfo=UTC),
                end_at=datetime(2026, 1, 1, tzinfo=UTC),
            )

    def test_trading_task_definition_defaults_to_dry_run(self) -> None:
        definition = TradingTaskDefinition(
            name="Live USD_JPY",
            instrument=CurrencyPair.of("USD_JPY"),
            account=Account(id=AccountId.of("001")),
        )

        assert definition.task_type == TaskType.TRADING
        assert definition.account == Account(id=AccountId.of("001"))
        assert definition.dry_run is True
