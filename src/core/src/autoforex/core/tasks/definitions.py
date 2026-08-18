"""Immutable task definitions."""

from __future__ import annotations

from logging import Logger
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from autoforex.core.clock import now
from autoforex.core.logging import get_logger
from autoforex.core.models.accounts import Account
from autoforex.core.models.base import DomainModel
from autoforex.core.models.identifiers import new_uuid
from autoforex.core.models.money import CurrencyPair
from autoforex.core.strategies.models import StrategyParameters
from autoforex.core.tasks.state import TaskType

_LOGGER: Logger = get_logger(__name__)


class BaseTaskDefinition(DomainModel):
    """Immutable definition of what should be executed.

    A definition describes *what* to run (instrument, parameters, time window)
    but not *how*: the concrete strategy and data source are supplied to the
    executor at run time, not named here. The tick granularity is a property of
    the data source, not of the definition.
    """

    id: UUID = Field(default_factory=new_uuid)
    name: str = Field(min_length=1)
    instrument: CurrencyPair
    parameters: StrategyParameters = Field(default_factory=StrategyParameters)
    created_at: AwareDatetime = Field(default_factory=now)

    @model_validator(mode="after")
    def _log_task_definition(self) -> Self:
        task_type = getattr(self, "task_type", "")
        task_type_value = task_type.value if isinstance(task_type, TaskType) else str(task_type)
        _LOGGER.debug(
            "Validated task definition %s",
            self.id,
            extra={
                "task_definition_id": str(self.id),
                "task_name": self.name,
                "task_type": task_type_value,
                "instrument": str(self.instrument),
                "parameter_count": len(self.parameters.values),
            },
        )
        return self


class BacktestTaskDefinition(BaseTaskDefinition):
    """Definition for replaying historical market data through a strategy."""

    task_type: Literal[TaskType.BACKTEST] = TaskType.BACKTEST
    start_at: AwareDatetime
    end_at: AwareDatetime

    @model_validator(mode="after")
    def _validate_period(self) -> BacktestTaskDefinition:
        _LOGGER.debug(
            "Validating backtest task period",
            extra={
                "task_definition_id": str(self.id),
                "task_name": self.name,
                "instrument": str(self.instrument),
                "start_at": self.start_at.isoformat(),
                "end_at": self.end_at.isoformat(),
            },
        )
        if self.start_at >= self.end_at:
            _LOGGER.debug(
                "Rejected invalid backtest task period",
                extra={
                    "task_definition_id": str(self.id),
                    "start_at": self.start_at.isoformat(),
                    "end_at": self.end_at.isoformat(),
                },
            )
            msg = "start_at must be earlier than end_at"
            raise ValueError(msg)
        _LOGGER.debug(
            "Validated backtest task period",
            extra={
                "task_definition_id": str(self.id),
                "start_at": self.start_at.isoformat(),
                "end_at": self.end_at.isoformat(),
            },
        )
        return self


class TradingTaskDefinition(BaseTaskDefinition):
    """Definition for running a strategy against a live broker account."""

    task_type: Literal[TaskType.TRADING] = TaskType.TRADING
    account: Account
    dry_run: bool = True


type TaskDefinition = BacktestTaskDefinition | TradingTaskDefinition
