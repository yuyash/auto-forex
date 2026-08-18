"""Shared primitives for Core domain models."""

from __future__ import annotations

from logging import Logger
from typing import Any, Self

from pydantic import BaseModel, ConfigDict

from autoforex.core.logging import get_logger

_LOGGER: Logger = get_logger(__name__)


class DomainModel(BaseModel):
    """Base class for validated, immutable AutoForex domain objects."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    def dump(self, **kwargs: Any) -> dict[str, Any]:
        """Return a Python dict of the model (shorthand for ``model_dump``)."""
        return self.model_dump(**kwargs)

    def evolve(self, **changes: Any) -> Self:
        """Return a validated copy with selected fields changed."""
        if changes:
            _LOGGER.debug(
                "Evolving domain model %s",
                self.__class__.__name__,
                extra={
                    "domain_model": self.__class__.__name__,
                    "changed_fields": ",".join(sorted(changes)),
                },
            )
        data = self.model_dump(mode="python", round_trip=True)
        data.update(changes)
        return self.__class__.model_validate(data)
