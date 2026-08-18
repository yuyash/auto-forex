"""Strategy abstraction for auto trading algorithms."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, fields
from decimal import Decimal
from logging import Logger
from uuid import UUID

from pydantic import Field

from autoforex.core.logging import get_logger
from autoforex.core.models.base import DomainModel
from autoforex.core.models.metadata import Metadata
from autoforex.core.models.money import CurrencyPair, Money
from autoforex.core.sources.models import Candle, Tick
from autoforex.core.strategies.execution import StrategyEventRequest, StrategyExecutionResponse
from autoforex.core.strategies.models import StrategyParameters, StrategyState
from autoforex.core.tasks.state import TaskType

_LOGGER: Logger = get_logger(__name__)


@dataclass(frozen=True)
class StrategyLogContext(Mapping[str, str | int]):
    """Structured logging context for strategy lifecycle callbacks."""

    task_id: str
    task_type: str
    strategy_name: str
    strategy_class: str
    instrument: str
    parameter_count: int

    def __getitem__(self, key: str) -> str | int:
        try:
            return getattr(self, key)
        except AttributeError as exc:
            raise KeyError(key) from exc

    def __iter__(self) -> Iterator[str]:
        return (field.name for field in fields(self))

    def __len__(self) -> int:
        return len(fields(self))


class StrategyContext(DomainModel):
    """Runtime context passed to strategies by task executors."""

    task_id: UUID
    task_type: TaskType
    instrument: CurrencyPair
    account_balance: Money = Field(default_factory=lambda: Money.of("10000", "USD"))
    state: StrategyState = Field(default_factory=StrategyState)
    metadata: Metadata = Field(default_factory=Metadata)

    @property
    def pip_size(self) -> Decimal:
        """Return the instrument-derived pip size."""
        return self.instrument.pip_size

    def with_state(self, state: StrategyState) -> StrategyContext:
        """Return a copy of this context carrying the given strategy state."""
        return self.model_copy(update={"state": state})

    def with_account_balance(self, account_balance: Money) -> StrategyContext:
        """Return a copy of this context carrying the latest realized account balance."""
        return self.model_copy(update={"account_balance": account_balance.require_positive()})


class StrategyResult(DomainModel):
    """Strategy output for a single lifecycle or market-data callback."""

    events: tuple[StrategyEventRequest, ...] = ()
    state: StrategyState | None = None


class Strategy(ABC):
    """Base class for concrete trading strategies such as Snowball."""

    def __init__(
        self,
        *,
        name: str,
        parameters: StrategyParameters | None = None,
    ) -> None:
        _LOGGER.debug(
            "Initializing strategy %s",
            name,
            extra={
                "strategy_name": name,
                "strategy_class": self.__class__.__name__,
            },
        )
        self.name = name
        self.parameters = self.normalize_parameters(parameters or StrategyParameters())
        self.validate_parameters(self.parameters)
        _LOGGER.info(
            "Initialized strategy %s",
            self.name,
            extra={
                "strategy_name": self.name,
                "strategy_class": self.__class__.__name__,
                "parameter_count": len(self.parameters.values),
            },
        )

    @classmethod
    def default_parameters(cls) -> StrategyParameters:
        """Return strategy-specific default parameters."""
        return StrategyParameters()

    @classmethod
    def normalize_parameters(
        cls,
        parameters: StrategyParameters,
    ) -> StrategyParameters:
        """Normalize external parameters into the strategy's canonical shape."""
        normalized = cls.default_parameters().merge(parameters)
        _LOGGER.debug(
            "Normalized strategy parameters for %s",
            cls.__name__,
            extra={
                "strategy_class": cls.__name__,
                "parameter_count": len(normalized.values),
            },
        )
        return normalized

    @classmethod
    def validate_parameters(cls, parameters: StrategyParameters) -> None:
        """Validate strategy parameters before a task starts."""
        _LOGGER.debug(
            "Validated strategy parameters for %s",
            cls.__name__,
            extra={
                "strategy_class": cls.__name__,
                "parameter_count": len(parameters.values),
            },
        )
        _ = parameters

    def on_start(self, context: StrategyContext) -> StrategyResult:
        """Handle task start before market data is processed."""
        _LOGGER.debug(
            "Strategy %s handled default on_start",
            self.name,
            extra=self._log_extra(context=context),
        )
        return StrategyResult()

    def on_recover(self, context: StrategyContext) -> StrategyResult:
        """Restore an interrupted run without repeating start side effects."""
        _LOGGER.debug(
            "Strategy %s handled default on_recover",
            self.name,
            extra=self._log_extra(context=context),
        )
        return StrategyResult(state=context.state)

    @abstractmethod
    def on_tick(self, tick: Tick, context: StrategyContext) -> StrategyResult:
        """Process one market tick and emit strategy events."""

    def on_candle(self, candle: Candle, context: StrategyContext) -> StrategyResult:
        """Process one candle when a strategy consumes candle data."""
        _LOGGER.debug(
            "Strategy %s ignored candle in default on_candle",
            self.name,
            extra={
                **self._log_extra(context=context),
                "timestamp": candle.timestamp.isoformat(),
                "granularity": str(candle.granularity),
            },
        )
        return StrategyResult()

    def on_execution_reports(
        self,
        reports: Sequence[StrategyExecutionResponse],
        context: StrategyContext,
    ) -> StrategyState:
        """Reconcile broker execution reports into strategy state."""
        _LOGGER.debug(
            "Strategy %s ignored execution reports in default handler",
            self.name,
            extra={
                **self._log_extra(context=context),
                "execution_report_count": len(reports),
            },
        )
        return context.state

    def on_stop(self, context: StrategyContext) -> StrategyResult:
        """Handle task stop after market data processing ends."""
        _LOGGER.debug(
            "Strategy %s handled default on_stop",
            self.name,
            extra=self._log_extra(context=context),
        )
        return StrategyResult()

    def _log_extra(self, *, context: StrategyContext) -> StrategyLogContext:
        return StrategyLogContext(
            task_id=str(context.task_id),
            task_type=context.task_type.value,
            strategy_name=self.name,
            strategy_class=self.__class__.__name__,
            instrument=str(context.instrument),
            parameter_count=len(self.parameters.values),
        )
