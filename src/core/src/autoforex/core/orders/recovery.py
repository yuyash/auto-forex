"""Contracts for recoverable broker execution."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractContextManager
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import AwareDatetime

from autoforex.core.models.base import DomainModel
from autoforex.core.models.brokers import Order, Position, PositionSide, Trade
from autoforex.core.models.values import Units
from autoforex.core.strategies.execution import StrategyEventRequest, StrategyExecutionResponse


class BrokerMutationOperation(StrEnum):
    """Broker mutations that may require crash recovery."""

    PLACE_ORDER = "place_order"
    CLOSE_POSITION = "close_position"
    CLOSE_TRADE = "close_trade"


class BrokerMutation(DomainModel):
    """Provider-neutral description of one broker mutation."""

    command_id: UUID
    task_id: UUID
    operation: BrokerMutationOperation
    order: Order | None = None
    position: Position | None = None
    position_side: PositionSide | None = None
    trade: Trade | None = None
    units: Units | None = None
    provider_cursor: str | None = None


class BrokerReconciliationOutcome(StrEnum):
    """Outcome of checking whether a broker mutation took effect."""

    APPLIED = "applied"
    NOT_APPLIED = "not_applied"
    INDETERMINATE = "indeterminate"


class BrokerReconciliation(DomainModel):
    """Result of reconciling one broker mutation with provider state."""

    outcome: BrokerReconciliationOutcome
    order: Order | None = None
    details: str = ""


@runtime_checkable
class BrokerMutationReconciler(Protocol):
    """Optional provider capability used to resolve interrupted mutations."""

    def capture_execution_cursor(self) -> str | None:
        """Return a provider cursor immediately before a mutation."""

    def reconcile_execution(self, mutation: BrokerMutation) -> BrokerReconciliation:
        """Determine whether an interrupted mutation took effect."""


class ExecutionRecoveryBatch(DomainModel):
    """A durable group of strategy requests that must finish together."""

    task_id: UUID
    requests: tuple[StrategyEventRequest, ...]
    checkpoint_at: AwareDatetime | None = None


@runtime_checkable
class BrokerExecutionCoordinator(Protocol):
    """Coordinate durable execution batches around broker requests."""

    def prepare(
        self,
        requests: Sequence[StrategyEventRequest],
        *,
        checkpoint_at: datetime | None,
    ) -> None:
        """Durably prepare requests before they reach a broker."""

    def pending(self, task_id: UUID) -> Sequence[ExecutionRecoveryBatch]:
        """Return incomplete request batches for a recovering task."""

    def response_applied(self, response: StrategyExecutionResponse) -> None:
        """Record that a broker response was applied to strategy state."""

    def complete(self, requests: Sequence[StrategyEventRequest]) -> None:
        """Record that every request in a prepared batch completed."""

    def checkpointed(self, requests: Sequence[StrategyEventRequest]) -> None:
        """Record that the task checkpoint covering a batch was persisted."""

    def execution_scope(
        self,
        request: StrategyEventRequest,
    ) -> AbstractContextManager[None]:
        """Associate broker mutations with one strategy request."""


class BrokerExecutionUnresolvedError(RuntimeError):
    """Raised when a broker mutation cannot be reconciled safely."""
