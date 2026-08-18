"""Strategy-related value objects."""

from __future__ import annotations

from autoforex.core.models.mapping import MappingValueObject


class StrategyParameters(MappingValueObject):
    """Immutable parameters passed to a strategy instance."""


class StrategyState(MappingValueObject):
    """Immutable state snapshot emitted by a strategy callback."""
