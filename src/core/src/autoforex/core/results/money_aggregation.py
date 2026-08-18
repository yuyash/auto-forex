"""Aggregation helpers for money and task date ranges."""

from __future__ import annotations

from datetime import datetime

from autoforex.core.models.money import Currency, Money
from autoforex.core.tasks.execution import ExecutableTask

type Task = ExecutableTask


class MoneyAccumulator:
    """Money aggregation helper."""

    @staticmethod
    def sum(values: tuple[Money, ...], *, currency: Currency) -> Money:
        """Return a currency-checked sum."""
        total = Money.of("0", currency)
        for value in values:
            total += value.require_currency(currency)
        return total


class DateRange:
    """Datetime aggregation helpers."""

    @staticmethod
    def finished_at(task: Task) -> datetime | None:
        """Return the task's terminal timestamp when available."""
        return task.completed_at or task.stopped_at

    @staticmethod
    def earliest(values: tuple[datetime | None, ...]) -> datetime | None:
        """Return earliest concrete datetime."""
        concrete = tuple(value for value in values if value is not None)
        return min(concrete) if concrete else None

    @staticmethod
    def latest(values: tuple[datetime | None, ...]) -> datetime | None:
        """Return latest concrete datetime."""
        concrete = tuple(value for value in values if value is not None)
        return max(concrete) if concrete else None
